"""Rich Word copy editing without rewriting the original DOCX.

Operations target exact runs, stable paragraph indices or simple table cells,
with checksum preconditions. The unchanged OOXML package parts remain in place
via python-docx; the resulting document is always written as a new copy.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any, Literal

from docx import Document
from docx.shared import Cm
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from PIL import Image, UnidentifiedImageError

from automoto import office, sandbox
from automoto.document_workspace import (
    MAX_DOCUMENT_BYTES, _allowed_source, _atomic_file, _root, _sha, _unique
)
from automoto.visual_studio import _auth

router = APIRouter(prefix="/api/documents/docx", tags=["document-rich"])
ALLOWED_STYLES = {"Normal", "Title", "Subtitle", "Quote"} | {f"Heading {i}" for i in range(1, 7)}
MAX_OPS = 15
MAX_PARAGRAPHS = 300
MAX_TABLES = 40


class RichOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["replace_run", "set_style", "table_cell", "append_row", "insert_image"]
    paragraph: int | None = Field(None, ge=0, le=10000)
    run: int | None = Field(None, ge=0, le=10000)
    table: int | None = Field(None, ge=0, le=500)
    row: int | None = Field(None, ge=0, le=2000)
    cell: int | None = Field(None, ge=0, le=30)
    expected: str | None = Field(None, max_length=12000)
    text: str | None = Field(None, max_length=12000)
    style: str | None = Field(None, max_length=50)
    values: list[str] | None = Field(None, max_length=12)
    image_path: str | None = Field(None, max_length=500)
    width_cm: float | None = Field(None, gt=0, le=14, allow_inf_nan=False)


class RichCopyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(..., min_length=1, max_length=600)
    sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    operations: list[RichOperation] = Field(..., min_length=1, max_length=MAX_OPS)


def _word_source(raw: str, digest: str | None = None) -> Path:
    path = _allowed_source(raw)
    if path.suffix.lower() != ".docx":
        raise HTTPException(422, "Rich copy editing supports DOCX documents only")
    meta = office.inspect_file(path)
    if meta["macros"]:
        raise HTTPException(422, "Macro-containing Word files are not accepted")
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, "Document exceeds the 20 MB limit")
    with zipfile.ZipFile(path) as archive:
        if any("_xmlsignatures/" in entry.lower() for entry in archive.namelist()):
            raise HTTPException(422, "Signed documents cannot be edited without invalidating their signatures")
    if digest is not None and _sha(path) != digest:
        raise HTTPException(409, "The source DOCX changed; reopen it before making another copy")
    return path


def _image_path(raw: str | None) -> Path:
    if not raw or raw.startswith("/") or "\\" in raw or "\x00" in raw:
        raise HTTPException(422, "Select an existing uploaded PNG or JPEG")
    try:
        path = sandbox.resolve(raw, base=_root(), allow_outside=False)
        relative = path.relative_to(_root())
    except (sandbox.SandboxError, ValueError):
        raise HTTPException(403, "Image is outside your workspace") from None
    if not relative.parts or relative.parts[0] != "uploads" or len(relative.parts) < 2:
        raise HTTPException(403, "Only private uploaded images may be inserted")
    if path.is_symlink() or not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise HTTPException(422, "Image must be a non-symlink PNG or JPEG")
    if path.stat().st_size > 8 * 1024 * 1024:
        raise HTTPException(413, "Image exceeds the 8 MB size limit")
    try:
        with Image.open(path) as image:
            if image.format not in {"PNG", "JPEG"} or image.width * image.height > 24_000_000:
                raise ValueError("unsupported or oversized image")
            image.verify()
    except (OSError, ValueError, UnidentifiedImageError):
        raise HTTPException(422, "The uploaded image could not be safely decoded") from None
    return path


def _paragraph(doc: Any, index: int | None):
    if index is None or not 0 <= index < len(doc.paragraphs):
        raise HTTPException(422, "Select an existing Word paragraph")
    return doc.paragraphs[index]


def _table(doc: Any, index: int | None):
    if index is None or not 0 <= index < len(doc.tables):
        raise HTTPException(422, "Select an existing Word table")
    return doc.tables[index]


def _cell(table: Any, row: int | None, cell: int | None):
    if row is None or cell is None or not 0 <= row < len(table.rows):
        raise HTTPException(422, "Select an existing table row and cell")
    cells = table.rows[row].cells
    if not 0 <= cell < len(cells):
        raise HTTPException(422, "Table cell index is out of range")
    selected = cells[cell]
    props = selected._tc.tcPr
    if props is not None and (props.gridSpan is not None or props.vMerge is not None):
        raise HTTPException(422, "Merged table cells must be edited in the original Word editor")
    return selected


def _apply(doc: Any, operation: RichOperation) -> str:
    kind = operation.kind
    if kind == "replace_run":
        p = _paragraph(doc, operation.paragraph)
        if operation.run is None or not 0 <= operation.run < len(p.runs):
            raise HTTPException(422, "Choose a visible text run in the selected paragraph")
        run = p.runs[operation.run]
        if operation.expected is None or run.text != operation.expected:
            raise HTTPException(409, "Paragraph text has changed; reopen the document before editing")
        if operation.text is None or operation.text == operation.expected:
            raise HTTPException(422, "Enter different replacement text")
        # Only the selected run is changed; other runs, fonts and images stay intact.
        run.text = operation.text
        return f"Replaced text run {operation.run} in paragraph {operation.paragraph}"
    if kind == "set_style":
        p = _paragraph(doc, operation.paragraph)
        if operation.style not in ALLOWED_STYLES:
            raise HTTPException(422, "Unsupported Word paragraph style")
        if p.style.name == operation.style:
            raise HTTPException(422, "Paragraph already uses that style")
        if operation.style not in doc.styles:
            raise HTTPException(422, "Selected style is unavailable in the Word document")
        p.style = doc.styles[operation.style]
        return f"Set paragraph {operation.paragraph} style to {operation.style}"
    if kind == "table_cell":
        t = _table(doc, operation.table)
        cell = _cell(t, operation.row, operation.cell)
        if len(cell.paragraphs) != 1 or len(cell.paragraphs[0].runs) > 1:
            raise HTTPException(422, "Complex cell formatting cannot be edited losslessly here")
        p = cell.paragraphs[0]
        if operation.expected is None or p.text != operation.expected:
            raise HTTPException(409, "Table cell changed; reopen before editing")
        if operation.text is None or operation.text == operation.expected:
            raise HTTPException(422, "Enter different table cell text")
        if p.runs:
            p.runs[0].text = operation.text
        else:
            p.add_run(operation.text)
        return f"Edited cell {operation.cell} in table {operation.table}, row {operation.row}"
    if kind == "append_row":
        table = _table(doc, operation.table)
        if len(table.rows) >= 100 or not table.rows:
            raise HTTPException(422, "The table is too large or has no editable rows")
        cols = len(table.rows[0].cells)
        values = operation.values
        if cols > 12 or not values or len(values) != cols or any(
                not isinstance(value, str) or len(value) > 500 for value in values):
            raise HTTPException(422, "Provide one short value for each of the existing table columns")
        # Reject merged rows, whose span and cell geometry cannot be preserved.
        for row in table.rows:
            for idx in range(len(row.cells)):
                _cell(table, table.rows.index(row), idx)
        row = table.add_row()
        for cell, value in zip(row.cells, values):
            cell.text = value
        return f"Appended one editable row to table {operation.table}"
    if kind == "insert_image":
        paragraph = _paragraph(doc, operation.paragraph)
        image = _image_path(operation.image_path)
        width = Cm(operation.width_cm or 5.0)
        next_paragraph = paragraph.insert_paragraph_before()
        paragraph._p.addnext(next_paragraph._p)
        next_paragraph.add_run().add_picture(str(image), width=width)
        return f"Inserted a real uploaded image after paragraph {operation.paragraph}"
    raise HTTPException(422, "Unsupported Word editing action")


def _read_docx(source: Path):
    try:
        return Document(str(source))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise HTTPException(422, f"Could not parse this Word file: {str(exc)[:180]}") from None


@router.get("/structure")
def docx_structure(path: str, request: Request):
    _auth(request)
    source = _word_source(path)
    doc = _read_docx(source)
    paragraphs = []
    for index, p in enumerate(doc.paragraphs[:MAX_PARAGRAPHS]):
        paragraphs.append({
            "index": index, "text": p.text[:1800], "style": p.style.name,
            "runs": [{"index": j, "text": r.text[:12000], "bold": r.bold, "italic": r.italic}
                     for j, r in enumerate(p.runs[:30])],
            "truncated_runs": len(p.runs) > 30,
        })
    tables = []
    for index, table in enumerate(doc.tables[:MAX_TABLES]):
        tables.append({
            "index": index, "rows": len(table.rows), "columns": len(table.columns),
            "preview": [[cell.text[:300] for cell in row.cells[:12]]
                        for row in table.rows[:12]],
            "truncated": len(table.rows) > 12 or len(table.columns) > 12,
        })
    return {
        "path": source.relative_to(_root()).as_posix(),
        "sha256": _sha(source), "paragraphs": paragraphs, "tables": tables,
        "images": len(doc.inline_shapes), "sections": len(doc.sections),
        "truncated": len(doc.paragraphs) > MAX_PARAGRAPHS or len(doc.tables) > MAX_TABLES,
        "limitations": "Run-level and simple-table copy editing only. Existing Word layout, fields and images are preserved where supported; inspect revised pages before sharing.",
    }


@router.post("/revise")
def revise_docx(body: RichCopyIn, request: Request):
    _auth(request)
    original = _word_source(body.path, body.sha256)
    doc = _read_docx(original)
    changes = []
    # Entire operation list is validated before any output is published.
    for op in body.operations:
        changes.append(_apply(doc, op))
    if _sha(original) != body.sha256:
        raise HTTPException(409, "The original DOCX changed during editing")
    stream = io.BytesIO()
    try:
        doc.save(stream)
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(422, f"Could not generate revised Word copy: {str(exc)[:180]}") from None
    bytes_data = stream.getvalue()
    if len(bytes_data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, "Revised Word copy is too large")
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix="automoto-rich-word-") as td:
        verification = Path(td) / "revised.docx"
        verification.write_bytes(bytes_data)
        meta = office.inspect_file(verification)
        if meta["macros"]:
            raise HTTPException(422, "The output contains active macros")
        Document(str(verification))  # required: real OOXML roundtrip
    if _sha(original) != body.sha256:
        raise HTTPException(409, "The original DOCX changed before publication")
    new_path = _unique(original.stem + "-edited", ".docx")
    _atomic_file(new_path, bytes_data)
    return {
        "path": new_path.relative_to(_root()).as_posix(),
        "source_sha256": body.sha256, "operations": len(changes),
        "changes": changes,
        "message": "Saved a new editable Word file; the original source was not changed.",
        "limitations": "Some advanced Word features may need manual review; this is a structured copy editor, not a lossless Word clone.",
    }
