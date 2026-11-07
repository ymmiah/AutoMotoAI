"""AutoMoto AI Spreadsheet & Invoice Intelligence v1 — private, offline foundations.

V1 deliberately stores literal cell data only. Imported formulas are *not*
evaluated; spreadsheet calculation and round-tripping arrive in later milestones.
All writes use fresh private paths and leave uploaded originals unchanged.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import secrets
import tempfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, ConfigDict, Field, model_validator

from automoto import office
from automoto.document_workspace import _atomic_file, _root
from automoto.visual_studio import _auth

router = APIRouter(prefix="/api/spreadsheets", tags=["spreadsheet-workspace"])
ROOT_DIR = "artifacts/spreadsheets"
MAX_SHEETS = 5
MAX_ROWS = 100
MAX_COLS = 16
MAX_CELL_CHARS = 2000
MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_SAVED_BYTES = 750_000
SHEET_FILE = re.compile(r"^[a-z0-9-]{1,48}-[0-9a-f]{12}\.sheet\.json$")
INVOICE_FILE = re.compile(r"^[a-z0-9-]{1,48}-[0-9a-f]{12}\.invoice\.json$")
BAD_SHEET_NAME = re.compile(r"[\[\]:*?/\\\\]")


class SheetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=31)
    rows: list[list[Any]] = Field(default_factory=list, max_length=MAX_ROWS)


class BookIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=100)
    sheets: list[SheetIn] = Field(..., min_length=1, max_length=MAX_SHEETS)


class ExportIn(BookIn):
    format: Literal["xlsx", "csv"] = "xlsx"


class ImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(..., min_length=9, max_length=300)


class InvoiceLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(..., min_length=1, max_length=200)
    quantity: str = Field(..., min_length=1, max_length=30)
    unit_price: str = Field(..., min_length=1, max_length=30)


class InvoiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: str = Field(..., min_length=1, max_length=60)
    seller: str = Field(..., min_length=1, max_length=500)
    customer: str = Field(..., min_length=1, max_length=500)
    issue_date: date
    due_date: date
    currency: Literal["GBP", "EUR", "USD"] = "GBP"
    tax_rate: str = Field("0", min_length=1, max_length=10)
    lines: list[InvoiceLine] = Field(..., min_length=1, max_length=40)

    @model_validator(mode="after")
    def due_after_issue(self):
        if self.due_date < self.issue_date:
            raise ValueError("The due date must not precede the invoice date.")
        return self


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.strip().lower()).strip("-")[:48] or "file"


def _storage(create: bool = False) -> Path:
    root = _root()
    parent = root / "artifacts"
    directory = root / ROOT_DIR
    if parent.is_symlink() or directory.is_symlink():
        raise HTTPException(403, "Spreadsheet storage symlinks are not allowed.")
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    if directory.exists() and not directory.is_dir():
        raise HTTPException(403, "Spreadsheet storage is not a directory.")
    if not directory.resolve().is_relative_to(root):
        raise HTTPException(403, "Spreadsheet storage is outside your workspace.")
    return directory


def _normalise(book: BookIn) -> dict[str, Any]:
    name = book.name.strip()
    if not name:
        raise HTTPException(422, "Enter a workbook name.")
    used: set[str] = set()
    sheets = []
    for sheet in book.sheets:
        label = sheet.name.strip()
        if not label or BAD_SHEET_NAME.search(label) or label.startswith("'") or label.endswith("'"):
            raise HTTPException(422, "A worksheet name is invalid for Excel.")
        if label.casefold() in used:
            raise HTTPException(422, "Worksheet names must be unique.")
        used.add(label.casefold())
        clean_rows = []
        for row in sheet.rows:
            if len(row) > MAX_COLS:
                raise HTTPException(422, "V1 supports a maximum of 16 columns per worksheet.")
            clean_row = []
            for value in row:
                if value is None or isinstance(value, bool):
                    clean_row.append(value)
                elif isinstance(value, str):
                    if len(value) > MAX_CELL_CHARS:
                        raise HTTPException(422, "One cell exceeds the 2,000-character limit.")
                    clean_row.append(value)
                elif isinstance(value, (int, float)):
                    if isinstance(value, float) and not math.isfinite(value) or abs(value) > 1e12:
                        raise HTTPException(422, "A numeric cell is outside the supported range.")
                    clean_row.append(value)
                else:
                    raise HTTPException(422, "Cells must contain text, numbers, booleans or blanks.")
            clean_rows.append(clean_row)
        sheets.append({"name": label, "rows": clean_rows})
    return {"name": name, "sheets": sheets}


def _make_path(name: str, suffix: str) -> Path:
    return _storage(create=True) / f"{_slug(name)}-{secrets.token_hex(6)}.{suffix}"


def _save_record(name: str, schema: str, data: dict[str, Any]) -> dict[str, str]:
    raw = json.dumps({"schema": schema, "data": data}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_SAVED_BYTES:
        raise HTTPException(413, "Private draft is too large.")
    extension = "sheet.json" if schema == "spreadsheet-v1" else "invoice.json"
    path = _make_path(name, extension)
    _atomic_file(path, raw)
    return {"path": path.relative_to(_root()).as_posix(), "sha256": hashlib.sha256(raw).hexdigest()}


def _load_record(raw: str, schema: str, expression: re.Pattern[str]) -> tuple[Path, dict[str, Any]]:
    if not isinstance(raw, str) or len(raw) > 300 or not raw.startswith(ROOT_DIR + "/"):
        raise HTTPException(403, "Only private spreadsheet drafts can be opened.")
    name = raw[len(ROOT_DIR) + 1:]
    if not expression.fullmatch(name):
        raise HTTPException(403, "Invalid private draft path.")
    path = _storage() / name
    if path.is_symlink() or not path.is_file():
        raise HTTPException(404, "Private draft not found.")
    if path.stat().st_size > MAX_SAVED_BYTES:
        raise HTTPException(413, "Private draft is too large.")
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
        if content.get("schema") != schema or not isinstance(content.get("data"), dict):
            raise ValueError("Invalid format")
        return path, content["data"]
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        raise HTTPException(422, "Private draft is corrupted.") from None


def _upload(raw: str) -> Path:
    if not isinstance(raw, str) or len(raw) > 300 or not raw.startswith("uploads/"):
        raise HTTPException(403, "Only uploaded spreadsheets can be imported.")
    name = raw[8:]
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise HTTPException(403, "Invalid upload path.")
    path = _root() / "uploads" / name
    if path.is_symlink() or path.parent.is_symlink() or not path.resolve().is_relative_to(_root()):
        raise HTTPException(403, "Import symlinks are prohibited.")
    if not path.is_file():
        raise HTTPException(404, "Uploaded file not found.")
    if path.suffix.lower() not in (".xlsx", ".csv"):
        raise HTTPException(415, "V1 can import .xlsx and .csv files only.")
    if path.stat().st_size > MAX_IMPORT_BYTES:
        raise HTTPException(413, "Upload exceeds the 10 MB V1 import limit.")
    return path


def _literal(value: Any, warnings: set[str]) -> Any:
    if value is None or isinstance(value, (int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) and abs(value) <= 1e12 else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    text = str(value)
    if text.startswith("="):
        warnings.add("Formula cells are imported as literal text, not recalculated or executed in V1.")
    if len(text) > MAX_CELL_CHARS:
        text = text[:MAX_CELL_CHARS]
        warnings.add("Some source cell text was truncated at 2,000 characters.")
    return text


def _import_source(path: Path) -> dict[str, Any]:
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    warnings: set[str] = set()
    sheets: list[dict[str, Any]] = []
    if path.suffix.lower() == ".xlsx":
        try:
            facts = office.inspect_file(path)
            if facts["macros"] or facts["external_links"]:
                raise HTTPException(422, "Macro-bearing or externally linked spreadsheets are refused.")
            wb = load_workbook(path, read_only=True, data_only=False, keep_links=False)
            try:
                for ws in wb.worksheets[:MAX_SHEETS]:
                    rows = []
                    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row or 1, MAX_ROWS),
                                            min_col=1, max_col=min(ws.max_column or 1, MAX_COLS),
                                            values_only=True):
                        rows.append([_literal(v, warnings) for v in row])
                    sheets.append({"name": ws.title, "rows": rows})
                    if (ws.max_row or 0) > MAX_ROWS or (ws.max_column or 0) > MAX_COLS:
                        warnings.add("Some source rows or columns were excluded by V1 preview limits.")
                if len(wb.worksheets) > MAX_SHEETS:
                    warnings.add("Only the first five source worksheets were imported.")
            finally:
                wb.close()
        except HTTPException:
            raise
        except (OSError, ValueError, KeyError, IndexError, TypeError, EOFError) as exc:
            raise HTTPException(422, "Could not safely import this Excel file.") from None
    else:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream)
                rows = []
                for i, row in enumerate(reader):
                    if i >= MAX_ROWS:
                        warnings.add("Only the first 100 CSV rows were imported.")
                        break
                    if len(row) > MAX_COLS:
                        warnings.add("CSV columns beyond the first 16 were excluded.")
                    rows.append([_literal(v, warnings) for v in row[:MAX_COLS]])
            sheets = [{"name": "Sheet1", "rows": rows}]
        except (UnicodeError, OSError, csv.Error, ValueError):
            raise HTTPException(422, "CSV must be valid UTF-8 and correctly formatted.") from None
    if hashlib.sha256(path.read_bytes()).hexdigest() != before:
        raise HTTPException(409, "Uploaded file changed during import.")
    result = _normalise(BookIn(name=path.stem[:100], sheets=[SheetIn(**s) for s in sheets]))
    return {"workbook": result, "sha256": before, "warnings": sorted(warnings),
            "original_unchanged": True, "not_full_fidelity": True}


def _write_xlsx(path: Path, workbook: dict[str, Any]) -> None:
    book = Workbook()
    book.remove(book.active)
    thin = Side(style="hair", color="CBD5E1")
    for source in workbook["sheets"]:
        sheet = book.create_sheet(source["name"])
        for i, row in enumerate(source["rows"], start=1):
            for j, value in enumerate(row, start=1):
                cell = sheet.cell(i, j)
                cell.value = value
                # A literal beginning with '=' must never become executable Excel code.
                if isinstance(value, str):
                    cell.data_type = "s"
                cell.alignment = Alignment(vertical="center", wrap_text=True)
                if i == 1:
                    cell.fill = PatternFill("solid", fgColor="1E293B")
                    cell.font = Font(name="Aptos", color="FFFFFF", bold=True, size=11)
                else:
                    cell.font = Font(name="Aptos", color="1E293B", size=10)
                cell.border = Border(bottom=thin)
        for col in range(1, min(MAX_COLS, max((len(r) for r in source["rows"]), default=1)) + 1):
            longest = max((len(str(r[col - 1])) for r in source["rows"] if len(r) >= col and r[col - 1] is not None), default=8)
            sheet.column_dimensions[get_column_letter(col)].width = min(38, max(13, longest + 3))
        sheet.freeze_panes = "A2"
        if source["rows"]:
            last = get_column_letter(max((len(r) for r in source["rows"]), default=1))
            sheet.auto_filter.ref = f"A1:{last}{len(source['rows'])}"
    book.save(path)


def _safe_csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    # CSV clients may interpret any of these prefixes as formula instructions.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def _money(raw: str, *, positive: bool = False, places: int = 2, maximum: str = "1000000") -> Decimal:
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", raw.strip()):
        raise HTTPException(422, "Enter non-negative decimal values for quantity, price and tax.")
    try:
        value = Decimal(raw.strip())
    except InvalidOperation:
        raise HTTPException(422, "Invalid decimal amount.") from None
    if value > Decimal(maximum) or value < 0 or (positive and value == 0):
        raise HTTPException(422, "Quantity, price or tax is outside the permitted range.")
    if value.as_tuple().exponent < -places:
        raise HTTPException(422, "Too many decimal places in a quantity, price or tax.")
    return value


def _invoice_preview(invoice: InvoiceIn) -> dict[str, Any]:
    rate = _money(invoice.tax_rate, maximum="100")
    lines = []
    net = Decimal("0")
    for item in invoice.lines:
        if not item.description.strip():
            raise HTTPException(422, "Invoice item descriptions cannot be blank.")
        qty = _money(item.quantity, positive=True, places=3)
        price = _money(item.unit_price)
        total = (qty * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        net += total
        lines.append({"description": item.description.strip(), "quantity": str(qty),
                      "unit_price": f"{price:.2f}", "line_total": f"{total:.2f}"})
    vat = (net * rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    gross = net + vat
    return {"currency": invoice.currency, "invoice_number": invoice.number.strip(),
            "lines": lines, "subtotal": f"{net:.2f}", "tax_rate": str(rate),
            "tax": f"{vat:.2f}", "total": f"{gross:.2f}",
            "draft_only": True, "sent": False, "paid": False,
            "notice": "Draft calculations only. Confirm VAT treatment, invoice details and legal requirements before issuing."}


def _write_invoice(path: Path, inv: InvoiceIn, totals: dict[str, Any]) -> None:
    book = Workbook()
    ws = book.active
    ws.title = "Invoice draft"
    ws.merge_cells("A1:D1")
    ws["A1"] = "INVOICE · DRAFT"
    ws["A1"].font = Font(name="Aptos Display", size=19, bold=True, color="142638")
    ws["A3"], ws["B3"] = "Number", inv.number
    ws["A4"], ws["B4"] = "Issue date", inv.issue_date.isoformat()
    ws["A5"], ws["B5"] = "Due date", inv.due_date.isoformat()
    ws["A7"], ws["C7"] = "From", "Bill to"
    ws["A8"], ws["C8"] = inv.seller, inv.customer
    ws["A8"].alignment = ws["C8"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[8].height = 62
    for j, value in enumerate(("Description", "Qty", f"Unit ({inv.currency})", f"Line ({inv.currency})"), start=1):
        cell = ws.cell(11, j, value)
        cell.fill = PatternFill("solid", fgColor="17324D")
        cell.font = Font(color="FFFFFF", bold=True)
    for i, item in enumerate(totals["lines"], start=12):
        ws.cell(i, 1, item["description"]).data_type = "s"
        ws.cell(i, 2, Decimal(item["quantity"]))
        ws.cell(i, 3, Decimal(item["unit_price"]))
        ws.cell(i, 4, Decimal(item["line_total"]))
        for j in (3, 4):
            ws.cell(i, j).number_format = '#,##0.00'
    footer = 13 + len(totals["lines"])
    for idx, (label, val) in enumerate((("Subtotal", totals["subtotal"]),
                                         ("Tax (" + totals["tax_rate"] + "%)", totals["tax"]),
                                         ("Total " + inv.currency, totals["total"])), start=footer):
        ws.cell(idx, 3, label)
        ws.cell(idx, 4, Decimal(val))
        ws.cell(idx, 4).number_format = '#,##0.00'
        ws.cell(idx, 3).font = Font(bold=True)
        ws.cell(idx, 4).font = Font(bold=True)
    ws.cell(footer + 5, 1, "DRAFT ONLY · Verify all invoice details before issue.")
    for col, width in {"A": 45, "B": 18, "C": 25, "D": 23}.items():
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A12"
    ws.sheet_view.showGridLines = False
    book.save(path)


def _deliver_excel(workbook: dict[str, Any], name: str) -> dict[str, Any]:
    target = _make_path(name, "xlsx")
    with tempfile.TemporaryDirectory(prefix="automoto-sheet-") as folder:
        temporary = Path(folder) / "safe.xlsx"
        _write_xlsx(temporary, workbook)
        facts = office.inspect_file(temporary)
        if facts["macros"] or facts["external_links"]:
            raise HTTPException(422, "Unsafe workbook output refused.")
        _atomic_file(target, temporary.read_bytes())
    return {"path": target.relative_to(_root()).as_posix(), "format": "xlsx",
            "download_url": "/api/files/download?path=" + target.relative_to(_root()).as_posix(),
            "formulas_evaluated": False, "original_unchanged": True}


@router.get("/list")
def list_spreadsheets(request: Request):
    _auth(request)
    directory = _storage()
    drafts = []
    invoices = []
    if directory.is_dir():
        for path in directory.iterdir():
            if path.is_symlink() or not path.is_file():
                continue
            if SHEET_FILE.fullmatch(path.name):
                drafts.append({"path": path.relative_to(_root()).as_posix(), "name": path.name,
                               "bytes": path.stat().st_size})
            elif INVOICE_FILE.fullmatch(path.name):
                invoices.append({"path": path.relative_to(_root()).as_posix(), "name": path.name,
                                 "bytes": path.stat().st_size})
    imports = []
    upload_dir = _root() / "uploads"
    if upload_dir.is_dir() and not upload_dir.is_symlink():
        for path in upload_dir.iterdir():
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in (".xlsx", ".csv") and path.stat().st_size <= MAX_IMPORT_BYTES:
                imports.append({"path": path.relative_to(_root()).as_posix(), "name": path.name})
    drafts.sort(key=lambda item: item["name"], reverse=True)
    invoices.sort(key=lambda item: item["name"], reverse=True)
    imports.sort(key=lambda item: item["name"].lower())
    return {"workbooks": drafts[:100], "invoices": invoices[:100], "imports": imports[:100],
            "offline": True, "limits": {"sheets": MAX_SHEETS, "rows": MAX_ROWS, "columns": MAX_COLS}}


@router.post("/import")
def import_spreadsheet(body: ImportIn, request: Request):
    _auth(request)
    return _import_source(_upload(body.path))


@router.post("/save")
def save_spreadsheet(body: BookIn, request: Request):
    _auth(request)
    workbook = _normalise(body)
    return {**_save_record(workbook["name"], "spreadsheet-v1", workbook), "original_unchanged": True}


@router.get("/load")
def load_spreadsheet(path: str, request: Request):
    _auth(request)
    target, content = _load_record(path, "spreadsheet-v1", SHEET_FILE)
    book = _normalise(BookIn.model_validate(content))
    return {"workbook": book, "path": target.relative_to(_root()).as_posix(), "read_only": True}


@router.post("/export")
def export_spreadsheet(body: ExportIn, request: Request):
    _auth(request)
    book = _normalise(body)
    if body.format == "xlsx":
        return _deliver_excel(book, book["name"])
    if len(book["sheets"]) != 1:
        raise HTTPException(422, "CSV export needs exactly one worksheet.")
    target = _make_path(book["name"], "csv")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    for row in book["sheets"][0]["rows"]:
        writer.writerow([_safe_csv_cell(v) for v in row])
    _atomic_file(target, stream.getvalue().encode("utf-8-sig"))
    rel = target.relative_to(_root()).as_posix()
    return {"path": rel, "format": "csv", "download_url": "/api/files/download?path=" + rel,
            "original_unchanged": True}


@router.post("/invoice/preview")
def preview_invoice(body: InvoiceIn, request: Request):
    _auth(request)
    return _invoice_preview(body)


@router.post("/invoice/save")
def save_invoice(body: InvoiceIn, request: Request):
    _auth(request)
    _invoice_preview(body)
    return {**_save_record(body.number, "invoice-v1", body.model_dump(mode="json")),
            "draft_only": True, "sent": False}


@router.get("/invoice/load")
def load_invoice(path: str, request: Request):
    _auth(request)
    target, content = _load_record(path, "invoice-v1", INVOICE_FILE)
    body = InvoiceIn.model_validate(content)
    return {"invoice": body.model_dump(mode="json"), "path": target.relative_to(_root()).as_posix(),
            "draft_only": True, "sent": False}


@router.post("/invoice/export")
def export_invoice(body: InvoiceIn, request: Request):
    _auth(request)
    totals = _invoice_preview(body)
    target = _make_path("invoice-" + body.number, "xlsx")
    with tempfile.TemporaryDirectory(prefix="automoto-invoice-") as folder:
        temporary = Path(folder) / "invoice.xlsx"
        _write_invoice(temporary, body, totals)
        facts = office.inspect_file(temporary)
        if facts["macros"] or facts["external_links"]:
            raise HTTPException(422, "Unsafe invoice output refused.")
        _atomic_file(target, temporary.read_bytes())
    rel = target.relative_to(_root()).as_posix()
    return {"path": rel, "download_url": "/api/files/download?path=" + rel,
            "format": "xlsx", "draft_only": True, "sent": False, "paid": False, "totals": totals}
