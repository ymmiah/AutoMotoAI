"""Spreadsheet, invoice and cash-summary tools. Logic stays in the studio modules.

A later spreadsheet module is picked up automatically when it is named
``automoto/<name>_studio_tools.py`` and defines ``STUDIO``.
"""

from __future__ import annotations

from automoto.studio_registry import OBJ, S, StudioSpec, call_studio, obj, studio_request
from automoto.tools import Tool, ToolContext, ToolFailed


def spreadsheet_calculate(ctx: ToolContext, workbook: dict) -> str:
    from automoto import spreadsheet_workspace

    body = spreadsheet_workspace.BookIn.model_validate(workbook)
    return call_studio(spreadsheet_workspace.calculate_spreadsheet, body, studio_request("POST"))


def spreadsheet_export(ctx: ToolContext, workbook: dict, format: str = "xlsx") -> str:
    from automoto import spreadsheet_workspace

    data = dict(workbook)
    data["format"] = format or "xlsx"
    body = spreadsheet_workspace.ExportIn.model_validate(data)
    return call_studio(spreadsheet_workspace.export_spreadsheet, body, studio_request("POST"))


def invoice_preview(ctx: ToolContext, document: dict) -> str:
    """Totals only. The studio does not write or send anything."""
    from automoto import commercial_documents

    body = commercial_documents.CommercialIn.model_validate(document)
    return call_studio(commercial_documents.preview_document, body, studio_request("POST"))


def invoice_pdf(ctx: ToolContext, document: dict) -> str:
    from automoto import commercial_documents

    body = commercial_documents.CommercialIn.model_validate(document)
    return call_studio(commercial_documents.export_document, body, studio_request("POST"))


def finance_summary(ctx: ToolContext, book: dict) -> str:
    """Cash figures from the user's entries. Nothing is saved or treated as bank-verified."""
    from automoto import financial_intelligence

    body = financial_intelligence.FinanceBook.model_validate(book)
    return call_studio(financial_intelligence.analyse, body, studio_request("POST"))


def finance_export(ctx: ToolContext, book: dict, format: str = "pdf") -> str:
    from automoto import financial_intelligence

    data = dict(book)
    data["format"] = format or "pdf"
    body = financial_intelligence.ExportIn.model_validate(data)
    return call_studio(financial_intelligence.export, body, studio_request("POST"))


def spreadsheet_ai_review(ctx: ToolContext, workbook: dict, mode: str = "insights", question: str = "",
                          target_cell: str = "A1", sheet: int = 0) -> str:
    """Local model proposal. consent is sent only because this call was approved. Nothing is written."""
    from automoto import spreadsheet_ai

    body = spreadsheet_ai.ReviewIn.model_validate({
        "workbook": workbook, "sheet": sheet, "mode": mode, "question": question,
        "target_cell": target_cell, "consent": True,
    })
    result = call_studio(spreadsheet_ai.review, body, studio_request("POST"))
    if '"applied": true' in result.lower():
        raise ToolFailed("Spreadsheet AI tried to apply a change. That result was discarded.")
    return result


STUDIO = StudioSpec(
    id="spreadsheet",
    name="Spreadsheet and invoices",
    hosted_ok=True,
    approval="risky",
    local_only=("spreadsheet_ai_review",),
    words=r"\b(invoices?|quotations?|quotes?|cash flow|financial summary|spreadsheet studio)\b",
    exts=(".xlsx", ".xlsm", ".xls", ".csv"),
    skills=("spreadsheet-invoices",),
    fuzzy=("invoice", "quotation", "spreadsheet"),
    how="Calculate with spreadsheet_calculate and publish a new workbook with spreadsheet_export "
        "(real formulas, calculation_mode formulas). For an invoice or quote, invoice_preview the totals, "
        "then invoice_pdf. The PDF is a private draft: do not say it was emailed, issued or paid. "
        "finance_summary uses only the figures the user typed; finance_export writes the PDF or CSV. "
        "spreadsheet_ai_review returns a proposal and does not edit cells. Name the file when you finish.",
    labels={
        "spreadsheet_calculate": "Calculating the spreadsheet",
        "spreadsheet_export": "Exporting the spreadsheet",
        "invoice_preview": "Checking the invoice totals",
        "invoice_pdf": "Making the invoice PDF",
        "finance_summary": "Summarising the figures",
        "finance_export": "Exporting the financial report",
        "spreadsheet_ai_review": "Reviewing the sheet",
    },
    tools=(
        Tool("spreadsheet_calculate", "Evaluate a workbook's safe formulas. Writes nothing.",
             obj({"workbook": OBJ}, ["workbook"]), "safe", spreadsheet_calculate),
        Tool("spreadsheet_export", "Write a new xlsx or csv workbook. Formula errors block the export. "
             "The original file is not overwritten.",
             obj({"workbook": OBJ, "format": S}, ["workbook"]), "risky", spreadsheet_export),
        Tool("invoice_preview", "Total an invoice or quotation. Saves nothing and sends nothing.",
             obj({"document": OBJ}, ["document"]), "safe", invoice_preview),
        Tool("invoice_pdf", "Write a new draft invoice or quote PDF. It is not sent, issued or marked paid.",
             obj({"document": OBJ}, ["document"]), "risky", invoice_pdf),
        Tool("finance_summary", "Cash summary from user-entered amounts only. Not bank-verified. Saves nothing.",
             obj({"book": OBJ}, ["book"]), "safe", finance_summary),
        Tool("finance_export", "Write a new cash-summary PDF or CSV from user-entered amounts. "
             "Draft invoices are not treated as revenue.",
             obj({"book": OBJ, "format": S}, ["book"]), "risky", finance_export),
        Tool("spreadsheet_ai_review", "Ask the local offline model about a workbook. Returns a proposal only. "
             "Not available on a hosted server. Do not write the suggestion into the sheet yourself "
             "unless the user approves a later edit.",
             obj({"workbook": OBJ, "mode": S, "question": S, "target_cell": S, "sheet": {"type": "integer"}},
                 ["workbook"]), "risky", spreadsheet_ai_review),
    ),
)
