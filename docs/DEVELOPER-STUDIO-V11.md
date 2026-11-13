# AutoMoto AI — Developer Studio V11: TeX Build & PDF Preview

**Milestone:** Phase 3, V11/64 · [V11 Notion milestone](https://app.notion.com/p/4131cc3365d681ed8456ce2462e2ac9d).

**Dependencies:** V10 merged to the V6 Developer Studio development branch. V11 is based on that development branch, **not main**. No production deployment, store upload or publication occurs in this PR.

## Delivered scope

V11 adds a consent-controlled local TeX compiler lifecycle, ephemeral PDF preview, compiler diagnostics and bounded SyncTeX source-to-PDF page navigation. It integrates with V9 LaTeX editing and V10 bibliography preflight without touching existing project files during normal application copying/preview operations.

### Compilation lifecycle

1. Open a local approved project and mark its exact filesystem identity **trusted**.
2. Select an existing main .tex file and click **Inspect tools**. Detect separately installed Tectonic or latexmk; hash the resolved binary bytes without running anything. No compiler or package is installed automatically.
3. Select a tool and **Approve & build PDF**. A separate visible consent dialogue explains that TeX is an external executable, **not an OS sandbox**. The request includes the approved executable path and SHA-256, both rechecked immediately before execution.
4. Build from a short-lived temporary snapshot of V9-inspected .tex files, referenced .bib files and directly referenced PNG/JPEG/PDF figures (all scoped to an approved local project). A bounded snapshot rejects incomplete/unreadable includes, restricted paths, symlinks, unexpected figures, oversized files and common shell escape constructs.
5. Invoke a fixed command with **no user/project arguments, no shell interpolation and explicit no-shell-escape**. Tectonic also receives --untrusted, --only-cached and the TECTONIC_UNTRUSTED_MODE environment variable. latexmk receives -norc and a fixed pdflatex template with -no-shell-escape. Temporary HOME, XDG_CONFIG_HOME, TEXMFHOME and output directory reduce accidental project/user configuration effects.
6. Capture bounded output and derive basic compiler diagnostics, including file/line errors and common warnings. A successful output must be a bounded ordinary PDF file with PDF header and EOF marker. Invalid PDFs are rejected. Sources stay in their original folders; temporary build files are deleted after execution.
7. Keep the PDF bytes and available SyncTeX pins **only in memory** for a short time. The preview is returned through a separately authenticated POST request and displayed using a local Blob URL. The UI can open it in a separate viewer or save a copy when explicitly requested.

**No source files are rewritten by the AutoMoto build manager.** However, the approved TeX engine still runs with the current OS-user permissions and could directly read, write or send other host files through engine bugs, supported TeX features or subprocesses. V11 does not prove that all host files remain unchanged. Compile only trusted, reviewed source and dependencies.

### Fixed compiler options

Supported modes are the **V1 Tectonic CLI** with its documented --untrusted, --only-cached, --synctex and --outdir flags, and **latexmk + pdflatex** with -norc, -pdf, -synctex=1 and a fixed -no-shell-escape child invocation. Tool versions are not yet certified. Installed tools that do not accept these options will return diagnostics rather than attempting a different or unsafe execution mode.

- [Tectonic V1 command reference](https://tectonic-typesetting.github.io/book/latest/ref/v1cli.html)
- [Tectonic untrusted/only-cached compile flags](https://tectonic-typesetting.github.io/book/latest/v2cli/compile.html)
- [LaTeX Workshop explanation of latexmk shell-escape and config risks](https://github.com/James-Yu/LaTeX-Workshop/wiki/FAQ)

The engine still may access the local filesystem or network: a command-line no-shell-escape flag is **not OS isolation**. V11 disables automatic Tectonic resource downloads using --only-cached; it does not guarantee that all possible latexmk child programs cannot access the network. The tool's external binary is not signed or attested.

### Compilation and preview limits

- One external TeX build at a time. Maximum runtime 15 seconds; 64 KiB compiler output, 100 parsed diagnostics.
- At most 96 source/figure files and 24 referenced figures, 10 MiB total input, 96 KiB per text source and 2 MiB per figure.
- PDF must have a valid PDF header and EOF marker, must be no larger than 4 MiB, and is not accepted from a symlink.
- Up to three PDF results, memory-only, expiring after 10 minutes or on engine restart. They are keyed by non-guessable build tokens and the approved project filesystem identity; preview retrieval rechecks workspace trust.
- SyncTeX: only regular bounded compressed/uncompressed artifacts, at most 2 MiB compressed / 8 MiB expanded / 5,000 decoded pins. Paths outside the temporary approved snapshot are excluded. Parsed source mappings are never blindly passed through to disk.
- Sample outputs and editor navigation are only as accurate as compiler-generated SyncTeX; no automatic PDF OCR, PDF text extraction or external preview service is used.

### SyncTeX navigation

A compiler-produced SyncTeX record ties a source file and line to a PDF page. V11 offers **source line → nearest page** navigation and **PDF page → approximate source** lookup. The latter chooses a pinned source line on that page; it is **not precise click-to-source navigation** or verified coordinate-level mapping. The UI updates a PDF viewer fragment to the page and opens the original project source in the V2 editor. If SyncTeX output is missing or unreadable, navigation controls remain disabled.

- [SyncTeX background and format](https://www.overleaf.com/learn/latex/MLTeX_EncTeX_and_SyncTeX_TeX_extensions)
- [SyncTeX stream description](https://github.com/go-synctex/docs/blob/main/docs/format.md)

### Figures and tables

V11 performs source-level discovery of supported includegraphics references and table environment occurrences. Referenced binary figures must be project-local PNG/JPEG/PDF files with recognizable header bytes and within size limits. Project-specific graphicspath, macro-expanded asset names, EPS and external image converters are **not implemented**; unsupported or unavailable figures are blocked, never silently fetched. Table locations are static source observations, not full table rendering or accessibility certification. Compiler-generated PDF output is responsible for actual layout.

## API surface

- GET /api/developer/studio/texbuild/engines?project=... — available installed binary paths and SHA-256, **no execution**.
- POST /api/developer/studio/texbuild/build — project, main, engine, expected executable path, expected SHA-256, confirmed=true, acknowledge_external_process_risk=true; optional active_path/active_text for unsaved buffer. Runs a fixed local compiler on a snapshot, reports result, logs/diagnostics and a private build ID after success.
- POST /api/developer/studio/texbuild/preview — project, build_id; returns ephemeral PDF bytes encoded as base64 after independent auth/trust/project-ID and TTL checks.
- POST /api/developer/studio/texbuild/sync/source-to-pdf — project, build_id, path, line; bounded source → page mapping when SyncTeX is present.
- POST /api/developer/studio/texbuild/sync/page-to-source — project, build_id, page; approximate page → source pin, not an exact click position.

The hosted API allowlist is not changed: these endpoints are unavailable in hosted mode. UI action confirmation is accompanied by server-side literal confirmation fields. Merely loading Developer Studio, opening a project or reading the compiler catalog **cannot launch TeX**.

## Tests and release gates

- tests/test_developer_texbuild.py tests real Python-based synthetic compiler subprocess execution, two engine policy modes, fixed argv and no-shell-escape flags, compiler SHA pinning, trust and auth, ephemeral snapshot figure/table handling, unsaved editor text, output size/time limits and cleanup, invalid PDF rejection, bounded SyncTeX parsing/navigation, cross-project preview isolation, preview TTL/revocation and unsafe resource rejection.
- apps/desktop/test/ui-smoke.cjs tests the real web interface with mocked compiler/API transport: inspect without execution; cancelled build runs nothing; approved build runs exactly once; invalid HTML in compiler diagnostics renders inert; preview loads only on request; source/page navigation and no upload of project data.
- Existing V1–V10 regression suite must continue to pass on Python 3.10/3.13 Linux/macOS/Windows, browser UI/security, Office/Docker/VS Code, installers, desktop packaging and docs.
- **Manual acceptance remains mandatory:** actual installed Tectonic and latexmk version compatibility; reproducible multi-file TeX compilation, bibliography cross-reference passes, SyncTeX page navigation accuracy, PDF rendering visual inspection; TeX command/path escaping and file/network security review; accessibility and keyboard testing.

**Not claimed:** universal secure/sandboxed compilation, package availability without network, byte-identical PDFs across machines, reproducible TeX Live environments, fully verified SyncTeX coordinate navigation, comprehensive macro-safe figures, production-ready PDF preview on every browser, or full academic publication verification.

## Recovery and rollback

Remove the V11 router and Studio UI mount, restart the engine; existing V1–V10 source files and trust settings remain intact. Temporary snapshots are automatically deleted when the build returns; PDF caches are memory only and disappear on restart. Manual copy/download of a PDF is separate from project file modification. No repo migrations, cloud assets, hidden background build agents or auto-deploy are involved.
