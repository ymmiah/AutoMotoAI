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

**Offline Monaco completion branch:** A pinned Monaco Editor 0.57.0 ESM bundle, CSS, worker scripts and font are now vendored under `automoto/web/static/vendor/monaco/` (with SHA-256 manifest, source lockfile, MIT licence and legal notices). Desktop/laptop sessions load the editor from the authenticated local server; no runtime CDN or external model is required. Each tab has a distinct Monaco model, while V2's existing authorised save, conflict checks and explicit approval remain the only write route. Textarea fallback remains available for narrow/touch or unsupported environments. **Keep V2 in Review until exact-head CI and real-device/accessibility checks pass.** Language servers, compiler/build/test runners, DAP debugging and AI code edits remain later milestones.

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

## Offline Monaco reproducibility and integrity

**Development source:** `tools/developer-monaco/package.json` pins Monaco `0.57.0`, patched DOMPurify `3.4.17` and esbuild `0.28.2` with a committed npm integrity lockfile. **Security note:** Monaco 0.57.0 distributes an embedded vulnerable DOMPurify 3.4.15 shim; `build.mjs` replaces that precise ESM shim with an import of the audited 3.4.17 npm package **before bundling**. Simply overriding the npm dependency would be insufficient. The manifest records the sanitizer pin and `npm audit` is a blocking CI check. Prefer an official patched Monaco release when one is available and verified. `tools/developer-monaco/build.mjs` bundles the ESM editor, TypeScript/JavaScript, CSS, HTML, JSON and core workers locally, and records per-file SHA-256 hashes in `manifest.json`. All runtime assets—including codicon fonts, stylesheets, workers, licence and notices—ship inside the Python package via `pyproject.toml` package-data rules.

To rebuild as a developer with internet access to the npm registry:

```sh
cd tools/developer-monaco
npm ci --no-audit --no-fund
npm run build
cd ../..
python -m pytest -q tests/test_developer_monaco_assets.py
```

The vendored files must be committed and verified before publishing any distribution; **end-user installation and startup do not download Monaco**. `.gitattributes` marks the vendored Monaco directory as byte-preserving (`-text`), preventing Windows CRLF checkout conversion of JS/CSS/worker assets and protecting SHA-256 manifest verification on every supported platform. Review `npm audit` for both the desktop and Monaco build dependencies before any public release. Build output is relatively large because TypeScript language services and workers are included; review installed size and lazy-load behaviour on supported devices.

**Regression requirements:** Playwright must demonstrate an actual `.monaco-editor` mounted from the same origin, edit a trusted file through Monaco, preserve unsaved state and detect external-disk conflicts; a fake textarea/highlight-only substitute is not acceptable. Test dark/light theme changes, responsive fallback, Unicode/LaTeX input, per-tab state, keyboard save, and secure source handling.

**Outstanding quality gates:** accessible installed Windows/macOS/Linux usage, offline startup with network disabled, worker/CSP compatibility, clipboard/IME, screen-reader fallback, large-file performance and packaging checks. A merged PR or a passing headless test alone is not production certification.
