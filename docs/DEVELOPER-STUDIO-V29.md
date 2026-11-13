# AutoMoto AI Developer Studio V29/64 — Scala, F# and Clojure

**Development-only.** V29 extends the V28 merged cumulative development branch. It does not change main, production deployment or stored user data. Approval and the existing central AutoMoto Agent remain separate.

## What is implemented

### Read-only, inert three-language inventory

The authenticated, local-only `GET /api/developer/studio/functional/inspect?project=...` endpoint records SHA-256 hashes of bounded Scala (`.scala`, `.sc`), F# (`.fs`, `.fsi`, `.fsx`) and Clojure/ClojureScript (`.clj`, `.cljc`, `.cljs`) sources.

It also reads, **without evaluating**, supported root and known fixed project manifests: Scala sbt and formatter metadata, Clojure `deps.edn`/`project.clj`/`bb.edn`, and F# project, NuGet and Paket metadata. Literal-looking dependencies and declarations are heuristic hints, **not** resolved package graphs, trusted dependency versions, a verified build or a formal language semantic parser.

Scan stops at 120 relevant entries, 192 KiB/source, 512 KiB/manifest and 8 MiB total. Incomplete scanning prevents execution. Symlinked known build-control files and linked source staging are refused. It reports fingerprints for installed Scala, scalac, sbt, scala-cli, .NET, fsharpc, Clojure/Clj, Leiningen, Babashka and clj-kondo, but **does not execute a tool or version query during discovery**.

### Fixed tool actions, not a general shell

The authenticated `POST /api/developer/studio/functional/run` requires a trusted local project, exact inventory/toolchain/executable SHA-256, new per-run `confirmed: true` and acknowledgement of unsandboxed code and network risk.

Allowed actions only:

| Action | Tool | Fixed command |
| --- | --- | --- |
| Installed version | scala, dotnet, clojure | `scala -version`, `dotnet --version`, `clojure -h` |
| Scala fixture | scala | `scala -nc test/Fixture.scala` (Scala 2 script mode; not general Scala 3 build support) |
| F# fixture | dotnet | `dotnet fsi --exec test/Fixture.fsx` |
| Clojure fixture | clojure | `clojure test/fixture_test.clj` (installed launchers differ) |

The fixture is staged from exact SHA-matched files in a private temporary folder. It must produce a documented `V29_*_PASS 42` marker and a successful exit status. A marker alone is not a proof of application correctness. No arbitrary paths, commands, shell flags, system package installers, `sbt` task evaluation, NuGet restore, `lein` execution, macros or CI agents are exposed to the caller. Sources are never intentionally overwritten by the Studio. This is **not** an OS sandbox: approved source code, interpreters and even some launcher/version commands may read files, access the network and create outside-folder side effects.

**Dependency resolution warning:** Some installed Clojure/Scala launchers can implicitly resolve or download runtime dependencies. The Studio does not invoke installers itself or guarantee network isolation. Run approved code only with audited installed runtimes and a controlled network environment. V29 does not certify the Scala 3/Scala CLI build path, F# type providers or ClojureScript compilation. Do not treat manifest discovery as equivalent to a complete supported language toolchain.

### User interface and central Agent

`Developer Studio → Scala, F# & Clojure · V29` shows file fingerprints, static declarations, risk flags, discovered executables, and consented fixture output with status announcement, keyboard-native controls and an explicit risk confirmation.

The **Central Agent release review** button fills the shared `deployment_readiness` bridge, but does **not** send, approve or execute the request. Existing Agent permissions, write/deployment restrictions and human review are unchanged.

## CI and acceptance

- `tests/test_developer_functional.py`: inert scan, source stability, manifest non-evaluation, symlink handling, hosted/auth refusal, changed inventory and executable refusal, no arbitrary arguments, trust, explicit consent, staging/source drift, and validated fixture marker.
- `tests/fixtures/v29-functional/`: reviewed independent Scala/F#/Clojure 6×7 fixtures and inert project manifests.
- `.github/workflows/developer-functional-v29.yml`: Windows/macOS/Ubuntu Python security tests and Ubuntu pinned installed-language acceptance with real Scala 2 script, F# Interactive and JVM Clojure commands on disposable CI runners only.
- `apps/desktop/test/ui-smoke.cjs`: live browser inventory, no execution/source mutation, and shared Agent review draft.

**Review required before merging into cumulative development:** exact-head three-OS tests, real Ubuntu installed interpreter acceptance, existing application/security/UI/desktop build regressions, accessibility checks and an independent review of unsandboxed execution, implicit dependency downloads and provenance. Do not merge into `main` or present as production-ready.

## Recovery

Commit/back up the trusted project before approving an external runner. Revert the V29 development branch or PR if tests fail; no schema migration, user data rewrite or automatic package installation is introduced by the Studio.

## Reference documentation

- [Scala CLI reference](https://scala-cli.virtuslab.org/docs/reference/cli-options/)
- [F# interactive](https://learn.microsoft.com/en-us/dotnet/fsharp/tools/fsharp-interactive/)
- [Clojure CLI](https://clojure.org/reference/clojure_cli)
