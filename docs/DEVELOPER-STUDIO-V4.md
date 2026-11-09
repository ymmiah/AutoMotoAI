# Developer Studio V4 — Project Navigation & UX

**Milestone:** V4 of 64 · **Branch:** `feature/developer-studio-v4-project-navigation-ux` · [Development PR #57](https://github.com/ymmiah/AutoMotoAI/pull/57) · [Notion milestone](https://app.notion.com/p/4131cc3365d681568539cf6183fd42b2)

**Prerequisite:** V3 file-safety PR #56 is still under review and V4 is based on its development branch. Do not merge V4 into `main` until V3 is resolved. Automated tests are necessary, not a substitute for independent keyboard/screen-reader and installed-device acceptance.

## Implemented scope

### Multi-root explorer

- Displays up to eight current/approved/recent roots obtained from the authenticated V1 roots endpoint. Clicking a root opens it through the V1 approved-project API and retains its independent current trust status. Unsaved tabs trigger the existing V2/V3 confirmation before switching.
- Search the currently selected root, or explicitly search up to five displayed roots. Each root is separately validated by the server; results record the original root and project-relative path.
- Search never escalates a root's permissions or automatically trusts a project. Results from untrusted roots can be viewed but cannot be edited without separate trust.

### Search and replacement review

- `POST /api/developer/studio/search`: bounded literal content or filename lookup within an approved root. Limits: 160-character literal terms, 300 files, 8 MiB of examined source, 100 returned hits; paths from excluded directories, secrets, links, junctions, binaries and oversized sources do not enter results.
- Search reports line and column, a bounded preview, exact raw-file SHA-256 and truncation metadata. UTF-8, UTF-8 BOM and BOM-backed UTF-16 are decoded by the existing V2 logic. Windows-1252 must be handled by the dedicated editor instead of automatically guessing.
- `POST /api/developer/studio/replace-preview`: on a *trusted* project and a selected existing file, validate the original SHA-256, encoding, literal search term and output size. Return the proposed working copy, match count and bounded unified diff. There is **no disk write** and no bulk replacement. If source bytes changed externally, reject with HTTP 409.
- The operator must inspect and confirm **Load into editor**. This action applies proposed text as *unsaved* editor changes only when the tab still has the same SHA-256, encoding, line ending and trust. Committing is a separate V2 confirmed save with another disk checksum check.

### Keyboard, panels and accessibility

- Ctrl/Cmd+Shift+P opens an in-app command palette; filter commands and select with Enter/arrow keys, Escape to close. Commands are real local UI actions, not generated shell commands.
- The explorer/editor divider supports keyboard Left/Right (5% steps), Home/End and pointer resizing with a bounded 24%–60% explorer width. Small viewports expose Explorer/Editor switches and stack panels without horizontal overflow.
- Search results, roots and commands use native focusable controls and accessible labels; no untrusted result text is inserted as HTML. Respect reduced-motion preferences.

### Opt-in session recovery

- When explicitly enabled, this browser stores only the navigation schema version, last validated project path, selected folder, open tab names and active tab name. **Source contents, recovery snapshots, API tokens, environment values and application credentials are never written to localStorage.**
- The session does not restore automatically. **Resume session** asks first, reopens the project via V1's real authorisation and reloads files from disk. This never bypasses trust or silently restores changed or unsaved bytes.
- **Clear saved session** deletes the local navigation record. The V3 manual private recovery feature remains the supported mechanism for restoring unsaved text.
- On a shared computer, project paths and filenames may still be sensitive. Use the opt-in choice cautiously; this feature is disabled unless specifically requested by the operator.

## Verification

- `tests/test_developer_navigation.py`: local-only auth and hosted-mode exclusion; approved path and trust; literal/case-sensitive search, filename search, excluded secret/symlink/binary/large files, bounded results, immutable preview, stale checksums, mixed-line-ending and encoding rejection.
- `apps/desktop/test/ui-smoke.cjs`: real offline Monaco editing, project search, content replacement preview without disk mutation, explicit proposal load/save, palette shortcuts, keyboard panel resize, navigation-only storage and mobile explorer/editor switch.
- Full repository CI must pass Python 3.10/3.13 on Windows/macOS/Linux, browser/Office/security/Docker/VS Code/visual foundation, platform installers and Windows desktop workflow at the exact V4 head. V3's own integration and manual sign-off must be resolved before final verification.

## Limitations and recovery

- Not a full-indexing server or language intelligence engine: search is bounded and may truncate. No regular-expression search, recursive bulk replacement, workspace indexing, Git operations, AI edits or source execution in V4.
- Source preview can contain excerpts from regular code files, which may themselves include secrets despite sensitive filename filters; the feature is local-only and results should not be exported automatically.
- Exact replacement output can be large (up to V2's 128 KiB file limit); large result review and screen-reader behaviour require installed-device tests. Symlink and concurrent-process rename races remain within the documented V3 caveats.
- If a preview becomes stale, reopen the file and run the search again. Never silently use a new checksum for an old proposal. Recover unsaved edits using V3's manual private snapshots if those were explicitly enabled.
- If browser storage is disabled or cleared, navigation-only session recovery is unavailable; project files are unchanged.

**Release status:** Draft implementation, subject to cross-platform CI, independent security/accessibility acceptance and V3 integration. Microsoft Store publication remains deferred.
