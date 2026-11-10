"""Developer Studio V15: read-only SQLite snapshots, safe SQL and rollback-only migrations.

No database credentials, production connections or SQL writes are accepted.
A bounded regular SQLite file is copied from an approved root via no-follow
file-descriptor checks into a private throwaway database. Query statements are
limited by SQLite authorizer, query_only, progress handler and output caps.
"""
from __future__ import annotations
import hashlib
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from automoto import developer_studio as studio

router=APIRouter(prefix="/api/developer/studio/sql",tags=["developer-sql"])
MAX_DB=8*1024*1024
MAX_QUERY=8000
MAX_ROWS=100
MAX_TOTAL_OUT=64*1024
MAX_SCHEMA=100
MAX_COLS=100
MAX_STEPS=100000
MAX_SECONDS=3.0
FORMATS={".sqlite",".sqlite3",".db"}
READ_PREFIX=re.compile(r"(?is)^\s*(?:select|with)\b")
DDL_CREATE=re.compile(r"(?is)^\s*CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)\b")
DDL_ALTER=re.compile(r"(?is)^\s*ALTER\s+TABLE\s+[\w\".]+\s+ADD\s+COLUMN\b")
DDL_DROP_INDEX=re.compile(r"(?is)^\s*DROP\s+INDEX\b")
NAME=re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,120}$")
SAFE_FUNCS=frozenset({"abs","avg","count","coalesce","ifnull","nullif","lower","upper",
 "length","min","max","sum","total","round","substr","trim","ltrim","rtrim",
 "replace","typeof","hex","printf","instr","like","glob","date","time",
 "datetime","strftime","julianday","unixepoch","json_extract","json_type",
 "json_valid","json_array_length","iif","cast"})

class ProjectIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    project:str=Field(min_length=1,max_length=1024)
    path:str=Field(min_length=1,max_length=1024)

class QueryIn(ProjectIn):
    sql:str=Field(min_length=1,max_length=MAX_QUERY)
    params:list[Any]=Field(default_factory=list,max_length=20)

class MigrationIn(ProjectIn):
    sql:str=Field(min_length=1,max_length=MAX_QUERY)
    confirmed:Literal[True]
    acknowledge_dry_run_only:Literal[True]

def _source(root:Path,relative:str)->bytes:
    if Path(relative).suffix.casefold() not in FORMATS:
        raise HTTPException(422,"Choose a local SQLite .db/.sqlite/.sqlite3 file.")
    path=studio._path(root,relative)
    if path.is_symlink() or getattr(path,"is_junction",lambda:False)():
        raise HTTPException(403,"Linked databases cannot be inspected.")
    for sidecar in ("-wal","-shm"):
        if Path(str(path)+sidecar).exists():
            raise HTTPException(409,"An active WAL/SHM sidecar exists; close the database or make a consistent backup before inspection.")
    flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_BINARY",0)
    try:
        fd=os.open(path,flags)
        with os.fdopen(fd,"rb") as f:
            before=os.fstat(f.fileno())
            if not stat.S_ISREG(before.st_mode) or not 100<=before.st_size<=MAX_DB:
                raise HTTPException(413,"SQLite file is not an ordinary file within the 8 MiB cap.")
            raw=f.read(MAX_DB+1)
            after=os.fstat(f.fileno())
        if len(raw)!=before.st_size or (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):
            raise HTTPException(409,"Database changed during snapshot copy.")
        if not raw.startswith(b"SQLite format 3\x00"):
            raise HTTPException(422,"File does not contain a SQLite 3 database header.")
        return raw
    except HTTPException:raise
    except OSError as exc:raise HTTPException(403,"Database cannot be safely opened.") from exc

@contextmanager
def _connection(raw:bytes):
    # The original source is never handed to SQLite by path, eliminating the
    # pathname-swap race. The connection touches only the temporary copy.
    with tempfile.TemporaryDirectory(prefix="automoto-sql15-") as directory:
        path=Path(directory)/"snapshot.sqlite"
        path.write_bytes(raw)
        con=sqlite3.connect(path,timeout=0.1,isolation_level=None)
        try:
            con.execute("PRAGMA trusted_schema=OFF")
            con.execute("PRAGMA busy_timeout=100")
            if hasattr(con,"setlimit"):
                con.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH,MAX_QUERY)
                con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,MAX_TOTAL_OUT)
            yield con
        finally:con.close()

def _schema(con:sqlite3.Connection)->list[dict]:
    try:
        rows=con.execute(
          "SELECT type,name,tbl_name,sql FROM sqlite_master "
          "WHERE type IN ('table','view','index') AND name NOT LIKE 'sqlite_%' "
          "ORDER BY type,name LIMIT ?",(MAX_SCHEMA+1,)).fetchall()
    except sqlite3.DatabaseError as exc:
        raise HTTPException(422,"SQLite source schema is invalid.") from exc
    if len(rows)>MAX_SCHEMA:
        raise HTTPException(413,"Too many schema objects to inspect safely.")
    result=[]
    for kind,name,parent,definition in rows:
        columns=[]
        if kind in ("table","view") and NAME.fullmatch(name):
            for col in con.execute('PRAGMA table_info("'+name+'")').fetchall()[:MAX_COLS]:
                columns.append({"name":col[1],"type":col[2],"not_null":bool(col[3]),
                                "primary_key":bool(col[5])})
        result.append({"type":kind,"name":name,"table":parent,
                       "definition_sha256":hashlib.sha256((definition or "").encode()).hexdigest(),
                       "columns":columns})
    return result

def _progress(con:sqlite3.Connection):
    started=time.monotonic()
    count=0
    def progress():
        nonlocal count
        count+=1000
        return 1 if count>MAX_STEPS or time.monotonic()-started>MAX_SECONDS else 0
    con.set_progress_handler(progress,1000)

def _authorizer(op, arg1, arg2, db, trigger):
    if op in (sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ):
        if op==sqlite3.SQLITE_READ and str(arg1 or "").startswith("sqlite_"):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    if op==sqlite3.SQLITE_FUNCTION and str(arg2 or "").casefold() in SAFE_FUNCS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY

def _params(values:list[Any])->list[Any]:
    result=[]
    for value in values:
        if value is None or isinstance(value,(bool,int,float)) or (
            isinstance(value,str) and len(value)<=256 and "\x00" not in value):
            result.append(value)
        else:raise HTTPException(422,"Query parameter type or length is not supported.")
    return result

def _query(con:sqlite3.Connection,statement:str,params:list[Any])->dict:
    if not READ_PREFIX.match(statement) or ";" in statement.strip().rstrip(";"):
        raise HTTPException(422,"Only one SELECT/CTE read query can be inspected.")
    con.execute("PRAGMA query_only=ON")
    con.set_authorizer(_authorizer)
    _progress(con)
    try:
        cursor=con.execute(statement,_params(params))
        if cursor.description is None:raise HTTPException(422,"Query did not return a read-only result set.")
        names=[d[0][:100] for d in cursor.description[:MAX_COLS]]
        raw=cursor.fetchmany(MAX_ROWS+1)
        rows=[]
        used=0
        for tup in raw[:MAX_ROWS]:
            row=[]
            for cell in tup[:MAX_COLS]:
                if isinstance(cell,(bytes,bytearray,memoryview)):
                    text="[binary:"+str(len(cell))+" bytes]"
                elif cell is None or isinstance(cell,(int,float,bool)):
                    text=cell
                else:
                    text=str(cell)[:1024]
                used+=len(str(text).encode("utf-8"))
                if used>MAX_TOTAL_OUT:raise HTTPException(413,"Query result exceeds the 64 KiB response cap.")
                row.append(text)
            rows.append(row)
        return {"columns":names,"rows":rows,"truncated":len(raw)>MAX_ROWS,
                "read_only":True,"executed_on_temporary_snapshot":True,
                "original_database_written":False,
                "result_bytes":used}
    except HTTPException:raise
    except (sqlite3.DatabaseError,sqlite3.Warning) as exc:
        raise HTTPException(422,"SQL query was denied or invalid; no write occurred.") from exc
    finally:
        con.set_authorizer(None)
        con.set_progress_handler(None,0)

def _migrate(con:sqlite3.Connection,statement:str)->dict:
    stripped=statement.strip().rstrip(";").strip()
    if (";" in stripped or "--" in stripped or "/*" in stripped or "*/" in stripped or
        not (DDL_CREATE.match(stripped) or DDL_ALTER.match(stripped) or DDL_DROP_INDEX.match(stripped))):
        raise HTTPException(422,"Only one bounded CREATE TABLE/INDEX, ALTER TABLE ADD COLUMN or DROP INDEX may be previewed.")
    original=_schema(con)
    _progress(con)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute(stripped)
        changed=_schema(con)
        con.execute("ROLLBACK")
        restored=_schema(con)
        if restored!=original:
            raise HTTPException(409,"Migration rollback did not restore the original snapshot schema.")
        return {"before":original,"after":changed,"rollback_verified":True,
                "executed_on_temporary_snapshot":True,
                "original_database_written":False,"migration_applied":False,
                "requires_human_review":True}
    except HTTPException:raise
    except sqlite3.DatabaseError as exc:
        raise HTTPException(422,"Migration is invalid or cannot be previewed safely.") from exc
    finally:
        if con.in_transaction:con.execute("ROLLBACK")
        con.set_progress_handler(None,0)

@router.post("/inspect")
def inspect(request:Request,body:ProjectIn):
    studio._auth(request)
    root=studio._project(body.project)
    raw=_source(root,body.path)
    with _connection(raw) as con:
        objects=_schema(con)
    return {"engine":"sqlite3","path":body.path,"database_sha256":hashlib.sha256(raw).hexdigest(),
            "schema":objects,"snapshot_only":True,"source_written":False,
            "dialect_support":{"sqlite":"read_only_snapshot","postgresql":"static_sql_only",
                               "mysql":"static_sql_only"},"no_credentials_or_network":True}

@router.post("/query")
def query(request:Request,body:QueryIn):
    studio._auth(request)
    root=studio._project(body.project)
    raw=_source(root,body.path)
    with _connection(raw) as con:
        result=_query(con,body.sql,body.params)
    return result

@router.post("/migration-preview")
def migration_preview(request:Request,body:MigrationIn):
    studio._auth(request)
    root=studio._project(body.project)
    raw=_source(root,body.path)
    with _connection(raw) as con:
        result=_migrate(con,body.sql)
    return result
