"""AutoMoto AI v4: private, non-issued invoice and quotation studio.

No payment processing, invoice dispatch, emails, third-party services or tax
determinations. All records and PDF exports are create-only local workspace
artifacts. Dates, VAT treatment and legal identifiers remain user-supplied.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import tempfile
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from automoto.document_workspace import _atomic_file, _root
from automoto.spreadsheet_workspace import _storage
from automoto.visual_studio import _auth

router = APIRouter(prefix="/api/spreadsheets/commercial", tags=["commercial-studio"])
FILE_NAME = re.compile(r"^[a-z0-9-]{1,48}-[0-9a-f]{12}\.(?:commercial|contact)\.json$")
DISALLOWED = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
PERCENT = Decimal("100")
ZERO = Decimal("0")
CENT = Decimal("0.01")
MAX_TOTAL = Decimal("1000000000")
MAX_RECORD = 750_000


class Party(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=140)
    address: str = Field(..., min_length=1, max_length=500)
    email: str = Field("", max_length=160)
    phone: str = Field("", max_length=70)
    registration: str = Field("", max_length=100)  # Company number / VAT identifier, user supplied

    @model_validator(mode="after")
    def validate_text(self):
        for key in ("name", "address", "email", "phone", "registration"):
            value = getattr(self, key)
            if DISALLOWED.search(value) or (key in ("name", "address") and not value.strip()):
                raise ValueError("Party details contain blank or invalid characters.")
        if self.email and ("@" not in self.email or any(char.isspace() for char in self.email)):
            raise ValueError("Enter a syntactically plausible email or leave it blank.")
        return self


class Brand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(..., min_length=1, max_length=100)
    accent: str = Field("#183153", pattern=r"^#[0-9A-Fa-f]{6}$")
    template: Literal["executive", "minimal"] = "executive"

    @model_validator(mode="after")
    def safe_title(self):
        if DISALLOWED.search(self.display_name) or not self.display_name.strip():
            raise ValueError("Invalid business display name.")
        return self


class Line(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(..., min_length=1, max_length=220)
    quantity: str = Field("1", min_length=1, max_length=26)
    unit_price: str = Field("0.00", min_length=1, max_length=26)
    discount_percent: str = Field("0", min_length=1, max_length=10)

    @model_validator(mode="after")
    def safe_description(self):
        if DISALLOWED.search(self.description) or not self.description.strip():
            raise ValueError("Item descriptions must contain printable text.")
        return self


class CommercialIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["invoice", "quotation"] = "invoice"
    review_state: Literal["draft", "reviewed"] = "draft"
    number: str = Field(..., min_length=1, max_length=60)
    issue_date: date
    due_date: date
    currency: Literal["GBP", "EUR", "USD"] = "GBP"
    seller: Party
    customer: Party
    brand: Brand
    lines: list[Line] = Field(..., min_length=1, max_length=40)
    discount_percent: str = Field("0", min_length=1, max_length=10)
    tax_percent: str = Field("0", min_length=1, max_length=10)
    tax_label: Literal["Tax", "VAT", "GST", "Sales tax"] = "Tax"
    notes: str = Field("", max_length=1000)
    terms: str = Field("", max_length=1000)

    @model_validator(mode="after")
    def validate_document(self):
        if DISALLOWED.search(self.number) or not self.number.strip():
            raise ValueError("Document reference is invalid.")
        if self.due_date < self.issue_date:
            raise ValueError("Due/valid-until date must be on or after the document date.")
        if DISALLOWED.search(self.notes) or DISALLOWED.search(self.terms):
            raise ValueError("Notes/terms include invalid characters.")
        return self


def _decimal(raw: str, *, maximum: Decimal, decimals: int, positive: bool = False) -> Decimal:
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", raw):
        raise HTTPException(422, "Use non-negative decimal values only.")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise HTTPException(422, "Invalid numeric amount.") from None
    if value > maximum or value < 0 or (positive and not value) or value.as_tuple().exponent < -decimals:
        raise HTTPException(422, "Amount is outside the supported range or precision.")
    return value


def _round(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def preview(body: CommercialIn) -> dict:
    """Every amount derives from Decimal, never binary floats."""
    rate = _decimal(body.tax_percent, maximum=PERCENT, decimals=2)
    discount_rate = _decimal(body.discount_percent, maximum=PERCENT, decimals=2)
    lines = []
    subtotal = ZERO
    line_discounts = ZERO
    for item in body.lines:
        quantity = _decimal(item.quantity, maximum=Decimal("100000"), decimals=3, positive=True)
        price = _decimal(item.unit_price, maximum=Decimal("1000000"), decimals=2)
        line_discount = _decimal(item.discount_percent, maximum=PERCENT, decimals=2)
        gross = _round(quantity * price)
        deduction = _round(gross * line_discount / PERCENT)
        net = gross - deduction
        subtotal += gross
        line_discounts += deduction
        if subtotal > MAX_TOTAL:
            raise HTTPException(422, "Document subtotal exceeds the V4 limit.")
        lines.append({
            "description": item.description.strip(), "quantity": str(quantity),
            "unit_price": f"{price:.2f}", "discount_percent": str(line_discount),
            "gross": f"{gross:.2f}", "discount": f"{deduction:.2f}", "net": f"{net:.2f}",
        })
    after_lines = subtotal - line_discounts
    order_discount = _round(after_lines * discount_rate / PERCENT)
    taxable = after_lines - order_discount
    tax = _round(taxable * rate / PERCENT)
    total = taxable + tax
    if total > MAX_TOTAL:
        raise HTTPException(422, "Document total exceeds the V4 limit.")
    return {
        "kind": body.kind, "number": body.number.strip(), "currency": body.currency,
        "review_state": body.review_state, "lines": lines,
        "subtotal": f"{subtotal:.2f}", "line_discounts": f"{line_discounts:.2f}",
        "document_discount_percent": str(discount_rate), "document_discount": f"{order_discount:.2f}",
        "taxable": f"{taxable:.2f}", "tax_percent": str(rate), "tax_label": body.tax_label,
        "tax": f"{tax:.2f}", "total": f"{total:.2f}", "draft_only": True,
        "issued": False, "sent": False, "paid": False,
        "notice": ("Private draft, not a legally issued invoice or accepted quotation. "
                   "Verify party details, tax treatment, jurisdiction, discounts and payment terms."),
        "rounding": "Round each extended line to 0.01, then each line discount, then document discount, then total tax; ROUND_HALF_UP.",
    }


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.lower().strip()).strip("-")[:48] or "draft"


def _path(name: str, extension: str) -> Path:
    return _storage(create=True) / f"{_slug(name)}-{secrets.token_hex(6)}.{extension}"


def _save(schema: str, name: str, data: dict, ext: str) -> dict:
    raw = json.dumps({"schema": schema, "data": data}, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_RECORD:
        raise HTTPException(413, "Document is too large to save.")
    path = _path(name, ext)
    _atomic_file(path, raw)
    return {"path": path.relative_to(_root()).as_posix(), "sha256": hashlib.sha256(raw).hexdigest()}


def _load(raw: str, extension: str, schema: str) -> tuple[Path, dict]:
    if not isinstance(raw, str) or len(raw) > 300 or not raw.startswith("artifacts/spreadsheets/"):
        raise HTTPException(403, "Only private commercial workspace files can be opened.")
    name = raw[len("artifacts/spreadsheets/"):]
    if not FILE_NAME.fullmatch(name) or not name.endswith("." + extension):
        raise HTTPException(403, "Invalid commercial file path.")
    path = _storage() / name
    if path.is_symlink() or not path.is_file():
        raise HTTPException(404, "Private file not found.")
    if path.stat().st_size > MAX_RECORD:
        raise HTTPException(413, "Private file exceeds the size limit.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema") != schema or not isinstance(value.get("data"), dict):
            raise ValueError("Invalid schema")
        return path, value["data"]
    except (OSError, ValueError, TypeError, AttributeError, UnicodeError):
        raise HTTPException(422, "Private file is corrupted.") from None


def _items(extension: str) -> list[dict]:
    folder = _storage()
    if not folder.is_dir():
        return []
    matches = []
    for file in folder.iterdir():
        if (not file.is_symlink() and file.is_file()
                and FILE_NAME.fullmatch(file.name) and file.name.endswith("." + extension)):
            matches.append({"name": file.name, "path": file.relative_to(_root()).as_posix(),
                            "bytes": file.stat().st_size})
    return sorted(matches, key=lambda item: item["name"], reverse=True)[:100]


@router.get("/list")
def list_records(request: Request):
    _auth(request)
    return {"documents": _items("commercial.json"), "customers": _items("contact.json"),
            "offline": True, "no_payment_actions": True}


@router.post("/preview")
def preview_document(body: CommercialIn, request: Request):
    _auth(request)
    return preview(body)


@router.post("/save")
def save_document(body: CommercialIn, request: Request):
    _auth(request)
    totals = preview(body)
    return {**_save("commercial-v4", body.number, body.model_dump(mode="json"), "commercial.json"),
            "kind": body.kind, "review_state": body.review_state,
            "total": totals["total"], "draft_only": True, "sent": False, "paid": False}


@router.get("/load")
def load_document(path: str, request: Request):
    _auth(request)
    file, data = _load(path, "commercial.json", "commercial-v4")
    body = CommercialIn.model_validate(data)
    return {"path": file.relative_to(_root()).as_posix(), "document": body.model_dump(mode="json"),
            "draft_only": True, "read_only": True}


@router.post("/customer/save")
def save_customer(body: Party, request: Request):
    _auth(request)
    return {**_save("contact-v4", body.name, body.model_dump(mode="json"), "contact.json"),
            "customer": body.name.strip()}


@router.get("/customer/load")
def load_customer(path: str, request: Request):
    _auth(request)
    file, data = _load(path, "contact.json", "contact-v4")
    body = Party.model_validate(data)
    return {"path": file.relative_to(_root()).as_posix(), "customer": body.model_dump(mode="json"),
            "read_only": True}


@router.post("/export")
def export_document(body: CommercialIn, request: Request):
    _auth(request)
    totals = preview(body)
    from automoto.commercial_pdf import render_pdf  # loaded only for PDF export
    target = _path(body.number + "-" + body.kind, "pdf")
    with tempfile.TemporaryDirectory(prefix="automoto-v4-pdf-") as folder:
        temp = Path(folder) / "commercial-draft.pdf"
        render_pdf(body, totals, temp)
        content = temp.read_bytes()
        if not content.startswith(b"%PDF-") or len(content) > 3_000_000:
            raise HTTPException(422, "PDF generation failed safety checks.")
        _atomic_file(target, content)
    rel = target.relative_to(_root()).as_posix()
    return {"path": rel, "download_url": "/api/files/download?path=" + rel,
            "format": "pdf", "kind": body.kind, "total": totals["total"],
            "draft_only": True, "issued": False, "sent": False, "paid": False}
