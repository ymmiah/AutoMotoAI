"""Developer Studio V4 local project search and replace-review boundaries."""
from __future__ import annotations

import hashlib
from fastapi.testclient import TestClient
import pytest

from automoto import sandbox, server
from automoto.hosted import path_allowed

BASE="/api/developer/studio"
HEADERS={"X-AutoMoto-Token":server.SESSION_TOKEN}


@pytest.fixture
def workspace(tmp_path,monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE",str(tmp_path/"workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT","10000")
    monkeypatch.delenv("AUTOMOTO_MODE",raising=False)
    root=sandbox.default_root()/"v4-project"
    (root/"src").mkdir(parents=True)
    (root/"src"/"main.py").write_bytes("hello world\nHELLO again\n".encode())
    (root/"src"/"second.py").write_bytes(b"no match here\n")
    (root/".env").write_text("hello secret",encoding="utf-8")
    (root/".git").mkdir()
    (root/".git"/"config").write_text("hello secret",encoding="utf-8")
    return TestClient(server.app),root


def search(client,root,query="hello",**kwargs):
    return client.post(BASE+"/search",headers=HEADERS,json={
        "project":str(root),"query":query,**kwargs
    })


def trust(client,root):
    r=client.post(BASE+"/trust",headers=HEADERS,
                  json={"project":str(root),"trusted":True,"confirmed":True})
    assert r.status_code==200,r.text


def preview(client,root,expected=None,**kwargs):
    path=root/"src"/"main.py"
    return client.post(BASE+"/replace-preview",headers=HEADERS,json={
        "project":str(root),"path":"src/main.py","query":"hello",
        "replacement":"goodbye","expected_sha256":expected or hashlib.sha256(path.read_bytes()).hexdigest(),
        "encoding":"utf-8",**kwargs
    })


def test_untrusted_can_search_only_authorised_local_project(workspace,tmp_path):
    client,root=workspace
    assert not path_allowed("POST",BASE+"/search")
    assert not path_allowed("POST",BASE+"/replace-preview")
    assert client.post(BASE+"/search",json={"project":str(root),"query":"hello"}).status_code==403
    r=search(client,root)
    assert r.status_code==200,r.text
    assert r.json()["source_modified"] is False
    assert len(r.json()["items"])==2
    assert all(x["path"]=="src/main.py" for x in r.json()["items"])
    assert [x["line"] for x in r.json()["items"]]==[1,2]
    assert search(client,tmp_path/"outside").status_code==403


def test_filename_mode_search_boundaries_and_case(workspace):
    client,root=workspace
    r=search(client,root,query=".PY",scope="filename")
    assert r.status_code==200,r.text
    assert {x["path"] for x in r.json()["items"]}=={"src/main.py","src/second.py"}
    assert search(client,root,query="hello",case_sensitive=True).json()["items"][0]["line"]==1
    assert len(search(client,root,query="HELLO",case_sensitive=True).json()["items"])==1
    assert search(client,root,query="hello",directory="../outside").status_code==403
    assert search(client,root,query=" ").status_code==422


def test_secrets_symlinks_binary_and_large_sources_skipped(workspace):
    client,root=workspace
    (root/"src"/"binary.py").write_bytes(b"hello\x00ignore")
    (root/"src"/"huge.py").write_bytes(b"hello"*30000)
    alias=root/"src"/"linked.py"
    try:
        alias.symlink_to(root/".env")
    except (OSError,NotImplementedError):
        pass
    r=search(client,root)
    assert r.status_code==200
    assert all(x["path"]=="src/main.py" for x in r.json()["items"])
    assert all("secret" not in x["preview"] for x in r.json()["items"])


def test_replace_preview_requires_trust_and_never_writes(workspace):
    client,root=workspace
    source=root/"src"/"main.py"
    old=source.read_bytes()
    assert preview(client,root).status_code==403
    trust(client,root)
    response=preview(client,root)
    assert response.status_code==200,response.text
    data=response.json()
    assert data["count"]==2
    assert "goodbye world" in data["text"]
    assert "goodbye again" in data["text"]
    assert data["requires_review"] is True
    assert data["source_modified"] is False
    assert source.read_bytes()==old
    # A stale checksum cannot propose edits against changed bytes.
    sha=hashlib.sha256(old).hexdigest()
    source.write_bytes(b"someone else replaced me\n")
    assert preview(client,root,expected=sha).status_code==409


def test_replace_literal_regex_escaped_no_backslash_interpretation(workspace):
    client,root=workspace
    source=root/"src"/"main.py"
    source.write_text("foo.bar\\nfoobar\n",encoding="utf-8")
    trust(client,root)
    r=preview(client,root,query="foo.bar",replacement=r"\\1\\server")
    assert r.status_code==200,r.text
    assert r.json()["count"]==1
    assert r.json()["text"].startswith(r"\\1\\server")


def test_unsafe_replacement_and_encoding_are_blocked(workspace):
    client,root=workspace
    trust(client,root)
    assert preview(client,root,replacement="x"*1025).status_code==422
    source=root/"src"/"main.py"
    source.write_bytes("hello\r\nHELLO\n".encode())
    assert preview(client,root).status_code==422
    source.write_bytes("hello\n".encode())
    assert preview(client,root,query="hello",replacement="\x00").status_code==422
    assert source.read_bytes()==b"hello\n"


def test_search_hits_cap_and_oversized_queries(workspace):
    client,root=workspace
    (root/"src"/"main.py").write_bytes(("hello\n"*150).encode())
    r=search(client,root)
    assert r.status_code==200
    assert r.json()["truncated"] is True
    assert len(r.json()["items"])==100
    assert search(client,root,query="x"*161).status_code==422
