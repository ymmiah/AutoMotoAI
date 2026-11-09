# Developer Studio V6 — Secure Language Server Protocol Host

**Milestone:** Phase 2, V6 of 64 · [Notion milestone](https://app.notion.com/p/4131cc3365d681fca6d6e5556b040d3a)
**Dependency:** V5 PR #58 was merged into the V4 development branch; V4 PR #57 depends on V3 PR #56. This V6 branch is based on the updated V4 development head, not main.

## Implemented scope

- Local-only authenticated LSP host, bounded JSON-RPC 2.0 framing over server stdin/stdout, protocol reader thread, correlated request IDs, deterministic cancellation on request timeout, crash handling, explicit stop and idle expiry.
- Fixed, source-controlled server allowlist, never derived from repository files, for Python (pyright-langserver), TypeScript/JavaScript (typescript-language-server), Rust (rust-analyzer), Go (gopls), C/C++ (clangd). Each server is available only when its executable resolves outside the project and is executable. No automatic installation, execution or search-based shell invocation.
- Starting a server requires an approved local root, current explicit trust decision and a separate confirmation for that subprocess. Maximum two concurrent sessions; project identity and trust are rechecked for every subsequent operation.
- LSP initialize/initialized, didOpen/didChange with bounded UTF-8 in-memory document content, hover, completion, definition, references, rename preview and published diagnostics.
- Sanitation and limits on returned data. File locations must resolve within the same selected project; Markdown/code/diagnostic strings are rendered as inert text in the browser. Server-initiated requests, including workspace edits and arbitrary commands, are rejected. Rename is an inspection-only proposal, never auto-applied.
- Accessible responsive Developer Studio controls for server discovery, startup, stop, hover, completion, definitions, references, diagnostics and rename proposals. Supported output navigates to the relevant file and cursor; source saving remains exclusively handled by the established V2 safe editor.

## Explicit trust model and limitations

**Running any language server is execution of external software.** A trusted workspace and a fixed command list reduce risk but **are not an operating-system sandbox**. Language servers may read files, access the host, perform network operations, interpret project settings or load plugins according to their own behaviour. Only start servers you trust for projects you trust. The product makes no claim that running an installed language server cannot execute project-dependent code internally. Hosted mode remains denylisted and V6 never starts services automatically.

Resource protections: 512 KiB protocol message cap; 4 KiB header cap; 128 KiB source-document cap; two process sessions; five-minute idle expiry; eight-second per-request timeout; bounded diagnostics, completions, navigation and rename-preview results. These are application-layer bounds, not OS-enforced memory, CPU, network or filesystem limits. Windows subprocess trees may require OS-specific enforcement in later releases. Untrusted source file content is never directly supplied as a shell command.

A server being installed does not certify compatible versions, healthy operation, performance, feature completeness or language support. The LSP capabilities returned by a server are only advertised capabilities. Not all languages in the V5 registry have a usable server, and unavailable servers stay disabled. Rename results are previews, not Code Actions. V6 offers explicit on-demand editor controls rather than silently enabling automatic completion on every keystroke. Full broad language adapters, advanced grammar parsing, debug execution and host sandboxing remain separate future milestones or corrective work.

## API

- GET /api/developer/studio/lsp/servers?project=... — approved binaries and availability, no process launch.
- POST /api/developer/studio/lsp/start — trusted project, selected allowlisted language, confirmed=true; starts process, performs initialize and returns opaque session token and advertised capabilities.
- POST /api/developer/studio/lsp/document — opens/updates project-local bounded source text, synchronised with server only after user startup.
- POST /api/developer/studio/lsp/query — only hover, completion, definition, references, rename; requires project session ID, project-local path, position and optional text. Rename requires a validated identifier and responds as preview_only.
- POST /api/developer/studio/lsp/diagnostics — bounded inert diagnostic messages from publishDiagnostics.
- POST /api/developer/studio/lsp/stop — terminate the session and child process group where supported.

## Tests and quality gates

- tests/test_developer_lsp.py uses a real local Python subprocess implementing JSON-RPC framing, not a mocked response broker: initialise, didOpen diagnostics, hover/completion, project-only definition/references, bounded rename previews, explicit trust, hosted denial, symlink/traversal restrictions, session isolation, crashed and malicious oversized servers, timeout and cancellation.
- apps/desktop/test/ui-smoke.cjs checks real browser controls, consent, mocked protocol API interaction, inert display, start/stop and unchanged source bytes. Mocked browser API responses do not establish real server toolchain compatibility.
- Required exact-head GitHub CI: Python and security suites, browser smoke, Windows/macOS/Linux and desktop build. Installed-language-server acceptance with pinned real versions still required. Do not call V6 Verified until those checks and independent keyboard/screen-reader acceptance are complete.

## Recovery

Revert V6 commits or disable the V6 router and panel; existing V1–V5 editing, trust and project records remain intact. V6 has no database migrations or code-writing endpoint. Stop existing sessions before restarting the service. Recheck V3/V4/V5 dependency and security gates before retargeting to main; do not merge dependent drafts to main prematurely.
