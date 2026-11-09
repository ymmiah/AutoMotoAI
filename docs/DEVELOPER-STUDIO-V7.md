# Developer Studio V7 — Parsing & Source Indexing

**Milestone:** Phase 2 · V7/64 · [Notion milestone](https://app.notion.com/p/4131cc3365d681eaa410f9a3b34cde3c)
**Dependency:** V6 draft PR #59 (this V7 branch is based on V6 head), V5 PR #58 merged only into V4 development branch, V4 PR #57 and V3 PR #56 remain unmerged. V7 is not a production release.

## Implementation

- Local-only, authenticated project source index using approved V1 roots and sandbox paths. The index is held only in server process memory (LRU capped at three workspaces), with no database, project .index file or cloud request.
- Deterministic, read-only breadth-first discovery excludes existing V1 secret paths, links/junctions, generated/build/dependency folders, known credential filenames and binary/private suffixes. Caps: 250 files, 160 directories, 320 entries per directory, 8 subdirectory levels, 6 MiB of read source per scan and 96 KiB per file. The per-workspace cache additionally caps retained parsed records at 5,000 symbols and 20,000 lexical tokens; reaching either limit marks results as incomplete. Incomplete scans are clearly labelled truncated.
- SHA-256-based incremental parsing cache. Refresh always rehashes bounded source bytes and reuses parsed entries when unchanged, reparses changed files and removes deleted files; generation numbers and parse/reuse/removal counters are returned. Existing project edits are never written by the index.
- Python standard-library `ast` definitions with nested qualified scopes, syntax-error reporting and `tokenize` name occurrences without counting Python comments or strings.
- Explicit **heuristic** symbol extraction for JavaScript, TypeScript, Rust, Go, Java, Kotlin, Swift, PHP, C#, C/C++, Ruby, Bash, CSS and Markdown. These results are not presented as Tree-sitter, AST or verified semantic references.
- HTML/JS/CSS embedded-language boundaries: local HTML script/style region discovery (up to 16) and approximate child symbols, excluding JSON-LD/application JSON scripts from JavaScript symbol parsing.
- Qualified symbol search, read-only lexical occurrences, editor unsaved-buffer outline and source location navigation. The unsaved outline is not added to the disk-backed index unless the editor explicitly saves the file through the existing checksum-protected V2 edit workflow.
- UI: responsive, keyboard-accessible Source intelligence panel with Refresh index, Current file outline, symbol query, navigable results and Find occurrences.

## HTTP API

POST /api/developer/studio/index/refresh — approved project and bounded rehash/parse, returns generation, counts, truncation and no-write flags.

POST /api/developer/studio/index/symbols — project + optional filename/query, returns up to 100 symbols, scope, parser name, location and confidence.

POST /api/developer/studio/index/references — project + identifier and optional filename, returns at most 100 **lexical** token occurrences, NOT verified cross-module reference resolution.

POST /api/developer/studio/index/outline — project and existing project-relative source path, plus optional bounded unsaved editor text. Parses directly without persistence and returns symbols/embedded regions.

All four endpoints use the existing local-only session authorisation, are excluded from hosted-mode allowlists, reject unsafe roots and paths, and never execute code, shell commands, project scripts, language servers or network requests.

## Security and limitations

- Recognition is intentionally conservative. Only Python uses a full syntax AST; other languages have approximate declaration extraction and may miss advanced constructs, generics, nested scopes and multi-line declarations. A reliable multi-language Tree-sitter grammar distribution is **not bundled by V7**. Do not claim complete Tree-sitter or semantic indexing support.
- References are lexical token matches; they may include unrelated identifiers and do not resolve imports, semantic scopes, symbol aliases or cross-language references. The future V37–V39 roadmap addresses wider cross-language graph and refactoring.
- Embedded HTML script/style parsing is bounded and heuristic; it never evaluates scripts or fetches linked files.
- No persistent filesystem index, no hidden source upload, no project writes and no automatic network calls.
- Incremental means **re-use of cached parsed entries after full bounded hash verification**. The tool does not claim event-driven background file watching or unbounded whole-monorepo coverage.
- Files that are oversized, non-UTF-8, binary, linked, excluded or inaccessible are skipped. Truncation signals incomplete results. Sensitive data in source files not matching the exclusion rules may still be read in memory; choose approved projects accordingly.
- Existing build/run and source-editing permissions are unchanged. LSP is still separate and requires explicit approval.

## Testing and acceptance

- `tests/test_developer_index.py`: Python AST scopes and Unicode, non-semantic heuristic labels, embedded HTML JS/CSS, syntax errors, lexical occurrences, unsaved-buffer isolation, SHA-256 reuse/reparse, edit and deletion invalidation, restricted folders/secrets and symlinks, local-only authentication, hosted denial, bounded scans and no source writes.
- `apps/desktop/test/ui-smoke.cjs`: real HTTP index refresh, search, lexical occurrences, current-file outline, tracked source additions/changes/deletions, index UI and untouched source bytes.
- Existing V1–V6 tests and Windows/macOS/Linux CI remain mandatory. Real large-repository behaviour, cross-platform installed-app keyboard/screen-reader acceptance and independent security review must be recorded before milestone verification.

## Recovery

V7 stores index state only in memory. Restarting the AutoMoto engine drops cached symbols without affecting source files or V1–V6 configuration. Revert the V7-only route, module and UI integration to return to V6. Maintain dependent PR merge order: V3 → V4/V5 → V6 → V7, with review and acceptance at each stage.

**Notion status:** Building/Review until exact-head regression evidence and manual acceptance; not Verified merely because source was pushed.
