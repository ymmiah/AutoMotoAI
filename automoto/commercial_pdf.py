"""Offline branded commercial PDF drafts using ReportLab Platypus.

Every user-controlled text value is XML escaped before it reaches a Paragraph.
The PDF has page-aware tables and persistent DRAFT markings. No external URLs,
webfonts, images, callbacks, scripts, invoice sends or network access.
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

PAGE_W, PAGE_H = A4
ACCENT_BG = colors.HexColor("#F4F7FB")
GREY = colors.HexColor("#607087")
TEXT = colors.HexColor("#16283D")


def _safe(value: object) -> str:
    return escape(str(value or "")).replace("\n", "<br/>")


def _party(party, style) -> Paragraph:
    details = [party.name, party.address]
    if party.email:
        details.append(party.email)
    if party.phone:
        details.append(party.phone)
    if party.registration:
        details.append("Registration / tax identifier: " + party.registration)
    return Paragraph("<br/>".join(_safe(line) for line in details), style)


def render_pdf(body, totals: dict, destination: Path) -> None:
    accent = colors.HexColor(body.brand.accent)
    minimal = body.brand.template == "minimal"
    top = 52 * mm if minimal else 58 * mm
    pdf = SimpleDocTemplate(
        str(destination), pagesize=A4, rightMargin=17 * mm, leftMargin=17 * mm,
        topMargin=top, bottomMargin=24 * mm, title="DRAFT " + body.kind.upper()
        + " " + body.number[:50], author="AutoMoto AI - Private draft",
        pageCompression=1,
    )
    title_style = ParagraphStyle("Title", fontName="Helvetica-Bold",
                                  fontSize=23, leading=29, textColor=accent, spaceAfter=12)
    text = ParagraphStyle("Text", fontName="Helvetica", fontSize=9, leading=14,
                          textColor=TEXT, splitLongWords=True)
    header = ParagraphStyle("Header", parent=text, fontName="Helvetica-Bold", fontSize=9,
                            textColor=accent, spaceAfter=7)
    caption = ParagraphStyle("Caption", parent=text, fontSize=8, leading=11, textColor=GREY)
    small = ParagraphStyle("TableBody", parent=text, fontSize=8.5, leading=12)
    small_bold = ParagraphStyle("TableBold", parent=small, fontName="Helvetica-Bold")
    money = ParagraphStyle("Amount", parent=small, alignment=TA_RIGHT)
    money_bold = ParagraphStyle("AmountBold", parent=money, fontName="Helvetica-Bold")
    table_heading = ParagraphStyle("TableHeading", parent=small_bold, textColor=colors.white)
    story = []

    label = "INVOICE" if body.kind == "invoice" else "QUOTATION"
    story.append(Paragraph("DRAFT " + label, title_style))
    story.append(Paragraph("Document reference: " + _safe(body.number), small_bold))
    story.append(Spacer(1, 6 * mm))

    left_head = "FROM"
    right_head = "BILL TO" if body.kind == "invoice" else "PREPARED FOR"
    parties = Table([
        [Paragraph(left_head, header), Paragraph(right_head, header)],
        [_party(body.seller, text), _party(body.customer, text)],
    ], colWidths=[87 * mm, 87 * mm], hAlign="LEFT")
    parties.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
    ]))
    story.append(parties)
    story.append(Spacer(1, 7 * mm))

    metadata = [
        [Paragraph("Date", caption), Paragraph("Due date" if body.kind == "invoice" else "Valid until", caption),
         Paragraph("Currency", caption), Paragraph("Review status", caption)],
        [Paragraph(body.issue_date.isoformat(), small_bold),
         Paragraph(body.due_date.isoformat(), small_bold),
         Paragraph(body.currency, small_bold),
         Paragraph("Reviewed draft" if body.review_state == "reviewed" else "Draft", small_bold)],
    ]
    block = Table(metadata, colWidths=[43.5 * mm] * 4)
    block.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ACCENT_BG),
        ("TOPPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 11),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(block)
    story.append(Spacer(1, 8 * mm))

    widths = [76 * mm, 19 * mm, 27 * mm, 25 * mm, 27 * mm]
    column_names = ["DESCRIPTION", "QTY", "UNIT PRICE", "DISCOUNT", "LINE TOTAL"]
    table = [[Paragraph(x, table_heading) for x in column_names]]
    for line in totals["lines"]:
        table.append([
            Paragraph(_safe(line["description"]), small),
            Paragraph(_safe(line["quantity"]), small),
            Paragraph(body.currency + " " + line["unit_price"], money),
            Paragraph(line["discount_percent"] + "%", money),
            Paragraph(body.currency + " " + line["net"], money_bold),
        ])
    lines_table = Table(table, colWidths=widths, repeatRows=1, hAlign="LEFT",
                        splitByRow=1)
    lines_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ACCENT_BG]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, accent),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#E4E9EF")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
        ("TOPPADDING", (0, 1), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 9),
    ]))
    story.append(lines_table)
    story.append(Spacer(1, 8 * mm))

    rows = [
        ("Line subtotal", totals["subtotal"]),
        ("Line discounts", "-" + totals["line_discounts"]),
        ("Order discount (" + totals["document_discount_percent"] + "%)",
         "-" + totals["document_discount"]),
        ("Taxable amount", totals["taxable"]),
        (totals["tax_label"] + " (" + totals["tax_percent"] + "%)", totals["tax"]),
        ("TOTAL", totals["total"]),
    ]
    totals_rows = [
        [Paragraph(_safe(label), small_bold if label == "TOTAL" else small),
         Paragraph(body.currency + " " + value, money_bold if label == "TOTAL" else money)]
        for label, value in rows
    ]
    totals_table = Table(totals_rows, colWidths=[59 * mm, 42 * mm], hAlign="RIGHT")
    totals_table.setStyle(TableStyle([
        ("LINEABOVE", (0, -1), (-1, -1), 1.2, accent),
        ("BACKGROUND", (0, -1), (-1, -1), ACCENT_BG),
        ("TOPPADDING", (0, -1), (-1, -1), 10),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(KeepTogether(totals_table))
    story.append(Spacer(1, 8 * mm))
    for title, value in (("Notes", body.notes), ("Terms", body.terms)):
        if value:
            story.append(KeepTogether([Paragraph(title.upper(), header),
                                       Paragraph(_safe(value), small), Spacer(1, 5 * mm)]))
    story.append(HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#CBD5E1")))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("PRIVATE DRAFT ONLY. Not issued, sent, accepted or paid. "
                           "Tax, legal details and commercial terms must be verified "
                           "before use.", caption))

    def decoration(canvas, document):
        canvas.saveState()
        if not minimal:
            canvas.setFillColor(accent)
            canvas.rect(0, PAGE_H - 12 * mm, PAGE_W, 12 * mm, stroke=0, fill=1)
        canvas.setFont("Helvetica-Bold", 11)
        canvas.setFillColor(accent)
        canvas.drawString(17 * mm, PAGE_H - 28 * mm, body.brand.display_name[:80])
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(GREY)
        canvas.drawRightString(PAGE_W - 17 * mm, PAGE_H - 28 * mm,
                               "PRIVATE COMMERCIAL DRAFT")
        canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
        canvas.line(17 * mm, 19 * mm, PAGE_W - 17 * mm, 19 * mm)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(17 * mm, 13 * mm, "DRAFT ONLY - NOT ISSUED")
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(PAGE_W - 17 * mm, 13 * mm, "Page " + str(document.page))
        canvas.restoreState()

    pdf.build(story, onFirstPage=decoration, onLaterPages=decoration)
