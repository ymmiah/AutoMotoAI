# Developer Studio V20/64 — C and C++ Engineering

Status: development only. Builds on V19 merged into the aggregate development branch; not main and not a production release.

## Shipped in this development milestone

- Authenticated, local-only project inspection of CMakeLists.txt (including nested CMake manifests), CMake presets, .clangd and bounded C/C++ source/header files. Uses the established approved-root path policy, rejects linked root configuration and avoids executing any source during inspection.
- Bounded SHA-256 source and CMake manifest snapshots, lexical functions and includes, C/C++ language detection. Lexical symbols are not a C/C++ AST and cannot substitute for Clang diagnostics.
- Root compile_commands.json can be parsed without running its commands; all executable command strings, arguments, user paths and flags are omitted from output. Rejects malformed, oversized, out-of-root or linked compilation database paths.
- Detects SHA-pinned installed CMake, CTest, GCC, Clang, MSVC cl and clangd. Existing V6 clangd language server and V8 native DAP debugger adapters are reused, with separate user approval; V20 never launches a debugger or silently attaches to a process.
- Fixed real task options: CMake/CTest/clangd/compiler version checks; temporary CMake configure+build; configure+build+CTest; and POSIX Clang/GCC AddressSanitizer/UndefinedBehaviorSanitizer build and CTest. All tasks require an explicitly trusted local project, *fresh* user consent, an exact tool SHA-256 and an unchanged manifest/source and toolset snapshot.
- Builds use a private temporary CMake output path, CMAKE_EXPORT_COMPILE_COMMANDS=ON, Debug builds, bounded process time and combined output; no persistent binary, package installation or automatic release action. Compilation and test commands can execute third-party code with OS-user privileges; this is NOT a sandbox. CMake may fetch dependencies itself if configured. Source immutability is not certified.
- Recognises GCC/Clang-style compiler errors with independently validated project-relative paths. Reports short bounded sanitiser evidence lines without interpreting them as proof of complete vulnerability detection. Sanitiser detection is proven by executing an intentional heap memory defect on Linux in dedicated CI.
- Same central AutoMoto Agent bridge used by all Studios: the V20 panel only prepares a deployment-readiness review, never automatically executes, publishes, deploys, changes Agent permissions or creates a second Agent.

## Tests / acceptance requirements

- tests/test_developer_native.py: real C and C++ compiler/CTest project, real CMake build, source-inert inspection, relative compiler error paths, SHA protection, compile command redaction, symlink and workspace trust checks and deliberate Linux AddressSanitizer memory corruption.
- .github/workflows/developer-native-v20.yml: Python 3.13 plus native CMake and compiler test matrix on Ubuntu/macOS/Windows; Windows MSVC developer environment.
- apps/desktop/test/ui-smoke.cjs: CMake/source/UI scanning, redaction and same shared Agent hand-off without project changes.
- All existing core Python 3.10/3.13, Office, security, UI, Docker, VS Code, Windows desktop, docs and prior Go/Rust acceptance suites remain required. Human-run real clangd/DAP debugging, accessibility checks and security review remain open until evidence proves acceptance.

## Safeguards and limitations

- The build/test/sanitiser workflow is opt-in but **not isolated**. CMakeLists can call arbitrary processes, write files and access the network during configuration; tests can do the same. SHA fingerprint checks detect some stale changes, not malicious code or time-of-check/time-of-use races. Do not execute untrusted repositories outside an appropriately isolated OS/container and independent approval.
- Compiler, linker and dynamic library behaviour varies with the installed toolchain. POSIX-only Clang/GCC ASan/UBSan is offered where available. Windows MSVC sanitiser workflows and native debugger stepping are not certified by this milestone. Debugging still requires explicit use of V8 DAP controls.
- Internal static scan does not validate ABI compatibility, include graphs, compilation database commands, linker flags, runtime or debugger correctness. Source files may be changed by external tooling even when build artifacts are cleaned.
- Offline dependency fetching is not guaranteed by CMake (unlike V19 Cargo); network access is not blocked at the OS level. This must be explicitly disclosed to all operators.
- Some larger projects and complex CMake presets need extra acceptance; no arbitrary CLI flags or opaque user-controlled commands are passed into the backend.

## Rollback and next gates

Inspection leaves user projects unchanged. Prior to any consented build or test, back up or commit local source. If external tools alter the project, revert from its own backup/VCS. Remove the V20 router, Studio panel and tests by reverting V20 development commits, preserving all V1–V19 state, projects, user data and the central Agent.

V20 is not Verified until the exact-head CI and platform checks pass, independent manual native debugger/clangd navigation and release-security review is performed, and the whole project has human sign-off. Never merge into main or deploy by inference.

## Official references

- CMake CLI and build workflow: https://cmake.org/cmake/help/latest/manual/cmake.1.html
- CTest: https://cmake.org/cmake/help/latest/manual/ctest.1.html
- Compilation database: https://clang.llvm.org/docs/JSONCompilationDatabase.html
- Clang AddressSanitizer: https://clang.llvm.org/docs/AddressSanitizer.html
