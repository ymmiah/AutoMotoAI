# Developer Studio V2 — Safe Multi-Tab Source Editor

**Status:** Development, awaiting exact-head CI and manual acceptance. This is version 2 of the planned 64-version [AutoMoto Developer Studio roadmap](https://app.notion.com/p/4131cc3365d68198acf2e795f20bb6cd).

## Implemented

- Local-only authenticated source editor under the existing Developer Studio UI, with up to 10 in-memory source tabs, native Unicode textarea editing, Tab/Shift+Tab indentation, keyboard Ctrl/Cmd+S, line/column status, responsive layout and the application's built-in light/dark themes.
- Local syntax-highlighted preview uses the **already bundled** Highlight.js library and DOMPurify; the source always remains inert. No script or package is executed.
- UTF-8, UTF-8 BOM, UTF-16 little-endian and big-endian BOM detection, with explicit Windows-1252 option for legacy files. Invalid, binary and oversized source data fails closed.
- Native per-file line ending detection (LF, CRLF, CR, none, mixed); preserve selected line endings on save, and require an explicit choice if a file has mixed endings.
- Trust-based editing: untrusted project sources are browsable but read-only. Explicit user confirmation is required to trust a project and separately to save source. Revocation immediately disables editing and auto-save.
- Loss-resistant save: SHA-256 expected-content precondition; reject external changes with HTTP 409 and retain in-memory unsaved edits. Write into a uniquely named temporary file in the same directory, fsync, preserve permission bits and atomically replace. No unexpected source creation, execution, Git operations or cloud uploads.
- Optional **per-session** auto-save after user explicitly confirms; disabled by default, only for trusted source, with 1.8-second debounce and stale-write detection.
- Reload confirmation, dirty tab close confirmation, project-switch confirmation and in-app page-navigation guard when changes are unsaved.
- Test fixtures for Unicode, BOM, CRLF, source privacy, trust, binary/large files, conflict, revoked trust, no-op save, error recovery; Playwright tests for real UI source edits, tabs and conflicts.

## Supported file operations

| API | Function | Security |
| --- | --- | --- |
| GET /api/developer/studio/file | Inspect small source file; return Unicode text and exact raw-byte checksum | Local authentication, approved root, sensitive-file/symlink checks |
| POST /api/developer/studio/save-file | Replace an existing source file only after exact digest match | Local authentication, trusted exact project, explicit confirm, atomic replacement |

Source editing is deliberately not available on hosted tenants. The V1 explorer and Research/Document/Visual/Spreadsheet workflows are unchanged.

## How to use

1. Open AutoMoto locally, then Developer Studio.
2. Select/open a project inside the AutoMoto workspace or an explicitly approved root from Settings → Files.
3. Select a source file in Explorer. In untrusted mode it opens for review but is not editable.
4. Trust the project only if you recognise it and intend to modify its source. Trust **does not** authorise running its scripts or dependencies.
5. Edit one or more tabs. Use the highlighted preview to inspect syntax. For a legacy Windows-1252 file, choose that encoding in **Open as** and reopen the file.
6. Save via the dedicated button or Ctrl/Cmd+S. Confirm the save. The server refuses silently replacing files that changed after you opened them. Reopen and manually reconcile conflicting changes.
7. Optionally enable per-session auto-save with an additional explicit confirmation. Auto-save is off by default and stops after a conflict.

## Known limits (do not overstate capability)

**Monaco is not yet bundled.** The working editor uses the native accessible textarea plus a separate syntax-highlighted preview, not Monaco's editing/completion/navigation engine. The original V2 Notion specification requires Monaco: **keep V2 in Review, not Verified, until offline Monaco bundling and real-device tests are complete.** Language servers, compiler/build/test runners, DAP debugging and AI code edits are later milestones.

Only existing regular source files up to 128 KiB are editable. UTF-8/UTF-16 BOM and explicit Windows-1252 are covered; unmarked UTF-16 or other encodings are not. Mixed line endings require selecting one style before saving. Editing a file can change its last-modified time and inode; do not promise preservation of all ACLs or extended attributes. External filesystem tools that race a save at the exact replacement instant may still need further OS-specific hardening; the digest and inode preconditions are best-effort and not an OS-wide compare-and-swap primitive. Hosted or shared-workspace source editing remains disabled.

No background cloud sync, automatic Git commit, package installation, shell execution, AI review, publication or deployment.

## Quality gates before V2 verification

- Entire Python suite on Windows/macOS/Linux, Python 3.10/3.13.
- Real Playwright browser smoke and cross-studio UI regression.
- Security, VS Code, Docker, Office, install, docs and Windows desktop workflows.
- Manual UTF-8/UTF-16/legacy encoding, newline, symlink/junction, permission and checksum-collision probes across real Windows/macOS/Linux installations.
- Keyboard, screen-reader and narrow-screen accessibility checks.
- Offline Monaco editor bundle included in distributable Python/desktop assets and tested without a network.
- Confirm safe recovery after source changes by external processes, interrupted saves, full disks and read-only destinations.
- Review release licensing of all editor dependencies.

**Release:** No publication, Store submission, deployment or production-readiness claim without explicit approval.
