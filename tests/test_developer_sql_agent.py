"""V15: real SQLite snapshot safety, dialect/GraphQL and central Studio Agent tests."""
from __future__ import annotations
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient
import pytest
from automoto import (sandbox, server, developer_sql as sql, developer_data as data,
                      studio_agent_bridge as bridge)
from automoto.hosted import path_allowed

H={"X-AutoMoto-Token":server.SESSION_TOKEN}
BASE="/api/developer/studio/sql"
DATA="/api/developer/studio/data"
BRIDGE="/api/agent/studios"


@pytest.fixture
def root(tmp_path,monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME",str(tmp_path/"private"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE",str(tmp_path/"workspace"))
    monkeypatch.setenv("AUTOMOTO_DATA_DIR",str(tmp_path/"private"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT","10000")
    monkeypatch.delenv("AUTOMOTO_MODE",raising=False)
    base=sandbox.default_root()/"v15-database"
    base.mkdir(parents=True)
    with sqlite3.connect(base/"example.sqlite") as con:
        con.execute("CREATE TABLE records(id INTEGER PRIMARY KEY, name TEXT NOT NULL, amount INTEGER)")
        con.executemany("INSERT INTO records(name,amount) VALUES (?,?)",
                        [("Alpha",10),("Beta",25),("Gamma",40)])
    (base/"schema.graphql").write_text(
      'type Query {\n  records(limit: Int): [Record!]!\n  version: String\n}\n'
      'type Mutation { updateRecord(id: Int): Boolean }\n'
      'type Record {\n id: Int!\n name: String!\n}\n',encoding="utf-8")
    (base/"pg.sql").write_text("CREATE TABLE users(id SERIAL PRIMARY KEY, metadata JSONB);",encoding="utf-8")
    (base/"mysql.sql").write_text("CREATE TABLE users (id INT AUTO_INCREMENT PRIMARY KEY) ENGINE=InnoDB;",encoding="utf-8")
    return TestClient(server.app),base


def post(client,path,payload):
    return client.post(path,headers=H,json=payload)


def args(root,**extra):
    return {"project":str(root),"path":"example.sqlite",**extra}


def test_actual_sqlite_schema_snapshot_and_parameterised_select(root):
    client,directory=root
    source=directory/"example.sqlite"
    original=source.read_bytes()
    r=post(client,BASE+"/inspect",args(directory))
    assert r.status_code==200,r.text
    report=r.json()
    assert report["database_sha256"]==hashlib.sha256(original).hexdigest()
    assert report["dialect_support"]["sqlite"]=="read_only_snapshot"
    assert any(x["name"]=="records" for x in report["schema"])
    assert len(report["schema"][0]["columns"])==3
    result=post(client,BASE+"/query",args(directory,
      sql="SELECT name,amount FROM records WHERE amount >= ? ORDER BY id",
      params=[20]))
    assert result.status_code==200,result.text
    assert result.json()["rows"]==[["Beta",25],["Gamma",40]]
    assert result.json()["read_only"] and result.json()["original_database_written"] is False
    assert source.read_bytes()==original


@pytest.mark.parametrize("statement",[
    "DELETE FROM records","UPDATE records SET name='X'",
    "DROP TABLE records","PRAGMA user_version=9","ATTACH DATABASE '/tmp/hack' AS hack",
    "SELECT load_extension('x')","SELECT randomblob(2000000)",
    "SELECT name FROM records; DELETE FROM records",
    "WITH changed AS (DELETE FROM records RETURNING id) SELECT * FROM changed"
])
def test_query_denies_writes_dangerous_functions_and_multiple_statements(root,statement):
    client,folder=root
    original=(folder/"example.sqlite").read_bytes()
    r=post(client,BASE+"/query",args(folder,sql=statement))
    assert r.status_code in (413,422),r.text
    assert (folder/"example.sqlite").read_bytes()==original


def test_query_limits_rows_response_size_and_query_timeout(root,monkeypatch):
    client,folder=root
    monkeypatch.setattr(sql,"MAX_ROWS",1)
    r=post(client,BASE+"/query",args(folder,sql="SELECT name FROM records ORDER BY id"))
    assert r.status_code==200,r.text
    assert len(r.json()["rows"])==1 and r.json()["truncated"] is True
    monkeypatch.setattr(sql,"MAX_STEPS",1000)
    r=post(client,BASE+"/query",args(folder,
        sql="WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x<1000000) SELECT max(x) FROM c"))
    assert r.status_code==422


def test_migration_preview_rollback_even_when_preview_changes_schema(root):
    client,folder=root
    original=(folder/"example.sqlite").read_bytes()
    p={**args(folder),"sql":"ALTER TABLE records ADD COLUMN reviewed INTEGER",
       "confirmed":True,"acknowledge_dry_run_only":True}
    assert post(client,BASE+"/migration-preview",{k:v for k,v in p.items() if k!="confirmed"}).status_code==422
    preview=post(client,BASE+"/migration-preview",p)
    assert preview.status_code==200,preview.text
    v=preview.json()
    assert v["rollback_verified"] is True and v["migration_applied"] is False
    assert "reviewed" not in [c["name"] for c in v["before"][0]["columns"]]
    assert "reviewed" in [c["name"] for c in v["after"][0]["columns"]]
    assert (folder/"example.sqlite").read_bytes()==original
    with sqlite3.connect(folder/"example.sqlite") as con:
        cols=[x[1] for x in con.execute("PRAGMA table_info(records)")]
        assert "reviewed" not in cols


@pytest.mark.parametrize("statement",[
    "DROP TABLE records","DELETE FROM records","ALTER TABLE records RENAME TO broken",
    "CREATE TRIGGER t AFTER INSERT ON records BEGIN DELETE FROM records; END",
    "CREATE TABLE bad (x INT); DROP TABLE records",
    "CREATE VIRTUAL TABLE f USING fts5(contents)",
])
def test_migration_rejects_unsafe_or_unsupported_ddl(root,statement):
    client,folder=root
    original=(folder/"example.sqlite").read_bytes()
    r=post(client,BASE+"/migration-preview",args(folder,sql=statement,
               confirmed=True,acknowledge_dry_run_only=True))
    assert r.status_code==422,r.text
    assert (folder/"example.sqlite").read_bytes()==original


def test_linked_traversal_and_wal_sidecars_denied(root,tmp_path):
    client,folder=root
    assert post(client,BASE+"/inspect",args(folder,path="../outside.sqlite")).status_code in (403,422)
    link=folder/"linked.sqlite"
    try:
        link.symlink_to(folder/"example.sqlite")
        assert post(client,BASE+"/inspect",args(folder,path="linked.sqlite")).status_code==403
    except (OSError,NotImplementedError):pass
    side=folder/"example.sqlite-wal"
    side.write_bytes(b"active WAL fixture")
    assert post(client,BASE+"/inspect",args(folder)).status_code==409


def test_graphql_static_type_navigation_and_mutation_denial(root):
    client,folder=root
    req={"project":str(folder),"path":"schema.graphql","dialect":"graphql"}
    inspect=post(client,DATA+"/inspect",req)
    assert inspect.status_code==200,inspect.text
    assert {x["name"] for x in inspect.json()["types"]}=={"Query","Mutation","Record"}
    assert inspect.json()["query_executed"] is False
    ok=post(client,DATA+"/graphql-review",{**req,"operation":"query {\n records { name }\n version\n}"})
    assert ok.status_code==200,ok.text
    assert ok.json()["sent_to_server"] is False
    assert ok.json()["missing_root_fields"]==[]
    deny=post(client,DATA+"/graphql-review",{**req,"operation":"mutation { updateRecord(id:1) }"})
    assert deny.status_code==200 and deny.json()["allowed"] is False
    bad=post(client,DATA+"/graphql-review",{**req,"operation":"query {\n missingField\n}"})
    assert bad.status_code==200 and bad.json()["missing_root_fields"]==["missingField"]


def test_postgres_mysql_dialect_static_and_no_connections(root):
    client,folder=root
    for file,dialect,flag in (("pg.sql","postgresql","jsonb"),("mysql.sql","mysql","auto_increment")):
        r=post(client,DATA+"/inspect",{"project":str(folder),"path":file,"dialect":dialect})
        assert r.status_code==200,r.text
        assert r.json()["not_database_connected"] is True
        assert any(x["name"]==flag and x["matched"] for x in r.json()["static_dialect_clues"])


def test_studio_agent_registry_covers_all_five_real_pages(root):
    client,folder=root
    r=client.get(BRIDGE+"/catalog",headers=H)
    assert r.status_code==200,r.text
    assert {x["id"] for x in r.json()["studios"]}=={
        "documents","research","spreadsheets","visual","developer"}
    assert r.json()["automatic_deployment"] is False
    assert r.json()["requires_human_confirmation"] is True
    src=(Path(server.__file__).parent/"web"/"static"/"app.js").read_text(encoding="utf-8")
    for id_ in bridge.STUDIOS:
        assert '"'+id_+'"' in src
    assert "mountStudioAgentBridge" in src


def test_studio_agent_handoff_requires_auth_consent_and_no_auto_deploy(root,monkeypatch):
    client,folder=root
    starts=[]
    class FakeTask:
        id="mock-agent-task-15"
        status="queued"
    monkeypatch.setattr(server.TASKS,"start",lambda *args,**kw:
        starts.append((args,kw)) or FakeTask())
    payload={"studio":"visual","action":"deployment_readiness",
             "request":"Review accessibility and deployment readiness of this visual.",
             "confirmed":True,"accept_agent_review_only":True}
    assert client.post(BRIDGE+"/handoff",json=payload).status_code==403
    assert post(client,BRIDGE+"/handoff",{**payload,"confirmed":False}).status_code==422
    assert post(client,BRIDGE+"/handoff",{**payload,"accept_agent_review_only":False}).status_code==422
    assert starts==[]
    r=post(client,BRIDGE+"/handoff",payload)
    assert r.status_code==200,r.text
    assert r.json()["deployment_started"] is False
    assert r.json()["task_id"]=="mock-agent-task-15"
    assert len(starts)==1
    args_,kw=starts[0]
    assert kw["auto_deny"] is True
    assert kw["source"]=="studio:visual"
    assert kw["agent_kwargs"]["desktop"] is False
    assert kw["agent_kwargs"]["local_apps"] is False
    assert kw["conversation_id"]==r.json()["conversation_id"]
    assert "Do NOT deploy or publish" in args_[0][0]["content"]


def test_agent_workspace_must_be_trusted_developer_and_hosted_paths(root,monkeypatch):
    client,folder=root
    payload={"studio":"developer","action":"review","workspace":str(folder),
             "request":"Inspect this local source project for errors.",
             "confirmed":True,"accept_agent_review_only":True}
    assert post(client,BRIDGE+"/handoff",payload).status_code==403
    assert post(client,BRIDGE+"/handoff",{**payload,"studio":"research"}).status_code==403
    assert path_allowed("GET",BRIDGE+"/catalog") is True
    assert path_allowed("POST",BRIDGE+"/handoff") is True
    assert path_allowed("POST",BASE+"/query") is False
    assert path_allowed("POST",DATA+"/inspect") is False
