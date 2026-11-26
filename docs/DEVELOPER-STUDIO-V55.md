# Developer Studio V55 — Bounded agent test runs

## What is implemented

V55 lets the **bounded, locally approved coding agent** from V52–V54 check its own work. It adds one tool, `developer_agent_test`, which runs the project's **detected** test command once, after the user approves it, inside a hard time limit. It then returns pass/fail evidence the server observed for itself.

The agent still has no `run_shell`, `run_command`, `developer_run`, app-run, install, network, deploy or share tool. It cannot type a command: the tool's only argument is an optional recipe id, such as `python:pytest`, chosen from the list that V41 detection already offers for the project.

### Before anything runs

1. **Prepare (read-only).** The server checks that the project is trusted, detects its test commands from the manifests (`pytest`, `npm`/`pnpm`/`yarn`/`bun test`, `go test`, `cargo test`), checks that the program is installed and fixes a time limit. Nothing runs. A missing test command, a missing program, an unknown recipe or too little time left is refused **before** the user is asked, and the agent is told the tests were not run.
2. **Review.** The chat and the classic workbench show a card with the exact command, where it came from, the time limit, and a plain statement of what the run can touch. The buttons are **Run tests once** and **Skip**. Each approval counts once, and the approval id is created by the server, so a reused model tool-call id cannot replay it. Global auto-approval does not apply.
3. **Run.** Only after that approval, and only before the V52 deadline. The recipe is detected again and must hash to the command that was approved, so a command that changed or disappeared during the approval wait does not run. The run uses the V41 runner: its own process group (its own session on Unix), a reduced environment, no keyboard input, and output capped at 256 KB.
4. **Stop.** The whole process group is killed when the time limit is reached, when the user presses Stop or when the task is cancelled, not just the first process. On Unix this is `killpg`, and on Windows it is `taskkill /T /F`.
5. **Evidence.** The result goes back to the agent and appears in **Review → Tests** like a manual run.

### Time limits

| Limit | Value |
| --- | --- |
| Longest single test run | 180 seconds |
| Kept back for the agent to report afterwards | 5 seconds |
| Shortest run that will start | 10 seconds |

The limit is the smaller of 180 seconds and the session's remaining V52 time minus 5 seconds. It is worked out again after approval, because waiting for the user uses up session time. Unlike the V52 budget, which is cooperative, this limit is **enforced**: the test process group is killed when it is reached.

### Honest verdicts

The verdict comes from the exit code **and** the parsed test summary (pytest, Jest, Vitest, Mocha, Go and Cargo). Only `passed` counts as a pass.

| Verdict | Meaning |
| --- | --- |
| `passed` | Exit code 0, a recognised summary, at least one test passed and none failed |
| `failed` | Any recognised failure, or a non-zero exit code |
| `no_tests` | The runner found no tests (for example pytest exit code 5) |
| `passed_exit_code_only` | Exit code 0, but the output had no summary AutoMoto recognises, so the pass is unproven |
| `timed_out` | Stopped at the time limit |
| `cancelled` | Stopped by the user or by task cancellation |

The evidence also includes passed, failed and skipped counts, up to 12 failing test names, the exit code, the time taken, and the end of the output. The output is redacted for tokens and keys, then returned to the model inside an untrusted-data fence, so instructions printed by test code are treated as data. The agent's instructions require it to report the verdict exactly and to say "the tests were not run" when a run was refused, skipped or failed to start.

In the chat-first view, the progress card counts a test step as passed only when its verdict is `passed`, not merely because the tool finished.

## Safety boundaries

- **Not an operating-system sandbox.** Test code runs as the user and can read or change files and use the network, like any program the user runs. The approval card says so. V55 contains the *process* (time limit, process group, no input, reduced environment). It does not contain what the tests do.
- Only detected commands from the project's manifests. No free-form command text, arguments or environment from the model.
- Local only, trusted projects only, and one test run per project at a time, within V41's limit of 4 live runs.
- Tests that change files are not routed through V51 patches. The per-task Keep/Undo checkpoint (V34) still covers them.

## Also fixed

The V41 runner marked a run as ended before it recorded the final status. A reader polling at that moment could see an ended run still marked `running`. The final status and exit code are now recorded before the run is marked as ended.

## Verification

`tests/test_developer_agent_test.py` covers:
- the registry: the tool exists, takes no command text, and the agent still has no shell;
- a real approved pass and a real failure with failing test names;
- denial, and refusal before asking for an untrusted project, a missing test command, an unknown recipe or too little time;
- a command that disappears during approval;
- a time limit that kills a grandchild process, not only pytest;
- Stop during a run;
- redaction of a token printed by a test;
- every verdict rule.

`apps/desktop/test/agent-test-card.cjs` checks the approval card in Chromium:
- the command is shown as text;
- one click approves once;
- Skip says the tests were not checked;
- forged or incomplete evidence cannot be approved;
- no sideways scroll at 390 px.

`.github/workflows/developer-agent-test-v55.yml` runs both on Ubuntu, macOS and Windows.

## Next milestone

V56: let the agent run **one chosen test file or test name** through the same gateway. The target will be validated as a project path or test id, never passed as a raw argument. Rerunning only the tests that failed also belongs here.
