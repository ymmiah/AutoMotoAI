# AutoMoto AI — Developer Studio V9: Academic LaTeX Authoring

**Milestone:** Phase 3, version 9 of 64 · [V9 Notion milestone](https://app.notion.com/p/4131cc3365d68101a6d0c783a0d95310)

**Development chain:** V8 PR #61 and V7 PR #60 have been merged into V6 development branch. This V9 branch depends on the current V6 branch head, not a release build. Any later integration to main must preserve reviewed prerequisite merge order and quality gates.

## Scope delivered

V9 supplies non-executing academic LaTeX authoring capabilities alongside the V2 guarded source editor:

- Multi-file thesis structure discovery, following local LaTeX input/include/subfile commands from a selected .tex root, with bounded reads of included .tex and BibTeX files.
- Static lexical cross-reference resolution across included files: labels, reference commands and common citation variants. Duplicate label and bibliography-key detection, unresolved references/citations, missing includes, invalid include paths and elementary unmatched environment diagnostics.
- Sections/chapters outline, clickable source locations, BibTeX key index and bounded command/environment/reference/citation completions.
- Optional unsaved active .tex editor content for immediate cross-file revalidation without writing a file or changing the existing source-save workflow.
- Original academic thesis and article template previews, including a multi-file thesis chapter and demonstrative BibTeX bibliography, plus equation/align/matrix/fraction snippets. These are copy-only and cannot overwrite project files.
- Optional texlab fixed-command support through the existing V6 **explicitly approved** Language Server Protocol lifecycle. Starting texlab requires an installed server, trusted project and a separate user confirmation. No LaTeX compiler is installed or run by static analysis.

The V2 text/Monaco editor remains authoritative for saving .tex/.bib changes, including checksum conflict protection and other V2/V3 safeguards. No V9 endpoint writes documents.

## Trust and security limits

**Static validation is not compilation.** V9 does not expand TeX macros, evaluate package semantics, inspect .aux compiler output or certify publication-ready citations. A label or citation resolved in a bounded scanned graph means its textual key has a matching local declaration, not that a TeX compiler would resolve it after a complete build. Bibliography examples are marked placeholders, never real academic citations.

Source traversal uses approved local-only project sandbox and file checks, rejects symlinks and junctions and excludes generated, private or credential paths. Parent-relative includes are supported only if their normalized destination remains inside the same approved root; disallowed outside references are reported, never read.

Bounded static scan limits: 64 .tex files, 12 include levels, 2 MiB of aggregate source, 96 KiB per source file, and 120 diagnostic messages. File/label/reference/section responses are capped, with a truncated flag for incomplete scans. Executables, TeX macros, shell escape and external resources are **never evaluated** by this static analyser. It does not upload project contents.

TeX language servers and compilers are separate processes. texlab may be used only through the existing separately consented V6 LSP host. An installed language server is **not an OS sandbox** and may access project files or run configured external tools. V9 does not automatically enable it or certify its diagnostics without installed-app testing.

## API

- POST /api/developer/studio/latex/analyse — project, main, active_path (optional), active_text (optional). Returns graph files, chapters, labels, cross-references, BibTeX keys, diagnostics, truncation and explicit non-compilation flags.
- POST /api/developer/studio/latex/complete — above plus prefix and kind (auto, command, environment, label, citation), capped to 60 suggestions.
- GET /api/developer/studio/latex/templates — original thesis/article preview manifest. No mutation.
- POST /api/developer/studio/latex/template-preview — preview all proposed source files for a selected original template without writing them.

Endpoints are authenticated and local-only through V1 project security. They are not added to the hosted-mode allowlist and never execute code or write into a project.

## Tests and acceptance

tests/test_developer_latex.py uses real nested .tex and .bib files. It tests: multi-file labels and citations; revalidation after unsaved and saved changes; missing/duplicate references; escaped comments, verbatim and inline verb; bounded traversal; safe internal parent references; exclusion of external, linked and generated sources; UTF-16 cursor positions; command/environment/bibliography completion; preview-only academic templates; auth/hosted denial; and confirmation that merely analysing never launches texlab.

apps/desktop/test/ui-smoke.cjs exercises the actual API and browser UI for multi-file analysis, valid and invalid cross-references, BibTeX suggestions, maths snippets and three-file thesis templates, while checking unchanged source bytes.

Before marking **Verified**, require exact-head GitHub CI on Python 3.10/3.13 Windows/macOS/Linux, browser/security/Office/VS Code/Docker checks, Windows desktop and docs; independent real installed texlab diagnostics; verified multi-file thesis compilation by a separately authorised installed TeX distribution; manual keyboard/screen-reader accessibility and source-file race/path review. Automated static cross-reference tests alone do not meet the milestone's full verified-TeX requirement.

## Recovery

All V9 endpoints are read-only and have no database migrations, project-file writes or persistent index. Remove V9 router/UI integration to return to V8 behaviour; no project source needs migration. Template previews remain in memory. Stop any manually started texlab process through the existing V6 server controls. No merge into main, store publication or production deployment is performed as part of this development PR.
