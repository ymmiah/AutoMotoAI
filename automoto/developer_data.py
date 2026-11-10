"""V15 static GraphQL SDL/operation and SQL dialect inspection. Never sends queries."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from automoto import developer_index as index
from automoto import developer_studio as studio

router=APIRouter(prefix="/api/developer/studio/data",tags=["developer-data"])
MAX_BYTES=96*1024
MAX_TYPES=80
MAX_FIELDS=80
MAX_DEPTH=12
TYPE=re.compile(r"\b(type|interface|input|enum)\s+([A-Za-z_][A-Za-z0-9_]{0,80})\s*\{",re.I)
FIELD=re.compile(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]{0,80})\s*(?:\([^{}\r\n]{0,240}\))?\s*:\s*([\[\]!A-Za-z_0-9]{1,120})")
SQL_DIALECTS={
 "postgresql":(("serial",r"\bSERIAL\b"),("returning",r"\bRETURNING\b"),
               ("jsonb",r"\bJSONB\b"),("citext",r"\bCITEXT\b")),
 "mysql":(("auto_increment",r"\bAUTO_INCREMENT\b"),("engine",r"\bENGINE\s*="),
          ("backticks",r"\x60[^\x60]+\x60")),
 "sqlite":(("without_rowid",r"\bWITHOUT\s+ROWID\b"),("strict",r"\bSTRICT\b"))
}

class ScanIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    project:str=Field(min_length=1,max_length=1024)
    path:str=Field(min_length=1,max_length=1024)
    dialect:Literal["graphql","sqlite","postgresql","mysql"]

class OperationIn(ScanIn):
    operation:str=Field(min_length=1,max_length=8192)

def _read(root:Path,path:str,dialect:str)->str:
    permitted={".graphql",".gql"} if dialect=="graphql" else {".sql"}
    if Path(path).suffix.casefold() not in permitted:
        raise HTTPException(422,"Choose a project-local schema file of the selected dialect.")
    source=index._source(root,path)
    if not source or source[2]>MAX_BYTES:
        raise HTTPException(403,"Schema file missing, unsafe or oversized.")
    return source[0]

def _mask(text:str)->str:
    out=re.sub(r'"""[\s\S]*?"""',lambda m:" "*len(m.group(0)),text)
    out=re.sub(r'"(?:\\.|[^"\\])*"',lambda m:" "*len(m.group(0)),out)
    out=re.sub(r"(?m)#[^\n]*",lambda m:" "*len(m.group(0)),out)
    return out

def _schema(text:str)->list[dict]:
    masked=_mask(text)
    types=[]
    for match in TYPE.finditer(masked):
        if len(types)>=MAX_TYPES:break
        index_=match.end()
        level=1
        end=index_
        while end<len(masked) and level:
            if masked[end]=="{":level+=1
            if masked[end]=="}":level-=1
            end+=1
        if level!=0:
            raise HTTPException(422,"Unbalanced GraphQL schema block.")
        fields=[{"name":x.group(1),"type":x.group(2)}
                for x in FIELD.finditer(masked[index_:end-1])][:MAX_FIELDS]
        types.append({"kind":match.group(1).lower(),"name":match.group(2),"fields":fields})
    return types

def _operation(text:str,types:list[dict])->dict:
    masked=_mask(text)
    if len(masked)>8192 or any(x in masked for x in ("@defer","@stream")):
        raise HTTPException(422,"Unsupported query shape for static review.")
    if re.search(r"\b(mutation|subscription)\b",masked,re.I):
        return {"allowed":False,"reason":"Writes/subscriptions are not approved in V15.",
                "sent_to_server":False,"validated_semantically":False}
    if not re.match(r"(?is)^\s*(?:query\b[^{}]{0,250})?\s*\{",masked):
        return {"allowed":False,"reason":"Only a basic query operation is supported.",
                "sent_to_server":False,"validated_semantically":False}
    level=0
    max_depth=0
    for ch in masked:
        if ch=="{":
            level+=1;max_depth=max(max_depth,level)
        elif ch=="}":
            level-=1
            if level<0:break
    if level!=0 or max_depth>MAX_DEPTH:
        return {"allowed":False,"reason":"GraphQL selection braces are unbalanced or too deep.",
                "sent_to_server":False,"validated_semantically":False}
    root=next((x for x in types if x["kind"]=="type" and x["name"]=="Query"),None)
    if root is None:
        return {"allowed":False,"reason":"No Query root type was declared.",
                "sent_to_server":False,"validated_semantically":False}
    declared={x["name"] for x in root["fields"]}
    body=masked[masked.index("{")+1:]
    fields=[]
    depth=1
    for line in body.splitlines():
        stripped=line.strip()
        if depth==1:
            hit=re.match(r"^(?:[A-Za-z_][\w]*\s*:\s*)?([A-Za-z_][\w]*)",stripped)
            if hit and not stripped.startswith(("...", "__")):
                fields.append(hit.group(1))
        depth+=line.count("{")-line.count("}")
    missing=sorted(set(fields)-declared)
    return {"allowed":not missing,"missing_root_fields":missing,
            "root_fields":fields[:MAX_FIELDS],"depth":max_depth,
            "reason":"Static root-field approximation only; no semantic/runtime validation.",
            "sent_to_server":False,"validated_semantically":False,
            "approved_for_execution":False}

@router.post("/inspect")
def inspect(request:Request,body:ScanIn):
    studio._auth(request)
    root=studio._project(body.project)
    text=_read(root,body.path,body.dialect)
    if body.dialect=="graphql":
        return {"dialect":"graphql","types":_schema(text),"static_only":True,
                "network_used":False,"query_executed":False,
                "semantically_validated":False}
    clues=[{"name":label,"matched":bool(re.search(pattern,text,re.I))}
           for label,pattern in SQL_DIALECTS[body.dialect]]
    return {"dialect":body.dialect,"static_dialect_clues":clues,
            "schema_navigation":"unsupported_without_reviewed_backend",
            "network_used":False,"sql_executed":False,
            "migration_applied":False,"not_database_connected":True}

@router.post("/graphql-review")
def graphql_review(request:Request,body:OperationIn):
    studio._auth(request)
    if body.dialect!="graphql":
        raise HTTPException(422,"GraphQL review requires a local SDL schema.")
    root=studio._project(body.project)
    schema=_schema(_read(root,body.path,"graphql"))
    return {"schema_path":body.path,**_operation(body.operation,schema)}
