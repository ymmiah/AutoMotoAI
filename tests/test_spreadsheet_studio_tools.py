"""Spreadsheet and invoice tools call the studio and keep its safety rules."""

import json

from automoto import commercial_documents, hosted, sandbox, tools as tools_mod
from automoto.spreadsheet_studio_tools import invoice_pdf, spreadsheet_calculate, spreadsheet_export
from automoto.tools import ToolContext

CTX = ToolContext()
BOOK = {"name": "March totals", "calculation_mode": "formulas", "sheets": [{
    "name": "Budget", "rows": [["Item", "Cost"], ["Rent", 800], ["Total", "=SUM(B2)"]]}]}


def test_registered_levels_hosted_and_offline(monkeypatch):
    tools = tools_mod.build()
    assert tools["spreadsheet_calculate"].level == "safe"
    assert tools["spreadsheet_export"].level == "risky"
    assert tools["invoice_preview"].level == "safe"
    assert tools["invoice_pdf"].level == "risky"
    assert tools["finance_summary"].level == "safe"
    assert tools["finance_export"].level == "risky"
    names = hosted.hosted_tools()
    assert "invoice_pdf" in names and "spreadsheet_ai_review" not in names
    monkeypatch.setenv("AUTOMOTO_OFFLINE", "1")
    assert "spreadsheet_export" in tools_mod.build()


def test_calculate_and_export_call_the_studio(monkeypatch):
    seen = {}
    real = __import__("automoto.spreadsheet_workspace", fromlist=["export_spreadsheet"]).export_spreadsheet

    def wrap(body, request):
        seen["mode"] = body.calculation_mode
        return real(body, request)

    monkeypatch.setattr("automoto.spreadsheet_workspace.export_spreadsheet", wrap)
    calc = spreadsheet_calculate(CTX, BOOK)
    assert "800" in calc or "Budget" in calc
    out = spreadsheet_export(CTX, BOOK, "xlsx")
    assert seen["mode"] == "formulas" and ".xlsx" in out


def test_invoice_pdf_is_a_real_draft(monkeypatch):
    seen = {}
    real = commercial_documents.export_document

    def wrap(body, request):
        seen["kind"] = body.kind
        return real(body, request)

    monkeypatch.setattr(commercial_documents, "export_document", wrap)
    out = invoice_pdf(CTX, {
        "kind": "invoice", "number": "DRAFT-1", "issue_date": "2026-11-01", "due_date": "2026-11-08",
        "seller": {"name": "Harbour Studio", "address": "1 Dock Lane"},
        "customer": {"name": "Northwind Studios", "address": "9 Canal Street"},
        "brand": {"display_name": "HARBOUR", "accent": "#183153"},
        "lines": [{"description": "Website maintenance", "quantity": "1", "unit_price": "10.00"}]})
    assert seen["kind"] == "invoice"
    path = json.loads(out)["path"]
    assert (sandbox.default_root() / path).read_bytes().startswith(b"%PDF-")
    assert "sent" in out
