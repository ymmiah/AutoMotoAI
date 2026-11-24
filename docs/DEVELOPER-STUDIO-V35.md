# Developer Studio V35: newer languages (Zig, Nim, Crystal, Odin, Mojo, MoonBit)

V35 shows which newer languages a project uses, whether each one is installed on this computer, and how mature it is. Where AutoMoto has proved the official toolchain in CI, you can also run a tiny test program to confirm the compiler really works.

The desktop main screen is unchanged. V35 lives in **Tools → Zig, Nim & newer languages**, on desktop, tablet and phone.

## What you see

1. **Check this project.** Reads files only. You get one card per language with:
   - how many files and which manifests (`build.zig.zon`, `*.nimble`, `shard.yml`, `moon.mod.json`, `mojoproject.toml` and others) the project has;
   - a maturity badge: **Stable** (Nim, Crystal), **Pre-1.0** (Zig, Odin), **Preview** (Mojo) or **Beta** (MoonBit);
   - **Installed** or **Not installed**. When it's missing, the card shows the install command with a copy button, or a link to the official install guide;
   - the version the project asks for (for example `minimum_zig_version`), and whether that's inside the range AutoMoto has tested.
2. **Try a tiny test program** (Zig, Nim, Crystal and Odin only). After you confirm, AutoMoto builds and runs its *own* small example, not your code, in a temporary folder that is then deleted. The card says "Works: Zig 0.17.1 built and ran the test program" and whether that version is tested, older or newer than tested. If it fails, the compiler's own message is shown with a copy button.

Advanced details holds the full JSON result.

## Version notes

AutoMoto keeps its own notes per language (last reviewed 2026-11). They are advice, not a promise from the language projects.

| Language | Maturity | Tested range | Test program | Proved in CI on |
| --- | --- | --- | --- | --- |
| Zig | Pre-1.0 | 0.14.0 to 0.17 | yes | Linux |
| Nim | Stable | 2.0.0 to 2.4 | yes (needs a C compiler) | Linux |
| Crystal | Stable | 1.10.0 to 1.22 | yes | Linux |
| Odin | Pre-1.0, monthly dev releases | dev-2025-01 to dev-2026-11 | yes (needs clang or the Visual Studio build tools) | Linux |
| Mojo | Preview, no native Windows | – | no, files are read only | – |
| MoonBit | Beta | – | no, files are read only | – |

A version below the range is reported as **older than tested**; a newer one as **newer than tested** (it will probably work). An unreadable version is never treated as supported.

## Safety

- Inspection never runs project code, never evaluates manifests (`build.zig` is itself a Zig program, Nim's `staticExec` and Crystal's `{{ run() }}` run code at compile time) and never installs packages.
- It flags code that runs other programs, uses the network, runs code while compiling, or calls C.
- The test program needs a trusted project, your confirmation, and the exact compiler bytes you saw (SHA-256). If the compiler changes in between, the request is refused with 409. Shell wrappers (`.cmd`, `.bat`, `.ps1`) and executables inside project folders are refused.
- The compiler runs with a reduced environment, an empty temporary home and temporary caches (`ZIG_GLOBAL_CACHE_DIR`, `--nimcache`, `CRYSTAL_CACHE_DIR`), a 240-second limit and capped output. Only one check runs at a time.
- A check only counts as passed when the program prints the exact expected line. Exit code 0 alone is not success.

## API (local only)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/developer/studio/emerging/inspect?project=` | Languages, files, manifests, toolchains with SHA-256, version notes. Runs nothing. |
| POST | `/api/developer/studio/emerging/check` | `{project, language, expected_executable, expected_sha256, confirmed: true, accept_unsandboxed_toolchain: true}`. `language` is `zig`, `nim`, `crystal` or `odin`. |

## Tests and CI

`tests/test_developer_emerging.py` covers read-only inspection, every language detected, Mojo and MoonBit never offered a check, missing toolchains reported (never claimed), risk signals, project version requirements, version classification, trust and SHA pinning, marker-based success, refused consent, linked manifests, oversized files and authentication.

The **Developer Studio V35 Emerging languages acceptance** workflow runs those tests on Ubuntu and Windows (and macOS when V35 files change), then installs the official Zig 0.17.1, Nim 2.4.2, Crystal 1.22.3 and Odin dev-2026-11a releases on a disposable Ubuntu runner, verifies each download's SHA-256, and runs the real checks through the API.

## Limitations

- Declarations and risk signals are pattern matches, not a compiler.
- Real toolchains are proved on Linux only. On Windows and macOS the check still runs if the compiler is installed, but AutoMoto hasn't verified those hosts in CI, and the card says so.
- Mojo and MoonBit are inspection only in this version.
- The test program proves the compiler works. It doesn't build your project, resolve dependencies or prove your code compiles.
- The compiler is not OS-sandboxed and may use the network if it chooses to.
- No release readiness is claimed for any of these languages.

## Recovery

- **"Not installed" but you installed it:** restart AutoMoto so it sees the new PATH, then press Check this project again.
- **"The compiler changed since you approved it":** press Check this project again, then retry.
- **Nim or Odin fails with a linker or C compiler error:** install gcc or clang (Linux and macOS) or the Visual Studio build tools (Windows).
- **Undo:** V35 never writes to your project, so there's nothing to undo. To remove the feature, revert the V35 PR.
