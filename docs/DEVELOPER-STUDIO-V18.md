# Developer Studio V18/64 — Go Engineering

Status: development draft only, based on V17 merged into the existing development branch. Never claim a release to main or production.

## Implemented

- Authenticated local-only Go project inspection of in-root go.mod, go.work, go.sum and go.work.sum, nested module declarations, workspaces and SHA-256 fingerprints. All reads are size-bounded and reject linked/restricted source paths.
- Package/function candidates, test-file inventory, HTTP/gRPC import hints and service fingerprints. These are lexical findings, not semantic Go compilation or a full security audit.
- Existing V6 Go LSP/gopls provides separately consented navigation and language-server diagnostics; V18 exposes a shortcut to that same panel rather than launching an additional server.
- Actual user-approved installed Go/gopls versions, Go build, Go test, Go vet and CPU profiling of one discovered test package. No arbitrary command lines, package installation, shell execution or automatic deployment.
- Go workspace commands run with an exact snapshot of source and manifest checksums, pinned local executable SHA-256, explicit workspace trust and one fresh approval per action. Commands are fixed, timeout/output bounded and restricted to in-root project patterns.
- Go environment forces GOTOOLCHAIN=local, GOENV=off, GOPROXY=off, GOSUMDB=off, GOVCS=off, CGO_ENABLED=0, and explicit GOWORK in the approved root or off. This prevents ordinary Go command downloads but is NOT a network or OS sandbox.
- CPU profile is collected in a private temporary directory; only a bounded local pprof text summary and fingerprint are returned. Raw profile bytes are automatically deleted, not retained or uploaded.
- Shared central AutoMoto Agent integration: review-only deployment-readiness form, separate user confirmation, no second Studio agent and no release or deployment.

## Quality gates

- New cross-platform real-Go workflow exercises Go 1.27.4 and Python 3.13 on Linux, Windows and macOS.
- Tests cover two local Go modules with an HTTP service, real build/test/vet, Go workspace escape/replacements, source and manifest changes, token/trust/consent checks, profile deletion and hosted-mode denial.
- Browser smoke test exercises source inspection, inert output, central Agent hand-off and absence of implicit source edits.
- Existing Python 3.10/3.13, UI, security, Office, Docker, VS Code, Windows desktop and docs checks remain required.
- Real full-stack acceptance, screen-reader and keyboard review, Go toolchain compatibility checks and a separate human release sign-off remain outstanding until verified.

## Security, limitations and rollback

Project Go tests and external tools execute as the local user's OS account and can modify files, read secrets or access the network. Hash pins, offline Go module settings, trust and consent are not OS isolation. Go workspace replace directives and references outside the approved root block execution. Large or partially discovered projects fail closed instead of claiming full coverage.

Lexical symbol/service hints are not equivalent to gopls semantic analysis; the existing gopls LSP remains independently authorised. The ephemeral build output is not a deployable release. A profiling summary is advisory and never certifies production performance.

Inspection does not edit the project. Before consenting to unsandboxed Go test/build/profile, manually back up or commit the project; those processes may write files. To roll back, revert V18 changes on the development branch, leaving V1–V17 and central Agent state unchanged. Actual deployment requires independent safety admission, rollback and explicit release approval across all distribution routes.

## Official references

- Go modules and workspaces: https://go.dev/ref/mod
- Go diagnostics and profiling: https://go.dev/doc/diagnostics
- gopls diagnostics: https://go.dev/gopls/features/diagnostics
- Go releases: https://go.dev/doc/devel/release
