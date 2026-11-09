# AutoMoto AI — Developer Studio V8: Toolchain & Debugger Adapter SDK

**Milestone:** Phase 2, V8/64 · [Notion](https://app.notion.com/p/4131cc3365d6816e8e2af04bebc01f4f)  
**Dependency:** V7 PR #60 merged into the V6 development branch. V6 PR #59, V4 PR #57 and V3 PR #56 remain upstream development dependencies. V8 is based on V6, not main.

## Delivered features

The V8 SDK is an **authenticated, local-only, declarative external adapter registry** for six categories: compiler, test, formatter, linter, package manager and debugger. It allows registering an adapter for an already installed tool without changing the application core. It does **not** download or install external executables.

Each adapter pins an absolute executable path and its SHA-256; the binary is rehashed at each launch. Each registration belongs to an explicitly trusted project filesystem identity and uses up to 12 fixed literal arguments. Descriptors persist in the private AutoMoto data directory at developer-studio/external-adapters.json, outside project source. Persistence is atomic and limited to 24 descriptors/64 KiB; corruption fails closed.

Registration cannot execute or modify project source. Running a registered command always requires an additional, explicit acknowledgement that the external executable may modify files, execute project scripts and access the network. Execution uses a direct argument array with no shell; a timeout and bounded output protect the host from accidental runaway runs but do not provide an operating-system sandbox.

### Adapter manifest contract

| Property | Description |
| --- | --- |
| id | Unique lowercase adapter ID scoped to a trusted project |
| label | Human-readable tool name |
| language | Existing V5 language registry identifier |
| category | compiler, test, formatter, linter, package or debugger |
| protocol | process for ordinary roles; dap for debugger |
| executable | Absolute installed executable path, outside approved source roots |
| args | Fixed string arguments, maximum 12, not templated |
| expected_sha256 | Operator-approved current executable SHA-256 |
| confirmed | Explicit true during registration |

Example: a Python test adapter can register an independently installed Python executable with the fixed arguments Python -m pytest --version. The executable SHA-256 must be obtained from the inspect endpoint, and the external pytest module must already be installed. Registering that manifest does not run it.

## V8 API

- GET /api/developer/studio/adapters/catalog?project=... — describe roles and project-bound registrations without executing anything.
- POST /api/developer/studio/adapters/inspect — trusted project and absolute executable; calculate SHA-256 without running the tool.
- POST /api/developer/studio/adapters/register — add validated descriptor with verified expected SHA-256, explicit consent; no installation or execution.
- POST /api/developer/studio/adapters/unregister — delete adapter metadata with consent; binary remains installed.
- POST /api/developer/studio/adapters/run — execute pinned process with project trust, explicit per-run approval, process timeout, bounded output and direct argv.
- POST /api/developer/studio/adapters/dap/initialize — perform a strictly bounded DAP capability handshake for a registered debugger with per-run approval; no debuggee launch.

## Debug Adapter Protocol implementation

The DAP adapter SDK sends one framed initialize request (sequence 1), reads at most 16 bounded frames and validates the matching response type, request_seq, command and success field. Returned capability data is restricted to an allowlist of Boolean flags. The adapter is terminated immediately after the handshake. V8 **does not send launch, attach, configurationDone, breakpoints or debugger execution commands**.

Protocol reference: [Microsoft Debug Adapter Protocol — Overview](https://microsoft.github.io/debug-adapter-protocol/overview).

V8 therefore implements an external debugger adapter **interface and initialization**, not interactive debugging, breakpoint handling, variable inspection or a debuggee runtime. Those remain distinct future milestones.

## Trust and security

**External compilers, formatters, package managers, test runners and debuggers are real third-party processes.** Hash pinning confirms approved bytes, not safety, reputation, integrity of dependencies or compatibility. Executed tools retain their OS-user access and may read/write files, spawn children, run project scripts, contact remote networks or leak credentials accessible to that OS user. V8 is **not** an OS sandbox.

Controls include local-only session authorisation, exact root identity and trust checks, absolute-system-executable requirement, no approved source-root executable loading, fixed argv without shell interpolation, per-run write-risk approval, reduced inherited environment (no API key/token variables or PYTHONPATH), 7-second tool timeout, 64-KiB output cap, 6-second DAP timeout, 64-KiB protocol-frame cap, concurrency limiting, and best-effort process-group termination on Unix.

Not implemented: OS syscall/network/filesystem confinement, Windows Job Object process-tree control, CPU/RAM quotas, notarisation/signing trust, remote package/tool install, full DAP debugging or automated source rollback. **Source files changed by a permitted external process are not automatically reversible.** Run only independently trusted tools in deliberately trusted projects.

## Tests and acceptance

- tests/test_developer_adapters.py: actual Python subprocess executions, SHA-256 registration and execution rechecks, local/hosted boundary, trust revocation, identity isolation, environment stripping, fixed-argument validation, timeouts, output flooding, registry corruption handling, six adapter roles and real synthetic DAP subprocess framing/invalid/timeout scenarios.
- apps/desktop/test/ui-smoke.cjs: live interface controls, metadata-only registration, separate execution confirmation, inert rendering of malicious output and debugger handshake-only UI.
- Existing V1–V7 Python and browser regression tests must remain green across Windows, macOS and Linux. A green simulated DAP fixture does **not** prove compatibility with any real third-party debugger.

Manual acceptance still required: exact-head CI/Windows build, actual installed compiler/linter and DAP adapter test with recorded versions, editor keyboard/screen-reader interaction, external tool security review and V3–V7 integration gates.

## Recovery

Unregister the descriptor, which leaves the externally installed executable untouched. Disabling the V8 API router and Studio panel removes execution functionality without modifying existing V1–V7 project records. Registry data is held outside source roots. Restarting the engine does not execute registered commands or auto-run any tool. No automatic publication, merge to main or production deployment is part of V8.
