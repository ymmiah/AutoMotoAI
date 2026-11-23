# Developer Studio V52 — Bounded coding agent

## User experience

AutoMoto Developer Studio now uses one review-first path for both the chat-first workspace and the classic coding agent. The user opens a trusted local project, asks for a task, reviews the V50 plan, and chooses **Review & start task**. Only after a separate start confirmation does the bounded coding agent begin. The chat-first composer offers compact optional limits; the classic workbench shows the same settings and progress.

The default budget is **8 model steps, 20 tool calls and 5 minutes**. Selectable caps are at most **12 model steps, 30 tool calls and 10 minutes**. A task reports model and tool usage and the remaining time. Stop cancels the pending task, including a waiting approval, at its next safe point. Existing per-task Keep/Undo review checkpoints remain the user's way to decide what source changes to retain.

## Server-side controls

- The client submits the approved V50 `plan_id`, the original task request and the chosen limits on `POST /api/agent`. The server re-evaluates the plan from the **current** project files and rejects a stale plan with HTTP 409. The plan hash is a freshness check, **not** an authentication credential.
- V52 is only available on the locally authorised Developer Studio API for a trusted project. Hosted access, untrusted roots and mobile/LAN clients are rejected. At most one bounded coding session is permitted to be active on the local server at a time.
- `CodingBudget` tracks elapsed monotonic time and tool calls in an individual run. The agent checks its budget before model steps and tool calls; hitting a cap stops the loop without attempting a hidden final model request.
- Crucially, **global automatic approval does not apply in a bounded coding run**. Only a short audited list of read-only tools can proceed automatically. Other calls (including writes into scratch, commands, tests, file changes and external interactions) always require a distinct human approval. Denied calls do not run.
- If the user's approval arrives after the deadline, the agent refuses to execute that tool. Approval waits cannot exceed the remaining session time. Other safety-policy blocks still take precedence.
- The task status `limited` is terminal and has a clear reason; the task response contains a `coding_budget` snapshot. A limited or cancelled run never schedules a new run automatically.

## Operational limitations

**This is a cooperative agent budget, not a process sandbox or hard operating-system deadline.** A model request or process that was already running when the time limit expired cannot be forcibly terminated by these checks. The agent will not initiate another model/tool action after the limit is noticed. Underlying tool permissions, timeouts and sandbox rules still apply. Prefer approved bounded test adapters; review any shell command before allowing it.

**V51's dedicated safe patch panel is not yet a universal patch gateway for all coding-agent edits.** The agent's existing editing tools are still available behind an explicit per-call approval, and its checkpoint review/undo remains in place. Routing all agent-generated edits through V51's atomically previewed, checksum-bound patch transactions and tightly confining arbitrary shell scripts require further work. Do not represent either as already guaranteed.

The plan identifies *suggested* steps. Model-generated tool selection and task outcomes are not certified as correct merely because the plan was reviewed. A failure or unavailable test must be reported rather than relabelled as a pass. Existing code, plans and source snippets are untrusted inputs to the model.

## Verification

Python acceptance tests:

- `tests/test_developer_coding_budget.py`: invalid caps, operation accounting, mandatory approval even under global auto mode, exhausted step/operation budgets and late-approval rejection.
- `tests/test_developer_bounded_agent_api.py`: plan digest validation, stale source refusal, local-only and trust constraints, over-budget request rejection, and the bound that the task manager receives.

Browser regressions check the user-selected budget, no model run before V50 plan review, a separate start confirmation, a submitted plan identifier and the visible chat budget display.

All CI workflows and manual desktop/mobile checks must pass before marking V52 release-ready. The branch is stacked on V51 → V50 → V49; merge or rebase in dependency order.

## Follow-up hardening

1. Require V51 patch transaction IDs for every code-modifying agent tool, with per-file limits and source digests.
2. Restrict test execution to sandboxed, audited adapters with execution deadlines enforceable at process level.
3. Add a durable audit record for each accepted/refused action, with bounded retention and redacted secrets.
4. Exercise full integration and cancellation with real slow providers and long-running test processes.
