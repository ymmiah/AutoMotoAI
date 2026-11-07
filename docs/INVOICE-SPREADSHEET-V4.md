# AutoMoto AI - Invoice & Spreadsheet Intelligence V4

**Fourth of eight planned development milestones. Not a public release or Microsoft Store publication.**

## Business document studio

Open Invoices & Spreadsheets, then Business documents. The existing basic invoices and V1-V3 spreadsheet features remain intact.

- Prepare branded **invoice or quotation drafts** using Executive or Minimal PDF layouts, business display name and an accessible dark accent colour. Logo uploads are not yet provided.
- Specify an internal reference, document date, due date / quote-valid-until date, GBP/EUR/USD currency and explicit review state (draft or reviewed).
- Keep full seller and customer names, postal addresses, optional email, telephone and registration/VAT reference.
- Save private, create-only customer contact records and reuse them in new documents.
- Add up to 40 item lines with quantities (three decimal places), unit prices (two decimal places), and line discounts. Apply a document-level discount.
- Choose a manual Tax/VAT/GST/Sales tax label and percentage. A default 0% is not a legal tax determination.
- Preview all money using Python Decimal, then save an immutable JSON draft or generate a locally rendered page-aware multi-page PDF with totals, page numbering and prominent DRAFT notices.
- Reviewed is a review *stage*, not an invoice-issued or quote-accepted state. No invoice is sent, no payment is collected, no debts are adjusted and no accounting entries are posted.

## Calculation method and limits

Round each quantity-by-price extended amount to two decimal places (ROUND_HALF_UP); then round its line discount. Sum the line amounts and subtract the rounded line discounts, subtract the rounded document discount, then apply and round the user-supplied document-level tax. A detailed preview discloses the rounding sequence.

This is an explicit simple tax model, not jurisdiction-specific VAT/GST determination. Exemptions, tax-inclusive prices, multi-rate VAT, reverse charge, credit notes, compliance checks, payment reconciliation, customer statements, email delivery and currency exchange are not automated. Before issuing a legal document elsewhere, the user must check party identity, tax and terms.

## Privacy, security and backward compatibility

All new records are private and create-only, stored in tenant-scoped workspace artifacts/spreadsheets, with random server-generated filenames. Existing workbooks and V1-V3 invoice records remain unchanged. File loading is path-restricted, schema-checked and authenticated. Hosted mode explicitly allowlists only the required routes. No issue, accept, send, pay, refund, delete or hidden status-transition endpoints exist.

The local ReportLab PDF generator needs neither LibreOffice nor a cloud service. Untrusted descriptions and party fields are XML-escaped; unsupported characters, excessive values, bad dates, unknown properties, unsafe brand colours and overlong inputs are rejected. PDF exports are checked before being exposed through the existing authenticated download mechanism.

Authenticated paths:
- GET /api/spreadsheets/commercial/list
- POST /api/spreadsheets/commercial/preview
- POST /api/spreadsheets/commercial/save
- GET /api/spreadsheets/commercial/load
- POST /api/spreadsheets/commercial/export
- POST /api/spreadsheets/commercial/customer/save
- GET /api/spreadsheets/commercial/customer/load

## Verification and acceptance

Run Python tests: python -m pytest -q tests/test_commercial_documents.py tests/test_spreadsheet_workspace.py tests/test_spreadsheet_formulas.py tests/test_spreadsheet_formatting.py

Run browser tests: cd apps/desktop && npm run test:ui

Full GitHub Actions tests cover Python 3.10/3.13 on Linux, macOS and Windows; UI, security, Office, VS Code, Docker, installers, Windows desktop and docs. New tests cover Decimal rounding, line/order discounts, multi-page PDF text, immutable records, customer contacts, unsafe paths and injection boundaries. Real installed desktop, PDF rendering and print-layout inspection remain necessary for final acceptance; automated text extraction does not prove pixel-perfect pagination or multilingual font support.

## Remaining agreed roadmap

V5: Financial dashboards and reporting.
V6: Offline optional AI spreadsheet assistant.
V7: Controlled workflow integration and audit logs.
V8: Production hardening and final acceptance.

Microsoft Store publication remains explicitly deferred.
