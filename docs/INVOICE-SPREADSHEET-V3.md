# AutoMoto AI — Invoice & Spreadsheet Intelligence v3

**Milestone 3 of the approved eight-version development roadmap**. This is development, not a Microsoft Store release.

## V3 features

- Basic bounded Excel cell formatting: bold/italic, left/centre/right alignment, fill/text colours, and recognised number formats (general, number, integer, GBP, USD, EUR and percentage). Styles are explicit cell-address metadata, stored in private workbook JSON drafts and applied in exported XLSX copies.
- Freeze header row, first column or both. Enable or disable Excel header filter buttons. Choose a bounded column width (8–48).
- A selected-cell formatting toolbar. Undo/Redo retains styling, layout, sort order and validation changes.
- Sort complete data rows by a chosen column, leaving headers in place. Cell styling travels with its row. Sorting is explicitly refused for worksheets containing formulas because the V3 editor does not rewrite their references.
- Non-destructive filter/search by a selected column. Filters affect only the current view, not saved/exported data; clearing restores all visible rows.
- Set a dropdown list, whole-number or decimal-value rule for each column A–P. Browser cell entry/paste refuses invalid values; independently the authenticated API validates values before saving or exporting. New XLSX files receive genuine Excel validation controls.
- Import simple recognised visible XLSX styles using the existing safe, read-only, SHA-256 checked importer. Uploaded originals are never overwritten. Incoming formulas remain literal until intentionally enabled.

## Compatibility limits

**Partial Excel support, not full-fidelity editing.** Complex merges, charts, shapes, formulas outside the V2 allowlist, pivot tables, workbook protection, hyperlinks, external links, macros, named ranges, conditional formatting, custom number formats and calculated caches are not round-tripped. Original freezes, column widths, filter settings and validation rules are not imported in V3. The importer warns about those limitations. The editor does not silently overwrite or modify the original workbook.

Older V1/V2 drafts without style metadata remain compatible. Invoice drafts from previous milestones remain independent.

### Bounds and security

Up to five worksheets, 100 rows and 16 columns each; 500 styled cells, 16 column rules and ten dropdown entries per list; widths 8–48. Lists cannot include Excel formula expressions or unsafe characters. Unknown properties, invalid addresses, oversized values and unsafe worksheet paths are rejected. No eval, user macros, remote formula execution or customer transaction actions are enabled.

## Verification

Python: python -m pytest -q tests/test_spreadsheet_formatting.py tests/test_spreadsheet_formulas.py tests/test_spreadsheet_workspace.py

Browser and desktop UI: cd apps/desktop && npm run test:ui

Real browser acceptance checks private workbook styling, freeze/column width, decimal validation, formula-safe sorting and non-destructive filters. Full GitHub Actions must pass Office, security, Docker, VS Code, installers, Windows app and the cross-platform Python matrix.

Manual acceptance remains required in installed Excel/LibreOffice and on native hardware, including accessibility, keyboard flow, responsiveness and locale-specific number formatting. Automated tests alone do not establish complete Office compatibility.

## Remaining roadmap

V4: branded invoice and quotation drafts, PDF, discounts, customer details, VAT safeguards.
V5: financial dashboards and reporting.
V6: opt-in local AI spreadsheet assistance.
V7: business workflow integrations and audit logging.
V8: production hardening, recovery and acceptance.

Microsoft Store publication remains deferred.
