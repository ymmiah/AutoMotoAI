# Developer Studio V19/64 — Rust Engineering

Status: dependent development pull request. V19 extends V18 on the aggregate development branch, not production/main.

## Implemented

- Local authenticated, read-only Cargo.toml/Cargo.lock and workspace member inspection. Explicit in-root multi-crate memberships, SHA-256 manifests and source inventories; bounded no-follow reads and denial of linked paths, unsupported globbed members, duplicate entries and unsafe file paths.
- Real rustc/Cargo/rust-analyzer executable discovery with SHA-256 pins; separate read-only evidence of lldb-dap/codelldb native debugger availability. Existing consent-bound V6 rust-analyzer LSP and V8 DAP registration/handshake remain authoritative; V19 does not create another LSP or launch/attach a debugger.
- Basic lexical source/function/type outlines, rustfmt and Clippy workflows and compiler output path validation. Lexical symbol detection is not a Rust AST or a substitute for rust-analyzer semantic diagnostics.
- Fixed, explicit local tasks: cargo --version, rustc --version, rust-analyzer --version, cargo check --workspace --all-targets --frozen --message-format=short, cargo build --workspace --frozen, cargo test --workspace --frozen, cargo clippy --workspace --all-targets --frozen -- -D warnings, and cargo fmt --all -- --check.
- Runs require local-only authentication, trusted approved project, fresh consent to unsandboxed execution, exact manifest/source fingerprints and pinned installed executable, repeated checks just before launch and bounded process time/output. One Rust run at a time; no CLI injection, shell or arbitrary user-provided flags.
- Isolated temporary CARGO_TARGET_DIR and CARGO_HOME, CARGO_NET_OFFLINE=true and RUSTUP_AUTO_INSTALL=0 to refuse ordinary Cargo network fetches and toolchain auto-installation. Temporary builds are cleaned after runs; no build release artefact or automatic package installation. Project code and build tools remain **not OS/network sandboxed** and can modify project files or access the network.
- Refuses tool execution on missing Cargo.lock, workspace member mismatch, custom out-of-root target paths, Cargo patch/replace directives, build scripts, project .cargo/config.toml, rust-toolchain.toml or partial source discovery. These restrictions are intentionally conservative; extra acceptance is needed for mature projects that use them.
- The Rust panel uses the same product-wide central AutoMoto Agent deployment-readiness *review* form. It never grants Agent deployment authority or creates a second Studio agent.

## Acceptance and tests

- tests/test_developer_rust.py exercises two real Rust crates (library and CLI), an internal path dependency, source fingerprints, bounded symbol discovery, manifest failures, symlink/traversal protection, Cargo config/build-script restrictions, trust/consent/binary/manifest changes, real rustc/Cargo check/build/test/Clippy/rustfmt, compiler errors and path sanitisation.
- Dedicated .github/workflows/developer-rust-v19.yml runs installed Rust stable with Clippy/rustfmt and Python 3.13 on Linux, macOS and Windows.
- Browser desktop smoke test checks Rust project evidence, inert inspection and shared central Agent linkage; existing whole-app tests/Windows packaging/docs remain required.
- Do not call V19 Verified until *exact-head* CI has passed and manual native debug, real rust-analyzer, accessibility, supply-chain, full project execution and independent security sign-off are demonstrated.

## Risk and recovery

Cargo/build scripts and Rust tests execute with the local user account's privileges, without OS/container/network sandboxing. Offline Cargo environment variables **do not stop user code** from accessing the internet or writing to source files; compile-time macros and build scripts may have access to user credentials and unprotected filesystem paths. Binary SHA-256 verifies bytes at one point, not trustworthiness or integrity after execution. Source files are not certified unchanged.

Inspection is non-mutating. Before approving a compiler/test run, create a versioned project backup. If a tool modifies the project, restore it through its own VCS/backup. Removing the V19 router, UI and tests by reverting V19 development commits leaves V1–V18 and central Agent intact. No production deployment or main-branch merge is implied.

## Official references

- Cargo workspace: https://doc.rust-lang.org/cargo/reference/workspaces.html
- Cargo locked/offline/frozen options: https://doc.rust-lang.org/cargo/commands/cargo-build.html
- Rust compiler error index: https://doc.rust-lang.org/error_codes/error-index.html
- rust-analyzer: https://rust-analyzer.github.io/
