---
name: spreadsheet-invoices
description: Build a formula workbook, a draft invoice or quote PDF, or a cash summary from numbers the user supplied.
category: office
tools: spreadsheet_calculate, spreadsheet_export, invoice_preview, invoice_pdf, finance_summary, finance_export, spreadsheet_ai_review
status: live
---
# Spreadsheet and invoices

Use only numbers the user gave you. Do not invent totals.

1. A workbook with formulas uses `calculation_mode` `formulas` and real formulas such as `=SUM(B2:B4)`. `spreadsheet_calculate` checks them. `spreadsheet_export` writes a new xlsx. If a formula errors, fix the workbook and export again.
2. An invoice or quote is a `document` object: seller, customer, dates, currency and lines. `invoice_preview` first, then `invoice_pdf`. Say it is a draft. Do not say it was emailed, issued or paid.
3. A cash summary is a `book` of user-entered entries. `finance_summary` then `finance_export`. Planned rows and draft invoices are not revenue. The result is not bank-verified.
4. `spreadsheet_ai_review` returns a suggestion and does not edit cells. Leave the sheet unchanged unless the user asks you to export a corrected workbook.
5. Name the file you wrote.
