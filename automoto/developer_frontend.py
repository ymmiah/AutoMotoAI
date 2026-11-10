"""Developer Studio V14: read-only frontend inventory, heuristic a11y and inert previews.

No source JavaScript, CSS import, network asset, package manager, server, filter,
framework renderer or browser automation is started by these endpoints.
HTML output is explicitly allowlisted, with strict CSP and sandboxed srcdoc UI.
"""
from __future__ import annotations

import hashlib
import html
import os
import re
import stat
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_index as idx
from automoto import developer_javascript as js
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/frontend", tags=["developer-frontend"])
MAX_BYTES = 96 * 1024
MAX_SCAN = 100
MAX_ISSUES = 100
MAX_NODES = 600
MAX_RULES = 100
FORMATS = {".html":"HTML", ".css":"CSS", ".scss":"SCSS", ".jsx":"JSX",
           ".tsx":"TSX", ".vue":"Vue", ".svelte":"Svelte"}
FRAMEWORK_FILES = {
    "Next.js": ("next.config.js","next.config.mjs","next.config.ts"),
    "Angular": ("angular.json",),
    "SvelteKit": ("svelte.config.js","svelte.config.ts"),
    "Nuxt": ("nuxt.config.js","nuxt.config.ts"),
    "Vite": ("vite.config.js","vite.config.ts"),
}
DANGEROUS = {"script","style","template","svg","math","iframe","object",
             "video","audio","canvas","form","frame","frameset","portal",
             "picture","noscript"}
DROP_VOID = {"embed","source","link","meta","base","param","track","wbr","area"}
TAGS = {"div","span","p","h1","h2","h3","h4","h5","h6",
        "header","footer","main","nav","section","article","aside",
        "ul","ol","li","strong","em","b","i","small","code","pre",
        "blockquote","hr","br","button","label","input","textarea",
        "select","option","a","table","thead","tbody","tr","th","td",
        "figure","figcaption","details","summary"}
VOID = {"hr","br","input"}
ATTR = {"class","id","title","role","lang","dir","for","type","name",
        "placeholder","value","disabled","checked","selected",
        "tabindex","colspan","rowspan"}
SAFE_VALUE = re.compile(r"^[A-Za-z0-9 _.,:#/()'\-]{0,180}$")
SELECTOR = re.compile(r"^(?:[A-Za-z][\w-]*|\.[A-Za-z][\w-]*|#[A-Za-z][\w-]*)$")
CSS_VALUE = re.compile(r"^[A-Za-z0-9#.,%()/ \-]{1,100}$")
PROPERTIES = {"color","background","background-color","display","padding",
              "padding-top","padding-bottom","padding-left","padding-right",
              "margin","margin-top","margin-bottom","margin-left","margin-right",
              "gap","width","max-width","min-width","height","min-height",
              "border","border-color","border-width","border-style","border-radius",
              "font-size","font-weight","font-family","line-height","text-align",
              "flex","flex-direction","flex-wrap","align-items","justify-content",
              "grid-template-columns","box-sizing","overflow-wrap"}
CSP = ("default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; "
       "img-src 'none'; font-src 'none'; connect-src 'none'; form-action 'none'; "
       "base-uri 'none'; object-src 'none'; frame-src 'none'")
SOURCE_TAG = re.compile(r"(?i)<(?:img|button|input|a|h[1-6])\b")
SCSS_MIXIN = re.compile(r"(?m)^\s*@(mixin|include|use|forward|import)\b")


class RootIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)


class PreviewIn(RootIn):
    path: str = Field(min_length=1, max_length=1024)
    stylesheet: Optional[str] = Field(default=None, max_length=1024)


def _read(root: Path, rel: str, suffixes: set[str]) -> tuple[str, str]:
    if Path(rel).suffix.lower() not in suffixes:
        raise HTTPException(422, "Select a supported frontend source file.")
    file = studio._path(root, rel)
    if not file.is_file():
        raise HTTPException(404, "Selected frontend file does not exist.")
    if any(idx._excluded(part, i < len(rel.split("/"))-1)
           for i, part in enumerate(rel.split("/"))):
        # Only built HTML is an explicit exception to V7's generated-file
        # exclusion. It is never interpreted or executed as an application.
        if not (len(rel.split("/")) == 2
                and rel.split("/")[0] in {"dist","build","out"}
                and rel.split("/")[1] == "index.html"):
            raise HTTPException(403, "Restricted or generated paths are not inspectable.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(file, flags)
        with os.fdopen(fd, "rb") as source:
            st = os.fstat(source.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_BYTES:
                raise HTTPException(413, "Frontend source exceeds the preview limit.")
            raw = source.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES or b"\x00" in raw:
            raise HTTPException(413, "Frontend file is oversized or binary.")
        return raw.decode("utf-8-sig"), hashlib.sha256(raw).hexdigest()
    except HTTPException:
        raise
    except (OSError, UnicodeError) as exc:
        raise HTTPException(422, "Frontend source is unavailable or is not UTF-8.") from exc


class _Audit(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.issues=[]
        self.lang=False
        self.viewport=False
        self.ids=[]
        self.labels=set()
        self.inputs=[]
        self.heading=0
        self.has_h1=False
        self.button=None
        self.link=None
        self.links=[]
        self.images=0
        self.nodes=0

    def issue(self, code: str, message: str):
        if len(self.issues) < MAX_ISSUES:
            self.issues.append({"code":code,"message":message,
                                "line":self.getpos()[0],"column":self.getpos()[1]})

    def handle_starttag(self, tag, pairs):
        self.nodes += 1
        if self.nodes > MAX_NODES:
            return
        attrs=dict(pairs)
        if tag=="html" and attrs.get("lang","").strip():
            self.lang=True
        if tag=="meta" and attrs.get("name","").lower()=="viewport":
            self.viewport=True
        if attrs.get("id"):
            self.ids.append(attrs["id"])
        if tag=="label" and attrs.get("for"):
            self.labels.add(attrs["for"])
        if tag=="img":
            self.images+=1
            if "alt" not in attrs:
                self.issue("image-alt","Image has no alt attribute (decorative images may use alt='').")
        if tag in {"input","select","textarea"} and attrs.get("type")!="hidden":
            self.inputs.append((attrs.get("id"), bool(attrs.get("aria-label") or attrs.get("aria-labelledby")),
                                self.getpos()[0]))
        if tag=="button":
            self.button={"name":bool(attrs.get("aria-label") or attrs.get("aria-labelledby")),
                         "text":"","line":self.getpos()[0]}
        if tag=="a":
            self.link={"name":bool(attrs.get("aria-label") or attrs.get("aria-labelledby")),
                       "text":"","line":self.getpos()[0]}
        if tag in {"h1","h2","h3","h4","h5","h6"}:
            level=int(tag[1])
            if level==1:self.has_h1=True
            if self.heading and level > self.heading+1:
                self.issue("heading-order","Heading level jumps from h%d to h%d."%(self.heading,level))
            self.heading=level

    def handle_data(self,data):
        if self.button:self.button["text"] += data[:300]
        if self.link:self.link["text"] += data[:300]

    def handle_endtag(self,tag):
        if tag=="button" and self.button:
            if not (self.button["name"] or self.button["text"].strip()):
                self.issue("button-name","Button has no discernible text or ARIA name.")
            self.button=None
        if tag=="a" and self.link:
            if not (self.link["name"] or self.link["text"].strip()):
                self.issue("link-name","Link has no discernible text or ARIA name.")
            self.link=None

    def finalise(self):
        if not self.lang:self.issue("document-language","HTML document language is missing.")
        if not self.viewport:self.issue("viewport","No responsive viewport meta declaration found.")
        if not self.has_h1:self.issue("heading-h1","No h1 heading found in the inspected HTML.")
        seen=Counter(self.ids)
        for value,count in seen.items():
            if count>1:self.issue("duplicate-id","Duplicate id attribute: "+value[:65])
        for field,aria,line in self.inputs:
            if not aria and (not field or field not in self.labels):
                if len(self.issues)<MAX_ISSUES:
                    self.issues.append({"code":"input-name","message":"Form control lacks an explicit label.",
                                        "line":line,"column":0})
        if self.nodes>MAX_NODES:self.issue("audit-limit","HTML element cap reached; audit incomplete.")
        return self.issues


class _SafeHTML(HTMLParser):
    """Emits only escaped, known inert tags; never exposes original active HTML."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output=[]
        self.skip=0
        self.stack=[]
        self.nodes=0
        self.omitted=0

    def handle_starttag(self,tag,pairs):
        if self.skip:
            if tag in DANGEROUS:self.skip+=1
            return
        if tag in DROP_VOID:
            self.omitted+=1
            return
        if tag in DANGEROUS:
            self.skip=1
            self.omitted+=1
            return
        if tag=="img":
            self.omitted+=1
            alt=dict(pairs).get("alt") or "image omitted"
            self.output.append('<span role="img" aria-label="'+html.escape(alt[:100],quote=True)+'">[image]</span>')
            return
        if tag not in TAGS:
            self.omitted+=1
            return
        if self.nodes>=MAX_NODES:return
        self.nodes+=1
        safe=[]
        for key,value in pairs:
            if value is None: value=""
            if key in ATTR or (key.startswith("aria-") and len(key)<45):
                if len(value)<=180 and SAFE_VALUE.fullmatch(value):
                    safe.append(key+'="'+html.escape(value,quote=True)+'"')
            if tag=="a" and key=="href" and re.fullmatch(r"#[A-Za-z][\w-]{0,90}",value):
                safe.append('href="'+html.escape(value,quote=True)+'"')
        self.output.append("<"+tag+(" "+" ".join(safe) if safe else "")+">")
        if tag not in VOID:self.stack.append(tag)

    def handle_endtag(self,tag):
        if self.skip:
            if tag in DANGEROUS:self.skip-=1
            return
        if tag in self.stack:
            while self.stack:
                top=self.stack.pop()
                self.output.append("</"+top+">")
                if top==tag:break

    def handle_data(self,data):
        if not self.skip and len(self.output)<MAX_NODES*4:
            self.output.append(html.escape(data[:6000]))

    def finalise(self):
        while self.stack:self.output.append("</"+self.stack.pop()+">")
        return "".join(self.output)[:90000]


def _css_preview(source: str) -> tuple[str,int]:
    """Conservative layout subset, not a full CSS/SCSS renderer."""
    source=re.sub(r"/\*.*?\*/","",source,flags=re.S)
    output=[]
    rejected=0
    for selector, body in re.findall(r"([^{}]{1,200})\{([^{}]{0,1600})\}",source)[:MAX_RULES]:
        fragments=[x.strip() for x in selector.strip().split(",")]
        if not fragments or len(fragments)>5 or not all(SELECTOR.fullmatch(x) for x in fragments):
            rejected+=1
            continue
        declarations=[]
        for entry in body.split(";")[:30]:
            if ":" not in entry:continue
            prop,value=(x.strip() for x in entry.split(":",1))
            if prop not in PROPERTIES or not CSS_VALUE.fullmatch(value):
                rejected+=1
                continue
            low=value.lower()
            if any(x in low for x in ("url(","var(","attr(","expression(","image-set(","javascript","@import")):
                rejected+=1
                continue
            declarations.append(prop+":"+value)
        if declarations:
            output.append(",".join(fragments)+"{"+";".join(declarations)+"}")
    return "\n".join(output)[:16000],rejected


def _framework_inventory(root:Path) -> dict:
    try:
        package=js._manifest(root)[0]
    except HTTPException:
        package=None
    framework=list(package["frameworks"]) if package else []
    seen={x["name"] for x in framework}
    markers=[]
    for name,paths in FRAMEWORK_FILES.items():
        for path in paths:
            try:
                f=studio._path(root,path)
                if f.is_file():
                    markers.append(path)
                    if name not in seen:
                        framework.append({"name":name,"declared_package":None,
                                          "declared_version":None})
                        seen.add(name)
                    break
            except (HTTPException,OSError):
                pass
    return {"frameworks":framework,"config_markers":markers,
            "package_manifest_sha256":package["package_json_sha256"] if package else None,
            "build_script_available":bool(package and "build" in package["scripts"]),
            "installed_framework_versions_verified":False,
            "framework_rendered":False}


@router.get("/inspect")
def inspect(request:Request,project:str):
    studio._auth(request)
    root=studio._project(project)
    files=[]
    truncated=False
    formats=Counter()
    for item,issue in idx._walk(root):
        if issue:truncated=True
        if item and Path(item).suffix.lower() in FORMATS:
            formats[FORMATS[Path(item).suffix.lower()]]+=1
            if len(files)<MAX_SCAN:files.append(item)
            else:truncated=True
    return {"schema_version":14,"files":sorted(files),"formats":dict(formats),
            "truncated":truncated,**_framework_inventory(root),
            "no_execution":True,"no_network":True,"project_files_modified":False,
            "responsive_preview_mode":"sanitised_static_only",
            "framework_requires_approved_v13_build":True}


@router.post("/preview")
def preview(request:Request,body:PreviewIn):
    studio._auth(request)
    root=studio._project(body.project)
    if Path(body.path).suffix.lower()!=".html":
        raise HTTPException(422,"V14 static browser preview requires HTML, not executable JSX/TSX/Vue/Svelte source.")
    text,sha=_read(root,body.path,{".html"})
    audit=_Audit()
    audit.feed(text)
    issues=audit.finalise()
    san=_SafeHTML()
    san.feed(text)
    result=san.finalise()
    css=""
    rejected=0
    stylesheet=None
    if body.stylesheet:
        if Path(body.stylesheet).suffix.lower()!=".css":
            raise HTTPException(422,"Only existing local plain CSS is supported; SCSS needs an approved build.")
        source,_=_read(root,body.stylesheet,{".css"})
        css,rejected=_css_preview(source)
        stylesheet=body.stylesheet
    # srcdoc is additionally rendered with iframe sandbox="" and no
    # allow-same-origin or allow-scripts by the actual V14 browser UI.
    # CSP must appear before any source-derived content.
    doc=('<!doctype html><html><head><meta charset="utf-8">'
         '<meta http-equiv="Content-Security-Policy" content="'+html.escape(CSP,quote=True)+'">'
         '<meta name="viewport" content="width=device-width,initial-scale=1">'
         '<style>*{box-sizing:border-box}body{margin:0;padding:16px;'
         'font-family:system-ui,sans-serif;line-height:1.5;overflow-wrap:anywhere}'
         +css+'</style></head><body>'+result+'</body></html>')
    return {"path":body.path,"source_sha256":sha,"stylesheet":stylesheet,
            "srcdoc":doc,"html_issues":issues,"issues_truncated":len(issues)>=MAX_ISSUES,
            "omitted_html_elements":san.omitted,
            "rejected_unsafe_or_unsupported_css_declarations":rejected,
            "sanitised_static_only":True,"source_javascript_executed":False,
            "framework_jsx_tsx_rendered":False,"external_assets_loaded":False,
            "source_files_modified":False,
            "preview_viewports":[375,768,1440],
            "csp":CSP,"iframe_sandbox_attribute":""}


@router.post("/audit")
def audit(request:Request,body:PreviewIn):
    studio._auth(request)
    root=studio._project(body.project)
    suffix=Path(body.path).suffix.lower()
    if suffix not in FORMATS:
        raise HTTPException(422,"Select a supported HTML/CSS/SCSS/JSX/TSX/Vue/Svelte file.")
    text,sha=_read(root,body.path,{suffix})
    issues=[]
    notes=[]
    if suffix==".html":
        scan=_Audit();scan.feed(text);issues=scan.finalise()
        notes.append("HTML checks are heuristics, not an automated WCAG 2.2 certification.")
    elif suffix in (".css",".scss"):
        if re.search(r"@import\b|url\s*\(|image-set\s*\(",text,re.I):
            issues.append({"code":"remote-resource-risk","message":"CSS references imports or URLs; V14 never resolves or fetches them.","line":1,"column":0})
        if re.search(r"(?i)min-width\s*:\s*(?:[5-9]\d{2}|[1-9]\d{3,})px",text):
            issues.append({"code":"fixed-min-width","message":"Large minimum width may cause narrow-screen overflow.","line":1,"column":0})
        if suffix==".scss" and SCSS_MIXIN.search(text):
            notes.append("SCSS requires a separately installed compiler; V14 does not evaluate imports, mixins or variables.")
        notes.append("CSS inspection cannot certify runtime contrast, overflow or computed accessibility.")
    else:
        notes.append("Component source uses dynamic framework syntax; V14 cannot establish actual DOM accessibility without a real build/render.")
        if SOURCE_TAG.search(text):
            notes.append("Detected potential interactive markup; inspect the rendered app in a browser.")
    return {"path":body.path,"format":FORMATS[suffix],
            "source_sha256":sha,"issues":issues[:MAX_ISSUES],
            "limitations":notes,"static_only":True,
            "actual_render_and_wcag_verified":False,"source_files_modified":False}
