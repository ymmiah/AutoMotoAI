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
from pydantic import BaseModel, Field, ConfigDict

from automoto import office, office_build, sandbox
from automoto.document_publishing import PublicationOptions, TEMPLATES, publishing_spec
from automoto.visual_studio import _auth, _quota_check

router = APIRouter(prefix="/api/documents", tags=["documents"])

DOCUMENTS_DIR = "artifacts/documents"
MAX_DRAFT_CHARS = 120_000
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
READABLE_EXT = {".docx", ".pdf", ".pptx", ".xlsx", ".md", ".txt",
                ".doc", ".odt", ".rtf", ".ppt", ".odp", ".xls", ".ods"}


class LayoutOptions(BaseModel):
    """Bounded author-controlled page styles, never arbitrary Office properties."""
    model_config = ConfigDict(extra="forbid")
    page_size: Literal["A4", "Letter"] = "A4"
    orientation: Literal["portrait", "landscape"] = "portrait"
    margins_cm: float = Field(2.5, ge=1.2, le=4, allow_inf_nan=False)
    font: Literal["Calibri", "Arial", "Aptos", "Georgia", "Times New Roman",
                  "Liberation Serif"] = "Calibri"
    font_size: int = Field(11, ge=9, le=16)
    line_spacing: float = Field(1.15, ge=1, le=2, allow_inf_nan=False)
    heading_color: str = Field("#1F3864", pattern=r"^#[0-9a-fA-F]{6}$")
    page_numbers: bool = True


class DocumentSource(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    markdown: str = Field(..., max_length=MAX_DRAFT_CHARS)
    options: LayoutOptions | None = None
    publication: PublicationOptions | None = None


class ExportIn(DocumentSource):
    format: Literal["docx", "pdf"] = "docx"


class ReplaceIn(BaseModel):
    path: str = Field(..., min_length=1, max_length=600)
    sha256: str = Field(..., min_length=64, max_length=64)
    find: str = Field(..., min_length=1, max_length=500)
    replace: str = Field(..., max_length=2_000)
    # v8: XLSX cell edits, e.g. {"Sheet1!B2": "new value"}. Ignored for DOCX/PPTX.
    cells: dict[str, Any] | None = None


class CreateIn(BaseModel):
    """v8: create a document from scratch in any supported format.

    The same Markdown source drives DOCX, PPTX, PDF and plain-text output;
    spreadsheets take explicit rows (or Markdown tables). Everything is
    create-only: a new uniquely-named file in the private documents folder.
    """
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=100)
    format: Literal["docx", "pptx", "xlsx", "pdf", "md", "txt"] = "docx"
    markdown: str = Field("", max_length=MAX_DRAFT_CHARS)
    options: LayoutOptions | None = None
    publication: PublicationOptions | None = None
    rows: list[list[Any]] | None = Field(None, max_length=10_000)
    sheet_name: str = Field("Sheet1", min_length=1, max_length=31)


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
    elif path.suffix.lower() not in READABLE_EXT:
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
        if not isinstance(obj, dict) or obj.get("schema") not in (1, 2, 3):
            raise ValueError("unrecognised document draft")
        # v1 drafts contain only name and Markdown; v2 adds optional options.
        source = DocumentSource.model_validate({
            "name": obj.get("name"), "markdown": obj.get("markdown"),
            "options": obj.get("options"), "publication": obj.get("publication")})
    except (ValueError, OSError, UnicodeError):
        raise HTTPException(422, "saved document draft is not valid") from None
    return source.model_dump(exclude_none=True)


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
            if not (path.name.endswith(".document.json") or path.suffix.lower() in READABLE_EXT):
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
                "markdown": data["markdown"], "options": data.get("options"),
                "publication": data.get("publication"),
                "editable": True, "sha256": _sha(file),
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
    draft: dict[str, Any] = {"schema": 1, "name": name, "markdown": body.markdown}
    if body.options is not None:
        draft["schema"] = 2
        draft["options"] = body.options.model_dump()
    if body.publication is not None:
        draft["schema"] = 3
        draft["publication"] = body.publication.model_dump(exclude_none=True)
    raw = json.dumps(draft, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
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
    options = body.options or LayoutOptions()
    spec.update({
        "properties": {"title": name, "language": "en-GB"},
        "page": {"size": options.page_size, "orientation": options.orientation,
                 "margins_cm": options.margins_cm},
        "theme": {"font": options.font, "heading_font": options.font,
                  "size": options.font_size, "line_spacing": options.line_spacing,
                  "heading_color": options.heading_color.removeprefix("#")},
        "page_numbers": options.page_numbers,
    })
    if body.publication is not None:
        try:
            spec, _ = publishing_spec(name, body.markdown, spec, body.publication)
        except ValueError as exc:
            raise HTTPException(422, str(exc)[:350]) from None
    return spec


@router.post("/create")
def create_document(body: CreateIn, request: Request):
    """v8: create a new document from scratch — DOCX, PPTX, XLSX, PDF, MD or TXT.

    Previously Document Assistant could only create Markdown drafts
    (``.document.json``) and export them as DOCX/PDF. The Office engines
    could already build PPTX/XLSX, but Document Assistant never exposed
    them. This endpoint reuses those engines, so every format is built
    from the same source instead of a separate code path.
    """
    _auth(request)
    name = _name(body.name)
    fmt = body.format
    warnings: list[str] = []
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix="automoto-document-create-") as td:
        folder = Path(td)
        if fmt == "md":
            produced = folder / "created.md"
            produced.write_text(body.markdown or f"# {name}\n", encoding="utf-8")
        elif fmt == "txt":
            produced = folder / "created.txt"
            produced.write_text(body.markdown or name, encoding="utf-8")
        elif fmt == "pdf":
            produced = folder / "created.pdf"
            _markdown_to_pdf(office_build.markdown_to_spec(body.markdown or f"# {name}\n"),
                             name, produced)
        elif fmt == "docx":
            source = DocumentSource(name=name, markdown=body.markdown or f"# {name}\n",
                                    options=body.options, publication=body.publication)
            spec = _build_spec(source)
            produced = folder / "created.docx"
            office_build.build_docx(spec, produced)
            office.inspect_file(produced)
        elif fmt == "pptx":
            spec = _markdown_to_slides(body.markdown or f"# {name}\n", name)
            produced = folder / "created.pptx"
            office_build.create_pptx(spec, produced)
            office.inspect_file(produced)
        elif fmt == "xlsx":
            rows = body.rows
            if not rows:
                spec = office_build.markdown_to_spec(body.markdown or "")
                tables = [b["rows"] for b in spec["blocks"] if b.get("type") == "table"]
                if not tables:
                    raise HTTPException(
                        422, "A spreadsheet needs rows or at least one Markdown table.")
                rows = tables[0]
                if len(tables) > 1:
                    warnings.append("Only the first Markdown table was used for the sheet.")
            for row in rows:
                if len(row) > 100:
                    raise HTTPException(422, "A spreadsheet row holds at most 100 cells.")
            produced = folder / "created.xlsx"
            office_build.create_xlsx(
                {"sheets": [{"name": body.sheet_name, "rows": rows}]}, produced)
            office.inspect_file(produced)
        else:  # pragma: no cover - pydantic Literal guards this
            raise HTTPException(422, "unsupported format")
        data = produced.read_bytes()
    target = _unique(name, "." + fmt)
    _atomic_file(target, data)
    return {"path": target.relative_to(_root()).as_posix(), "format": fmt,
            "warnings": warnings,
            "message": f"Created a new {fmt.upper()} document; no existing file was changed"}


def _markdown_to_slides(markdown: str, name: str) -> dict[str, Any]:
    """Turn Markdown headings into a slide deck: H1 is the title slide,
    each H2 starts a bullets slide, deeper headings and paragraphs become
    bullets. Image blocks are skipped (no source image is available here)."""
    spec = office_build.markdown_to_spec(markdown)
    slides: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def start_slide(title: str, layout: str = "bullets") -> dict[str, Any]:
        slide: dict[str, Any] = {"layout": layout, "title": title, "bullets": []}
        slides.append(slide)
        return slide

    for block in spec["blocks"]:
        kind = block.get("type")
        if kind == "heading" and block.get("level") == 1:
            current = start_slide(block["text"], "title")
            current["subtitle"] = name
        elif kind == "heading" and block.get("level") == 2:
            current = start_slide(block["text"])
        elif kind == "heading":
            if current is None:
                current = start_slide(name)
            current["bullets"].append(block["text"])
        elif kind in ("bullets", "numbered"):
            if current is None:
                current = start_slide(name)
            for item in block.get("items", []):
                current["bullets"].append(item[0] if isinstance(item, list) else item)
        elif kind in ("paragraph", "quote"):
            if current is None:
                current = start_slide(name)
            current["bullets"].append(block["text"])
        elif kind == "table":
            if current is None:
                current = start_slide(name)
            rows = block.get("rows") or []
            if rows:
                slides.append({"layout": "table", "title": current["title"], "rows": rows})
                current = None
    if not slides:
        slides.append({"layout": "title", "title": name, "subtitle": ""})
    return {"slides": slides[:300]}


def _markdown_to_pdf(spec: dict[str, Any], title: str, out: Path) -> None:
    """Build a PDF from Markdown blocks with reportlab (no LibreOffice
    needed), so PDF creation works even where LibreOffice is absent."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)
    from xml.sax.saxutils import escape

    styles = getSampleStyleSheet()
    heading = ParagraphStyle("da-heading", parent=styles["Heading1"],
                             fontSize=18, leading=22, spaceBefore=14, spaceAfter=6)
    heading2 = ParagraphStyle("da-heading2", parent=styles["Heading2"],
                              fontSize=14, leading=18, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("da-body", parent=styles["BodyText"],
                          fontSize=11, leading=15, spaceAfter=6)
    story: list[Any] = [Paragraph(escape(title), heading), Spacer(1, 0.2 * cm)]
    for block in spec["blocks"]:
        kind = block.get("type")
        text = str(block.get("text", ""))
        if kind == "heading":
            style = heading if block.get("level", 1) == 1 else heading2
            story.append(Paragraph(escape(text), style))
        elif kind in ("bullets", "numbered"):
            for item in block.get("items", []):
                item_text = item[0] if isinstance(item, list) else item
                story.append(Paragraph("• " + escape(str(item_text)), body))
        elif kind == "table":
            rows = [[escape(str(c)) for c in row] for row in block.get("rows", [])]
            if rows:
                table = Table([[Paragraph(c, body) for c in row] for row in rows])
                table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), "#1F3864"),
                    ("TEXTCOLOR", (0, 0), (-1, 0), "#FFFFFF"),
                    ("GRID", (0, 0), (-1, -1), 0.5, "#BFBFBF"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                story.append(table)
                story.append(Spacer(1, 0.3 * cm))
        elif kind == "page_break":
            from reportlab.platypus import PageBreak
            story.append(PageBreak())
        elif text:
            story.append(Paragraph(escape(text), body))
    SimpleDocTemplate(str(out), pagesize=A4, title=title,
                      leftMargin=2.5 * cm, rightMargin=2.5 * cm,
                      topMargin=2.5 * cm, bottomMargin=2.5 * cm).build(story)


@router.get("/templates")
def list_document_templates(request: Request):
    _auth(request)
    return {"templates": [{"id": key, **value} for key, value in TEMPLATES.items()],
            "note": "Templates contain placeholders, not verified facts or invented references."}


@router.post("/preflight")
def preflight_document(body: DocumentSource, request: Request):
    """Real, read-only Word build validation before a user chooses to publish."""
    _auth(request)
    spec = _build_spec(body)
    warnings: list[str] = []
    if body.publication is not None:
        try:
            spec, warnings = publishing_spec(_name(body.name), body.markdown, spec, body.publication)
        except ValueError as exc:
            raise HTTPException(422, str(exc)[:350]) from None
    from tempfile import TemporaryDirectory
    try:
        with TemporaryDirectory(prefix="automoto-document-preflight-") as td:
            preview = Path(td) / "verification.docx"
            info = office_build.build_docx(spec, preview)
            office.inspect_file(preview)
            bytes_count = preview.stat().st_size
    except (office.OfficeError, ValueError, OSError) as exc:
        raise HTTPException(422, f"Document cannot be published: {str(exc)[:400]}") from None
    return {"ready": True, "no_files_saved": True,
            "word_bytes": bytes_count, "headings": len(info["headings"]),
            "tables": info["tables"], "contents_page": info["has_toc"],
            "reference_count": len(body.publication.references) if body.publication else 0,
            "warnings": warnings,
            "limitations": "This preflight validates the OOXML build, not visual pagination, factual accuracy or citation authenticity."}


@router.post("/export")
def export_document(body: ExportIn, request: Request):
    _auth(request)
    name = _name(body.name)
    source = _build_spec(body)
    warnings = []
    if body.publication is not None:
        try:
            source, warnings = publishing_spec(name, body.markdown, source, body.publication)
        except ValueError as exc:
            raise HTTPException(422, str(exc)[:350]) from None
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix="automoto-document-export-") as td:
        folder = Path(td)
        docx = folder / "generated.docx"
        try:
            info = office_build.build_docx(source, docx)
            if info["has_toc"] and office.lo_available():
                # Populate a real TOC with measured page positions from the
                # locally rendered temporary Word copy. No online service.
                render = office.lo_convert(docx, "pdf", folder / "toc-preview")
                pages = office_build.toc_page_numbers(render, info["headings"])
                office_build.build_docx(source, docx, toc_pages=pages)
                if len(pages) < len(info["headings"]):
                    warnings.append("Some TOC page positions could not be verified; update fields in Word.")
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
            "warnings": warnings,
            "message": "Published a new file from editable source; original documents unchanged"}


@router.post("/replace-copy")
def replace_copy(body: ReplaceIn, request: Request):
    _auth(request)
    source = _allowed_source(body.path)
    # v8: find-and-replace copies now cover PPTX and XLSX too, using the
    # same Office edit engine the agent tools already use. PDF stays
    # read-only: it has no lossless text layer to edit in place.
    if source.suffix.lower() not in {".docx", ".pptx", ".xlsx"} \
            or source.name.endswith(".document.json"):
        raise HTTPException(
            422, "native find-and-replace copies are supported for DOCX, PPTX and XLSX only")
    if not re.fullmatch(r"[0-9a-f]{64}", body.sha256):
        raise HTTPException(422, "invalid SHA-256 precondition")
    if _sha(source) != body.sha256:
        raise HTTPException(409, "original changed since opening; reopen before editing")
    try:
        office.inspect_file(source)
    except office.OfficeError as exc:
        raise HTTPException(422, str(exc)) from None
    target = _unique(source.stem + "-revised", source.suffix.lower())
    temporary = target.with_name(f".editing-{secrets.token_hex(8)}{source.suffix.lower()}")
    try:
        shutil.copyfile(source, temporary)
        message = office_build.edit(temporary, replace=[{"old": body.find, "new": body.replace}],
                                    cells=body.cells)
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
            "message": f"Saved a new {source.suffix[1:].upper()} copy; original was not modified"}
