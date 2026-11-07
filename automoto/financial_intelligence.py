"""V5 financial intelligence: private manual cash-ledger and transparent analytics.

Cash-basis indicative reporting only. Draft invoices/quotes are not transaction
sources, and planned amounts are never counted in actual balances or surplus.
No payments, bank feeds, accounting entries or external integrations are made.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import secrets
import tempfile
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from automoto.document_workspace import _atomic_file, _root
from automoto.spreadsheet_workspace import _storage
from automoto.visual_studio import _auth

router = APIRouter(prefix="/api/spreadsheets/finance", tags=["finance-studio"])
CENT = Decimal("0.01")
LIMIT = Decimal("1000000000")
MAX_RECORD = 850_000
BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
FILE_NAME = re.compile(r"^[a-z0-9-]{1,48}-[0-9a-f]{12}\.finance\.json$")
CATEGORIES = (
    "Sales", "Services", "Subscriptions", "Other income",
    "Materials", "Payroll", "Rent", "Marketing", "Software", "Tax paid",
    "Travel", "Utilities", "Other expense", "Capital", "Other",
)


def _text(value: str, label: str) -> str:
    if BAD.search(value) or not value.strip():
        raise ValueError(f"{label} is blank or contains unsupported characters.")
    return value.strip()


def _money(value: str, label: str, *, positive: bool = False) -> Decimal:
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?", value):
        raise HTTPException(422, f"{label} must be a non-negative number with at most two decimals.")
    try:
        money = Decimal(value)
    except InvalidOperation:
        raise HTTPException(422, f"Invalid {label}.") from None
    if money > LIMIT or (positive and money == 0):
        raise HTTPException(422, f"{label} is outside supported bounds.")
    return money


def _money_str(value: Decimal) -> str:
    return f"{value.quantize(CENT):.2f}"


class CashEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    transaction_date: date
    kind: Literal["revenue", "expense", "capital_in", "capital_out"]
    status: Literal["actual", "planned"] = "planned"
    category: Literal[
        "Sales", "Services", "Subscriptions", "Other income",
        "Materials", "Payroll", "Rent", "Marketing", "Software", "Tax paid",
        "Travel", "Utilities", "Other expense", "Capital", "Other",
    ] = "Other"
    description: str = Field(..., min_length=1, max_length=220)
    reference: str = Field("", max_length=100)
    amount: str = Field(..., min_length=1, max_length=20)

    @model_validator(mode="after")
    def check(self):
        _text(self.description, "Description")
        if BAD.search(self.reference):
            raise ValueError("Reference contains invalid characters.")
        # A confirmed actual is user-attested only, NOT independently bank-verified.
        _money(self.amount, "Transaction amount", positive=True)
        return self


class FinanceBook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=100)
    currency: Literal["GBP", "EUR", "USD"] = "GBP"
    opening_balance: str = Field("0.00", min_length=1, max_length=20)
    period_from: date
    period_to: date
    entries: list[CashEntry] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def check(self):
        _text(self.name, "Book name")
        _money(self.opening_balance, "Opening cash balance")
        if self.period_to < self.period_from:
            raise ValueError("Report end must be on or after its start.")
        if (self.period_to.year - self.period_from.year) * 12 + (
            self.period_to.month - self.period_from.month) > 35:
            raise ValueError("Report periods are limited to 36 calendar months.")
        identities = [entry.entry_id for entry in self.entries]
        if len(identities) != len(set(identities)):
            raise ValueError("Duplicate transaction IDs are not permitted.")
        return self


class ExportIn(FinanceBook):
    format: Literal["csv", "pdf"]


def _monthly(start: date, finish: date) -> list[str]:
    y, m = start.year, start.month
    months = []
    while (y, m) <= (finish.year, finish.month):
        months.append(f"{y:04d}-{m:02d}")
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return months


def summarise(book: FinanceBook) -> dict:
    """Pure local calculation. No saved drafts or invoices are imported."""
    opening = _money(book.opening_balance, "Opening balance")
    opening_period = opening
    categories: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"revenue": Decimal(0), "expense": Decimal(0)})
    months = {key: {
        "revenue": Decimal(0), "expenses": Decimal(0), "capital_in": Decimal(0),
        "capital_out": Decimal(0), "planned_revenue": Decimal(0), "planned_expenses": Decimal(0),
    } for key in _monthly(book.period_from, book.period_to)}
    sums = {key: Decimal(0) for key in ("revenue", "expense", "capital_in", "capital_out")}
    plans = {"revenue": Decimal(0), "expense": Decimal(0)}
    counts = {"actual": 0, "planned": 0}
    for entry in book.entries:
        amount = _money(entry.amount, "Transaction amount", positive=True)
        if entry.status == "actual" and entry.transaction_date < book.period_from:
            opening_period += amount if entry.kind in ("revenue", "capital_in") else -amount
        if not book.period_from <= entry.transaction_date <= book.period_to:
            continue
        counts[entry.status] += 1
        month = entry.transaction_date.isoformat()[:7]
        if entry.status == "planned":
            if entry.kind in plans:
                plans[entry.kind] += amount
                months[month]["planned_revenue" if entry.kind == "revenue" else "planned_expenses"] += amount
            continue
        sums[entry.kind] += amount
        months[month][{"revenue": "revenue", "expense": "expenses",
                       "capital_in": "capital_in", "capital_out": "capital_out"}[entry.kind]] += amount
        if entry.kind in ("revenue", "expense"):
            categories[entry.category][entry.kind] += amount
    net_operating = sums["revenue"] - sums["expense"]
    net_financing = sums["capital_in"] - sums["capital_out"]
    closing = opening_period + net_operating + net_financing
    if abs(closing) > LIMIT * 1000 or abs(opening_period) > LIMIT * 1000:
        raise HTTPException(422, "Calculated cash balance exceeds reporting limits.")

    monthly = []
    running = opening_period
    for month, vals in months.items():
        net = vals["revenue"] - vals["expenses"]
        cash = net + vals["capital_in"] - vals["capital_out"]
        running += cash
        monthly.append({
            "month": month, "revenue": _money_str(vals["revenue"]),
            "expenses": _money_str(vals["expenses"]),
            "operating_surplus": _money_str(net),
            "financing_net": _money_str(vals["capital_in"] - vals["capital_out"]),
            "cash_movement": _money_str(cash), "cash_balance": _money_str(running),
            "planned_revenue": _money_str(vals["planned_revenue"]),
            "planned_expenses": _money_str(vals["planned_expenses"]),
        })
    per_category = [
        {"category": name, "revenue": _money_str(values["revenue"]),
         "expenses": _money_str(values["expense"])}
        for name, values in sorted(categories.items())
    ]
    ratio = (net_operating * 100 / sums["revenue"]).quantize(CENT) if sums["revenue"] else None
    return {
        "name": book.name.strip(), "currency": book.currency,
        "period_from": book.period_from.isoformat(), "period_to": book.period_to.isoformat(),
        "opening_cash": _money_str(opening_period), "revenue": _money_str(sums["revenue"]),
        "expenses": _money_str(sums["expense"]), "operating_surplus": _money_str(net_operating),
        "operating_margin_percent": _money_str(ratio) if ratio is not None else None,
        "capital_in": _money_str(sums["capital_in"]),
        "capital_out": _money_str(sums["capital_out"]),
        "net_cash_movement": _money_str(net_operating + net_financing),
        "closing_cash": _money_str(closing), "planned_revenue": _money_str(plans["revenue"]),
        "planned_expenses": _money_str(plans["expense"]), "entry_counts": counts,
        "months": monthly, "categories": per_category,
        "basis": "User-entered cash activity, not accrual accounts or statutory profit-and-loss.",
        "warnings": [
            "Actual entries are user-confirmed, NOT bank-verified; source records may be incomplete.",
            "Only manually entered entries are included. Draft invoices and quotations are NEVER revenue.",
            "Planned income and expenses are excluded from actual cash balances and operating surplus.",
            "Opening balance is user-supplied. Tax/VAT, unpaid invoices, depreciation, stock, "
            "capital gains, transfers and statutory tax treatment require separate review.",
            "Figures are not a statutory P&L, tax return, bank statement or audited accounts.",
        ],
        "offline": True, "bank_connected": False, "invoices_included": False,
    }


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:48] or "finance"


def _path(name: str, ext: str) -> Path:
    return _storage(create=True) / f"{_slug(name)}-{secrets.token_hex(6)}.finance.{ext}"


def _rel(path: Path) -> str:
    return path.relative_to(_root()).as_posix()


def _save(book: FinanceBook) -> dict:
    raw = json.dumps({"schema": "finance-v5", "data": book.model_dump(mode="json")},
                     ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_RECORD:
        raise HTTPException(413, "Financial snapshot is too large.")
    path = _path(book.name, "json")
    _atomic_file(path, raw)
    return {"path": _rel(path), "sha256": hashlib.sha256(raw).hexdigest(),
            "immutable_snapshot": True, "auto_posted": False}


def _load(raw: str) -> tuple[Path, FinanceBook]:
    prefix = "artifacts/spreadsheets/"
    if not isinstance(raw, str) or len(raw) > 300 or not raw.startswith(prefix):
        raise HTTPException(403, "Only private financial snapshots may be opened.")
    filename = raw[len(prefix):]
    if not FILE_NAME.fullmatch(filename):
        raise HTTPException(403, "Invalid financial snapshot path.")
    path = _storage() / filename
    if path.is_symlink() or not path.is_file():
        raise HTTPException(404, "Financial snapshot not found.")
    if path.stat().st_size > MAX_RECORD:
        raise HTTPException(413, "Financial snapshot exceeds the size limit.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != "finance-v5" or not isinstance(payload.get("data"), dict):
            raise ValueError("Unsupported schema")
        return path, FinanceBook.model_validate(payload["data"])
    except (OSError, ValueError, TypeError, AttributeError, UnicodeError):
        raise HTTPException(422, "Financial snapshot is corrupted.") from None


def _list() -> list[dict]:
    folder = _storage()
    if not folder.is_dir():
        return []
    return sorted([
        {"name": path.name, "path": _rel(path), "bytes": path.stat().st_size}
        for path in folder.iterdir()
        if not path.is_symlink() and path.is_file() and FILE_NAME.fullmatch(path.name)
    ], key=lambda item: item["name"], reverse=True)[:100]


def _csv_safe(value: str) -> str:
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def _csv(book: FinanceBook, report: dict) -> bytes:
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    for label, key in [
        ("Report", "name"), ("Currency", "currency"), ("Period from", "period_from"),
        ("Period to", "period_to"), ("Opening cash", "opening_cash"),
        ("Revenue (cash receipts)", "revenue"), ("Expenses (cash paid)", "expenses"),
        ("Operating cash surplus (not statutory profit)", "operating_surplus"),
        ("Capital in", "capital_in"), ("Capital out", "capital_out"),
        ("Cash movement", "net_cash_movement"), ("Closing cash", "closing_cash"),
    ]:
        # Calculated monetary fields are trusted numeric strings. Preserve negative
        # values as numbers in Excel; only user-controlled report names need escaping.
        writer.writerow([label, _csv_safe(report[key]) if key == "name" else report[key]])
    writer.writerow([])
    writer.writerow(["Month", "Revenue", "Expenses", "Cash operating surplus",
                     "Cash financing", "Cash movement", "Closing cash"])
    for item in report["months"]:
        writer.writerow([item[k] for k in ("month", "revenue", "expenses", "operating_surplus",
                                           "financing_net", "cash_movement", "cash_balance")])
    writer.writerow([])
    writer.writerow(["Transaction ID", "Date", "Status", "Type", "Category",
                     "Description", "Reference", "Amount", "Currency"])
    for entry in sorted(book.entries, key=lambda item: (item.transaction_date, item.entry_id)):
        if not book.period_from <= entry.transaction_date <= book.period_to:
            continue
        writer.writerow([
            _csv_safe(entry.entry_id), entry.transaction_date.isoformat(), entry.status, entry.kind,
            entry.category, _csv_safe(entry.description), _csv_safe(entry.reference),
            _money_str(_money(entry.amount, "Amount")), book.currency,
        ])
    writer.writerow([])
    for warning in report["warnings"]:
        writer.writerow(["LIMITATION", _csv_safe(warning)])
    return ("\ufeff" + out.getvalue()).encode("utf-8")


@router.get("/list")
def list_snapshots(request: Request):
    _auth(request)
    return {"snapshots": _list(), "draft_invoices_excluded": True, "offline": True}


@router.post("/analyse")
def analyse(body: FinanceBook, request: Request):
    _auth(request)
    return summarise(body)


@router.post("/save")
def save(body: FinanceBook, request: Request):
    _auth(request)
    summarise(body)  # validate resource bounds before any writes
    return _save(body)


@router.get("/load")
def load(request: Request, path: str):
    _auth(request)
    file, book = _load(path)
    return {"path": _rel(file), "book": book.model_dump(mode="json"),
            "read_only": True, "unchanged": True}


@router.post("/export")
def export(body: ExportIn, request: Request):
    _auth(request)
    report = summarise(body)
    target = _path(body.name, body.format)
    if body.format == "csv":
        content = _csv(body, report)
    else:
        from automoto.financial_pdf import render_finance_pdf
        with tempfile.TemporaryDirectory(prefix="automoto-finance-v5-") as temporary:
            draft = Path(temporary) / "cash-report.pdf"
            render_finance_pdf(body, report, draft)
            content = draft.read_bytes()
        if not content.startswith(b"%PDF-") or len(content) > 3_000_000:
            raise HTTPException(422, "Financial PDF generation failed validation.")
    if len(content) > 3_000_000:
        raise HTTPException(413, "Financial report exceeds the export limit.")
    _atomic_file(target, content)
    return {"path": _rel(target), "format": body.format, "currency": body.currency,
            "draft_invoices_excluded": True, "offline": True, "verified": False}
