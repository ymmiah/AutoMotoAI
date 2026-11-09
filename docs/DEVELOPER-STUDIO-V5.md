# Developer Studio V5 — Language Registry & Intelligent Detection

**Milestone:** Phase 2 · V5 of 64 · [Notion milestone](https://app.notion.com/p/4131cc3365d681c49a1cf40a8df7fc4c)
**Dependency:** [V4 draft PR #57](https://github.com/ymmiah/AutoMotoAI/pull/57) based on [V3 draft PR #56](https://github.com/ymmiah/AutoMotoAI/pull/56). V5 is a dependent development change, not a production release.

## Implemented features

- Authenticated, local-only language registry returns versioned, structured language IDs, filename, extension and shebang patterns, Monaco mappings, optional tool names, detection capabilities and unverified Windows/macOS/Linux compatibility.
- File and project detection reports primary and selected language, candidates, deterministic confidence, and concrete evidence. Conflicting extension/shebang evidence remains **ambiguous**. Unsupported file types remain **unknown**. C/C++ header extensions and .m files remain deliberately ambiguous.
- Framework recognition uses bounded local evidence: dependencies in package.json for Next.js/React/Vue/Angular/Svelte/Nuxt, composer.json for Laravel/Symfony, Python manifests for Django/Flask, Maven/Gradle for Spring Boot, project files for .NET/WordPress, pubspec.yaml for Flutter, Gemfile for Rails.
- Opt-in host toolchain probing checks whether a named executable is available on PATH. No compiler, script, language server or version command is executed; no packages are installed. Reports not_checked, available (located but unverified) and unavailable.
- Language intelligence panel displays project language, framework, current file, confidence, evidence and tool statuses. Monaco syntax mode can be overridden per file during the current Studio session without changing source bytes.

## Security boundaries

- Existing V1 workspace approval, local authentication and path restrictions apply. Hosted-mode default-deny rules remain unchanged.
- Restricted folders, secret file names, linked files and junctions are excluded from scanning. Source is read through bounded opens with final-file no-follow checks.
- File scans inspect at most 300 files, descend at most two subdirectory levels, and cap individual source/manifest reads at 128 KiB. Truncation is reported.
- Never run source code, installer hooks, npm scripts, package managers, version commands, LSP binaries, downloaders or arbitrary external programs during V5 detection.
- No network calls, file writes, trust escalation, secret persistence, model action privileges or AI-driven modifications.
- Treat manifest strings and project names as untrusted data. Neither a language detection nor a tool on PATH establishes verified build/test/debug support.

## HTTP API

- GET /api/developer/studio/language/registry — schema_version, language definitions and explicit detection-only support claims.
- POST /api/developer/studio/language/detect — accepts project, optional path and probe_tools boolean; reports language, candidates, evidence, frameworks, toolchain statuses, scan_truncated, read_only and source_executed.

## Verification

- tests/test_developer_languages.py: registry integrity, initial language fixtures, Unicode names, ambiguous extensions and shebangs, actual framework markers, malformed manifests, missing toolchains, opt-in executable lookup, bounded scanning, symlinks, traversal, local authorisation, hosted denial and no implicit source writes.
- apps/desktop/test/ui-smoke.cjs: Monaco mode switching, evidence panel, manifest-backed framework detection, explicit tool checks and unchanged source bytes.
- Run relevant Python, browser, Tauri/desktop packaging, security and Windows/macOS/Linux CI on the **exact** V5 PR head. Existing V1–V4 tests must remain green.

**Manual acceptance outstanding:** installed application verification, independent keyboard/screen-reader tests, genuine toolchain compatibility checks and review of security boundaries. A passing CI run is not alone a production release or a Verified milestone.

## Known limitations

Detection is conservative and uses manifest/file markers, not semantic parsing or LSP. The dominant language is selected by frequency from a bounded scan; the selected file takes priority. Monorepos and deeply nested framework markers can be missed and require later V7 indexing. Runtime presence is not version or functional compatibility validation. Some Monaco modes may use plain-text fallback when the grammar is not bundled. No compiler, debugger, LSP host or code-modifying AI agent is included in V5.

## Recovery and dependencies

V6 introduces LSP hosting, V7 introduces parsing/indexing, and V8 implements the toolchain/debugger adapter SDK. Revert the V5 changes to restore V4 functionality; no migration, V5 database or source rewrite is required. Keep V5 targeted at the V4 development branch until V3 and V4 quality gates are resolved. Do not merge draft dependent versions directly into main.
