"""Developer Studio V11 — consent-bound local TeX build and ephemeral PDF preview.

Compiles a bounded, validated SOURCE SNAPSHOT, never the user's project tree.
Tectonic is invoked untrusted/offline; latexmk uses an empty rc configuration,
explicit no-shell-escape and an ephemeral HOME. External TeX engines are NOT
OS-sandboxed: explicit per-run consent is required and this is not a guarantee
against malicious macros or engine bugs.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path, PurePosixPath
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_adapters as adapters
from automoto import developer_bibliography as bibliography
from automoto import developer_index as source_index
from automoto import developer_latex as latex
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/texbuild", tags=["developer-texbuild"])
SCHEMA = "1.0.0"
MAX_INPUT_FILES = 96
MAX_FIGURES = 24
MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_ASSET_BYTES = 2 * 1024 * 1024
MAX_PDF_BYTES = 4 * 1024 * 1024
MAX_LOG_BYTES = 64 * 1024
MAX_SYNCTEX_BYTES = 2 * 1024 * 1024
MAX_SYNCTEX_EXPANDED = 8 * 1024 * 1024
MAX_SYNCTEX_RECORDS = 5000
MAX_DIAGNOSTICS = 100
MAX_RUN_SECONDS = 15.0
MAX_PREVIEWS = 3
PREVIEW_TTL = 600
RUN_LOCK = threading.Lock()
PREVIEW_LOCK = threading.RLock()
PREVIEWS: "OrderedDict[str, dict]" = OrderedDict()

FIGURE = re.compile(r"\\includegraphics(?:\s*\[[^\]\r\n]{0,256}\])?\s*\{([^{}\r\n]{1,180})\}")
TABLE = re.compile(r"\\begin\s*\{table\*?\}")
CAPTION = re.compile(r"\\caption(?:\s*\[[^\]\r\n]{0,140}\])?\s*\{([^{}\r\n]{1,140})\}")
SHELL_COMMAND = re.compile(
    r"\\(?:write\s*18|immediate\s*\\write\s*18|input\s*\||openout\s*18|"
    r"usepackage(?:\s*\[[^\]\r\n]{0,80}\])?\s*\{minted\}|"
    r"begin\s*\{(?:minted|pythontex|shellescape)\})", re.I)
OUTPUT_CODE = re.compile(r"^(?:(?P<path>[^:\r\n]{1,240}\.tex):)?(?P<line>\d{1,7}):\s*(?P<message>.{1,260})$")
SYNC_INPUT = re.compile(r"^Input:(\d{1,5}):(.{1,1024})$")
SYNC_RECORD = re.compile(r"^[\[\]hvkgx]\s*(\d+),(\d+):(-?\d+),(-?\d+)(?::|,)")
SYNC_PAGE = re.compile(r"^\{(\d{1,5})$")
ASSET_EXTS = (".png", ".jpg", ".jpeg", ".pdf")


class RootIn(latex.ProjectIn):
    pass


class BuildIn(RootIn):
    engine: Literal["tectonic", "latexmk"]
    expected_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    confirmed: Literal[True]
    acknowledge_external_process_risk: Literal[True]


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    build_id: str = Field(min_length=32, max_length=120)


class JumpIn(PreviewIn):
    path: str = Field(min_length=1, max_length=1024)
    line: int = Field(ge=1, le=1000000)


class PageIn(PreviewIn):
    page: int = Field(ge=1, le=10000)


def _trust(root: Path) -> None:
    with studio.STATE_LOCK:
        if not studio._trusted(root, studio._load()):
            raise HTTPException(403, "Trust this exact local workspace before running a TeX engine.")


def _engines(root: Path) -> list[dict]:
    choices = []
    for engine in ("tectonic", "latexmk"):
        found = shutil.which(engine)
        if not found:
            choices.append({"name": engine, "status": "unavailable"})
            continue
        try:
            result = adapters._fingerprint(str(Path(found).absolute()), root)
            choices.append({"name": engine, "status": "installed_not_executed",
                            **result})
        except HTTPException:
            choices.append({"name": engine, "status": "not_approved"})
    return choices


def _selected(root: Path, body: BuildIn) -> dict:
    tool = next((x for x in _engines(root) if x["name"] == body.engine), None)
    if not tool or tool["status"] != "installed_not_executed":
        raise HTTPException(409, "This compiler is not installed as an approved system executable.")
    if tool["sha256"] != body.expected_sha256 or tool["executable"] != body.expected_executable:
        raise HTTPException(409, "Compiler path or SHA-256 has changed; inspect and approve again.")
    return tool


def _safe_figure(root: Path, from_file: str, value: str) -> Optional[str]:
    """Only directly named, project-local PNG/JPEG/PDF figure files are supported."""
    suffix = PurePosixPath(value).suffix.casefold()
    choices = (suffix,) if suffix else ASSET_EXTS
    for ext in choices:
        if ext not in ASSET_EXTS:
            continue
        rel = latex._safe_relative(root, from_file, value, ext)
        if rel is not None and (root / rel).is_file():
            return rel
    return None


def _safe_binary_source(root: Path, relative: str) -> bytes:
    """No symlinks, large files or non-regular source files."""
    path = studio._path(root, relative)
    if path == root or not path.is_file() or path.is_symlink():
        raise HTTPException(403, "Figure or source is outside approved project files.")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
                     getattr(os, "O_BINARY", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ASSET_BYTES:
                raise HTTPException(413, "Figure exceeds the safe asset size limit.")
            raw = stream.read(MAX_ASSET_BYTES + 1)
            if len(raw) > MAX_ASSET_BYTES:
                raise HTTPException(413, "Figure exceeds the safe asset size limit.")
            if path.suffix.casefold() == ".pdf" and not raw.startswith(b"%PDF-"):
                raise HTTPException(422, "PDF figure lacks a valid PDF header.")
            if path.suffix.casefold() == ".png" and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                raise HTTPException(422, "PNG figure lacks a valid PNG header.")
            if path.suffix.casefold() in (".jpg", ".jpeg") and not raw.startswith(b"\xff\xd8"):
                raise HTTPException(422, "JPEG figure lacks a valid JPEG header.")
            return raw
    except HTTPException:
        raise
    except (OSError, ValueError) as exc:
        raise HTTPException(422, "Figure cannot be read safely.") from exc


def _snapshot(root: Path, body: RootIn, stage: Path) -> dict:
    """Prepare only V9-inspected TeX/BibTeX files and directly referenced figures."""
    graph = latex._analyse(root, body)
    blockers = {"unsafe-include", "missing-include", "unreadable-tex",
                "unsafe-bibliography", "missing-bibliography", "unreadable-bibliography"}
    if graph["truncated"] or any(x["code"] in blockers for x in graph["diagnostics"]):
        raise HTTPException(409, "LaTeX source graph is incomplete or contains an unsafe include.")
    sources = {}
    figures = []
    tables = []
    digest = hashlib.sha256()
    paths = list(graph["files"])
    bib_paths = bibliography._bib_sources(root, body, graph)
    if len(paths) + len(bib_paths) > MAX_INPUT_FILES:
        raise HTTPException(413, "Too many source files for a bounded build.")
    for rel in sorted(set(paths + bib_paths)):
        text = latex._read(root, rel, body.active_path, body.active_text) if rel.endswith(".tex") else None
        if text is None:
            record = source_index._source(root, rel)
            if record is None:
                raise HTTPException(409, "Referenced bibliography or TeX source is unreadable.")
            raw = (record[0]).encode("utf-8")
        else:
            raw = text.encode("utf-8")
        if len(raw) > latex.MAX_TEXT_BYTES:
            raise HTTPException(413, "Source document is larger than the per-file limit.")
        sources[rel] = raw
        if rel.endswith(".tex"):
            masked = latex._mask(raw.decode("utf-8"))
            if SHELL_COMMAND.search(masked):
                raise HTTPException(422, "Potential shell-escape or executable TeX construct found; compilation refused.")
            tables.extend({"path": rel, "kind": "table", "line": masked.count("\n", 0, x.start()) + 1}
                          for x in TABLE.finditer(masked))
            for matched in FIGURE.finditer(masked):
                target = _safe_figure(root, rel, matched.group(1).strip())
                if not target:
                    raise HTTPException(409, "Figure is missing, linked, unsafe or uses an unsupported format.")
                figures.append({"source": rel, "path": target,
                                "line": masked.count("\n", 0, matched.start()) + 1})
    if len(figures) > MAX_FIGURES:
        raise HTTPException(413, "Figure cap reached.")
    for rel in sorted(set(f["path"] for f in figures)):
        if rel in sources:
            continue
        sources[rel] = _safe_binary_source(root, rel)
    if len(sources) > MAX_INPUT_FILES:
        raise HTTPException(413, "Source and figure file count cap reached.")
    size = sum(len(raw) for raw in sources.values())
    if size > MAX_INPUT_BYTES:
        raise HTTPException(413, "Source snapshot exceeds the total input limit.")
    for rel, raw in sorted(sources.items()):
        digest.update(rel.encode("utf-8") + b"\x00" + hashlib.sha256(raw).digest())
        destination = stage / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output:
            output.write(raw)
    return {"files": sorted(sources), "source_hash": digest.hexdigest(),
            "source_bytes": size, "figures": figures[:MAX_FIGURES],
            "table_locations": tables[:MAX_DIAGNOSTICS], "source_executed": False}


def _command(engine: str, executable: str, main: str, output: Path) -> list[str]:
    """Fixed CLI policy; never accept project-supplied arguments or command templates."""
    if engine == "tectonic":
        return [executable, "--untrusted", "--only-cached", "--synctex",
                "--keep-logs", "--outdir", str(output), main]
    if engine == "latexmk":
        return [executable, "-norc", "-pdf", "-interaction=nonstopmode",
                "-halt-on-error", "-file-line-error", "-synctex=1",
                "-outdir=" + str(output),
                "-pdflatex=pdflatex -no-shell-escape -interaction=nonstopmode -halt-on-error %O %S",
                main]
    raise HTTPException(422, "Unsupported fixed LaTeX engine.")


def _run_tool(root: Path, command: list[str], stage: Path, output: Path) -> dict:
    env = adapters._environment(root)
    env.update({
        "HOME": str(stage), "USERPROFILE": str(stage),
        "XDG_CONFIG_HOME": str(stage), "TEXMFHOME": str(stage / "texhome"),
        "TEXMFOUTPUT": str(output), "TECTONIC_UNTRUSTED_MODE": "1",
        "openin_any": "p", "openout_any": "p",
        "max_print_line": "160",
    })
    kwargs = {"cwd": str(stage), "env": env, "shell": False,
              "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE,
              "stderr": subprocess.STDOUT}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    started = time.monotonic()
    try:
        proc = subprocess.Popen(command, **kwargs)
    except OSError as exc:
        raise HTTPException(502, "Approved compiler could not be started.") from exc
    output_buf = bytearray()
    too_much = threading.Event()
    def reader():
        try:
            while True:
                part = proc.stdout.read(4096)
                if not part:
                    break
                remainder = MAX_LOG_BYTES - len(output_buf)
                output_buf.extend(part[:max(0, remainder)])
                if len(part) > remainder:
                    too_much.set()
                    adapters._terminate(proc)
                    break
        except (OSError, ValueError):
            pass
    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    timeout = False
    try:
        try:
            proc.wait(timeout=MAX_RUN_SECONDS)
        except subprocess.TimeoutExpired:
            timeout = True
            adapters._terminate(proc)
        thread.join(timeout=0.8)
    finally:
        adapters._terminate(proc)
        if proc.stdout:
            proc.stdout.close()
    return {"status": "output_limit" if too_much.is_set() else "timeout" if timeout
            else "completed" if proc.returncode == 0 else "failed",
            "exit_code": proc.returncode, "elapsed_ms": int((time.monotonic()-started)*1000),
            "log": output_buf.decode("utf-8", errors="replace"),
            "log_truncated": too_much.is_set(), "timed_out": timeout}


def _read_artifact(path: Path, cap: int, suffix: bytes) -> Optional[bytes]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > cap:
        return None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
                     getattr(os, "O_BINARY", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > cap:
                return None
            data = stream.read(cap + 1)
        if len(data) > cap or not data.startswith(suffix):
            return None
        return data
    except OSError:
        return None


def _log_diagnostics(text: str, stage: Path) -> list[dict]:
    cleaned = text.replace(str(stage), "<snapshot>").replace("\r", "")
    result = []
    last_error = None
    for raw in cleaned.split("\n")[:4000]:
        value = raw.strip()
        if not value:
            continue
        if value.startswith("! "):
            last_error = value[:260]
            result.append({"severity": "error", "message": value[:260], "path": None,
                           "line": None, "compiler_log": True})
            continue
        if last_error and re.match(r"l\.(\d+)\s", value):
            if result:
                result[-1]["line"] = int(re.match(r"l\.(\d+)", value).group(1))
            last_error = None
            continue
        line = OUTPUT_CODE.match(value)
        if line:
            path = line.group("path")
            result.append({"severity": "error" if "error" in value.lower() else "warning",
                           "message": line.group("message"),
                           "path": path if path and not Path(path).is_absolute() else None,
                           "line": int(line.group("line")),
                           "compiler_log": True})
        elif "warning:" in value.casefold() or "overfull \\hbox" in value.lower():
            result.append({"severity": "warning", "message": value[:260],
                           "path": None, "line": None, "compiler_log": True})
        if len(result) >= MAX_DIAGNOSTICS:
            break
    return result


def _synctex(raw: Optional[bytes], stage: Path, allow: set[str]) -> list[dict]:
    if not raw:
        return []
    try:
        if raw.startswith(b"\x1f\x8b"):
            with gzip.GzipFile(fileobj=__import__("io").BytesIO(raw)) as source:
                text = source.read(MAX_SYNCTEX_EXPANDED + 1)
        else:
            text = raw
        if len(text) > MAX_SYNCTEX_EXPANDED:
            return []
        content = text.decode("utf-8", errors="replace")
    except (OSError, EOFError, ValueError):
        return []
    inputs = {}
    pins = []
    page = None
    reading = False
    for line in content.splitlines()[:120000]:
        if not reading:
            if line == "Content:":
                reading = True
                continue
            match = SYNC_INPUT.match(line)
            if match:
                value = Path(match.group(2))
                candidate = value if value.is_absolute() else stage / value
                try:
                    relative = candidate.resolve(strict=False).relative_to(stage.resolve()).as_posix()
                except (OSError, ValueError):
                    continue
                if relative in allow:
                    inputs[int(match.group(1))] = relative
            continue
        if line.startswith("Postamble:"):
            break
        block = SYNC_PAGE.match(line)
        if block:
            page = int(block.group(1))
            continue
        if line.strip() == "}":
            page = None
            continue
        node = SYNC_RECORD.match(line)
        if not node or page is None:
            continue
        tag, source_line, x, y = (int(x) for x in node.groups())
        path = inputs.get(tag)
        if path and 0 < source_line <= 1000000 and 0 < page <= 10000:
            pins.append({"path": path, "line": source_line,
                         "page": page, "x_sp": x, "y_sp": y})
            if len(pins) >= MAX_SYNCTEX_RECORDS:
                break
    return pins


def _preview_get(root: Path, build_id: str) -> dict:
    _trust(root)
    with PREVIEW_LOCK:
        item = PREVIEWS.get(build_id)
        if item is None:
            raise HTTPException(404, "PDF preview is missing or has expired.")
        if time.monotonic() - item["created"] > PREVIEW_TTL:
            PREVIEWS.pop(build_id, None)
            raise HTTPException(410, "PDF preview expired; compile again with consent.")
        if item["project_identity"] != studio._identity(root):
            raise HTTPException(403, "Preview belongs to a different project identity.")
        PREVIEWS.move_to_end(build_id)
        return item


@router.get("/engines")
def engines(request: Request, project: str):
    studio._auth(request)
    root = studio._project(project)
    return {"engines": _engines(root), "auto_execute": False,
            "automatic_installation": False, "versions_checked": False,
            "platform_sandbox": False}


@router.post("/build")
def build(request: Request, body: BuildIn):
    studio._auth(request)
    root = studio._project(body.project)
    _trust(root)
    if body.active_text is not None and body.active_path is None:
        raise HTTPException(422, "Unsaved LaTeX text must identify its source path.")
    if not RUN_LOCK.acquire(blocking=False):
        raise HTTPException(429, "Another TeX compiler is running.")
    try:
        tool = _selected(root, body)
        with tempfile.TemporaryDirectory(prefix="automoto-v11-tex-") as folder:
            temp = Path(folder)
            stage = temp / "sources"
            output = temp / "pdf"
            stage.mkdir()
            output.mkdir()
            snapshot = _snapshot(root, body, stage)
            _trust(root)
            current = adapters._fingerprint(tool["executable"], root)
            if current["sha256"] != body.expected_sha256:
                raise HTTPException(409, "TeX compiler changed during build preparation.")
            cmd = _command(body.engine, tool["executable"], body.main, output)
            run = _run_tool(root, cmd, stage, output)
            log = _log_diagnostics(run["log"], stage)
            summary = {k: run[k] for k in ("status", "exit_code", "elapsed_ms", "log_truncated", "timed_out")}
            summary.update({"diagnostics": log, "source_hash": snapshot["source_hash"],
                            "input_file_count": len(snapshot["files"]),
                            "input_bytes": snapshot["source_bytes"],
                            "figures": snapshot["figures"],
                            "table_locations": snapshot["table_locations"],
                            "source_files_written": False, "snapshot_used": True,
                            "compiler": body.engine, "compiler_sha256": body.expected_sha256,
                            "explicit_approval": True, "platform_sandbox": False,
                            "automatic_network": False,
                            "compilation_command_policy": "fixed-args-no-shell-escape",
                            "build_log": run["log"][:MAX_LOG_BYTES].replace(str(stage), "<snapshot>").replace(str(temp), "<build>")})
            if run["status"] != "completed":
                return {**summary, "pdf_ready": False, "synctex_available": False}
            name = Path(body.main).stem
            pdf = _read_artifact(output / (name + ".pdf"), MAX_PDF_BYTES, b"%PDF-")
            if pdf is None or b"%%EOF" not in pdf[-2048:]:
                return {**summary, "status": "invalid_pdf", "pdf_ready": False,
                        "synctex_available": False}
            raw_sync = _read_artifact(output / (name + ".synctex.gz"), MAX_SYNCTEX_BYTES, b"\x1f\x8b")
            if raw_sync is None:
                raw_sync = _read_artifact(output / (name + ".synctex"), MAX_SYNCTEX_BYTES, b"SyncTeX Version:")
            pins = _synctex(raw_sync, stage, set(x for x in snapshot["files"] if x.endswith(".tex")))
            # Compiler runs from an independent ephemeral source tree, never the
            # original project path; PDF and SyncTeX are cached in memory only.
            build_id = secrets.token_urlsafe(36)
            item = {"created": time.monotonic(), "project_identity": studio._identity(root),
                    "pdf": pdf, "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
                    "pins": pins, "sources": snapshot["files"], "source_hash": snapshot["source_hash"],
                    "compiler": body.engine, "compiler_sha256": tool["sha256"]}
            with PREVIEW_LOCK:
                PREVIEWS[build_id] = item
                PREVIEWS.move_to_end(build_id)
                while len(PREVIEWS) > MAX_PREVIEWS:
                    PREVIEWS.popitem(last=False)
            return {**summary, "pdf_ready": True, "build_id": build_id,
                    "pdf_sha256": item["pdf_sha256"], "pdf_size": len(pdf),
                    "synctex_available": bool(pins), "synctex_records": len(pins),
                    "preview_ttl_seconds": PREVIEW_TTL}
    finally:
        RUN_LOCK.release()


@router.post("/preview")
def preview(request: Request, body: PreviewIn):
    studio._auth(request)
    root = studio._project(body.project)
    result = _preview_get(root, body.build_id)
    return {"pdf_base64": base64.b64encode(result["pdf"]).decode("ascii"),
            "pdf_sha256": result["pdf_sha256"], "content_type": "application/pdf",
            "expires_in_seconds": max(0, int(PREVIEW_TTL-(time.monotonic()-result["created"]))),
            "cached_only": True, "source_files_written": False}


@router.post("/sync/source-to-pdf")
def source_to_pdf(request: Request, body: JumpIn):
    studio._auth(request)
    root = studio._project(body.project)
    artifact = _preview_get(root, body.build_id)
    matches = [x for x in artifact["pins"] if x["path"] == body.path]
    if not matches or body.path not in artifact["sources"]:
        raise HTTPException(404, "No verified SyncTeX mapping for this source file.")
    nearest = min(matches, key=lambda p: (abs(p["line"]-body.line), p["page"]))
    return {"path": body.path, "requested_line": body.line,
            "matched_line": nearest["line"], "page": nearest["page"],
            "line_distance": abs(nearest["line"]-body.line),
            "exact_line_match": nearest["line"] == body.line,
            "source_to_pdf_verified": True, "page_navigation_only": True,
            "coordinates_available_unscaled": False}


@router.post("/sync/page-to-source")
def page_to_source(request: Request, body: PageIn):
    studio._auth(request)
    root = studio._project(body.project)
    artifact = _preview_get(root, body.build_id)
    matches = [x for x in artifact["pins"] if x["page"] == body.page and x["path"] in artifact["sources"]]
    if not matches:
        raise HTTPException(404, "No verified SyncTeX source pins for this PDF page.")
    # Page-based reverse jump is an approximate first source location on page,
    # NOT a click-coordinate inverse search.
    match = min(matches, key=lambda p: (p["line"], p["path"]))
    return {"page": body.page, "path": match["path"],
            "line": match["line"], "approximate_page_to_source": True,
            "exact_reverse_coordinate_mapping": False}
