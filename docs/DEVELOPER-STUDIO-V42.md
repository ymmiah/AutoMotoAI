# Developer Studio V42: debugger and profiling host

V42 lets a beginner pause a program on a line, step through it and see every value. It works through the Debug Adapter Protocol (DAP) with **debugpy** for Python, and with **GDB** (14 or newer) or **LLDB (lldb-dap)** for C, C++ and Rust programs built with debug info. It also explains pasted crashes and measures which Python functions are slow.

The desktop main screen is unchanged. V42 lives in **Tools → Debugger**, on desktop, tablet and phone.

## What you see

1. **What should run?** Press **Find programs**. AutoMoto lists the project's Python files (it skips tests) and its built native programs, and picks the matching debugger. If that debugger is missing, it says so and shows the install command, with a copy button, or the official link.
2. **Where should it pause?** (optional) Add stop points as a file and a line. After start, each one shows **Set** or **Not set**, as the debugger reports it. You can add or remove them while the program runs.
3. **Start debugging.** First a confirmation explains that your program really runs on this computer and is not sandboxed. Declining runs nothing.

While it runs:
- **Continue**, **Step over**, **Step into**, **Step out**, **Pause**, **Stop**, and **Restart** after it ends or crashes.
- **How it got here**: the call stack, with your own files highlighted.
- **Values right now**: arguments and local variables. Long values are shortened.
- **Watch**: names such as `total`, `user.name`, `items[0]` or `node->next`.
- **Program output**: in a collapsible box.
- If the program hits an uncaught error, it pauses on that line and shows the error.

**Explain a crash** reads pasted text and never runs anything. It handles:
- Python tracebacks
- Rust panics and Go panics
- Node.js, Java and .NET stack traces
- native backtraces
- signals, from negative exit codes or 128+n
- Windows crash codes such as `0xC0000005`

It shows a one-line summary, the first line in your project, and tips. The text isn't stored.

**Find what's slow (Python)** runs the selected Python file once under `cProfile`, for up to 2 minutes, and lists your slowest functions.

## Safety

| Guard | What it does |
| --- | --- |
| Trust | Start, Restart and Speed check need **Changes allowed** for the project. |
| Pinning | The debugger is pinned by SHA-256, refusing executables inside workspace roots. The program file is pinned too. If either changes, start and restart are refused. Restart re-checks both. |
| Consent | Every run needs a confirmation (`confirmed` plus `accept_unsandboxed_execution`). |
| Fixed debuggers | Only debugpy, GDB and lldb-dap, with fixed arguments. GDB runs with `-nx` and `set auto-load local-gdbinit off`, so project `.gdbinit` files don't run. The adapter runs from a temporary folder, with `PYTHONSAFEPATH=1` and a reduced environment. |
| No arbitrary evaluation | Watch accepts names, attributes, simple indexes and `->` only. Calls, operators and assignments are refused. Reverse requests from the adapter (such as `runInTerminal`) are refused. |
| Limits | 2 sessions at a time; 30 minutes each; 2 MB protocol messages; 64 KB output; 25 frames; 60 variables; 40 stop points; 12 watches. |
| Crash recovery | If the debugger itself dies, the session says **Debugger crashed** and stops your program's whole process tree. On Linux it also sweeps the session group. Restart keeps your stop points and watches. If the cause is clear from the debugger's own messages (for example *debugpy isn't installed*, or *GDB too old*), it says so. |
| Cleanup | Sessions end on Stop, on app exit and after the time limit. |

## API

All routes are under `/api/developer/studio/debug` and need the session token.

| Route | What it does |
| --- | --- |
| `GET /detect?project=` | Debuggers (status, SHA-256, install hint, CI-verified hosts) and targets with their SHA-256. Runs nothing. |
| `POST /start` | `{project, debugger, target, expected_target_sha256, expected_executable, expected_sha256, breakpoints:[{path,line}], confirmed, accept_unsandboxed_execution}` |
| `GET /state?session_id=` | Status, stop reason, frames, variables, watches, exception, stop-point results, output, exit code, error, `restart_available` |
| `POST /control` | `{session_id, action: continue/next/stepIn/stepOut/pause}` |
| `POST /breakpoints` | `{session_id, path, lines}` |
| `POST /watch` | `{session_id, expressions}` |
| `POST /stop` | Stop the session. |
| `POST /restart` | `{session_id, confirmed}` |
| `POST /profile` | Same pins and consent as `/start`. |
| `POST /crash` | `{project, text, exit_code?}`. Runs nothing. |

## Tests and CI

- `tests/test_developer_debug.py`:
  - A fake DAP adapter (`tests/fixtures/v42_fake_dap.py`) covers stack, variables and watch. It crashes on Continue to prove crash detection and Restart.
  - Refusals: trust, wrong hashes, wrong file type, unknown debugger, path escape, missing consent, unsafe watch expressions.
  - Crash explainer cases, the profiler, and session auth.
- Real tests:
  - `AUTOMOTO_V42_REAL_TOOL_TESTS=1`: debugpy breakpoint, stack, variables, watch and exit. An uncaught exception pauses on the right line. Killing the adapter kills the debuggee and Restart works.
  - `AUTOMOTO_V42_REAL_GDB=1`: a gcc-built C program through GDB's DAP, with a breakpoint, stack, locals and exit.
- `.github/workflows/developer-debug-v42.yml`:
  - Real debugpy on Ubuntu and Windows, plus macOS when V42 files change.
  - Real GDB on Ubuntu.
- `apps/desktop/test/developer-studio-e2e.cjs`: declining the confirmation runs nothing; a real pause at a stop point with frames, values and a watch, when debugpy is present; and the crash explainer.

## Limitations

- **Verified hosts:**
  - debugpy is verified by CI on Linux, Windows and macOS.
  - GDB is verified on Linux only. It isn't checked on Windows (use WSL or MSYS2) and isn't usually available on Apple silicon.
  - lldb-dap is supported but **not CI-verified**. Treat it as preview.
- **Not supported yet:** .NET (netcoredbg), Java/Kotlin (JDWP), Node.js, Go with Delve, attaching to a running process, remote debugging. The UI says so instead of pretending.
- Programs and debuggers are **not OS-sandboxed**. The guards are trust, pinning, consent, a reduced environment, a temporary working folder and time limits.
- Native stop points need a program built with debug info (`-g`, `cargo build`). Optimised builds may show *Not set* or missing values.
- The speed check is Python-only and samples one run. Native profiling (perf, Instruments, ETW) is not included.
- Values are shortened to 240 characters. Nested values aren't expandable yet.

## Recovery

| Problem | What to do |
| --- | --- |
| **Debugger crashed** | Press **Restart**. If it says debugpy isn't installed, copy the install command, run it, then Restart. |
| **The debugger program moved / changed** | Press **Find programs** again, then Start. |
| **The program changed since you approved it** | Find programs again. This is deliberate, so an edited file needs a fresh approval. |
| Stop point shows **Not set** | Rebuild with debug info, or check the file and line. |
| Stuck session | **Stop** always ends it. Sessions also end after 30 minutes and when AutoMoto quits. |
