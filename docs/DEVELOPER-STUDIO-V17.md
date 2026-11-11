# Developer Studio V17 / 64 — Python engineering and emerging toolchains

Development branch: feature/developer-studio-v17-python-emerging. V17 depends on V16 merged into the V12 aggregate development branch. It is not mainline, a store release, or a production deployment.

## Scope and implementation

- Authenticated, local-only project inspection of bounded pyproject.toml, requirements.txt, dependency groups, optional dependencies and lockfile fingerprints. TOML parsing uses tomllib with the existing Python 3.10 tomli fallback. Duplicate/invalid TOML and unsafe, linked or oversized manifests are rejected.
- Evidence-backed declared Python requirement, build backend and dependencies. Detect Django, Flask, FastAPI, Starlette, Litestar, Pydantic, SQLAlchemy and Pytest only from declarations; this is NOT proof packages are installed or work.
- Detect uv.lock, poetry.lock, pdm.lock and pip requirements. uv, ty and Ruff appear as separately fingerprinted installed tools where available; there is no automatic installation, download, uv sync, pip install, environment creation, build or lock update.
- Bounded Python source/test discovery that ignores private paths, virtual environments, links, hidden secret material and generated directories; per-source Python AST parsing with original source SHA-256 and no Python code execution.
- Existing V6 Pyright LSP remains the consented Python language server, with V17 optional explicit ty project checks and Ruff lint. ty and Ruff may execute project configuration and may perform writes; not sandboxed.
- Read-only .venv/pyvenv.cfg metadata; project tests require a separately created COPY-mode virtualenv interpreter (.venv/bin/python or .venv/Scripts/python.exe). Symlinked interpreters are deliberately refused. The copied interpreter and exact SHA-256 are checked immediately before a consented run. This is a local developer-execution boundary, not a security boundary.
- Fixed commands: Python/uv/ty/Ruff version, virtualenv Python -B -m pytest -q -p no:cacheprovider --disable-warnings, ty check --no-progress, Ruff check --no-cache .; no arbitrary shell, CLI flags or install commands accepted from the browser.
- Every real run requires exact local workspace trust, an unexpired current manifest fingerprint, a separately user-confirmed execution/writes risk warning and exact installed binary path/SHA-256. Output, time and concurrency are bounded; no unattended executions.
- Same universal V15 central AutoMoto Agent bridge. V17 only pre-fills the existing deployment-readiness form, with separate user confirmation and independent release approval; it never creates a new Studio agent, deploys or publishes.

## Limitations, threat model and residual risks

- Existing Python programs and Pytest, ty, Ruff and third-party tools can access user files/network and mutate project data at the user account level. There is no OS/container/network sandbox. Env sanitisation, SHA-256 and project trust are not sufficient protection against malicious project code, interpreter replacement races, dependency import attacks or misconfigured runners.
- Pytest depends on the user preparing an appropriate copied venv with its dependencies offline or through their own approved process. symlink-based standard POSIX environments are intentionally unavailable for execution; inspection still works. Python 3.10–3.13 CI does not prove all installed Python 3.14/3.15, uv, Ty, Ruff and framework stacks.
- AST parsing only validates grammar. It does not execute code, type-check, confirm framework behaviour or detect all vulnerabilities. Dependency versions are declared, not vulnerability-scanned or verified against registry releases. Lockfiles are checksum-inspected, not semantically resolved.
- Workflow does not create/edit projects, install dependencies, run a package build, or guarantee successful service start or runtime-debugger isolation. These parts of the V17 definition of done need separate real-project acceptance and additional hardened platform adapters.
- The run endpoint does not claim file immutability or block network at OS level; results explicitly say not verified.
- The existing shared Agent's V15/V16 deployment-readiness hand-off is *review-only*. Actual deployment admission enforcement for all outputs and distribution routes is a separate project gate.

## Verification

Test module: tests/test_developer_python.py. Inspect real TOML package declarations/uv evidence, AST syntax and source hashes, malformed lockfiles, symlinks, path traversal, unauthorised calls, changed manifest and tool identities, trust and per-run approvals, a real installed Python version process, and a copied .venv interpreter where available.

Pending final acceptance before calling V17 verified: exact-head GitHub Linux/macOS/Windows Python matrix, browser, security, Office, Docker, VS Code, installer, Windows app/docs builds; real Django/Flask/FastAPI, isolated venv Pytest, ty/ruff toolchains, accessibility and permissioned workflows; human review and release sign-off.

## Recovery / rollback

No automatic edits to user projects are performed by inspection. External tools MAY write to source; make a versioned backup before manually approving a run. Disable the V17 router and Studio panel by reverting the V17 development commits; retain V1–V16 files, trust records and central Agent. Never rewrite the user's project, remove .venv, or alter stored application data as part of rollback.

### Sources

- Python packaging metadata: https://packaging.python.org/en/latest/specifications/pyproject-toml/
- uv projects: https://docs.astral.sh/uv/concepts/projects/run/
- ty commands/type checking: https://docs.astral.sh/ty/reference/cli/
