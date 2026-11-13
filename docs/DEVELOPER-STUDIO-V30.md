# Developer Studio V30/64 — Elixir, Erlang and Gleam

**Development-only milestone.** Built on the V29 cumulative development branch after the exact V29 head passed all 15 GitHub workflows. This is an added BEAM-language integration, not a new release of main or a claim of production-grade language-server coverage.

## Delivered

### Inert source and manifest intelligence

Authenticated local route: GET /api/developer/studio/beam/inspect?project=...

- Bounded inventory of .ex, .exs, .erl, .hrl, .escript and .gleam files, with SHA-256 source provenance, heuristic symbol outlines and risk flags.
- Bounded *reading only* of Mix manifest/lockfile, Rebar config/lockfile, Erlang Makefile, Gleam TOML, formatter and other known metadata. Mix/Rebar configuration is executable code: **it must never be evaluated during discovery**.
- Literal-looking dependency coordinate hints are NOT installed/resolved dependency versions. Mix macros, code generation, Erlang behaviours, compiler plugins and Gleam imports are not proved correct by a regex scan.
- Installed elixir, elixirc, mix, erl, erlc, escript, rebar3, gleam and ElixirLS are reported as exact executable SHA-256 fingerprints without any source execution or version command. Windows shell-wrapper executables are blocked by the local tool gate.
- Known symlinked build control files or canonical executable fixtures are expressly rejected even if the index walker omits them. Maximum 130 relevant files, 192 KiB/source, 512 KiB/manifest, 8 MiB total; incomplete scans deny execution.

### Per-operation approved runtime tools

Authenticated local route: POST /api/developer/studio/beam/run

Project trust, exactly pinned input inventory, toolchain fingerprint, executable path and executable checksum, **fresh confirmed approval**, and an explicit unsandboxed file/network risk acknowledgement are mandatory.

| Task | Installed tool | Fixed command |
| --- | --- | --- |
| Tool version | elixir / erl / gleam | elixir --version / erl -version / gleam --version |
| Elixir fixture | elixir | elixir test/v30_fixture.exs |
| Erlang fixture | escript | escript test/v30_fixture.escript |
| Gleam fixture | gleam | gleam run --target erlang --no-print-progress |

Each fixed task operates only on the exact staged, hashed source data in a private temporary folder with bounded CLI runtime/output. V30 uses a **single reviewed, dependency-free Gleam package named v30_fixture**; arbitrary Gleam package names, dependencies, additional Gleam code and user-supplied CLI arguments are not admitted to this runner. Completion requires an actual zero exit code and the expected V30_*_PASS 42 output marker. This verifies a small real interpreter/compiler example, **not all Elixir, Erlang, or Gleam programs**.

No task installs packages, modifies the original project on purpose, publishes to Hex, deploys code or initiates a separate autonomous Agent action. The UI cannot approve host execution on behalf of a user.

### Critical execution boundary

**The temporary copy is not an OS, network or filesystem sandbox.** Interpreter processes are launched with the local user's privileges. Elixir, Erlang and Gleam code (and associated compilers) can read environment secrets, access network endpoints and modify paths outside the temporary project. Even a dependency-free Gleam project could trigger external runtime activity. The Studio does not verify absence of network traffic, isolate processes via containers, or certify supply-chain safety. Approve only independently audited trusted source, and use externally controlled network/firewall permissions if isolation is required.

Source, manifest and toolchain fingerprints are change-detection controls and do not remove time-of-check/time-of-use risk, interpreter compromise, or startup-hook risk. Real tool version output is returned only after approval and an external command completes.

### Central Agent and desktop UI

The V30 panel is mounted in Developer Studio using the existing styles, accessible status regions and keyboard-native selects and buttons. Source fingerprint/provenance, potential risk indicators, approved commands and result output are visible. Its Central Agent button only **drafts** a shared deployment_readiness review in the existing unified AutoMoto Agent. No additional automated permissions or deployment privileges are introduced.

### Real CI acceptance and recovery

- tests/fixtures/v30-beam contains genuine Elixir, Erlang escript and Gleam Erlang-target mathematical fixtures.
- tests/test_developer_beam.py covers read-only discovery, source and manifest drift, malicious manifest inertness, symlink rejection, local auth and hosted denial, checksum-pinned trust and consent, no arbitrary commands, Gleam dependency-free enforcement, successful and unsuccessful marker validation, and real installed interpreter API execution when explicitly enabled on disposable CI.
- .github/workflows/developer-beam-v30.yml runs inert Python tests on Windows/macOS/Ubuntu, and real Elixir, Erlang and Gleam compiler/runner fixture and API acceptance on an Ubuntu disposable runner. Runner toolchain installation happens **only in GitHub Actions**, never on customer devices.
- apps/desktop/test/ui-smoke.cjs checks the actual browser displays V30 source and manifests without executing a deliberately malicious Mix script, preserving source bytes and central Agent draft-only behaviour.
- Full earlier Developer Studio V18–V29, application security, UI/desktop and Windows packaging workflows must pass at the **same head SHA**.

Keep the PR in **Review** until the exact-head CI matrix is green, browser/desktop accessibility is reviewed, an independent security and dependency/network assessment is complete, and human approval is granted. Do not merge into main, publish binaries or call this a full BEAM IDE.

Recovery: restore developer source via version control if an independently authorised external tool causes host-side changes; revert V30 development commits without mutating main, accounts or existing projects.

### Official references

- [Elixir scripts and Mix](https://hexdocs.pm/mix/Mix.html)
- [Erlang escript](https://www.erlang.org/doc/apps/erts/escript_cmd.html)
- [Gleam CLI reference](https://gleam.run/documentation/command-line-reference/)
- [setup-beam GitHub Actions](https://github.com/erlef/setup-beam)
