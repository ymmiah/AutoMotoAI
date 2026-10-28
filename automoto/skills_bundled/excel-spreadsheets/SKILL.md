---
name: excel-spreadsheets
description: Build Excel (.xlsx) models, trackers and reports with live formulas, number formats, conditional formatting, validation and charts - and verify every formula.
category: office
tools: office_create_xlsx, office_edit, office_read, office_recalc, office_check, office_convert
optional_apps: libreoffice
status: live
---
# Excel spreadsheets

1. **Design the workbook**: an `Inputs` sheet (assumptions, clearly labelled, units in the header),
   a `Model`/`Data` sheet (calculations), and a `Summary` sheet (key outputs + chart). One table per
   block, headers in row 1, no merged cells inside data, no blank rows inside a table.
2. **Formulas, not numbers**: anything derived is a formula (`=SUM(B2:B13)`, `=B5*Inputs!$B$2`,
   `=IFERROR(C2/B2,0)`, `=XLOOKUP(...)` only if the user has Excel 365 - prefer `INDEX/MATCH` for
   compatibility). Use absolute refs (`$B$2`) for assumptions; add `names` for key inputs.
3. **Formatting**: `number_formats` for currency (`£#,##0.00`), percentages (`0.0%`), dates
   (`dd/mm/yyyy`); bold totals; `freeze` the header; `autofilter` on data tables; column widths auto.
   Conditional formats to highlight (data bars for magnitude, `cell_is` red for negatives).
   `validation` lists for categorical inputs.
4. **Charts**: column for comparisons, line for trends over time, pie only for ≤ 5 parts of a whole,
   scatter for relationships. Always a title and axis titles. Data range includes the header row.
5. **Verify**: run `office_recalc` - it recalculates with LibreOffice and lists every formula's value
   and any `#REF!`/`#DIV/0!`/`#NAME?`. Fix and re-run until 0 errors. Spot-check 2-3 values by hand.
6. `office_check` for missing sheets/external links; `office_convert to=pdf` if a printable copy is needed.
7. Report the sheets, key outputs (with values from the recalc) and the file path.

For data analysis of an existing file: `office_read` (formulas and values, a summary of numeric columns).
