# Developer Studio V1 — Trusted Workspace Foundation

**Development milestone 1 of 64. Read-only, local-only. No editor, build runner, debugger, AI patching, Git writes or publication.**

The [Notion master plan](https://app.notion.com/p/4131cc3365d68198acf2e795f20bb6cd) is the planning and status source. GitHub commits, tests and real-device checks determine which capabilities actually work.

## What is implemented

- Dedicated Developer Studio page and navigation, scoped responsive styling and source preview.
- Authenticated, local-only API under `/api/developer/studio`. Hosted deployments remain default-deny and the navigation item is hidden in hosted mode.
- Project choice is restricted to AutoMoto's private workspace or folders already authorised in **Settings → Files** / `AUTOMOTO_ALLOWED_ROOTS`. A typed arbitrary filesystem path does not provide access.
- Explicit project opening, recent-project list, trust and revoke-trust actions. Trust records include canonical directory path and filesystem identity, stored locally with owner-only permissions and atomic replacement.
- Bounded read-only directory listing and UTF-8 source previews (128 KiB). The UI displays text through `textContent`, not executable HTML. Each preview includes SHA-256 of the returned bytes.
- Excludes common secret files, credential directories, version-control internals, generated dependency directories and symbolic links. Rejects traversal, absolute paths outside the root, unapproved roots, junctions and ordinary file-type mismatches.
- Source file access never causes modifications; trust preference does not upgrade V1 into source editing or command execution.
- Python regression tests and a Playwright browser smoke for project opening, inert preview, untrusted file exclusions, explicit trust and source preservation.

## User workflow

1. Start AutoMoto locally with the normal authenticated launch link.
2. Open **Developer Studio** from the navigation.
3. Select the AutoMoto workspace or an approved location. To work on an external repository, add its containing directory to **Settings → Files** first.
4. Choose a project directory and select **Open project**. It starts as a restricted, read-only workspace.
5. Browse folders, inspect a UTF-8 text file and review its exact path and SHA-256 fingerprint. Large, binary or non-UTF-8 files are rejected without running anything.
6. Optionally select **Trust this project** and confirm the separate prompt. This records a preference for future development milestones only; V1 remains read-only. The same control can revoke trust.
7. Return to the selected project using recent projects.

## API (all local-only and authenticated)

| Method | Path | Effect |
| --- | --- | --- |
| GET | `/api/developer/studio/roots` | Authorised roots and valid recent projects; read-only |
| POST | `/api/developer/studio/open` | Verify allowed project, update local recent-project metadata |
| POST | `/api/developer/studio/trust` | Explicit confirm required; record or revoke trust |
| GET | `/api/developer/studio/tree?project=…&directory=…` | Safe bounded directory entries, no file content |
| GET | `/api/developer/studio/preview?project=…&path=…` | Inert UTF-8 preview and digest, never writes |

Project root and relative-path inputs are independently revalidated on every request. Browser-side navigation state never provides authority to read outside an allowed project.

## Security boundaries and limitations

- The existing sandbox's allowed-root and sensitive-path checks remain authoritative. Hosted mode cannot access V1 routes.
- V1 refuses symlinked/junction paths; it does not follow directory links, install dependencies, fetch repositories or run project hooks.
- The only local writes are private trust/recent metadata in AutoMoto's home. Project source files are never changed.
- No source content is sent to an AI provider, cloud service or external connector.
- Preview size is 128 KiB, UTF-8 only. Editor encoding support, broader source indexing, large-file handling and advanced project controls arrive in later milestones.
- Filesystem race hardening remains an explicit follow-up for any future mutating operations. V1 supplies no mutating project API; do not reuse its preview routine as a trusted write primitive.
- A trusted flag means a human explicitly selected that directory, **not** that its dependencies, build hooks, contents or instructions are safe to execute.

## Acceptance and tests

Run `python -m pytest -q tests/test_developer_studio.py` and the complete repository test suite. CI additionally executes the existing browser smoke with V1 navigation/preview/trust flows and regression tests for existing Research, Document, Visual and Spreadsheet Studios.

**Additional manual gates before declaring V1 verified:** approved external-root selection on real Windows/macOS/Linux installations; junction/symlink edge cases, network drives and renamed directories; screen-reader/keyboard focus, narrow-width layout, secure launch and recovery after invalid state, plus installed-app smoke. CI green alone is not a production release.

## Next

V2 adds full editing facilities, file-saving integrity and richer encoding support **only after** separate permissions and failure recovery are designed and verified. Store upload and production deployment remain deferred.
