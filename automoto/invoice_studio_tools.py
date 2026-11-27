"""Invoice Processing tools. Each one calls the invoice studio endpoint;
nothing is reimplemented here, and no tool pays, sends or posts anything.
"""
from __future__ import annotations

from automoto.studio_registry import OBJ, S, StudioSpec, call_studio, obj, studio_request
from automoto.tools import Tool, ToolContext

_READ = ("Read-only extraction. The imported original is copied once and never "
         "changed; a record is approved only through invoice_decide, and approval "
         "never pays, sends or posts anything.")


def invoice_extract(ctx: ToolContext, path: str, sha256: str) -> str:
    """Extract an invoice from an uploads/ source into a validated draft record."""
    from automoto import invoice_processing
    body = invoice_processing.ExtractIn.model_validate({"path": path, "sha256": sha256})
    return call_studio(invoice_processing.extract, body, studio_request("POST"))


def invoice_list(ctx: ToolContext) -> str:
    from automoto import invoice_processing
    return call_studio(invoice_processing.list_invoices, studio_request("GET"))


def invoice_detail(ctx: ToolContext, id: str) -> str:
    from automoto import invoice_processing
    return call_studio(invoice_processing.detail, id, studio_request("GET"))


def invoice_decide(ctx: ToolContext, id: str, action: str, reason: str) -> str:
    """Approve or reject an extracted invoice. Approval never pays or posts."""
    from automoto import invoice_processing
    body = invoice_processing.DecideIn.model_validate(
        {"id": id, "action": action, "reason": reason})
    return call_studio(invoice_processing.decide, body, studio_request("POST"))


def invoice_export(ctx: ToolContext, id: str, format: str = "json") -> str:
    from automoto import invoice_processing
    body = invoice_processing.ExportIn.model_validate({"id": id, "format": format})
    return call_studio(invoice_processing.export, body, studio_request("POST"))


STUDIO = StudioSpec(
    id="invoice",
    name="Invoice Processing",
    hosted_ok=True,
    approval="risky",
    local_only=(),
    words=r"\b(invoice|invoices|vat|receipt|bill to|amount due)\b",
    exts=(".pdf", ".png", ".jpg", ".jpeg", ".xlsx", ".csv"),
    skills=("spreadsheet-invoices",),
    fuzzy=("invoice", "vat", "receipt"),
    how="Extract an invoice with invoice_extract (keep the record id and sha256). "
        "Check it with invoice_detail, correct fields only with a reason, and "
        "approve or reject with invoice_decide. Approval only marks the draft "
        "approved; it never pays, sends or posts anything. Export with "
        "invoice_export as csv, xlsx, json or pdf. Finish by naming the file.",
    labels={
        "invoice_extract": "Extracting the invoice",
        "invoice_list": "Listing invoices",
        "invoice_detail": "Opening the invoice record",
        "invoice_decide": "Deciding the invoice",
        "invoice_export": "Exporting the invoice",
    },
    tools=(
        Tool("invoice_extract", "Extract an invoice from an uploads/ file into a "
             "validated draft record with per-field evidence. " + _READ,
             obj({"path": S, "sha256": S}, ["path", "sha256"]), "risky", invoice_extract),
        Tool("invoice_list", "List extracted invoices and the review queue.",
             obj({}), "safe", invoice_list),
        Tool("invoice_detail", "Open one extracted invoice record with its fields, "
             "evidence, issues, corrections and decisions.",
             obj({"id": S}, ["id"]), "safe", invoice_detail),
        Tool("invoice_decide", "Approve or reject an extracted invoice with a reason. "
             "Approval is blocked while error issues remain. Never pays or posts.",
             obj({"id": S, "action": S, "reason": S}, ["id", "action", "reason"]),
             "risky", invoice_decide),
        Tool("invoice_export", "Export an extracted invoice as csv, xlsx, json or a "
             "printable audit pdf. Creates a new file only.",
             obj({"id": S, "format": S}, ["id"]), "risky", invoice_export),
    ),
)
