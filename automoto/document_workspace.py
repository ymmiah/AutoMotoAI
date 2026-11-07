"""Document Assistant v1: safe native drafts and Office-backed publication.

The editor owns Markdown source. Imported Office/PDF documents are read-only
extractions; DOCX-only find/replace creates a new copy with an explicit SHA-256
precondition, never overwriting the supplied file. All paths are confined to
private workspace folders. This intentionally does not promise WYSIWYG editing.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from automoto import office, office_build, sandbox
from automoto.visual_studio import _auth, _quota_check

router = APIRouter(prefix="/api/documents", tags=["documents"])

DOCUMENTS_DIR = "artifacts/documents"
MAX_DRAFT_CHARS = 120_000
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
VISIBLE_EXT = {".document.json", ".md", ".txt", ".docx", ".pdf", ".pptx", ".xlsx"}


class DocumentSource(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    markdown: str = Field(..., max_length=MAX_DRAFT_CHARS)


class ExportIn(DocumentSource):
    format: Literal["docx", "pdf"] = "docx"


class ReplaceIn(BaseModel):
    path: str = Field(..., min_length=1, max_length=600)
    sha256: str = Field(..., min_length=64, max_length=64)
    find: str = Field(..., min_length=1, max_length=500)
    replace: str = Field(..., max_length=2_000)


def _root() -> Path:
    return sandbox.default_root().resolve()


def _folder() -> Path:
    return sandbox.resolve(DOCUMENTS_DIR, base=_root(), allow_outside=False)


def _slug(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", name.strip().lower()).strip("-")
    return cleaned[:48].rstrip("-") or "document"


def _name(value: str) -> str:
    name = value.strip()
    if not name:
        raise HTTPException(422, "Give this document a name")
    return name


def _unique(name: str, suffix: str) -> Path:
    folder = _folder()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{_slug(name)}-{secrets.token_hex(6)}{suffix}"


def _allowed_source(raw: str) -> Path:
    if not raw or "\\" in raw or raw.startswith("/") or any(c in raw for c in "\x00\r\n"):
        raise HTTPException(403, "invalid document path")
    try:
        path = sandbox.resolve(raw, base=_root(), allow_outside=False)
        relative = path.relative_to(_root())
    except (ValueError, sandbox.SandboxError):
        raise HTTPException(403, "document is outside your private workspace") from None
    # A document can be imported only from an uploads folder or opened from
    # this application's own output folder; no arbitrary private files.
    if not relative.parts or not ((relative.parts[0] == "uploads" and len(relative.parts) >= 2)
            or (relative.parts[:2] == ("artifacts", "documents") and len(relative.parts) >= 3)):
        raise HTTPException(403, "open documents only from uploads or Document Assistant")
    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != _root()):
        raise HTTPException(403, "document symlinks are not allowed")
    if not path.is_file():
        raise HTTPException(404, "document not found")
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, "document exceeds the 20 MB opening limit")
    if path.name.endswith(".document.json"):
        if relative.parts[:2] != ("artifacts", "documents"):
            raise HTTPException(403, "editable drafts belong to the Document Assistant folder")
    elif path.suffix.lower() not in {".docx", ".pdf", ".pptx", ".xlsx", ".md", ".txt"}:
        raise HTTPException(415, "unsupported document format")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_file(target: Path, data: bytes) -> None:
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, "output exceeds size limit")
    _quota_check(len(data))
    # Create-only names and same-folder transactional publication.
    temporary = target.with_name(f".working-{secrets.token_hex(8)}.part")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
        if target.exists():
            raise HTTPException(409, "document output already exists")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _draft(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict) or obj.get("schema") != 1:
            raise ValueError("unrecognised document draft")
        source = DocumentSource.model_validate({"name": obj.get("name"), "markdown": obj.get("markdown")})
    except (ValueError, OSError, UnicodeError):
        raise HTTPException(422, "saved document draft is not valid") from None
    return source.model_dump()


@router.get("/list")
def list_documents(request: Request):
    _auth(request)
    items = []
    for rel in ("uploads", DOCUMENTS_DIR):
        folder = sandbox.resolve(rel, base=_root(), allow_outside=False)
        if not folder.is_dir() or folder.is_symlink():
            continue
        for path in folder.iterdir():
            if path.is_symlink() or not path.is_file():
                continue
            if not (path.name.endswith(".document.json") or path.suffix.lower() in
                    {".docx", ".pdf", ".pptx", ".xlsx", ".md", ".txt"}):
                continue
            stat = path.stat()
            if stat.st_size > MAX_DOCUMENT_BYTES:
                continue
            items.append({"path": path.relative_to(_root()).as_posix(),
                          "name": path.name, "size": stat.st_size,
                          "mtime": int(stat.st_mtime),
                          "kind": "draft" if path.name.endswith(".document.json") else path.suffix.lower()[1:]})
    items.sort(key=lambda entry: (-entry["mtime"], entry["name"]))
    return {"documents": items[:100], "libreoffice": office.lo_available()}


@router.get("/open")
def open_document(request: Request, path: str):
    _auth(request)
    file = _allowed_source(path)
    relative = file.relative_to(_root()).as_posix()
    kind = "draft" if file.name.endswith(".document.json") else file.suffix.lower().lstrip(".")
    if kind == "draft":
        data = _draft(file)
        return {"path": relative, "name": data["name"], "kind": "draft",
                "markdown": data["markdown"], "editable": True, "sha256": _sha(file),
                "notice": "Native editable Markdown draft. The original source remains unchanged."}
    if kind in {"md", "txt"}:
        if file.stat().st_size > MAX_DRAFT_CHARS:
            raise HTTPException(413, "plain-text document is too large for the source editor")
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeError:
            raise HTTPException(422, "document requires UTF-8 text") from None
        return {"path": relative, "name": file.stem, "kind": kind, "markdown": text,
                "editable": True, "sha256": _sha(file),
                "notice": "Edits will save as a new draft; the imported file will not be overwritten."}
    try:
        text = office.read(relative, max_chars=30001, max_rows=40)
    except (office.OfficeError, ValueError, OSError, UnicodeError) as exc:
        raise HTTPException(422, f"could not read this document: {str(exc)[:350]}") from None
    truncated = len(text) >= 30001
    return {"path": relative, "name": file.name, "kind": kind,
            "extracted_text": text[:30000], "truncated": truncated,
            "editable": False, "sha256": _sha(file),
            "notice": "Read-only extraction, not a lossless layout editor. Download the original, or use a separate, approved copy for DOCX text replacement."}


@router.post("/save")
def save_document(body: DocumentSource, request: Request):
    _auth(request)
    name = _name(body.name)
    raw = json.dumps({"schema": 1, "name": name, "markdown": body.markdown},
                     ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_DRAFT_CHARS * 4 + 1024:
        raise HTTPException(413, "document draft is too large")
    path = _unique(name, ".document.json")
    _atomic_file(path, raw)
    return {"path": path.relative_to(_root()).as_posix(),
            "kind": "draft", "message": "Editable source saved as a separate document draft"}


def _build_spec(body: DocumentSource) -> dict[str, Any]:
    name = _name(body.name)
    spec = office_build.markdown_to_spec(body.markdown)
    if len(spec["blocks"]) > 1000:
        raise HTTPException(413, "document exceeds 1000 content blocks")
    if any(b.get("type") == "image" for b in spec["blocks"]):
        raise HTTPException(422, "embedded image paths are not supported in v1; add images in the existing Office tools")
    # The Word engine owns actual page layout. Markdown remains the editable
    # source and is not misrepresented as a round-trip Word document editor.
    spec.update({"properties": {"title": name, "language": "en-GB"},
                 "page": {"size": "A4", "margins_cm": 2.5}})
    return spec


@router.post("/export")
def export_document(body: ExportIn, request: Request):
    _auth(request)
    name = _name(body.name)
    source = _build_spec(body)
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix="automoto-document-export-") as td:
        folder = Path(td)
        docx = folder / "generated.docx"
        try:
            office_build.build_docx(source, docx)
            office.inspect_file(docx)
            if body.format == "pdf":
                if not office.lo_available():
                    raise HTTPException(501, "PDF publishing needs local LibreOffice; DOCX export is available")
                produced = office.lo_convert(docx, "pdf", folder / "pdf")
            else:
                produced = docx
            data = produced.read_bytes()
        except (office.OfficeError, ValueError, OSError) as exc:
            raise HTTPException(422, f"document publishing failed: {str(exc)[:450]}") from None
    target = _unique(name, "." + body.format)
    _atomic_file(target, data)
    return {"path": target.relative_to(_root()).as_posix(), "format": body.format,
            "message": "Published a new file from editable source; original documents unchanged"}


@router.post("/replace-copy")
def replace_copy(body: ReplaceIn, request: Request):
    _auth(request)
    source = _allowed_source(body.path)
    if source.suffix.lower() != ".docx" or source.name.endswith(".document.json"):
        raise HTTPException(422, "native find-and-replace is supported for DOCX copies only")
    if not re.fullmatch(r"[0-9a-f]{64}", body.sha256):
        raise HTTPException(422, "invalid SHA-256 precondition")
    if _sha(source) != body.sha256:
        raise HTTPException(409, "original changed since opening; reopen before editing")
    try:
        office.inspect_file(source)
    except office.OfficeError as exc:
        raise HTTPException(422, str(exc)) from None
    target = _unique(source.stem + "-revised", ".docx")
    temporary = target.with_name(f".editing-{secrets.token_hex(8)}.docx")
    try:
        shutil.copyfile(source, temporary)
        message = office_build.edit(temporary, replace=[{"old": body.find, "new": body.replace}])
        count = int(re.search(r": (\d+) change", message).group(1))
        if not count:
            raise HTTPException(422, "the exact phrase was not found; no copy was saved")
        office.inspect_file(temporary)
        if temporary.stat().st_size > MAX_DOCUMENT_BYTES:
            raise HTTPException(413, "revised document exceeds the 20 MB document limit")
        if _sha(source) != body.sha256:
            raise HTTPException(409, "original changed during editing; no copy was saved")
        _quota_check(temporary.stat().st_size)
        if target.exists():
            raise HTTPException(409, "document output already exists")
        temporary.replace(target)
    except (office.OfficeError, ValueError, OSError) as exc:
        raise HTTPException(422, f"copy edit failed: {str(exc)[:350]}") from None
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": target.relative_to(_root()).as_posix(), "changes": count,
            "message": "Saved a new DOCX copy; original was not modified"}
