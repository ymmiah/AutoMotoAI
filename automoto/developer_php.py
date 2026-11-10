"""Developer Studio V16 — PHP, Composer and WordPress security-first workflows.

Project reads and proposed WordPress fixes are copy-only. Real PHP tools require
project trust, explicit per-run consent and exact project/source/binary SHA-256
revalidation. External PHP/Composer/project code is NOT sandboxed.
"""
from __future__ import annotations
import hashlib
import json
import re
import shutil
import threading
from pathlib import Path
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from automoto import developer_adapters as adapters
from automoto import developer_editor as editor
from automoto import developer_index as index
from automoto import developer_javascript as js
from automoto import developer_studio as studio

router=APIRouter(prefix="/api/developer/studio/php", tags=["developer-php-wordpress"])
VERSION="1.0.0"
MAX_FILES=50
MAX_MANIFEST=96*1024
MAX_FINDINGS=60
RUN_LOCK=threading.Lock()
PHP_DIAGNOSTIC=re.compile(r"(?im)^(?:PHP\s+)?(?:Parse\s+error|Fatal\s+error|Warning):\s*(.{1,280})$")
PHP_VERSION=re.compile(r"PHP\s+(\d+\.\d+\.\d+)")
WP_HEADER=re.compile(r"(?mi)^\s*\*?\s*(Plugin Name|Version|Requires PHP|Text Domain):[ \t]*(.{1,160})$")
HOOK=re.compile(r"\b(add_action|add_filter|add_shortcode|register_activation_hook|register_deactivation_hook)\s*\(\s*(['\"])([^'\"]{1,160})\2")
ACTIVATION_HOOK=re.compile(r"\b(register_(?:de)?activation_hook)\s*\(\s*__FILE__\s*,",re.I)

def _hooks(text: str) -> list[tuple[str,str]]:
    ordinary=[(m.group(1),m.group(3)) for m in HOOK.finditer(text)]
    lifecycle=[(m.group(1),"__FILE__") for m in ACTIVATION_HOOK.finditer(text)]
    return ordinary+lifecycle

RAW_NOTICE=re.compile(r"(?m)^(?P<indent>[ \t]*)echo[ \t]+\$_GET\[(?P<quote>['\"])notice(?P=quote)\][ \t]*;[ \t]*(?P<end>\r?$)")
RULES=(
    ("raw-superglobal-echo",re.compile(r"\becho\s+\$_(?:GET|POST|REQUEST)\s*\[",re.I),
     "Unescaped request value is echoed; inspect the exact HTML/attribute/URL/JS context."),
    ("eval-php",re.compile(r"\beval\s*\(",re.I),
     "Dynamic PHP evaluation may execute attacker-controlled expressions."),
    ("maybe-unsafe-unserialize",re.compile(r"\bunserialize\s*\(",re.I),
     "Unserialisation of untrusted input can trigger object injection."),
    ("database-query",re.compile(r"\$wpdb\s*->\s*(?:query|get_results|get_row)\s*\(",re.I),
     "Review SQL placeholders, prepare() usage and input escaping; this is not proof of SQL injection."),
    ("wordpress-ajax",re.compile(r"\badd_action\s*\(\s*['\"]wp_ajax_(?:nopriv_)?",re.I),
     "Review callback nonce, authentication, capability checks and output escaping."),
)
TOOLS=("php","composer")
ACTIONS=("version","lint","composer_validate","phpunit","phpstan","psalm")


class InspectIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    project:str=Field(min_length=1,max_length=1024)


class PatchIn(InspectIn):
    path:str=Field(min_length=1,max_length=1024)
    expected_sha256:str=Field(pattern=r"^[a-f0-9]{64}$")


class RunIn(InspectIn):
    task:Literal["version","lint","composer_validate","phpunit","phpstan","psalm"]
    tool:Literal["php","composer"]
    path:Optional[str]=Field(default=None,max_length=1024)
    expected_manifest_sha256:str=Field(pattern=r"^[a-f0-9]{64}$")
    expected_source_sha256:Optional[str]=Field(default=None,pattern=r"^[a-f0-9]{64}$")
    expected_executable:str=Field(min_length=1,max_length=2048)
    expected_sha256:str=Field(pattern=r"^[a-f0-9]{64}$")
    confirmed:Literal[True]
    accept_unsandboxed_execution_and_write_risk:Literal[True]


def _unique(pairs):
    found={}
    for key,value in pairs:
        if key in found:
            raise ValueError("Duplicate Composer JSON key.")
        found[key]=value
    return found


def _composer(root:Path)->tuple[dict,str]:
    content=index._source(root,"composer.json")
    if not content:
        return {"present":False,"require":{},"require-dev":{},"scripts":[]},hashlib.sha256(b"no-composer-json").hexdigest()
    if content[2]>MAX_MANIFEST:
        raise HTTPException(413,"composer.json exceeds the supported manifest size.")
    try:
        data=json.loads(content[0],object_pairs_hook=_unique)
    except (ValueError,TypeError,RecursionError) as exc:
        raise HTTPException(422,"composer.json is malformed or contains duplicate keys.") from exc
    if not isinstance(data,dict):
        raise HTTPException(422,"composer.json must contain an object.")
    deps={}
    for key in ("require","require-dev"):
        value=data.get(key,{})
        if not isinstance(value,dict):
            raise HTTPException(422,"Composer dependency maps must be objects.")
        deps[key]={str(k)[:120]:str(v)[:100] for k,v in list(value.items())[:120]
                   if isinstance(k,str) and isinstance(v,str)}
    scripts=data.get("scripts",{})
    if not isinstance(scripts,dict):
        raise HTTPException(422,"Composer scripts must be an object.")
    return {"present":True,**deps,"scripts":sorted(scripts)[:30],
            "name":str(data.get("name",""))[:160],
            "php_requirement":deps["require"].get("php"),
            "frameworks":[name for name,package in (
                ("Laravel","laravel/framework"),("Symfony","symfony/framework-bundle"),
                ("WordPress","johnpbloch/wordpress"),("PHPUnit","phpunit/phpunit"),
                ("PHPStan","phpstan/phpstan"),("Psalm","vimeo/psalm"))
                if package in {**deps["require"],**deps["require-dev"]}]},content[1]


def _php_source(root:Path,path:str)->tuple[str,str]:
    if not path.lower().endswith(".php"):
        raise HTTPException(422,"Select an existing project-local .php source file.")
    record=index._source(root,path)
    if not record:
        raise HTTPException(403,"PHP source missing, linked, restricted or oversized.")
    return record[0],record[1]


def _issues(text:str,path:str)->list[dict]:
    findings=[]
    for key,pattern,advice in RULES:
        for match in list(pattern.finditer(text))[:MAX_FINDINGS]:
            findings.append({"code":key,"path":path,
                             "line":text.count("\n",0,match.start())+1,
                             "message":advice,"confidence":"lexical-needs-human-review"})
            if len(findings)>=MAX_FINDINGS:
                break
        if len(findings)>=MAX_FINDINGS:
            break
    return findings


def _project(root:Path)->dict:
    composer,manifest=_composer(root)
    files=[]
    truncated=False
    for item,incomplete in index._walk(root):
        if incomplete:
            truncated=True
        if item and item.lower().endswith(".php"):
            if len(files)<MAX_FILES:
                files.append(item)
            else:
                truncated=True
    plugins=[]
    issues=[]
    for path in files:
        text,checksum=_php_source(root,path)
        # WordPress plugin headers must be in the opening comment, not in
        # arbitrary code or a translated/embedded string.
        beginning=text[:8192]
        if beginning.lstrip().startswith("<?php") and "/*" in beginning[:120]:
            h={k.lower().replace(" ","_"):v.strip()
               for k,v in WP_HEADER.findall(beginning.split("*/",1)[0])}
            if h.get("plugin_name"):
                plugins.append({"path":path,"sha256":checksum,
                                "header":h,"hooks":[{"type":kind,"identifier":identifier}
                                                  for kind,identifier in _hooks(text)[:60]]})
        issues.extend(_issues(text,path)[:max(0,MAX_FINDINGS-len(issues))])
    tools=[]
    for name in TOOLS:
        location=shutil.which(name)
        if not location:
            tools.append({"name":name,"status":"unavailable"})
            continue
        if Path(location).suffix.lower() in (".cmd",".bat",".ps1"):
            tools.append({"name":name,"status":"shell_wrapper_blocked"})
            continue
        try:
            verified=adapters._fingerprint(str(Path(location).absolute()),root)
            tools.append({"name":name,"status":"installed_not_executed",**verified})
        except HTTPException:
            tools.append({"name":name,"status":"not_approved"})
    return {"schema_version":VERSION,"composer":composer,
            "composer_sha256":manifest,"php_files":sorted(files),
            "scan_truncated":truncated,"wordpress_plugins":plugins[:25],
            "findings":issues[:MAX_FINDINGS],"toolchains":tools,
            "project_trusted":studio._trusted(root,studio._load()),
            "central_agent_studio":"developer",
            "agent_deployment_handoff_required":True,
            "deployment_started":False,"tool_executed":False,
            "scan_not_security_certification":True,
            "project_files_modified":False}


def _vendor_entry(root:Path,name:str)->str:
    if name not in ("phpunit","phpstan","psalm"):
        raise HTTPException(422,"Unsupported pinned PHP project tool.")
    parts=("vendor","bin",name)
    path=root
    for part in parts:
        path=path/part
        if path.is_symlink() or getattr(path,"is_junction",lambda:False)():
            raise HTTPException(403,"Symlinked project tool requires separate review.")
    if not path.is_file() or path.stat().st_size>1024*1024:
        raise HTTPException(409,"Project-local tool is not installed as a regular PHP entry point.")
    first=path.open("rb").read(256)
    if b"<?php" not in first:
        raise HTTPException(422,"Installed project tool is not a supported PHP entry point.")
    return str(path)


def _command(root:Path,body:RunIn,exe:str)->list[str]:
    if body.task=="version":
        if body.path or body.expected_source_sha256:
            raise HTTPException(422,"Version check does not accept a source file.")
        return [exe,"-v" if body.tool=="php" else "--version"]
    if body.task=="lint":
        if body.tool!="php" or not body.path or not body.expected_source_sha256:
            raise HTTPException(422,"PHP lint requires a file and exact SHA-256.")
        _php_source(root,body.path)
        return [exe,"-l",body.path]
    if body.path or body.expected_source_sha256:
        raise HTTPException(422,"Project-wide tools do not accept a source-file override.")
    if body.task=="composer_validate":
        if body.tool!="composer":
            raise HTTPException(422,"Composer validation requires an approved Composer executable.")
        return [exe,"--no-plugins","validate","--no-check-publish","--no-interaction"]
    if body.tool!="php":
        raise HTTPException(422,"Test and static-analysis tools run with the selected PHP interpreter.")
    if body.task=="phpunit":
        return [exe,_vendor_entry(root,"phpunit"),"--colors=never"]
    if body.task=="phpstan":
        return [exe,_vendor_entry(root,"phpstan"),"analyse","--no-progress","--error-format=raw"]
    if body.task=="psalm":
        return [exe,_vendor_entry(root,"psalm"),"--no-progress","--output-format=console"]
    raise HTTPException(422,"Unsupported PHP task.")


def _patch(root:Path,path:str,digest:str)->dict:
    source,original=_php_source(root,path)
    if original!=digest:
        raise HTTPException(409,"WordPress source changed; inspect before preparing a fix.")
    if not source.lstrip().startswith("<?php"):
        raise HTTPException(422,"Not a PHP source file.")
    headers=dict((k.lower(),v) for k,v in WP_HEADER.findall(source[:8192].split("*/",1)[0]))
    if "plugin name" not in headers:
        raise HTTPException(422,"Choose an existing file with a WordPress plugin header.")
    matches=list(RAW_NOTICE.finditer(source))
    if len(matches)!=1:
        raise HTTPException(422,"This narrow fix requires exactly one literal echo of the notice GET field.")
    target=matches[0]
    fixed=(target.group("indent")+
           "echo isset( $_GET['notice'] ) ? esc_html( sanitize_text_field( wp_unslash( $_GET['notice'] ) ) ) : '';"+
           target.group("end"))
    after=source[:target.start()]+fixed+source[target.end():]
    before_hooks=_hooks(source)
    after_hooks=_hooks(after)
    if before_hooks!=after_hooks or len(after.encode("utf-8"))>editor.MAX_BYTES:
        raise HTTPException(409,"Patch does not preserve hooks or exceeds the editor size limit.")
    return {"path":path,"source_sha256":original,"patched_text":after,
            "patched_sha256":hashlib.sha256(after.encode("utf-8")).hexdigest(),
            "finding":"raw-superglobal-echo",
            "mitigation":"check missing input, unslash, sanitise text, escape HTML output",
            "preserved_hooks":len(before_hooks),
            "preview_only":True,"existing_settings_untouched":True,
            "saved":False,"linted":False,"agent_deployment_approved":False,
            "instructions":"Review both versions, validate the exact HTML context, and use V2 guarded save with the original SHA-256. Run PHP -l and plugin tests before agent deployment-readiness review."}


@router.get("/inspect")
def inspect(request:Request,project:str):
    studio._auth(request)
    return _project(studio._project(project))


@router.post("/patch-preview")
def patch_preview(request:Request,body:PatchIn):
    studio._auth(request)
    root=studio._project(body.project)
    return _patch(root,body.path,body.expected_sha256)


@router.post("/run")
def run(request:Request,body:RunIn):
    studio._auth(request)
    root=studio._project(body.project)
    adapters._trusted(root)
    if not RUN_LOCK.acquire(blocking=False):
        raise HTTPException(429,"A PHP toolchain task is already running.")
    try:
        before=_project(root)
        if body.expected_manifest_sha256!=before["composer_sha256"]:
            raise HTTPException(409,"Composer manifest changed since inspection.")
        tool=next((x for x in before["toolchains"] if x["name"]==body.tool),None)
        if not tool or tool["status"]!="installed_not_executed":
            raise HTTPException(409,"Approved PHP/Composer binary is unavailable.")
        if tool["sha256"]!=body.expected_sha256 or tool["executable"]!=body.expected_executable:
            raise HTTPException(409,"The system tool binary changed since approval.")
        if body.task=="lint":
            if not body.path or not body.expected_source_sha256:
                raise HTTPException(422,"PHP lint requires a source SHA-256.")
            _,source_sha=_php_source(root,body.path)
            if source_sha!=body.expected_source_sha256:
                raise HTTPException(409,"The PHP source changed since approval.")
        command=_command(root,body,tool["executable"])
        if _composer(root)[1]!=before["composer_sha256"]:
            raise HTTPException(409,"Composer manifest changed during task preparation.")
        if body.task=="lint" and _php_source(root,body.path)[1]!=body.expected_source_sha256:
            raise HTTPException(409,"PHP source changed while preparing the task.")
        adapters._trusted(root)
        verified=adapters._fingerprint(tool["executable"],root)
        if verified["sha256"]!=body.expected_sha256:
            raise HTTPException(409,"PHP tool binary changed during preparation.")
        record={"id":"php16-"+body.task,"category":"test",
                "executable":tool["executable"],"sha256":tool["sha256"],
                "args":command[1:],"project_identity":studio._identity(root)}
        # V13 reuses V8's scrubbed environment, no shell and bounded output.
        result=js._run_task(root,record)
        result.update({"task":body.task,"tool":body.tool,
                       "composer_sha256":body.expected_manifest_sha256,
                       "agent_linked":True,"agent_deployment_approved":False,
                       "deployment_started":False,"external_process_unsandboxed":True,
                       "files_unchanged":"not_verified",
                       "php_version":(PHP_VERSION.search(result["output"]).group(1)
                                      if body.task=="version" and body.tool=="php"
                                      and PHP_VERSION.search(result["output"]) else None),
                       "diagnostics":[{"message":m.group(1).strip()}
                                      for m in list(PHP_DIAGNOSTIC.finditer(result["output"]))[:30]]})
        return result
    finally:
        RUN_LOCK.release()
