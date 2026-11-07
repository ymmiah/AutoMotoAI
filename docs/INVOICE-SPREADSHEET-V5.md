# AutoMoto AI - Invoice & Spreadsheet Intelligence V5

Milestone 5 of the approved eight-version roadmap. This is a local financial-analysis workspace, not a bank, accounting service, payment processor or tax adviser.

## Financial Intelligence & Dashboards

Open Invoices & Spreadsheets -> Financial dashboard. All V1-V4 tools remain available.

- Maintain a manually entered cash ledger with a unique transaction ID, date, movement type, category, description, reference, currency, amount and status.
- Choose GBP, EUR or USD, enter an opening cash balance, and select a period of up to 36 calendar months.
- Planned is the default status and is excluded from actual figures. Actual (user-confirmed) means the user declares that cash was received or paid; AutoMoto has no independent bank verification.
- Supported movements: Revenue (cash received), Expense (cash paid), Capital in (owner contribution), Capital out (owner withdrawal). Capital transactions move cash but never operating cash surplus.
- Show monthly revenue, expenses, operating cash surplus/deficit, opening and closing cash, financing cash, margin and separate planned figures.
- Accessible monthly bar chart, detailed monthly table and category performance breakdown.
- Save immutable private JSON snapshots. Load older copies without changing them.
- Export detailed CSV and locally generated, page-aware PDF reports with visible financial limitations.

## Basis, controls and exclusions

This is an indicative CASH-BASIS cash-activity summary, not accrual profit, statutory P&L, audited accounts, tax filing or a bank statement.

Only manually entered user-confirmed actual movements are included in actual totals. Draft invoices and quotations are NEVER imported or counted as revenue, including reviewed drafts. No invoice issue, quotation acceptance, payment processing, bank reconciliation, credit note, journal posting, collection or settlement occurs.

Operating cash surplus is actual receipts minus actual operating expenses. It is not formal profit. Unpaid invoices, bills, VAT, stock, depreciation, capital gains, exchange conversion and other accounting adjustments need separate professional review. The interface displays negative cash rather than hiding it.

## Calculation rules

- Input amounts and opening balance must be non-negative Decimal numbers with at most 2 decimal places. Transaction amount must be greater than zero.
- Currency never converts automatically. All entries in a book share one currency.
- Starting cash for a report period includes the user's initial balance PLUS actual movements before that period starts.
- Actual revenues and expenses within the period determine operating cash surplus.
- Owner capital flows change cash but not operating surplus.
- Planned transactions remain in a separate future column, never actual cash or surplus.
- Entries after the report end date do not affect the figures. Margin is unavailable (null) if actual receipts are zero.

## Privacy, security, supported bounds

All routes use AutoMoto authentication and hosted-mode tenancy. No network, payment APIs, bank integrations, AI providers or unapproved tools are invoked.

Maximum 500 entries, 36 report months, bounded amounts and descriptions, strict transaction-ID uniqueness, no unknown keys, and validated dates/categories/statuses/currencies. Snapshot files have unpredictable create-only names under the tenant-private artifacts/spreadsheets folder, separate from all V1-V4 records. Loading rejects traversal and symlinks. PDF user strings are XML escaped; CSV text is escaped to avoid spreadsheet formula injection. The resulting reports explicitly state that they are unverified and not statutory statements.

Authenticated API routes:
- GET /api/spreadsheets/finance/list
- POST /api/spreadsheets/finance/analyse
- POST /api/spreadsheets/finance/save
- GET /api/spreadsheets/finance/load?path=...
- POST /api/spreadsheets/finance/export (csv or pdf)

No send/pay/issue/connect/reconcile endpoint is added.

## Verification and acceptance

Run: python -m pytest -q tests/test_financial_intelligence.py tests/test_commercial_documents.py tests/test_spreadsheet_workspace.py tests/test_spreadsheet_formulas.py tests/test_spreadsheet_formatting.py

Run real browser acceptance: cd apps/desktop && npm run test:ui

Run the complete GitHub Actions matrix: Python 3.10/3.13 on Linux/macOS/Windows, Office, Visual Foundation, security, Docker, installers, Windows desktop, UI and docs.

Required checks: Decimal precision, actual/planned segregation, capital treatment, correct pre-period cash, month/category totals, zero revenue, negative balance, immutable records, private path handling, genuine PDF/CSV, hostile input escaping, no network side effects and exclusion of saved draft invoices.

Manual desktop, PDF pagination, screen-reader, keyboard, mobile and print-layout acceptance remains necessary before calling this production-ready.

## Remaining milestones

V6: Opt-in locally running AI spreadsheet assistance and safe approval boundaries.
V7: Controlled cross-module workflows, auditable actions and permissioned integrations.
V8: Production hardening, security, recovery and final acceptance.

Microsoft Store publication remains deferred until explicitly authorised.
