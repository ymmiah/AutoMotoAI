# AutoMoto AI — Invoice & Spreadsheet Intelligence V6

**Milestone 6 of 8.** Development-only feature. V6 is stacked on V5 until V5 is merged; there is no Microsoft Store publication.

## Offline AI Spreadsheet Assistant

The existing spreadsheet editor gains an **Offline AI assistant** panel, which keeps the original workbook as the authority. Its tools have separate trust levels.

**1. Deterministic quality audit (no model required).** Inspect the current worksheet for leading/trailing whitespace, identical data rows, mixed number/text columns and errors from the supported V2 formula engine. This is a bounded heuristic check, not a guarantee that values are correct. Audits make no network calls, file writes or edits.

**2. Optional local Ollama assistant.** With a model already downloaded and enabled in **Settings → Offline AI**, a user can explicitly tick a consent checkbox and request one of:

- Evidence-backed, read-only observations about sampled cells;
- One safe formula suggestion for a selected cell (only when safe formula mode is already enabled);
- One proposed clean-up of an existing text cell.

The review sends a bounded sample of **at most 60 cell values**, each clipped to 120 characters, to the configured **loopback-only local Ollama server**. The selected model must be installed. There is no cloud fallback, external API key, internet lookup, browser tool, shell access, payment action, remote model or financial-data sync.

The model receives a system-level warning that worksheet values, headings, text, links and cells are untrusted input and must not be obeyed as instructions. The model must return constrained JSON. All user-controlled data and model output is rendered as text, never executable HTML.

**Evidence boundary:** each AI observation must include a cell address and an **exact quotation** of a supplied sampled cell; unsupported evidence is dropped. Each actionable suggestion must contain valid evidence. Exact quotation is a provenance test, **not proof that the model's interpretation or formula is correct**.

## Approval and data safety

V6 **never automatically applies** AI output. The original and suggested value appear side by side with evidence and a reason. The user must click Review and apply, confirm the single-cell action and pass a fresh server validation before the browser makes an Undo-tracked edit. This new API is read-only, returns no saved workbook and applies no changes itself.

- The current workbook is deterministically normalised and hashed. Changed workbooks, changed target cells or stale hashes return HTTP 409.
- Formula proposals must pass the allowlisted V2 parser and evaluator, with checks for circular dependencies and target-cell errors. External workbooks, macros, network formulas, scripts and unsupported functions are rejected.
- Text clean-up cannot introduce formula-like content, control characters or changes to non-text cells.
- Existing column-validation rules are also checked by the editor before applying a proposed change.
- Only the explicitly selected cell can be changed, in the current session. The user may Undo. Existing saved drafts, imports, invoices, financial reports and original files remain untouched; saving a private copy requires a separate user action.
- The browser discards suggestions if the working snapshot changes while the model responds or during approval.

### Security and deployment

The new routes are authenticated:

- POST /api/spreadsheets/ai/audit — deterministic read-only check, including hosted mode within its tenant.
- POST /api/spreadsheets/ai/review — **local desktop only**; blocked in hosted/multiuser mode; requires consent, safe local Ollama and an installed enabled model.
- POST /api/spreadsheets/ai/validate — read-only workbook hash and formula-check route; **not** an editing or filesystem operation.

Existing authentication, request limits and hosted routing remain. The model has no connected tools and cannot browse or run commands. Loopback is checked before any Ollama call, with a bounded model response and timeout. The workbook and the model response are both treated as untrusted data.

### Supported limits

V6 inherits workbook limits (up to 5 worksheets, 100 rows and 16 columns, and 300-character V2 formulas); an individual AI proposal is capped at 200 characters. At most 60 sampled cells, at most 120 characters per sampled cell, at most 8 verified evidence citations and at most 8 insight results are returned.

No automated anomaly repair, bulk rewriting, formula conversion, unsupervised data cleaning, cloud-model fallback, background spreadsheet scraping, tax calculation, financial advice, bank integrations or invoice issuance is included.

## Acceptance

Python tests: python -m pytest -q tests/test_spreadsheet_ai.py tests/test_spreadsheet_formulas.py tests/test_spreadsheet_workspace.py

Browser acceptance: cd apps/desktop && npm run test:ui

Full GitHub Actions matrix: Windows/macOS/Linux Python 3.10 and 3.13, Office, UI, security, Docker, installers, Windows app and docs.

Regression tests cover model-free audit, explicit opt-in, local-only enforcement, source evidence verification, invalid/cyclic/external formulas, literal legacy imports, read-only approval, stale snapshot rejection, unsafe text clean-up, prompt-injection boundaries and browser flows. The browser cannot simulate real installed hardware or prove the quality of all downloaded Ollama models. Real local-model, performance, accessibility and interactive desktop acceptance remain outstanding until performed manually.

## Remaining roadmap

**V7**: Controlled and auditable document/spreadsheet/business workflows with explicit permissions and approval.

**V8**: Production hardening, cross-platform recovery and final security/accessibility/accuracy acceptance.

Microsoft Store publication is still deferred.
