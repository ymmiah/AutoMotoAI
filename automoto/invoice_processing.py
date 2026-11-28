"""Invoice Processing (Phase 2, issue #10): extract, validate, review, export.

Workflow: a source file already in the user's private ``uploads/`` folder (or an
authorised email attachment saved there) -> text extraction -> validated JSON
with per-field source location and confidence -> vendor/order-line matching ->
anomaly detection -> draft record -> human approval -> CSV/XLSX/JSON/audit-PDF
export.

What this module does NOT do: it never pays, sends, posts, modifies an ERP or
submits bank changes. Approval only marks a draft record approved; there is no
payment, dispatch or accounting action anywhere in this module. Tax/VAT rates
are configurable policies, never a legal determination: an unrecognised rate is
flagged for human review, never silently accepted or invented.

Offline-first: text extraction uses the local pypdf / python-docx / openpyxl
stack already in the app. Image OCR is optional and only runs when a local
``tesseract`` binary is present on the host; a scanned image with no OCR engine
is stored as ``needs_ocr`` with no fields invented. No cloud service, no new
mandatory dependency, no Pinecone.

Evidence: every extracted field carries its source location (page, line,
character span, verbatim source text) and a confidence score. A field that
cannot be found is ``null`` with confidence 0 and a ``missing_field`` issue --
never guessed. Imported originals are copied once into the private invoice
store and never modified; extracted records are create-only JSON files.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import secrets
import shutil
import subprocess
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from automoto import sandbox
from automoto.document_workspace import _atomic_file, _root, _sha
from automoto.visual_studio import _auth

router = APIRouter(prefix="/api/invoices", tags=["invoice-processing"])

SCHEMA = "invoice-extract-v1"
MAX_SOURCE_BYTES = 10_000_000
MAX_PDF_PAGES = 50
MAX_TEXT_CHARS = 180_000
MAX_LINES = 200
MAX_RECORDS = 200
CENT = Decimal("0.01")
TOLERANCE = Decimal("0.01")
SUPPORTED = {".pdf", ".txt", ".md", ".docx", ".xlsx", ".csv", ".png", ".jpg", ".jpeg"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
CURRENCIES = {
    "GBP", "EUR", "USD", "CHF", "JPY", "CAD", "AUD", "NZD", "SEK", "NOK", "DKK",
    "PLN", "CZK", "HUF", "RON", "BGN", "HRK", "ISK", "SGD", "HKD", "INR", "ZAR",
}
SYMBOL_TO_CURRENCY = {"£": "GBP", "€": "EUR", "$": "USD", "¥": "JPY", "₹": "INR"}
# Configurable VAT policy: name -> rate percent. These are policy values the
# user configures, not legal advice; anything outside them is flagged.
DEFAULT_VAT_POLICY = {"standard": "20", "reduced": "5", "zero": "0"}
BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
TOKEN = re.compile(r"^[0-9a-f]{24}$")
MONEY_RE = re.compile(
    r"(?:£|€|\$|¥|₹)?\s*-?\d{1,3}(?:[,\s]\d{3})*(?:[.,]\d{2})|-?\d+(?:[.,]\d{2})?")
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?\b")
SORT_CODE_RE = re.compile(r"\b\d{2}-\d{2}-\d{2}\b")

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _store(create: bool = False) -> Path:
    root = _root()
    directory = root / "artifacts" / "invoices"
    if create:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        for sub in ("sources", "records", "exports"):
            (directory / sub).mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.exists():
        if directory.is_symlink() or not directory.is_dir():
            raise HTTPException(403, "Invoice storage must remain private.")
        if not directory.resolve().is_relative_to(root):
            raise HTTPException(403, "Invoice storage escapes this workspace.")
    return directory


def _records_dir(create: bool = False) -> Path:
    return _store(create) / "records"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.lower().strip()).strip("-")[:48] or "invoice"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _source_path(raw: str) -> Path:
    """Confine an extraction source to uploads/ (same rule as Document Assistant)."""
    if not raw or "\\" in raw or raw.startswith("/") or any(c in raw for c in "\x00\r\n"):
        raise HTTPException(403, "invalid invoice source path")
    try:
        path = sandbox.resolve(raw, base=_root(), allow_outside=False)
        relative = path.relative_to(_root())
    except (ValueError, sandbox.SandboxError):
        raise HTTPException(403, "invoice source is outside your private workspace") from None
    if not relative.parts or relative.parts[0] != "uploads" or len(relative.parts) < 2:
        raise HTTPException(403, "invoices are extracted only from uploads/")
    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != _root()):
        raise HTTPException(403, "invoice source symlinks are not allowed")
    if not path.is_file():
        raise HTTPException(404, "invoice source not found")
    if path.suffix.lower() not in SUPPORTED:
        raise HTTPException(415, "unsupported invoice source format")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise HTTPException(413, "invoice source exceeds the 10 MB limit")
    return path


def _copy_source(path: Path, sha: str) -> Path:
    """Copy-only import of the original; the uploaded file is never modified."""
    folder = _store(create=True) / "sources"
    name = f"{sha[:16]}-{_slug(path.stem)}{path.suffix.lower()}"
    target = folder / name
    if not target.exists():
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:
            raise HTTPException(409, "Invoice source changed during import.")
        _atomic_file(target, data)
        try:
            target.chmod(0o600)
        except OSError:
            pass
    return target


def _save_record(record: dict) -> Path:
    folder = _records_dir(create=True)
    target = folder / f"{record['id']}.json"
    raw = json.dumps({"schema": SCHEMA, "data": record}, ensure_ascii=False,
                     separators=(",", ":")).encode("utf-8")
    if target.exists():
        # Our own record: rewrite atomically (the imported original is untouched).
        tmp = target.with_name(f".working-{secrets.token_hex(8)}.part")
        try:
            tmp.write_bytes(raw)
            tmp.replace(target)
        finally:
            tmp.unlink(missing_ok=True)
    else:
        _atomic_file(target, raw)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target


def _load_record(record_id: str) -> dict:
    if not TOKEN.fullmatch(record_id or ""):
        raise HTTPException(422, "Invalid invoice record identifier.")
    path = _records_dir() / f"{record_id}.json"
    if path.is_symlink() or not path.is_file():
        raise HTTPException(404, "Invoice record not found.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != SCHEMA or not isinstance(payload.get("data"), dict):
            raise ValueError("Unsupported schema")
        return payload["data"]
    except (OSError, ValueError, TypeError, AttributeError, UnicodeError):
        raise HTTPException(422, "Invoice record is corrupted.") from None


def _all_records() -> list[dict]:
    folder = _records_dir()
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.json"), key=lambda p: p.name, reverse=True)[:MAX_RECORDS]:
        try:
            out.append(_load_record(path.stem))
        except HTTPException:
            continue
    return out


# ---------------------------------------------------------------------------
# Text extraction (local only)
# ---------------------------------------------------------------------------


def _lines_of(page: int, text: str) -> list[dict]:
    lines = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if raw.strip():
            lines.append({"page": page, "line": number, "text": raw.rstrip()})
    return lines


def _extract_pages(path: Path) -> tuple[list[dict], bool, str | None]:
    """Return (lines, needs_ocr, note). Lines carry page/line/text for evidence."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                raise HTTPException(422, "Encrypted PDFs require an independently unlocked copy.")
            total = len(reader.pages)
            lines: list[dict] = []
            for i in range(min(total, MAX_PDF_PAGES)):
                text = reader.pages[i].extract_text() or ""
                lines.extend(_lines_of(i + 1, text))
                if sum(len(item["text"]) for item in lines) >= MAX_TEXT_CHARS:
                    break
            if not lines:
                return [], True, "PDF has no extractable text (scanned image only)."
            return lines, False, ("partial: only the first "
                                  f"{MAX_PDF_PAGES} pages were read." if total > MAX_PDF_PAGES else None)
        except HTTPException:
            raise
        except (OSError, ValueError, TypeError, UnicodeError, KeyError, IndexError,
                EOFError, PdfReadError) as exc:
            raise HTTPException(422, "Could not safely extract this PDF: " + str(exc)[:160]) from None
    if suffix in (".txt", ".md"):
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError) as exc:
            raise HTTPException(422, "Could not safely read this text source: "
                                + str(exc)[:160]) from None
        return _lines_of(1, text[:MAX_TEXT_CHARS]), False, None
    if suffix == ".docx":
        from automoto import office
        try:
            facts = office.inspect_file(path)
            if facts.get("macros"):
                raise HTTPException(422, "Macro-containing sources are not accepted for invoices.")
            return _lines_of(1, office.read_docx(path)[:MAX_TEXT_CHARS]), False, None
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, "Could not safely extract this document: "
                                + str(exc)[:160]) from None
    if suffix == ".xlsx":
        from openpyxl import load_workbook
        try:
            book = load_workbook(str(path), read_only=True, data_only=True)
            lines = []
            for sheet in book.worksheets:
                for row in sheet.iter_rows(values_only=True):
                    cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                    if cells:
                        lines.append({"page": 1, "line": len(lines) + 1,
                                      "text": " ".join(cells), "sheet": sheet.title})
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, "Could not safely extract this spreadsheet: "
                                + str(exc)[:160]) from None
        return lines[:MAX_TEXT_CHARS // 40], False, None
    if suffix == ".csv":
        try:
            text = path.read_text(encoding="utf-8-sig", errors="strict")
            rows = list(csv.reader(io.StringIO(text)))
        except (OSError, UnicodeError, csv.Error) as exc:
            raise HTTPException(422, "Could not safely read this CSV source: "
                                + str(exc)[:160]) from None
        lines = [{"page": 1, "line": i + 1, "text": " | ".join(c.strip() for c in row if c.strip())}
                 for i, row in enumerate(rows)
                 if any(c.strip() for c in row)]
        return lines, False, None
    if suffix in IMAGE_EXTS:
        binary = shutil.which("tesseract")
        if binary is None:
            return [], True, "Image source needs OCR; no local tesseract binary is installed."
        try:
            proc = subprocess.run(
                [binary, str(path), "stdout", "--psm", "6"],
                capture_output=True, text=True, timeout=120, check=False)
        except (OSError, subprocess.SubprocessError):
            return [], True, "Local OCR failed to run on this image."
        if proc.returncode != 0 or not proc.stdout.strip():
            return [], True, "Local OCR produced no text for this image."
        return _lines_of(1, proc.stdout[:MAX_TEXT_CHARS]), False, "Text from local tesseract OCR."
    raise HTTPException(415, "unsupported invoice source format")


# ---------------------------------------------------------------------------
# Money, dates, evidence
# ---------------------------------------------------------------------------


def _parse_money(raw: str) -> Decimal | None:
    """Parse 1,234.56 and 1.234,56 (decimal comma) deterministically."""
    if raw is None:
        return None
    text = str(raw).strip().replace("£", "").replace("€", "").replace("$", "") \
        .replace("¥", "").replace("₹", "").replace("\u00a0", " ").strip()
    text = re.sub(r"^(GBP|EUR|USD|CHF|JPY)\s+", "", text, flags=re.I)
    text = text.replace(" ", "")
    if not re.fullmatch(r"-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?|-?\d+(?:[.,]\d{1,2})?", text):
        return None
    if "," in text and "." in text:
        # The last separator is the decimal point; the other groups thousands.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        text = text.replace(",", ".") if len(parts) == 2 and len(parts[-1]) in (1, 2) \
            else text.replace(",", "")
    elif "." in text:
        # A lone dot with only 3-digit groups (1.000, 1.234.567) is a thousands
        # separator, not a decimal point; 1.5 and 12.34 stay decimal.
        parts = text.split(".")
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]) \
                and len(parts[0].lstrip("-")) <= 3:
            text = text.replace(".", "")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if abs(value) > Decimal("1000000000"):
        return None
    return value


def _round(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _parse_date(raw: str) -> str | None:
    text = raw.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y",
                "%B %d, %Y", "%b %d, %Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


_DATE_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}[-.]\d{1,2}[-.]\d{2,4}"
    r"|\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}"
    r"|(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4})\b",
    re.I)


def _field(value: Any, confidence: float, line: dict | None = None,
           start: int = 0, end: int = 0) -> dict:
    """One extracted field: value, confidence, and its exact source location."""
    if line is None:
        return {"value": value, "confidence": confidence, "source": None}
    return {"value": value, "confidence": confidence,
            "source": {"page": line.get("page"), "line": line.get("line"),
                       "sheet": line.get("sheet"),
                       "start": start, "end": end, "text": line["text"]}}


def _find_label(lines: list[dict], labels: tuple[str, ...]) -> tuple[dict, re.Match] | None:
    pattern = re.compile(r"^\s*(?:" + "|".join(labels) + r")\s*[:#-]?\s*(.+)$", re.I)
    for line in lines:
        match = pattern.match(line["text"])
        if match:
            return line, match
    return None


def _money_in(text: str) -> tuple[Decimal, int, int] | None:
    """Best money match: prefer a currency symbol, then a decimal part, so a
    rate such as 'VAT 20%: £9.00' yields 9.00 and not 20."""
    best: tuple[int, Decimal, int, int] | None = None
    for match in re.finditer(r"[£€$¥₹]?\s*-?\d[\d\s.,]*\d(?:[.,]\d{2})?", text):
        value = _parse_money(match.group(0))
        if value is None:
            continue
        score = (2 if re.search(r"[£€$¥₹]", match.group(0)) else 0) \
            + (1 if re.search(r"[.,]\d{2}$", match.group(0).strip()) else 0)
        if best is None or score > best[0]:
            best = (score, value, match.start(), match.end())
    if best is None:
        return None
    return best[1], best[2], best[3]

# ---------------------------------------------------------------------------
# Field extraction (deterministic, label-driven; nothing is invented)
# ---------------------------------------------------------------------------

_LABEL_VALUE = ("invoice no", "invoice number", "invoice #", "invoice ref", "inv no",
                "invoice no\\.", "ref no")
_DATE_LABELS = ("invoice date", "date issued", "issued", "issue date", "date")
_DUE_LABELS = ("due date", "payment due", "due by", "pay by")
_SELLER_LABELS = ("from", "seller", "supplier", "billed by", "issued by", "vendor")
_BUYER_LABELS = ("bill to", "billed to", "customer", "sold to", "buyer", "client",
                 "invoice to", "payable by")
_VAT_NO_LABELS = ("vat no", "vat number", "vat reg", "vat registration", "tax id",
                  "tax no", "tax number", "company no", "registration no")
_TOTAL_LABELS = ("total due", "amount due", "balance due", "grand total", "total",
                 "amount payable", "total amount")
_SUBTOTAL_LABELS = ("subtotal", "sub-total", "net total", "net amount", "total excl")
_TAX_LABELS = ("vat amount", "vat", "tax amount", "tax", "gst amount", "sales tax")


def _labelled_money(lines: list[dict], labels: tuple[str, ...],
                    skip_labels: tuple[str, ...] = ()) -> dict | None:
    pattern = re.compile(r"^\s*(?:" + "|".join(labels) + r")\s*[:#-]?\s*(.+)$", re.I)
    skip = re.compile(r"^\s*(?:" + "|".join(skip_labels) + r")\b", re.I) if skip_labels else None
    for line in lines:
        if skip and skip.search(line["text"]):
            continue
        match = pattern.match(line["text"])
        if not match:
            continue
        # "VAT No: GB123456789" is an identifier, not an amount.
        if re.match(r"\s*(no|number|num|ref)\b", match.group(1), re.I):
            continue
        money = _money_in(match.group(1))
        if money is None:
            continue
        value, start, end = money
        base = match.start(1)
        return _field(str(value), 0.95, line, base + start, base + end)
    return _field(None, 0.0)


def _labelled_date(lines: list[dict], labels: tuple[str, ...]) -> dict | None:
    found = _find_label(lines, labels)
    if not found:
        return _field(None, 0.0)
    line, match = found
    value_text = match.group(1)
    found_date = _DATE_RE.search(value_text)
    if not found_date:
        return _field(None, 0.0)
    parsed = _parse_date(found_date.group(0))
    if parsed is None:
        return _field(None, 0.0)
    base = match.start(1)
    return _field(parsed, 0.95, line, base + found_date.start(), base + found_date.end())


def _labelled_text(lines: list[dict], labels: tuple[str, ...],
                   max_len: int = 140) -> dict | None:
    found = _find_label(lines, labels)
    if not found:
        return _field(None, 0.0)
    line, match = found
    value = match.group(1).strip()
    if not value or BAD.search(value):
        return _field(None, 0.0)
    return _field(value[:max_len], 0.95, line, match.start(1), match.end(1))


def _party(lines: list[dict], labels: tuple[str, ...], fallback_first: bool = False) -> dict:
    labelled = _labelled_text(lines, labels)
    if labelled["value"] is not None:
        return labelled
    if fallback_first:
        # Seller is often the first non-empty line(s) of a letterhead invoice.
        for line in lines[:3]:
            text = line["text"].strip()
            if text and "invoice" not in text.lower() and len(text) <= 80 \
                    and _money_in(text) is None:
                return _field(text, 0.65, line, 0, len(text))
    return _field(None, 0.0)


def _currency(lines: list[dict], totals: dict) -> dict:
    joined = "\n".join(item["text"] for item in lines)
    # A currency symbol on a line that actually carries a money amount beats a
    # bare code word mentioned anywhere in the document (e.g. a note about an
    # exchange rate), so check amount lines first.
    for symbol, code in SYMBOL_TO_CURRENCY.items():
        for line in lines:
            if symbol in line["text"] and _money_in(line["text"]) is not None:
                return _field(code, 0.9, line, line["text"].index(symbol),
                              line["text"].index(symbol) + 1)
    for code in sorted(CURRENCIES):
        if re.search(r"\b" + code + r"\b", joined):
            for line in lines:
                hit = re.search(r"\b" + code + r"\b", line["text"])
                if hit:
                    return _field(code, 0.9, line, hit.start(), hit.end())
    for symbol, code in SYMBOL_TO_CURRENCY.items():
        for line in lines:
            if symbol in line["text"]:
                return _field(code, 0.85, line, line["text"].index(symbol),
                              line["text"].index(symbol) + 1)
    return _field(None, 0.0)


def _vat_rate(lines: list[dict], policy: dict[str, str]) -> dict:
    for line in lines:
        match = re.search(r"VAT\s*(?:@|at|rate)?\s*(\d+(?:\.\d+)?)\s*%", line["text"], re.I)
        if match:
            return _field(match.group(1), 0.9, line, match.start(1), match.end(1))
        match = re.search(r"(?:tax|VAT)\s*(?:@|at)?\s*(\d+(?:\.\d+)?)\s*%", line["text"], re.I)
        if match:
            return _field(match.group(1), 0.85, line, match.start(1), match.end(1))
    return _field(None, 0.0)


def _bank_fields(lines: list[dict]) -> dict:
    iban = _field(None, 0.0)
    sort_code = _field(None, 0.0)
    account = _field(None, 0.0)
    reference = _field(None, 0.0)
    for line in lines:
        text = line["text"]
        if iban["value"] is None:
            hit = IBAN_RE.search(text)
            if hit:
                iban = _field(hit.group(0).replace(" ", ""), 0.95, line,
                              hit.start(), hit.end())
        if sort_code["value"] is None:
            hit = SORT_CODE_RE.search(text)
            if hit:
                sort_code = _field(hit.group(0), 0.95, line, hit.start(), hit.end())
        if account["value"] is None:
            hit = re.search(r"account\s*(?:no|number|#)?\s*[:#-]?\s*(\d{6,10})\b",
                            text, re.I)
            if hit:
                account = _field(hit.group(1), 0.9, line, hit.start(1), hit.end(1))
        if reference["value"] is None:
            hit = re.search(r"(?:payment\s+ref(?:erence)?|pay(?:ment)?\s+ref)\s*[:#-]?\s*([A-Za-z0-9][A-Za-z0-9 -]{2,30})",
                            text, re.I)
            if hit:
                reference = _field(hit.group(1).strip(), 0.85, line,
                                   hit.start(1), hit.end(1))
    return {"iban": iban, "sort_code": sort_code, "account_number": account,
            "payment_reference": reference}


_LINE_ROW = re.compile(
    r"^(?P<desc>.+?)\s+(?P<qty>\d+(?:[.,]\d+)?)\s*(?:x|×)?\s+"
    r"(?P<unit>[£€$¥₹]?\s*-?\d[\d\s.,]*\d(?:[.,]\d{2})?)\s+"
    r"(?P<total>[£€$¥₹]?\s*-?\d[\d\s.,]*\d(?:[.,]\d{2})?)\s*$")
_SINGLE_AMOUNT = re.compile(
    r"^(?P<desc>[A-Za-z][A-Za-z0-9 ,.'()\-/&]{2,80}?)\s+"
    r"(?P<amount>[£€$¥₹]?\s*-?\d[\d\s.,]*\d(?:[.,]\d{2})?)\s*$")
_SKIP_LINE = re.compile(r"subtotal|total|tax|vat|balance|amount due|due date|invoice|page \d"
                        r"|iban|sort code|account no|account number|payment ref|vat no|reg no",
                        re.I)


def _line_items(lines: list[dict]) -> list[dict]:
    items: list[dict] = []
    for line in lines:
        text = line["text"].strip()
        if _SKIP_LINE.search(text) or len(text) > 160:
            continue
        match = _LINE_ROW.match(text)
        if match:
            qty = _parse_money(match.group("qty").replace(",", "."))
            unit = _parse_money(match.group("unit"))
            total = _parse_money(match.group("total"))
            if qty is None or unit is None or total is None or qty <= 0:
                continue
            items.append({
                "description": _field(match.group("desc").strip(), 0.9, line,
                                      match.start("desc"), match.end("desc")),
                "quantity": _field(str(qty), 0.9, line, match.start("qty"), match.end("qty")),
                "unit_price": _field(str(unit), 0.9, line, match.start("unit"), match.end("unit")),
                "line_total": _field(str(total), 0.9, line, match.start("total"), match.end("total")),
            })
            continue
        match = _SINGLE_AMOUNT.match(text)
        if match and not re.search(r"\b(date|number|no\.?|ref)\b", text, re.I):
            amount = _parse_money(match.group("amount"))
            if amount is None:
                continue
            items.append({
                "description": _field(match.group("desc").strip(), 0.7, line,
                                      match.start("desc"), match.end("desc")),
                "quantity": _field("1", 0.7, line, 0, 0),
                "unit_price": _field(str(amount), 0.7, line,
                                     match.start("amount"), match.end("amount")),
                "line_total": _field(str(amount), 0.7, line,
                                     match.start("amount"), match.end("amount")),
            })
    return items[:MAX_LINES]


def _parse_invoice(lines: list[dict], policy: dict[str, str]) -> dict:
    """Extract every Phase 2 field with evidence; missing fields stay null."""
    number = _labelled_text(lines, _LABEL_VALUE, 60)
    if number["value"] is None:
        for line in lines:
            hit = re.search(r"\b(?:INV|INVOICE)[- ]?(\d{3,})\b", line["text"], re.I)
            if hit:
                number = _field(hit.group(0), 0.8, line, hit.start(), hit.end())
                break
    seller = _party(lines, _SELLER_LABELS, fallback_first=True)
    buyer = _party(lines, _BUYER_LABELS)
    issue_date = _labelled_date(lines, _DATE_LABELS)
    due_date = _labelled_date(lines, _DUE_LABELS)
    vat_number = _labelled_text(lines, _VAT_NO_LABELS, 40)
    subtotal = _labelled_money(lines, _SUBTOTAL_LABELS)
    tax_amount = _labelled_money(lines, _TAX_LABELS)
    total = _labelled_money(lines, _TOTAL_LABELS, _SUBTOTAL_LABELS)
    vat_rate = _vat_rate(lines, policy)
    currency = _currency(lines, {})
    bank = _bank_fields(lines)
    line_items = _line_items(lines)
    # If no labelled subtotal exists, derive it from the line items (marked low).
    if subtotal["value"] is None and line_items:
        derived = sum(Decimal(item["line_total"]["value"]) for item in line_items)
        subtotal = {"value": str(_round(derived)), "confidence": 0.6,
                    "source": None, "derived_from": "line_items"}
    fields = {
        "seller": seller, "buyer": buyer, "invoice_number": number,
        "issue_date": issue_date, "due_date": due_date, "currency": currency,
        "vat_number": vat_number, "vat_rate_percent": vat_rate,
        "subtotal": subtotal, "tax_amount": tax_amount, "total": total,
        "bank": bank,
    }
    return {"fields": fields, "lines": line_items}


# ---------------------------------------------------------------------------
# Validation (Decimal arithmetic, duplicates, VAT policy, missing fields)
# ---------------------------------------------------------------------------


def _issue(code: str, severity: str, message: str, field: str | None = None) -> dict:
    return {"code": code, "severity": severity, "field": field, "message": message}


def _dec(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _validate(record: dict, policy: dict[str, str],
              existing: list[dict]) -> list[dict]:
    fields = record["fields"]
    lines = record["lines"]
    issues: list[dict] = []

    required = {"invoice_number": "Invoice number", "issue_date": "Issue date",
                "seller": "Seller", "total": "Total amount", "currency": "Currency"}
    for key, label in required.items():
        value = fields[key]["value"]
        if value is None or (isinstance(value, str) and not value.strip()):
            issues.append(_issue("missing_field", "error", f"{label} was not found in the source.", key))

    # Line arithmetic: qty x unit price, then lines vs subtotal, then total.
    line_sum = Decimal("0")
    for index, item in enumerate(lines):
        qty = _dec(item["quantity"]["value"])
        unit = _dec(item["unit_price"]["value"])
        stated = _dec(item["line_total"]["value"])
        if qty is None or unit is None or stated is None:
            continue
        expected = _round(qty * unit)
        line_sum += expected
        if abs(expected - stated) > TOLERANCE:
            issues.append(_issue("arithmetic_line_total", "error",
                                 f"Line {index + 1} ({item['description']['value']}): "
                                 f"{qty} x {unit} = {expected}, but the source states {stated}.",
                                 f"lines[{index}].line_total"))
    subtotal = _dec(fields["subtotal"]["value"])
    if lines and subtotal is not None and abs(line_sum - subtotal) > TOLERANCE:
        issues.append(_issue("arithmetic_subtotal", "error",
                             f"Line items sum to {line_sum}, but the stated subtotal is {subtotal}.",
                             "subtotal"))
    tax = _dec(fields["tax_amount"]["value"])
    total = _dec(fields["total"]["value"])
    if subtotal is not None and tax is not None and total is not None:
        if abs((subtotal + tax) - total) > TOLERANCE:
            issues.append(_issue("arithmetic_total", "error",
                                 f"Subtotal {subtotal} + tax {tax} = {subtotal + tax}, "
                                 f"but the stated total is {total}.", "total"))
    rate = _dec(fields["vat_rate_percent"]["value"])
    if rate is not None and tax is not None and subtotal is not None:
        expected_tax = _round(subtotal * rate / Decimal("100"))
        if abs(expected_tax - tax) > TOLERANCE:
            issues.append(_issue("arithmetic_vat", "error",
                                 f"VAT at {rate}% of {subtotal} is {expected_tax}, "
                                 f"but the source states {tax}.", "tax_amount"))
    if rate is not None:
        allowed = {Decimal(v) for v in policy.values()}
        if rate not in allowed:
            issues.append(_issue("vat_rate_unrecognised", "warning",
                                 f"VAT rate {rate}% is not in the configured policy "
                                 f"({', '.join(sorted(policy.values()))}%). Needs human review; "
                                 "this is not a legal determination.", "vat_rate_percent"))
    if not lines:
        issues.append(_issue("no_line_items", "warning",
                             "No line items could be extracted from the source.", "lines"))
    issue_date = fields["issue_date"]["value"]
    due_date = fields["due_date"]["value"]
    if issue_date and due_date and due_date < issue_date:
        issues.append(_issue("due_before_issue", "error",
                             f"Due date {due_date} is before issue date {issue_date}.", "due_date"))
    # Duplicates: same source file, or same seller + invoice number.
    seller = (fields["seller"]["value"] or "").strip().lower()
    number = (fields["invoice_number"]["value"] or "").strip()
    for other in existing:
        if other["id"] == record["id"]:
            continue
        if other.get("source_sha256") == record["source_sha256"]:
            issues.append(_issue("duplicate_invoice", "error",
                                 "This exact source file was already processed as record "
                                 f"{other['id']}.", "invoice_number"))
            break
        other_fields = other.get("fields", {})
        other_seller = (other_fields.get("seller", {}).get("value") or "").strip().lower()
        other_number = (other_fields.get("invoice_number", {}).get("value") or "").strip()
        if seller and number and seller == other_seller and number == other_number:
            issues.append(_issue("duplicate_invoice", "error",
                                 f"Invoice {number} from {fields['seller']['value']} was already "
                                 f"processed as record {other['id']}.", "invoice_number"))
            break
    low = [key for key, item in fields.items()
           if key != "bank" and item["value"] is not None and item["confidence"] < 0.7]
    for key in low:
        issues.append(_issue("low_confidence_field", "warning",
                             f"Field {key} was extracted with low confidence "
                             f"({fields[key]['confidence']}); verify it before approval.", key))
    return issues


def _status(issues: list[dict], needs_ocr: bool) -> str:
    if needs_ocr:
        return "needs_ocr"
    if any(issue["severity"] == "error" for issue in issues):
        return "needs_review"
    if issues:
        return "needs_review"
    return "ready"

# ---------------------------------------------------------------------------
# Exports (CSV / XLSX / JSON / printable audit PDF)
# ---------------------------------------------------------------------------


def _csv_safe(value: str) -> str:
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def _export_csv(record: dict) -> bytes:
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    fields = record["fields"]
    writer.writerow(["Field", "Value", "Confidence", "Source"])
    for key, item in fields.items():
        if key == "bank":
            continue
        source = item.get("source") or {}
        writer.writerow([key, _csv_safe(str(item["value"] or "")),
                         item["confidence"],
                         _csv_safe(f"page {source.get('page')} line {source.get('line')}"
                                   if source else "derived / missing")])
    for key, item in fields["bank"].items():
        writer.writerow([f"bank.{key}", _csv_safe(str(item["value"] or "")),
                         item["confidence"], ""])
    writer.writerow([])
    writer.writerow(["Line", "Description", "Quantity", "Unit price", "Line total"])
    for index, item in enumerate(record["lines"], start=1):
        writer.writerow([index, _csv_safe(item["description"]["value"] or ""),
                         item["quantity"]["value"], item["unit_price"]["value"],
                         item["line_total"]["value"]])
    writer.writerow([])
    writer.writerow(["Issue code", "Severity", "Field", "Message"])
    for issue in record["issues"]:
        writer.writerow([issue["code"], issue["severity"], issue.get("field") or "",
                         _csv_safe(issue["message"])])
    writer.writerow([])
    writer.writerow(["Status", record["status"]])
    writer.writerow(["Source SHA-256", record["source_sha256"]])
    writer.writerow(["LIMITATION", "Extracted record only. Not issued, sent, paid or posted."])
    return ("\ufeff" + out.getvalue()).encode("utf-8")


def _xlsx_safe(value: Any) -> Any:
    """Same formula-injection guard as _csv_safe, for XLSX string cells."""
    return _csv_safe(value) if isinstance(value, str) else value


def _export_xlsx(record: dict) -> bytes:
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = "Invoice"
    fields = record["fields"]
    sheet.append(["Field", "Value", "Confidence", "Source page", "Source line"])
    for key, item in fields.items():
        if key == "bank":
            continue
        source = item.get("source") or {}
        sheet.append([key, _xlsx_safe(item["value"]), item["confidence"],
                      source.get("page"), source.get("line")])
    for key, item in fields["bank"].items():
        sheet.append([f"bank.{key}", _xlsx_safe(item["value"]), item["confidence"], None, None])
    sheet.append([])
    sheet.append(["Line", "Description", "Quantity", "Unit price", "Line total"])
    for index, item in enumerate(record["lines"], start=1):
        sheet.append([index, _xlsx_safe(item["description"]["value"]),
                      _xlsx_safe(item["quantity"]["value"]),
                      _xlsx_safe(item["unit_price"]["value"]),
                      _xlsx_safe(item["line_total"]["value"])])
    evidence = book.create_sheet("Evidence")
    evidence.append(["Field", "Value", "Confidence", "Verbatim source text"])
    for key, item in fields.items():
        if key == "bank":
            continue
        source = item.get("source") or {}
        evidence.append([key, _xlsx_safe(item["value"]), item["confidence"],
                         _xlsx_safe(source.get("text") or "")])
    issues = book.create_sheet("Issues")
    issues.append(["Code", "Severity", "Field", "Message"])
    for issue in record["issues"]:
        issues.append([issue["code"], issue["severity"], issue.get("field") or "",
                       _xlsx_safe(issue["message"])])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _export_pdf(record: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm,
                            topMargin=18 * mm, bottomMargin=20 * mm,
                            title="Invoice audit report " + record["id"],
                            author="AutoMoto AI - Invoice Processing (extracted record)")
    text = ParagraphStyle("Text", fontName="Helvetica", fontSize=9, leading=13)
    bold = ParagraphStyle("Bold", parent=text, fontName="Helvetica-Bold")
    heading = ParagraphStyle("Heading", parent=bold, fontSize=14, leading=18, spaceAfter=6)
    small = ParagraphStyle("Small", parent=text, fontSize=8, leading=11,
                           textColor=colors.HexColor("#607087"))
    story = [Paragraph("Invoice audit report", heading),
             Paragraph("Extracted record " + record["id"] + " — status: "
                       + record["status"], bold),
             Paragraph("Source: " + escape(record["source_path"]) + "<br/>SHA-256: "
                       + record["source_sha256"], small), Spacer(1, 5 * mm)]
    rows = [[Paragraph("Field", bold), Paragraph("Value", bold),
             Paragraph("Confidence", bold), Paragraph("Source", bold)]]
    fields = record["fields"]
    for key, item in fields.items():
        if key == "bank":
            continue
        source = item.get("source") or {}
        loc = (f"p{source.get('page')} l{source.get('line')}" if source else "—")
        rows.append([Paragraph(escape(key), text),
                     Paragraph(escape(str(item["value"] or "—")), text),
                     Paragraph(str(item["confidence"]), text),
                     Paragraph(escape(loc), text)])
    table = Table(rows, colWidths=[32 * mm, 62 * mm, 24 * mm, 56 * mm], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F7FB")),
                               ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#183153")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 4),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.append(table)
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("Line items", bold))
    line_rows = [[Paragraph("Description", bold), Paragraph("Qty", bold),
                  Paragraph("Unit price", bold), Paragraph("Line total", bold)]]
    for item in record["lines"]:
        line_rows.append([Paragraph(escape(str(item["description"]["value"] or "")), text),
                          Paragraph(escape(str(item["quantity"]["value"])), text),
                          Paragraph(escape(str(item["unit_price"]["value"])), text),
                          Paragraph(escape(str(item["line_total"]["value"])), text)])
    line_table = Table(line_rows, colWidths=[86 * mm, 24 * mm, 32 * mm, 32 * mm],
                       repeatRows=1)
    line_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F7FB")),
                                    ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#183153"))]))
    story.append(line_table)
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("Validation issues", bold))
    for issue in record["issues"]:
        story.append(Paragraph(f"[{issue['severity']}] {issue['code']}: "
                               + escape(issue["message"]), text))
    if not record["issues"]:
        story.append(Paragraph("No issues found.", text))
    if record.get("corrections"):
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph("Manual corrections", bold))
        for correction in record["corrections"]:
            story.append(Paragraph(
                f"{escape(correction['field'])}: {escape(str(correction['previous']))} -> "
                f"{escape(str(correction['new']))} "
                f"({escape(correction['reason'])}, {correction['at']})", text))
    if record.get("decisions"):
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph("Decisions", bold))
        for decision in record["decisions"]:
            story.append(Paragraph(
                f"{decision['action']}: {escape(decision['reason'])} ({decision['at']})", text))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("EXTRACTED RECORD ONLY. Not issued, sent, paid, posted or "
                           "bank-verified. Tax/VAT treatment must be verified before use.",
                           small))
    doc.build(story)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# API models and routes
# ---------------------------------------------------------------------------


class ExtractIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(..., min_length=1, max_length=300)
    sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    vat_policy: dict[str, str] | None = None


class CorrectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., pattern=r"^[0-9a-f]{24}$")
    field: str = Field(..., min_length=1, max_length=60)
    value: str | None = None
    reason: str = Field(..., min_length=5, max_length=500)

    @model_validator(mode="after")
    def check_reason(self):
        if BAD.search(self.reason) or not self.reason.strip():
            raise ValueError("A meaningful printable correction reason is required.")
        return self


class DecideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., pattern=r"^[0-9a-f]{24}$")
    action: Literal["approve", "reject"]
    reason: str = Field(..., min_length=5, max_length=500)

    @model_validator(mode="after")
    def check_reason(self):
        if BAD.search(self.reason) or not self.reason.strip():
            raise ValueError("A meaningful printable decision reason is required.")
        return self


class ExportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., pattern=r"^[0-9a-f]{24}$")
    format: Literal["csv", "xlsx", "json", "pdf"] = "json"


def _policy(body: ExtractIn) -> dict[str, str]:
    policy = dict(DEFAULT_VAT_POLICY)
    if body.vat_policy:
        for name, rate in body.vat_policy.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,30}", name or ""):
                raise HTTPException(422, "Invalid VAT policy name.")
            try:
                value = Decimal(str(rate))
            except InvalidOperation:
                raise HTTPException(422, "Invalid VAT policy rate.") from None
            if not value.is_finite() or value < 0 or value > 100:
                raise HTTPException(422, "VAT policy rate is outside 0-100%.")
            policy[name] = str(value)
    return policy


def _public(record: dict) -> dict:
    return record


@router.post("/extract")
def extract(body: ExtractIn, request: Request):
    _auth(request)
    policy = _policy(body)
    path = _source_path(body.path)
    if _sha(path) != body.sha256:
        raise HTTPException(409, "Invoice source changed; reselect it before extraction.")
    copy = _copy_source(path, body.sha256)
    lines, needs_ocr, note = _extract_pages(path)
    record_id = secrets.token_hex(12)
    if needs_ocr:
        record = {
            "id": record_id, "status": "needs_ocr",
            "source_path": body.path, "source_copy": copy.relative_to(_root()).as_posix(),
            "source_sha256": body.sha256, "vat_policy": policy,
            "fields": {key: _field(None, 0.0) for key in
                       ("seller", "buyer", "invoice_number", "issue_date", "due_date",
                        "currency", "vat_number", "vat_rate_percent", "subtotal",
                        "tax_amount", "total")},
            "lines": [],
            "issues": [_issue("needs_ocr", "error",
                              note or "This source needs OCR before any field can be read.")],
            "corrections": [], "decisions": [], "extracted_at": _now(),
            "note": note, "ocr_available": False,
        }
        # Bank fields keep the same shape as extracted records.
        record["fields"]["bank"] = {key: _field(None, 0.0) for key in
                                    ("iban", "sort_code", "account_number", "payment_reference")}
        _save_record(record)
        return _public(record)
    parsed = _parse_invoice(lines, policy)
    record = {
        "id": record_id, "status": "ready",
        "source_path": body.path, "source_copy": copy.relative_to(_root()).as_posix(),
        "source_sha256": body.sha256, "vat_policy": policy,
        "fields": parsed["fields"], "lines": parsed["lines"],
        "issues": [], "corrections": [], "decisions": [], "extracted_at": _now(),
        "note": note, "ocr_available": True,
    }
    record["issues"] = _validate(record, policy, _all_records())
    record["status"] = _status(record["issues"], needs_ocr=False)
    _save_record(record)
    return _public(record)


@router.get("/list")
def list_invoices(request: Request):
    _auth(request)
    items = []
    for record in _all_records():
        items.append({
            "id": record["id"], "status": record["status"],
            "invoice_number": record["fields"]["invoice_number"]["value"],
            "seller": record["fields"]["seller"]["value"],
            "total": record["fields"]["total"]["value"],
            "currency": record["fields"]["currency"]["value"],
            "issues": len(record["issues"]),
            "extracted_at": record["extracted_at"],
        })
    return {"invoices": items, "review_queue": [i for i in items if i["status"] != "ready"],
            "offline": True, "no_payment_actions": True}


@router.get("/detail")
def detail(id: str, request: Request):
    _auth(request)
    return _public(_load_record(id))


_FIELD_PATH = re.compile(r"^(seller|buyer|invoice_number|issue_date|due_date|currency|"
                         r"vat_number|vat_rate_percent|subtotal|tax_amount|total)"
                         r"|lines\[(\d+)\]\.(description|quantity|unit_price|line_total)$")
_BANK_PATH = re.compile(r"^bank\.(iban|sort_code|account_number|payment_reference)$")


def _apply_correction(record: dict, field_path: str, value: str | None) -> Any:
    match = _FIELD_PATH.fullmatch(field_path)
    bank = _BANK_PATH.fullmatch(field_path)
    if bank:
        target = record["fields"]["bank"][bank.group(1)]
        previous = target["value"]
        if value is not None and not value.strip():
            raise HTTPException(422, "Correction value must not be blank.")
        target["value"] = value
        target["confidence"] = 1.0
        target["source"] = None
        target["corrected"] = True
        return previous
    if not match:
        raise HTTPException(422, "Correction field is not supported.")
    if match.group(2) is not None:
        index = int(match.group(2))
        key = match.group(3)
        if index >= len(record["lines"]):
            raise HTTPException(422, "Correction line does not exist.")
        target = record["lines"][index][key]
        previous = target["value"]
        if key in ("quantity", "unit_price", "line_total"):
            if value is not None and _parse_money(value) is None:
                raise HTTPException(422, "Correction value is not a valid amount.")
            target["value"] = str(_parse_money(value)) if value is not None else None
        else:
            if value is not None and not value.strip():
                raise HTTPException(422, "Correction value must not be blank.")
            target["value"] = value
        target["confidence"] = 1.0
        target["source"] = None
        target["corrected"] = True
        return previous
    target = record["fields"][match.group(1)]
    previous = target["value"]
    key = match.group(1)
    if key in ("subtotal", "tax_amount", "total"):
        if value is not None and _parse_money(value) is None:
            raise HTTPException(422, "Correction value is not a valid amount.")
        target["value"] = str(_parse_money(value)) if value is not None else None
    elif key in ("issue_date", "due_date"):
        if value is not None and _parse_date(value) is None:
            raise HTTPException(422, "Correction value is not a valid date.")
        target["value"] = _parse_date(value) if value is not None else None
    elif key == "vat_rate_percent":
        if value is not None:
            try:
                rate = Decimal(str(value))
            except InvalidOperation:
                raise HTTPException(422, "Correction value is not a valid VAT rate.") from None
            if not rate.is_finite() or rate < 0 or rate > 100:
                raise HTTPException(422, "VAT rate is outside 0-100%.")
            target["value"] = str(rate)
        else:
            target["value"] = None
    elif key == "currency":
        if value is not None and value.upper() not in CURRENCIES:
            raise HTTPException(422, "Correction value is not a supported currency code.")
        target["value"] = value.upper() if value is not None else None
    else:
        if value is not None and not value.strip():
            raise HTTPException(422, "Correction value must not be blank.")
        target["value"] = value
    target["confidence"] = 1.0
    target["source"] = None
    target["corrected"] = True
    return previous


@router.post("/correct")
def correct(body: CorrectIn, request: Request):
    _auth(request)
    record = _load_record(body.id)
    if record["status"] in ("approved", "rejected"):
        raise HTTPException(409, "A decided record cannot be corrected; extract it again.")
    previous = _apply_correction(record, body.field, body.value)
    record["corrections"].append({
        "field": body.field, "previous": previous, "new": body.value,
        "reason": body.reason.strip(), "at": _now()})
    record["issues"] = _validate(record, record.get("vat_policy", DEFAULT_VAT_POLICY),
                                 _all_records())
    record["status"] = _status(record["issues"], needs_ocr=False)
    _save_record(record)
    return _public(record)


@router.post("/decide")
def decide(body: DecideIn, request: Request):
    _auth(request)
    record = _load_record(body.id)
    if record["status"] in ("approved", "rejected"):
        raise HTTPException(409, "This invoice has already been decided.")
    if record["status"] == "needs_ocr":
        raise HTTPException(409, "This invoice needs OCR text before it can be decided.")
    if body.action == "approve":
        errors = [issue for issue in record["issues"] if issue["severity"] == "error"]
        if errors:
            raise HTTPException(
                409, "Approval is blocked by unresolved errors: "
                     + "; ".join(issue["code"] for issue in errors)
                     + ". Correct them or reject the record.")
    record["decisions"].append({"action": body.action, "reason": body.reason.strip(),
                                "at": _now(), "actor": "local-owner"})
    record["status"] = "approved" if body.action == "approve" else "rejected"
    _save_record(record)
    return {"id": record["id"], "status": record["status"],
            "effect": "Review decision only; no payment, dispatch or posting was made."}


@router.post("/export")
def export(body: ExportIn, request: Request):
    _auth(request)
    record = _load_record(body.id)
    folder = _store(create=True) / "exports"
    if body.format == "json":
        content = json.dumps({"schema": SCHEMA, "data": record}, ensure_ascii=False,
                             indent=2).encode("utf-8")
        ext = "json"
    elif body.format == "csv":
        content = _export_csv(record)
        ext = "csv"
    elif body.format == "xlsx":
        content = _export_xlsx(record)
        ext = "xlsx"
    else:
        content = _export_pdf(record)
        ext = "pdf"
    if len(content) > 3_000_000:
        raise HTTPException(413, "Invoice export exceeds the 3 MB limit.")
    target = folder / f"{record['id']}-{_slug(str(record['fields']['invoice_number']['value'] or 'invoice'))}.{ext}"
    _atomic_file(target, content)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return {"path": target.relative_to(_root()).as_posix(), "format": body.format,
            "id": record["id"], "status": record["status"],
            "draft_only": True, "paid": False, "sent": False}
