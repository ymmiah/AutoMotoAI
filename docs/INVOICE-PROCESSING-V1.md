# Invoice Processing — Phase 2 (issue #10)

**Scope:** user-directed Phase 2 of the roadmap in issue #10. Phase 1 Document
Assistant (PR #119) is merged into main; this milestone does not rework it.
AI Receptionist (Phase 5) remains on hold and is not implemented here.

## What already existed (verified by reading the code, not by name)

- **Manual draft invoices** (`automoto/commercial_documents.py`, V4): user-typed
  seller/buyer, number, dates, GBP/EUR/USD, up to 40 lines, Decimal totals
  with ROUND_HALF_UP, create-only JSON records, branded PDF export via
  `commercial_pdf.py` (ReportLab, multipage, DRAFT-marked). No extraction,
  no OCR, no duplicate detection, no review queue.
- **Manual cash ledger** (`automoto/financial_intelligence.py`, V5): user-entered
  entries, CSV/PDF export, formula-safe CSV escaping. Draft invoices are never
  revenue. No invoice ingestion.
- **Review workflow** (`automoto/business_workflows.py`, V7): hash-chained
  approve/reject audit for two linked records. The approve/reject pattern and
  hash-chain idea were reused in spirit; invoice review needed its own queue,
  so it is not built on top of V7.
- **Text extraction** (`automoto/document_research.py`): pypdf per-page text
  (200 pages, 180,000 chars), DOCX via `office.read_docx`, plain text. Reused
  as the extraction pattern for PDF/DOCX/TXT.
- **Spreadsheet workspace**: openpyxl XLSX read/write, SHA-256 checks,
  copy-only imports. Reused for XLSX sources and XLSX export.
- **No OCR anywhere in the repo.** No tesseract/easyocr dependency or binary
  was found, and `tesseract` is not installed on this machine. Scanned images
  therefore cannot be read locally by default (see limitations).

## What Phase 2 adds (`automoto/invoice_processing.py`)

- **Ingest:** source must be in `uploads/` (same confinement as Document
  Assistant), SHA-256 checked before and after copy; the original is copied
  once into `artifacts/invoices/sources/` and never modified. Supported:
  PDF, TXT, MD, DOCX, XLSX, CSV, PNG, JPG, JPEG. 10 MB / 50 PDF pages /
  180,000 chars bounds.
- **Extraction:** deterministic label-driven parser over extracted text lines.
  Every field carries `{value, confidence, source: {page, line, start, end,
  verbatim text}}`. Fields: seller, buyer, invoice number, issue/due date,
  currency, VAT number, VAT rate, subtotal, tax amount, total, bank fields
  (IBAN, sort code, account number, payment reference), line items
  (description, quantity, unit price, line total). Money parses `1,234.56`
  and decimal-comma `1.234,56`; dates parse ISO, `DD/MM/YYYY` and
  `DD Month YYYY`. A field that cannot be found is `null` with confidence 0 —
  never guessed.
- **Validation (Decimal):** line `qty × unit price`, lines vs subtotal,
  subtotal + tax vs total, VAT rate × subtotal vs stated tax; missing required
  fields; duplicate invoice (same source SHA-256, or same seller + number);
  due date before issue date; VAT rate outside the configured policy;
  low-confidence fields. Issues carry code, severity (error/warning), field
  and message. Status is `ready`, `needs_review`, `needs_ocr`, `approved` or
  `rejected`.
- **Review queue:** `GET /api/invoices/list` (with `review_queue`),
  `GET /api/invoices/detail`, `POST /api/invoices/correct` (manual correction
  recorded with previous/new value, reason and timestamp, then re-validated),
  `POST /api/invoices/decide` (approve is blocked while error issues remain;
  approval only marks the draft approved — no payment, dispatch or posting).
- **Exports:** `POST /api/invoices/export` as CSV, XLSX (Invoice + Evidence +
  Issues sheets), JSON, or a printable audit PDF (fields with confidence,
  issues, corrections, decisions, "EXTRACTED RECORD ONLY" notice).
- **Agent tools** (`automoto/invoice_studio_tools.py`): `invoice_extract`,
  `invoice_list`, `invoice_detail`, `invoice_decide`, `invoice_export`,
  auto-registered by the studio registry; no change to `tools.py`.
- **Routes:** `server.py` includes the router; `hosted.py` allowlists
  `GET /api/invoices/(list|detail)` and `POST /api/invoices/(extract|correct|decide|export)`.
  No `/pay`, `/send` or ERP route exists.

## Fixtures and tests (`tests/test_invoice_processing.py`, 16 tests)

Fixtures are generated in-test with ReportLab/Pillow, so the suite is
deterministic with no committed binaries:

- Clean GBP PDF (VAT 20%, correct totals, IBAN/sort code/payment ref) — full
  field + evidence assertions.
- Multipage PDF, 60 line items over 2 pages.
- Foreign currency EUR with decimal-comma amounts; VAT 19% flagged under the
  default policy and accepted with a configured 19% policy.
- Reduced VAT 5%.
- Mismatched total and mismatched line total — caught, approval blocked,
  manual correction recorded and re-validated, then approved.
- Duplicate invoice (same file twice, and same seller + number).
- Missing fields — never invented (`null`, confidence 0).
- Non-invoice letter and corrupt PDF (422).
- Scanned image (Pillow-rendered PNG) — `needs_ocr`, no fields invented,
  decision refused.
- XLSX source, review-queue listing, all four export formats, source
  confinement / SHA-256 checks, auth + hosted scopes, money/date unit tests.

## Known limitations

- **No OCR by default.** Images and image-only PDFs are stored as
  `needs_ocr` with no fields extracted. If a local `tesseract` binary is
  present, it is used (`--psm 6`); there is no cloud OCR and no new
  dependency. Exact visual bounding boxes are therefore only available when
  OCR runs; text sources carry page/line/character-span evidence instead.
- **No email attachment ingestion.** The source must already be in
  `uploads/`; an authorised email attachment has to be saved there first.
  No Gmail/ERP/Business Central integration in this phase.
- **Deterministic parser, not a model.** Unusual layouts (multi-column
  invoices, tables split across pages, handwritten text) will produce
  low-confidence or missing fields and land in the review queue — by design,
  not silently.
- Currencies are limited to the configured ISO set; VAT policy defaults to
  standard 20 / reduced 5 / zero 0 and is configurable per extraction.
- No web UI yet for the invoice queue — REST + agent tools only.
