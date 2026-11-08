# AutoMoto AI — Invoice & Spreadsheet Intelligence V8

**Final implementation milestone (8 of 8), subject to acceptance.** V8 adds offline backup/recovery and transparent release-readiness checks, building on the existing V1–V7 spreadsheet, invoice, financial and workflow features. Completing a version milestone does **not** automatically make the product production-certified, legally compliant or ready for Microsoft Store publication.

## Recoverability and resilience

Open Invoices & Spreadsheets > Recovery & readiness. The release centre is private and authenticated.

1. Create a bounded ZIP archive of **existing saved records only**: V1 saved spreadsheet JSON, V1 basic invoice JSON, V4 commercial document and contact JSON, V5 financial ledger JSON. A consistent SQLite backup of the V7 approval/audit history is included when that database exists.
2. Receive the new private ZIP path and its SHA-256 digest. Download the archive through the existing authenticated file-download mechanism and protect it in an independently managed off-device destination.
3. Verify the selected archive. Server checks its SHA-256 against the expected stored digest, ZIP member names/count, uncompressed size, duplicate paths, per-entry SHA-256 and size, exact manifest format, saved record schema and calculation validation, and audit database integrity/hash chain.
4. Type **RESTORE COPIES**, tick the independent-copy declaration, confirm the action and perform a recovery drill. The server validates again and writes **new** private saved records using random identifiers and exclusive file creation; no saved source records are replaced or deleted.
5. If a workflow audit backup exists, it is written to an **isolated evidence file under artifacts/recovery**. The live approval database and its review states are not silently overwritten or activated. Existing invoice issuance/payment and financial posting remain entirely unaffected.

### Scope and limits

- Backup includes a maximum of **150 supported saved records**, up to **900 KB each** and bounded combined size, plus an optional workflow database up to **6 MB**. Archive compressed size is limited to **15 MB**; decompressed members are capped before reading. Archive processing is locally performed with Python standard library only.
- The manifest includes record filename, expected schema, byte length, SHA-256, creation time, and optional workflow-audit metadata. Backups are stored privately under artifacts/recovery, named with random 24-hex identifiers.
- Record schemas are validated through the same Pydantic models and core arithmetic checks used by the existing spreadsheet, commercial, invoice and financial modules. Invalid records block backup/recovery, rather than being silently accepted.
- No arbitrary paths or uploaded ZIP files can be restored via these APIs. Only server-created backup names in the current authenticated tenant's private recovery directory are supported. Unsafe ZIP member paths, duplicate names, symlinks, size overruns and manifest discrepancies are refused.
- Recovery uses exclusive new-file creation, never overwrite. If a write fails, the operation attempts to remove all newly created files while leaving originals intact; machine crash recovery still needs manual inspection for partial copies.
- No automatic backup schedule, cloud sync, storage provider, data migration, destructive import, finance reconciliation, trusted timestamp, PDF notarisation or background recovery exists in this release.
- **Backups are not encrypted.** ZIP archives may contain customer details and financial data. Store off-device copies securely with OS-level encryption/access controls, and do not share the ZIP or its contents publicly.
- SHA-256 confirms content against a previously trusted digest. The manifest/ZIP is **not digitally signed** and cannot protect against a privileged attacker able to replace both the archive and the expected digest. The V7 audit chain is also not independently notarised.
- Exports must be separately kept off the original device; a backup stored only on the same disk is insufficient for hardware failure or ransomware recovery.

### Identity, permissions and privacy

All routes use existing AutoMoto request authentication, CSRF/origin protection, hosted routing allowlist and request throttling. In hosted mode, operations are limited to the caller's own tenant workspace and do not cross account boundaries.

The release centre never sends model prompts, financial documents, passwords, emails or archive contents to cloud services. It cannot post payments, issue invoices, alter source books, promote archived review decisions into the live workflow database, change roles or publish software.

### Authenticated V8 endpoints

- GET /api/spreadsheets/release/readiness — read-only status of local workspace, audit and outstanding manual gates. Returns release_ready=false, store_publication_authorised=false.
- GET /api/spreadsheets/release/list — private archive names, sizes and digests.
- POST /api/spreadsheets/release/create — create a ZIP from valid saved records and a coherent V7 workflow history (if present).
- POST /api/spreadsheets/release/verify — check a selected private ZIP and provided SHA-256; no mutations.
- POST /api/spreadsheets/release/restore — require exact approval phrase and new-copy acknowledgement, reverify, then create independent copies.

No API authorises Microsoft Store release, bank connections, sending invoices, activating old decisions, or data deletion.

## Release acceptance gates

The release-status page is **fail-closed**: it reports incomplete checks and does not claim release readiness merely because the software builds.

| Gate | Required evidence |
|---|---|
| Cross-platform automated tests | Python 3.10/3.13 on Windows, Linux and macOS; real browser UI; Office; Docker; installer; VS Code; documentation |
| Backup drill | Create, verify, download, restore and independently reopen data; check original hashes and live workflow log |
| Incident recovery | Document how to recover on another device and what to do when source files, manifests or audit logs are corrupt |
| Security review | Threat-model and manually verify authentication, CSRF, tenant isolation, symlink/ZIP traversal, archive confidentiality, model-data injection and dependencies |
| Accessibility | Human screen-reader and keyboard inspection, 200% zoom, mobile layouts, colour contrast and focus order |
| Local AI | Install an approved Ollama model, verify loopback-only behaviour, consent, performance and no cloud fallback |
| Financial correctness | Recalculate money rounding and sample invoice/CSV/PDF output with representative real-world examples; manually check tax responsibilities |
| Publication | Written project-owner approval, code signing, installer/update testing, privacy disclosures, support and Microsoft submission checks |

CI does not independently test all manual gates, and the app does **not** pretend these have passed.

## Testing

Python: python -m pytest -q tests/test_spreadsheet_release.py tests/test_business_workflows.py tests/test_spreadsheet_ai.py tests/test_financial_intelligence.py tests/test_commercial_documents.py tests/test_spreadsheet_workspace.py

Full browser: cd apps/desktop && npm run test:ui

The browser tests use a real local server to create a private backup from actual saved quotation, spreadsheet and financial data; download the generated ZIP, verify its digest, refuse unacknowledged restore, recover new copies and confirm existing source documents and audit events remain unchanged. Python tests cover corruption, ZIP path traversal and bomb limits, duplicate names, changed archive digest, invalid business record schema, tampered audit history, symlinks and workspace isolation.

### Remaining work before a public release

V8 implements release assurance tooling, **not a signed final release**. The manual gates above and any defects uncovered by the full test matrix must be resolved before a production version can be called stable. Completion of the 8-version roadmap is independent of Microsoft Store publication, which remains deferred until explicitly requested.

## Recovery operator runbook

1. From the original working AutoMoto installation, select Recovery & readiness and create/verify an archive.
2. Download it and preserve its SHA-256 in a separate trusted record. Protect the ZIP with encrypted offline/off-device storage.
3. For a recovery rehearsal within the same AutoMoto workspace, select the archive, verify, and choose non-destructive restore. Confirm the new saved records appear, open representative files and verify their content.
4. For a different-machine disaster recovery, copy the securely stored archive to a trusted location and provision a clean, separately configured AutoMoto workspace; **V8 does not yet expose arbitrary ZIP upload or automatic cross-device import**. Assisted manual migration must be reviewed and separately validated.
5. If the V7 live review database is damaged, preserve the original and archived evidence before taking action. V8 does not silently promote archived approval events. Rebuild any review-state history only through a separately approved, documented restoration procedure.
6. When any verification fails, do not attempt to override checks by editing ZIP contents or hashes. Preserve evidence, investigate and use a verified earlier backup.
