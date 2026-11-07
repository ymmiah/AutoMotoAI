# AutoMoto AI — Invoice & Spreadsheet Intelligence v1

**Development milestone 1 of 8.** Integrated into the existing AutoMoto AI application. This does not publish an app, send an invoice, change payment status, or start Microsoft Store submission.

## Workbook workspace

Open **Invoices & Spreadsheets** from the sidebar or quick commands.

- Edit literal text and numbers in a keyboard-accessible grid.
- Add up to five named worksheets, with a maximum of 100 rows and 16 columns each in v1.
- Paste tab-separated cells. Leading-zero identifiers such as 00123 are retained as text.
- Import previously uploaded XLSX or UTF-8 CSV or upload through the workspace; original files remain unchanged.
- Save a new private create-only workbook draft and load previous copies without overwriting them.
- Export formatted XLSX or single-sheet CSV.
- XLSX string cells are typed as strings even when starting with an equals sign. CSV formula-like prefixes are escaped. **V1 does not evaluate formulas.**

Imported XLSX formulas are retained as literal text, never recalculated. Excel styling, charts, merged cells, images, macros, pivot tables, links, conditional rules and large datasets are not round-tripped. The UI warns about source truncation. Full Excel compatibility and formulas are later milestones.

## Invoice drafts

- Enter actual seller and buyer details, invoice number, issue and due dates, and GBP/EUR/USD currency.
- Supply a tax rate explicitly. The default 0% is not a tax or legal determination.
- Add up to 40 line items. Quantities support three decimal places; prices and tax rates support two.
- Preview totals through Python Decimal with ROUND_HALF_UP rounding at line totals and tax total.
- Save private JSON invoice drafts; load without silently modifying previously saved files.
- Export an XLSX labelled **DRAFT**, with item totals, tax, and invoice total.
- No email delivery, legal issue, payment processing, customer records, quotations, PDF billing or automatic transactions.

## Security boundaries

Offline and no required AI. Uses the existing authenticated workspace and hosted per-tenant isolation. All outputs are create-only under artifacts/spreadsheets. Imports only accept files directly inside uploads, reject traversal and symlinks, are capped at 10 MB, and use the existing Office ZIP/XXE inspection checks. Macros and external workbook links are refused. SHA-256 verifies source identity before and after import. Bounded data models refuse oversized rows/cells, invalid worksheet names, unknown fields and invalid XML control characters. All original uploads are preserved.

Authenticated API routes:
- GET /api/spreadsheets/list
- POST /api/spreadsheets/import
- POST /api/spreadsheets/save
- GET /api/spreadsheets/load
- POST /api/spreadsheets/export
- POST /api/spreadsheets/invoice/preview
- POST /api/spreadsheets/invoice/save
- GET /api/spreadsheets/invoice/load
- POST /api/spreadsheets/invoice/export

Unsupported update, pay and other arbitrary operations are not exposed.

## Validation

Run Python tests with: python -m pytest -q tests/test_spreadsheet_workspace.py

Run desktop/browser UI regression tests with: cd apps/desktop && npm run test:ui

Full CI must validate Python 3.10 and 3.13 on Linux/macOS/Windows, Office functionality, security, Visual Foundation, installers, UI and Windows desktop packaging. Real installed desktop acceptance is still required for keyboard navigation, small-screen layout and Microsoft Excel/LibreOffice import-export fidelity. Mocked or automated tests are not hardware-level proof.

## Agreed roadmap

V1: Offline workspace, basic workbook editing, literal exports and invoice draft foundation.
V2: Formula engine, references, recomputation and Undo/Redo.
V3: Excel fidelity, formatting, sorting/filtering and validation.
V4: Invoice and quotation studio, PDF, branding and customer records.
V5: Financial dashboards, budget/cash-flow analysis and reporting.
V6: Opt-in local AI spreadsheet assistance and anomaly review.
V7: Integrated business workflows, audit logs and approved automation.
V8: Final cross-platform security, accessibility, recovery and production acceptance.

**No Microsoft Store publication until separately authorised.**
