"""Page-aware locally rendered V5 cash-basis analytics report (ReportLab)."""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

DARK = colors.HexColor("#142B40")
BLUE = colors.HexColor("#254669")
PALE = colors.HexColor("#F2F6FA")
MUTED = colors.HexColor("#587087")
WIDTH = 174 * mm


def _safe(value: object) -> str:
    return escape(str(value or "")).replace("\n", "<br/>")


def render_finance_pdf(book, report: dict, target: Path) -> None:
    doc = SimpleDocTemplate(str(target), pagesize=A4, leftMargin=18*mm,
                            rightMargin=18*mm, topMargin=38*mm, bottomMargin=24*mm,
                            title="AutoMoto V5 private cash-basis report", author="AutoMoto AI",
                            pageCompression=1)
    heading = ParagraphStyle("Heading", fontName="Helvetica-Bold", fontSize=20,
                             leading=25, textColor=DARK, spaceAfter=12)
    section = ParagraphStyle("Section", fontName="Helvetica-Bold", fontSize=11,
                             leading=15, textColor=DARK, spaceBefore=8, spaceAfter=8)
    base = ParagraphStyle("Base", fontName="Helvetica", fontSize=8.7,
                          leading=12.5, textColor=DARK, splitLongWords=True)
    small = ParagraphStyle("Small", parent=base, fontSize=7.6, leading=11)
    strong = ParagraphStyle("Strong", parent=base, fontName="Helvetica-Bold")
    right = ParagraphStyle("Right", parent=small, alignment=TA_RIGHT)
    header = ParagraphStyle("Header", parent=small, fontName="Helvetica-Bold", textColor=colors.white)
    notice = ParagraphStyle("Notice", parent=small, textColor=MUTED)
    flow = [
        Paragraph("FINANCIAL INTELLIGENCE", heading),
        Paragraph("PRIVATE / UNVERIFIED / CASH-BASIS INDICATIVE REPORT", strong),
        Spacer(1, 2*mm),
        Paragraph("Workspace: " + _safe(report["name"]), base),
        Paragraph("Period: " + report["period_from"] + " to " + report["period_to"]
                  + "  |  Currency: " + report["currency"], base),
        Spacer(1, 7*mm),
        Paragraph("Cash movement overview", section),
    ]
    labels = [
        ("Cash opening", "opening_cash"), ("Confirmed revenue receipts", "revenue"),
        ("Confirmed operating expenses", "expenses"),
        ("Operating cash surplus / deficit", "operating_surplus"),
        ("Capital contributed", "capital_in"), ("Owner capital withdrawn", "capital_out"),
        ("Net cash movement", "net_cash_movement"), ("Cash closing", "closing_cash"),
    ]
    cards = [
        [Paragraph(_safe(label), base),
         Paragraph(report["currency"] + " " + _safe(report[key]), right)]
        for label, key in labels
    ]
    overview = Table(cards, colWidths=[99 * mm, 75 * mm], hAlign="LEFT")
    overview.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, PALE]),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEABOVE", (0, -1), (-1, -1), 1.2, BLUE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    flow.append(overview)
    flow.append(Spacer(1, 3*mm))
    flow.append(Paragraph(
        "Only user-entered, user-confirmed cash transactions are included in actual totals. "
        "Unpaid invoices, quotation drafts and planned entries are excluded.", notice))
    flow.append(Paragraph("Monthly performance", section))

    colwidths = [27*mm, 31*mm, 31*mm, 36*mm, 49*mm]
    monthly = [[Paragraph(text, header) for text in
                ("Month", "Receipts", "Expenses", "Cash surplus", "Cash balance")]]
    for entry in report["months"]:
        monthly.append([
            Paragraph(entry["month"], small),
            Paragraph(_safe(entry["revenue"]), right),
            Paragraph(_safe(entry["expenses"]), right),
            Paragraph(_safe(entry["operating_surplus"]), right),
            Paragraph(_safe(entry["cash_balance"]), right),
        ])
    tbl = Table(monthly, colWidths=colwidths, repeatRows=1, hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    flow.append(tbl)
    flow.append(Paragraph("Breakdown by category (actual transactions)", section))
    if report["categories"]:
        breakdown = [[Paragraph(text, header) for text in ("Category", "Revenue", "Expenses")]]
        for row in report["categories"]:
            breakdown.append([
                Paragraph(_safe(row["category"]), small),
                Paragraph(_safe(row["revenue"]), right),
                Paragraph(_safe(row["expenses"]), right),
            ])
        cat = Table(breakdown, colWidths=[92*mm, 41*mm, 41*mm], repeatRows=1)
        cat.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BLUE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        flow.append(cat)
    else:
        flow.append(Paragraph("No actual operating cash activity in the selected period.", small))

    flow.append(Paragraph("Manually entered activity in selected period", section))
    transactions = [
        e for e in sorted(book.entries, key=lambda e: (e.transaction_date, e.entry_id))
        if book.period_from <= e.transaction_date <= book.period_to
    ]
    if transactions:
        lines = [[Paragraph(v, header) for v in ("Date", "Kind", "Description", "Amount")]]
        for entry in transactions:
            lines.append([
                Paragraph(entry.transaction_date.isoformat(), small),
                Paragraph(_safe(entry.kind) + "<br/>" + _safe(entry.status), small),
                Paragraph(_safe(entry.description) + "<br/>" +
                          _safe(entry.category) + " / " + _safe(entry.reference), small),
                Paragraph(_safe(entry.amount), right),
            ])
        ledger = Table(lines, colWidths=[25*mm, 30*mm, 85*mm, 34*mm], repeatRows=1)
        ledger.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BLUE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        flow.append(ledger)
    else:
        flow.append(Paragraph("No entries in this period.", small))
    flow.append(Spacer(1, 5*mm))
    flow.append(Paragraph("Limitations and verification", section))
    for warning in report["warnings"]:
        flow.append(Paragraph("- " + _safe(warning), notice))
        flow.append(Spacer(1, 2*mm))

    def decorate(canvas, document):
        canvas.saveState()
        w, h = A4
        canvas.setFillColor(DARK)
        canvas.rect(0, h-11*mm, w, 11*mm, fill=1, stroke=0)
        canvas.setFillColor(DARK)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(18*mm, h-24*mm, "AUTOMOTO AI  /  CASH INTELLIGENCE V5")
        canvas.setStrokeColor(colors.HexColor("#CFD8E3"))
        canvas.line(18*mm, 18*mm, w-18*mm, 18*mm)
        canvas.setFont("Helvetica", 7.6)
        canvas.setFillColor(MUTED)
        canvas.drawString(18*mm, 12.5*mm, "UNVERIFIED / NOT AN AUDITED OR STATUTORY STATEMENT")
        canvas.drawRightString(w-18*mm, 12.5*mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(flow, onFirstPage=decorate, onLaterPages=decorate)
