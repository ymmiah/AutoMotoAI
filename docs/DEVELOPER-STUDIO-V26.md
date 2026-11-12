# AutoMoto AI Developer Studio V26/64 — Shell and Automation

**Development-only milestone.** Based on the V25-merged cumulative development branch. Never run these features as a privileged daemon or production deployment mechanism.

## Delivered

- Authenticated **inert** inventory of bounded `.sh`, `.bash`, `.zsh`, `.fish`, `.ps1`, `.psm1`, `.bat` and `.cmd` files. Reports SHA-256 file inventory, interpreter family, physical line count and heuristic risk signals. Inspection does not execute scripts, open shell sessions, run startup profiles, load PowerShell modules or alter source files.
- Warns on common destructive commands, recursive deletion, network/download-and-run patterns, privilege changes, shell substitution and credential/environment references. Warnings are **not** proof a script is unsafe; absence of a warning is **not** proof it is safe. Script syntax and command security cannot be established using regular expressions.
- Fingerprints installed Bash, Zsh, Fish, PowerShell Core, Windows PowerShell, cmd.exe and ShellCheck binaries without invoking them. The existing local project trust registry and central AutoMoto Agent remain the sole authorities for workspace and release-readiness review.
- Explicit **trust, per-task confirmation, unsandboxed-risk acknowledgement and exact source/inventory/toolchain SHA-256 checks** for every external command. Bounded staging to a private, disposable project copy, subprocess argument arrays without `shell=True`, a fixed 30-second task timeout and output-size limits. Approval does not install tools, connect devices, run services or publish anything.
- Fixed **non-executing** syntax commands: `bash --noprofile --norc -n`, `zsh -f -n`, `fish --no-config -n` and PowerShell's .NET `Parser::ParseFile` AST parser. A separate optional installed ShellCheck binary provides Bash/sh static diagnostics with `--norc --shell=bash --format=gcc`. No equivalent general safe Batch parser is claimed.
- A deliberately restricted **literal-only smoke fixture runner**. Only fixed `scripts/smoke.sh`, `smoke.bash`, `smoke.zsh`, `smoke.fish`, `smoke.ps1`, `smoke.cmd` or `smoke.bat` may execute, if every byte matches the narrow line grammar. It permits only literal echo/printf or Write-Output and clean exit instructions. It refuses general scripts, user-supplied commands, arbitrary flags, expansion, quotes inside arguments, pipes, redirection, assignments, loops, eval, file/network commands and shell chaining. An eligible fixture cannot invoke an external command via the admitted language grammar; this **does not make its interpreter OS-sandboxed**.
- Existing separately approved LSP/debug-adapter workflows remain separate. The **same central AutoMoto Agent** can receive a review draft; drafts are never automatically submitted, and no autonomous shell deployment privileges are added.

## Acceptance evidence

- `tests/fixtures/v26-shell/scripts/`: portable literal-output Bash, Zsh, Fish, PowerShell and Batch smoke samples; intentionally destructive Bash and malformed PowerShell files to ensure inspection-only handling.
- `tests/test_developer_shell.py`: inert source inventory and preservation, suspicious-command signals, forbidden destructive/variable/pipeline/redirection shell constructs, PowerShell/Batch restrictions, authenticated local-only enforcement, linked file rejection, source/tool fingerprint drift, strict consent and anti-parameter-injection validation; real eligible fixture execution and real syntax/PowerShell parser testing where appropriate tools exist.
- `.github/workflows/developer-shell-v26.yml`: real Ubuntu Bash, Zsh, Fish, ShellCheck; macOS Bash and Zsh environment tests; Windows PowerShell and Batch real fixture smoke. Tool installation is allowed only on disposable CI runners. Passing tests require the exact PR-head workflow, not just a fixture that exists.
- `apps/desktop/test/ui-smoke.cjs`: read-only visual source evidence, hazardous-script display and same central Agent review draft, with byte-for-byte preservation of original scripts.
- New route `/api/developer/studio/shell/inspect` (GET) and `/api/developer/studio/shell/run` (POST), both local-only and authenticated. Existing Studio modules and stored user data remain intact.

## Limitations and safety

**This is not a general-purpose script execution engine, malware detector, policy verifier or sandbox.** Interpreter binaries and approved diagnostic tools operate with the caller's filesystem and network privileges, even inside a temporary copy. Existing system shell startup files, tool vulnerabilities, custom executable wrappers and environment configuration can still affect the host. File hashes and a narrow command grammar reduce some accident classes but are not sufficient to promise absolute security.

- Syntax-only diagnostic checks are intentionally allowed for scripts that contain destructive text, but **never execute** those script statements.
- A PowerShell AST parser only reports syntax; it does not guarantee security or analyse dynamic modules. Batch syntax checks beyond conservative inspection are not offered.
- ShellCheck is heuristic static lint and is not substituted for a POSIX shell; Zsh/Fish/PowerShell/Batch use their own separate diagnosis paths. Fish, Zsh and PowerShell are not automatically installed by the desktop app.
- On Windows, an executable ending in `.cmd`, `.bat` or `.ps1` is not accepted as a toolchain binary; native `cmd.exe` and PowerShell binaries are fingerprinted instead.
- The literal-only execution grammar may be broadened only in a subsequent reviewed milestone with a formally specified sandbox policy, stronger isolation and explicit user consent. Arbitrary `rm`, `curl | sh`, remote code, privilege escalation, file deletion, credential collection, system automation and CI/CD deployment are deliberately excluded.

## Recovery and review

Commit/back up the original workspace before any approved external tool execution. If host toolchain side effects occur despite fixed commands, use OS process/security controls and restore affected data from version control or backups. Revert V26 changes on the development branch without altering V1–V25 or user data.

**Review**, not Verified, until exact-head Windows/macOS/Linux interpreter and UI/security tests, all prior language regressions, Windows desktop packaging, audit of the fixture grammar and subprocess environment, manual PowerShell/ShellCheck checks, and explicit human approval. Do not merge into `main` or release autonomous automation features based only on an initial CI run.

## Technical documentation

- [Bash invocation options](https://www.gnu.org/software/bash/manual/bash.html#Invoking-Bash)
- [Zsh invocation](https://zsh.sourceforge.io/Doc/Release/Invocation.html)
- [Fish command-line options](https://fishshell.com/docs/current/cmds/fish.html)
- [PowerShell parser API](https://learn.microsoft.com/en-us/dotnet/api/system.management.automation.language.parser.parsefile)
- [ShellCheck](https://www.shellcheck.net/)
