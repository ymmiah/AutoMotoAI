"""V12 manuscript analysis: non-executing, bounded Typst and Quarto inspection."""
from __future__ import annotations
import re
import shutil
from collections import Counter, deque
from pathlib import Path
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from automoto import developer_bibliography as bib
from automoto import developer_index as index
from automoto import developer_latex as latex
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/manuscripts", tags=["developer-manuscripts"])
VERSION = "1.0.0"
MAX_FILES = 32
MAX_DEPTH = 8
MAX_BIB = 12
MAX_SOURCE_BYTES = 96 * 1024
MAX_TOTAL_BYTES = 1024 * 1024
MAX_ITEMS = 120
CITE_KEY = re.compile(r"(?<![\w@])@([A-Za-z][A-Za-z0-9_:./+-]{0,100})")
TYPST_INCLUDE = re.compile(r'(?m)^\s*#include\s*"([^"\r\n]{1,180})"')
TYPST_BIB = re.compile(r'(?m)#bibliography\s*\(\s*"([^"\r\n]{1,180}\.bib)"')
QUARTO_INCLUDE = re.compile(r'\{\{<\s*include\s+([A-Za-z0-9_./-]{1,180}\.(?:qmd|md))\s*>\}\}')
QUARTO_BIB = re.compile(r"(?m)^\s*bibliography:\s*(.+?)\s*$")
QUARTO_CODE = re.compile(r"(?m)^ {0,3}[\x60~]{3,}\s*\{[A-Za-z0-9_-]{1,40}")
HEADER_Q = re.compile(r"(?m)^ {0,3}(#{1,6})\s+(.{1,160})$")
HEADER_T = re.compile(r"(?m)^ {0,3}(={1,6})\s+(.{1,160})$")

class ScanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    main: str = Field(min_length=1, max_length=1024)
    format: Literal["typst", "quarto"]
    active_path: Optional[str] = Field(default=None, max_length=1024)
    active_text: Optional[str] = Field(default=None, max_length=MAX_SOURCE_BYTES)

class StarterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["typst", "quarto"]

def _relative(root: Path, current: str, value: str, extensions: set[str]) -> Optional[str]:
    val = value.strip()
    if (not val or len(val) > 180 or "\x00" in val or "\\" in val
            or val.startswith(("/", "~")) or ":" in val or "?" in val):
        return None
    parts = list(Path(current).parent.as_posix().split("/"))
    if parts == ["."]:
        parts = []
    for part in val.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    if not parts:
        return None
    rel = "/".join(parts)
    if Path(rel).suffix.casefold() not in extensions:
        return None
    if any(index._excluded(x, i < len(parts)-1) for i, x in enumerate(parts)):
        return None
    try:
        dest = studio._path(root, rel)
        if dest == root or not dest.is_file():
            return None
    except (HTTPException, OSError, ValueError):
        return None
    return rel

def _read(root: Path, path: str, active_path: Optional[str],
          active_text: Optional[str]) -> Optional[str]:
    if active_text is not None and path == active_path:
        if len(active_text.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise HTTPException(413, "Unsaved manuscript text is too large.")
        return active_text
    source = index._source(root, path)
    return source[0] if source else None

def _masked(source: str, fmt: str) -> str:
    """Mask literal regions without changing source positions."""
    def blank(match):
        return re.sub(r"[^\n\r]", " ", match.group(0))
    if fmt == "quarto":
        text = re.sub(r"(?ms)^ {0,3}([\x60~]{3,})[^\n]*\n.*?^ {0,3}\1[ \t]*\r?$", blank, source)
        text = re.sub(r"<!--.*?-->", blank, text, flags=re.S)
        text = re.sub(r"(?ms)\A---[^\n]*\n.*?^---[ \t]*\r?$", blank, text, count=1)
        text = re.sub(r"\x60[^\x60\n]{0,2000}\x60", blank, text)
    else:
        text = re.sub(r"(?s)/\*.*?\*/", blank, source)
        text = re.sub(r"(?m)//[^\n]*$", blank, text)
        text = re.sub(r"\x60[^\x60\n]{0,2000}\x60", blank, text)
    return text

def _quarto_bibs(source: str) -> list[str]:
    header = re.match(r"\A---\s*\r?\n(.*?)^---\s*$", source, flags=re.S | re.M)
    if not header:
        return []
    value = QUARTO_BIB.search(header.group(1))
    if not value:
        return []
    raw = value.group(1).strip()
    names = raw[1:-1].split(",") if raw.startswith("[") and raw.endswith("]") else [raw]
    return [name.strip().strip("'\"") for name in names[:MAX_BIB] if name.strip()]

def _scan(root: Path, body: ScanIn) -> dict:
    suffix = ".typ" if body.format == "typst" else ".qmd"
    main = studio._path(root, body.main)
    if not main.is_file() or main.suffix.casefold() != suffix:
        raise HTTPException(422, "Select an existing project-local " + suffix + " manuscript.")
    if body.active_text is not None:
        if not body.active_path:
            raise HTTPException(422, "Unsaved buffer requires an active manuscript path.")
        active = studio._path(root, body.active_path)
        if not active.is_file() or active.suffix.casefold() not in (".typ", ".qmd", ".md"):
            raise HTTPException(422, "Active buffer must be an existing approved manuscript.")
    pending = deque([(body.main, 0)])
    visited, refs, headings = set(), [], []
    bibliography, warnings = set(), []
    total = cells = 0
    while pending:
        path, depth = pending.popleft()
        if path in visited:
            continue
        if len(visited) >= MAX_FILES or depth > MAX_DEPTH:
            warnings.append({"code": "scan-limit", "path": path, "message": "Scan incomplete."})
            break
        visited.add(path)
        text = _read(root, path, body.active_path, body.active_text)
        if text is None:
            warnings.append({"code": "missing-source", "path": path,
                             "message": "Manuscript source is unreadable or oversized."})
            continue
        total += len(text.encode("utf-8"))
        if total > MAX_TOTAL_BYTES:
            warnings.append({"code": "size-limit", "path": path, "message": "Source budget reached."})
            break
        masked = _masked(text, body.format)
        for m in CITE_KEY.finditer(masked):
            key = m.group(1).rstrip(".,;:")
            if key:
                refs.append({"key": key, "path": path,
                             **latex._position(masked, m.start(1))})
        header = HEADER_T if body.format == "typst" else HEADER_Q
        for m in header.finditer(masked):
            headings.append({"title": m.group(2).strip()[:150], "level": len(m.group(1)),
                             "path": path, **latex._position(masked, m.start(2))})
        if body.format == "typst":
            for m in TYPST_BIB.finditer(masked):
                bibliography.add((path, m.group(1)))
            includes = [m.group(1) for m in TYPST_INCLUDE.finditer(masked)]
        else:
            for name in _quarto_bibs(text):
                bibliography.add((path, name))
            includes = [m.group(1) for m in QUARTO_INCLUDE.finditer(masked)]
            cells += len(QUARTO_CODE.findall(text))
        for item in includes[:MAX_FILES]:
            ext = {".typ"} if body.format == "typst" else {".qmd", ".md"}
            target = _relative(root, path, item, ext)
            if not target:
                warnings.append({"code": "missing-or-unsafe-include", "path": path,
                                 "message": "Included source is missing or unsafe."})
            elif target not in visited:
                pending.append((target, depth+1))
    entries, bpaths = [], []
    for source, name in sorted(bibliography)[:MAX_BIB]:
        relative = _relative(root, source, name, {".bib"})
        if not relative:
            warnings.append({"code": "missing-or-unsafe-bibliography", "path": source,
                             "message": "Bibliography is missing or unsafe."})
            continue
        if relative in bpaths:
            continue
        bpaths.append(relative)
        result = index._source(root, relative)
        if result is None:
            warnings.append({"code": "unreadable-bibliography", "path": relative,
                             "message": "Bibliography is unreadable."})
            continue
        total += result[2]
        if total > MAX_TOTAL_BYTES:
            warnings.append({"code": "size-limit", "path": relative, "message": "Budget reached."})
            break
        found, errors = bib._parse_bib(result[0], relative)
        entries.extend(found)
        warnings.extend(errors)
    counts = Counter(e["key"] for e in entries)
    cited = list(dict.fromkeys(item["key"] for item in refs))
    issues = [{"key": e["key"], "issues": ["placeholder metadata"]
               if any(bib.PLACEHOLDER.search(e["fields"].get(f,""))
                      for f in ("author", "title", "journal")) else []}
              for e in entries if e["key"] in cited]
    return {"schema_version": VERSION, "format": body.format, "main": body.main,
            "files": sorted(visited)[:MAX_FILES], "headings": headings[:MAX_ITEMS],
            "citations": refs[:MAX_ITEMS], "cited_keys": cited[:MAX_ITEMS],
            "bibliography_files": bpaths, "bibliography_keys": sorted(counts)[:MAX_ITEMS],
            "missing_citations": [key for key in cited if key not in counts][:MAX_ITEMS],
            "duplicate_keys": [key for key, count in counts.items() if count>1][:MAX_ITEMS],
            "citation_issues": issues[:MAX_ITEMS], "warnings": warnings[:MAX_ITEMS],
            "executable_code_chunks": cells,
            "code_execution_warnings": ["Quarto code cells must not be rendered without separate execution review."] if cells else [],
            "truncated": any(w["code"] in ("scan-limit","size-limit") for w in warnings),
            "static_analysis_only": True, "compiler_executed": False,
            "project_files_modified": False, "citation_identity_verified": False,
            "not_publication_ready": True}

def _starter(fmt: str) -> tuple[str, str]:
    if fmt == "typst":
        return ("manuscript.typ",
                '// REVIEW-ONLY. Verify each claim against its original source.\n'
                '#set page(paper: "a4")\n'
                '= Research manuscript\n'
                '\n== Research question\n\nAuthor a reviewed question.\n'
                '\n== Evidence review\n\nInsert only human-reviewed claims and citations.\n'
                '\n== Method and limitations\n\nDescribe limitations here.\n')
    return ("manuscript.qmd",
            '---\ntitle: "Research manuscript - review draft"\n'
            'format: html\nexecute:\n  enabled: false\n---\n\n'
            '# Research question\n\nAuthor a reviewed question.\n\n'
            '# Evidence review\n\nInsert only human-reviewed claims and citations.\n\n'
            '# Method and limitations\n\nDescribe limitations here.\n')

@router.post("/scan")
def scan(request: Request, body: ScanIn):
    studio._auth(request)
    return _scan(studio._project(body.project), body)

@router.get("/toolchains")
def toolchains(request: Request, project: str):
    studio._auth(request)
    studio._project(project)
    return {"tools": [{"name": name, "installed_path_detected": bool(shutil.which(name)),
                       "executed": False, "version_verified": False}
                      for name in ("typst","quarto","pandoc")],
            "automatic_rendering": False, "quarto_code_cells_executed": False}

@router.post("/starter")
def starter(request: Request, body: StarterIn):
    studio._auth(request)
    path, source = _starter(body.format)
    return {"path": path, "text": source, "copy_only": True,
            "project_written": False, "compiler_executed": False,
            "no_generated_references": True}
