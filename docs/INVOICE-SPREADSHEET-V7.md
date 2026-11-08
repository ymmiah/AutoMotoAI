# AutoMoto AI — Invoice & Spreadsheet Intelligence V7

**Milestone 7 of the approved eight-version roadmap.** V7 is a permission-controlled, review-only workflow and evidence-linking system. It is not a payment engine, accounting journal, invoice issuance system or externally notarised audit service.

## Function

Open Invoices & Spreadsheets > Workflows & audit.

1. Load saved private workbooks, commercial quotation/invoice drafts and financial snapshots. Each source has a workspace path, type and current SHA-256 fingerprint.
2. Link two different record types for business review, evidence handoff or cash reconciliation review (requires one financial snapshot). Provide a meaningful note and confirm that nothing will be posted or changed.
3. The authenticated server checks both schemas, private paths and file hashes, then creates a pending review in a separate local SQLite database. All originals remain unchanged.
4. An authorised actor can approve, reject or cancel a pending review with a reason and explicit confirmation. Approval also rechecks both source digests and fails HTTP 409 if either source changed.
5. Inspect event history and independently request verification of its SHA-256 hash chain. Workflow status comes from appended events; there is no editable workflow status field.

## Roles and permissions

Local desktop owner may request, approve, reject or cancel in their own workspace. This is a SINGLE-PERSON approval, not independent two-person authorisation.

In hosted mode, authenticated user-role accounts may request and cancel their own reviews. Authenticated admin-role accounts may approve or reject within their own existing tenant workspace. Each hosted user has an isolated workspace, so this version does NOT offer a shared cross-user inbox or handoffs between different accounts. The UI reflects server-derived role capabilities, and the backend separately enforces each action. No client-supplied role, actor or security status is trusted.

Approval has **no business execution effect**: it never changes workbook cells or source files, sends invoices, accepts quotes, records payments, adjusts debts or posts cash/ledger transactions. The application does not trigger agent tools, external network calls or financial services.

## Security and storage

Allowed references are saved private records in artifacts/spreadsheets matching exact filename and schema rules: spreadsheet-v1 for .sheet.json, commercial-v4 for .commercial.json, and finance-v5 for .finance.json. Uploaded source files, symlinks, traversal, arbitrary absolute paths and mismatched schemas are rejected. Each source file is bounded to 850 KB.

Workflow metadata is stored in a separate tenant-scoped SQLite database in artifacts/workflows/workflow-events-v7.sqlite3. File/directory permissions are private on POSIX where supported. All queries are parameterised; write decisions run inside SQLite BEGIN IMMEDIATE transactions to serialise competing approvals. The bounded first implementation supports up to 500 reviews.

Each audit event stores action, authenticated actor, role, reason, time, previous event hash and its own canonical SHA-256 hash. Reading and writing verifies the entire existing chain and decision sequence. If in-place corruption is detected, operations are blocked with HTTP 409.

**Integrity limitation:** This is an unkeyed local hash chain, not immutable WORM storage or externally anchored notarisation. A privileged actor who can fully rewrite the database and recompute hashes, or delete the whole file, can evade verification. Source files can also be modified by a local privileged operator. No legally guaranteed tamper-proof evidence or independent signature is claimed.

The existing authentication, CSRF, request throttling, hosted allowlist and tenant containment remain in force. No send, issue, pay, bank-sync, finance-post, external email, bulk write, or event-edit endpoint exists.

## API

GET /api/spreadsheets/workflows/sources — private source list, type and digest.

GET /api/spreadsheets/workflows/list — latest reviews and server-side role capabilities.

GET /api/spreadsheets/workflows/detail — one review and complete timeline.

GET /api/spreadsheets/workflows/verify — audit chain integrity.

POST /api/spreadsheets/workflows/create — require exact source hashes, record pending review.

POST /api/spreadsheets/workflows/decide — approve/reject/cancel with role, stale hash and confirmed reason checks.

## Verification

Python: python -m pytest -q tests/test_business_workflows.py tests/test_spreadsheet_ai.py tests/test_financial_intelligence.py tests/test_commercial_documents.py

Browser: cd apps/desktop && npm run test:ui

Cross-platform CI must cover Linux/macOS/Windows Python 3.10 and 3.13, security, Office, Docker, VS Code, Visual Foundation, browser, installers, Windows app and docs. Regression tests cover valid permissions, source schema and SHA, stale/duplicate approval, audit-log tamper detection, private path safety and unchanged commercial/financial records.

Manual acceptance remains required for installed app, keyboard/screen-reader interactions, real file permissions, database backup/recovery, corrupted audit behaviour and hosted tenant boundaries. CI alone does not establish complete production or legal compliance.

## Continuity from V6

PR #38 merged V6 into the V5 feature branch after PR #37 merged V5 into main, so the V6 feature was not automatically incorporated into main. V7 explicitly carries forward its local AI backend, interface, tests, documentation and integrated routes, to be verified by the combined CI run.

## Remaining milestone

V8 — production hardening, backups/recovery, security, performance, cross-platform and accessibility acceptance, followed by a separately authorised release. Microsoft Store publication remains deferred.
