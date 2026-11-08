# AutoMoto AI V8.1 — Windows SQLite recovery reliability

## Why this patch is required

V8 pull request #41 was merged even though its last CI run failed both Windows Python versions. Linux and macOS, the Windows desktop build, security, browser, Office, installers and docs passed. The Windows Python 3.10/3.13 logs show a reproducible `PermissionError: [WinError 32]` while attempting to remove temporary `workflow.sqlite3` and `audit.sqlite3` files during the V8 recovery tests.

Python's `sqlite3.Connection` context manager **commits/rolls back a transaction; it does not close the database handle**. Windows prevents deletion of the still-open SQLite file. The resulting cleanup exception masks legitimate success or failure of the backup/verification procedure and can leave temporary files behind.

## Code changes

- Use `contextlib.closing` for both sides of the SQLite live-database-to-temporary-database backup. Open the live audit **read-only** using a properly encoded `Path.as_uri()` file URI and `mode=ro`.
- Use explicit `closing` for the independent read-only archive-verification connection. Complete the `PRAGMA quick_check` and V7 SHA-256 event/metadata audit before closing the handle and deleting its temporary directory.
- Use explicit `closing` for the release-readiness read-only integrity check. It must never retain a Windows file lock on the active workflow database.
- Add a regression exercising real source records, a V7 workflow, archive creation and verification, plus tracked temporary directories that must be deleted before the HTTP operation returns. The test applies on Linux, macOS and Windows.
- Repair the existing tampered-audit test fixture so its own SQLite connection is closed explicitly on Windows.

## Preservation and safety

No API route, document schema, financial calculation, permissions, audit-event format, encryption claim or restore semantics are changed. Recovery still creates new copies only. Existing files, workflow approvals, financial entries and Microsoft Store deployment remain untouched.

## Acceptance gates

```bash
python -m pytest -q tests/test_spreadsheet_release.py tests/test_business_workflows.py
python -m pytest -q
cd apps/desktop && npm run test:ui
```

A successful V8.1 merge requires the **Windows Python 3.10 and 3.13 jobs** to pass on this specific head SHA, as well as the existing cross-platform CI, Windows desktop and docs workflows. No manual native installer acceptance, real offline model test, accessibility audit or Microsoft Store publication is implied by this patch.

Do not merge on Linux-only green results. Final production and Microsoft Store release remain blocked by the documented V8 operator acceptance gates.
