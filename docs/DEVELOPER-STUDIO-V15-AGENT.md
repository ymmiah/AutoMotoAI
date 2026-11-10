# AutoMoto AI — Developer Studio V15: SQL, Data, GraphQL & Central Agent Integration

**Milestone:** Phase 4, V15 of 64: https://app.notion.com/p/4131cc3365d681d480eaef9944de042d

**Branch:** feature/developer-studio-v15-sql-agent-bridge, based on V14 merged into the V12 development stack. It is not a mainline release or production deployment.

## V15 SQLite, PostgreSQL/MySQL and GraphQL

Developer Studio V15 introduces read-only local SQLite inspection, bounded SELECT/CTE execution in a temporary copy, rollback-only migration previews, static SQL dialect hints and a bounded GraphQL source reviewer.

### SQLite snapshot safety

- Select a regular database under a V1-approved project root, with extension .db/.sqlite/.sqlite3, a SQLite 3 magic header, and a maximum 8 MiB source size.
- Read from a no-follow descriptor and copy only the checked source bytes into a private disposable folder. The original database path is never passed to SQLite.
- Refuse active WAL/SHM sidecars rather than presenting a potentially stale view of a live database.
- Discover bounded tables, views, indexes and schema definition hashes.
- Run SELECT or WITH read-only queries against the throwaway copy using SQLite query_only, a deny-by-default authorizer with a bounded safe-function list, parameter binding, 3-second/100k-progress-step resource controls, maximum 100 rows and 64 KiB output.
- Refuse attempts to write, use unsafe functions, attach other databases or run multiple statements.
- A separately confirmed migration-preview API accepts one CREATE TABLE/INDEX, ALTER TABLE ADD COLUMN or DROP INDEX. It executes only on the disposable copy, collects before/after schema, rolls back and asserts schema is restored. It does not apply changes to source databases.
- A source checksum and external backups remain essential: file-level SQLite snapshots are deliberately unavailable while a WAL sidecar exists. The SQLite parser itself is complex; these safeguards are not an OS sandbox or a guarantee of immunity from malicious SQLite files.

### Static GraphQL and SQL dialects

- Scan project-local GraphQL SDL for bounded types/interfaces/inputs/enums and field declarations. Basic read-query inspection compares approximate root-field names against declared Query root fields, rejects mutation/subscription, and enforces brace/depth limits.
- A GraphQL reviewed operation is **not semantically compiled or executed**. Fragments, directives, complex aliases and multiple operations need later full-AST support.
- PostgreSQL/MySQL/SQLite .sql files receive bounded static dialect hints. There are **no live PostgreSQL/MySQL connections or schema/credential access**; do not claim cross-dialect runtime compatibility.

## New permanent product-wide design rule: all Studios linked to one central Agent

All five top-level Studio pages display the same central Agent bridge:

- Document Assistant
- Research Studio
- Invoice & Spreadsheet Intelligence, including its financial/commercial/invoice workflows
- Visual Studio
- Developer Studio, including earlier V1–V14 features and V15

The shared app shell mounts studio-agent-bridge.js at these five pages. It performs an authenticated GET /api/agent/studios/catalog handshake before claiming a connection. No agent run is started on opening or switching Studios.

Only after an explicit user confirmation does POST /api/agent/studios/handoff create a saved central Agent conversation and its own source-labelled task ID. Its actions are Review, Plan and Deployment readiness, each **review-only**. The central Agent engine is reused; no new Studio-specific model or unreviewed external service is introduced. Tool approval requests are auto-denied for these Studio-initiated review tasks. Deployments, application installation, source mutations, publications and communications need separate user-approved actions; the bridge never performs them directly.

A trusted local Developer project may be attached only after V1 project identity/trust checks. Other Studios cannot supply arbitrary workspace paths. No file contents or credentials are automatically sent. Hosted access requires signed-in tenant authentication and existing hosted quotas/isolated tools; hosted sessions cannot attach local project roots. The resulting task and conversation can be inspected through the existing Agent UI.

This is an integration rule for future Studio builds and deployment reviews **after merge and distribution**. It does not retroactively alter previously released versions or claim old Studio exports were agent-approved. Earlier manual export functions are preserved.

### Routes

Agent:
- GET /api/agent/studios/catalog
- POST /api/agent/studios/handoff

Local Developer V15:
- POST /api/developer/studio/sql/inspect
- POST /api/developer/studio/sql/query
- POST /api/developer/studio/sql/migration-preview
- POST /api/developer/studio/data/inspect
- POST /api/developer/studio/data/graphql-review

All Developer data routes are hosted-default-denied. Agent hand-offs remain review-only and require explicit confirmation.

## Tests, limitations and manual acceptance

Automated tests use a real project-local SQLite file, parameterised SELECT and schema read, write/DDL/function injection rejection, rollback verification, WAL/symlink/path restrictions, GraphQL mutation rejection, static dialect hints, and mocked central Agent tasks verifying the five-Studio registry, required authorisation and approval gates. Browser smoke tests exercise the panels and the shared Agent link.

Manual gates remain: actual complex schema migration/dialect testing, review of malformed SQLite files, GraphQL full grammar/parser support, central Agent approvals and task lifecycle under real accounts, responsive/keyboard/screen-reader assessments, Windows/macOS/Linux CI, desktop and docs packaging, security and independent release sign-off.

No automatic migration, deployment, production changes, external database connection, Microsoft Store upload or mainline merge.

Rollback: unregister V15 and Agent bridge routers and remove shared Studio panel mount and allowlist entries. No existing project database or earlier Studio document needs migration. Separately approved Agent conversations remain subject to ordinary conversation retention controls.
