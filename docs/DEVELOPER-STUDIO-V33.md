# AutoMoto AI Developer Studio V33/64 — Workbench, coding Agent and WebAssembly

## Scope

V33 extends the approved milestone (WAT, WASM, WASI, WIT and component-aware tooling) with a requested VS Code-inspired workbench redesign and task-scoped central AutoMoto AI Agent.

### Workbench

- Persistent dark editor workbench with title bar, project toolbar, activity rail, file Explorer, existing source editor, optional coding-agent pane, and collapsible language/toolchain extension drawer.
- Existing language adapters, editor, file safeguards, search/navigation, trust controls and developer workflows remain mounted; no project migration or source replacement.
- Responsive tablet/mobile layout, keyboard-focus indicators, ARIA status and reduced-motion handling.
- Browser smoke captures the V33 workbench, verifies existing explorer/editor presence, WebAssembly inspection and non-execution.

### Autonomous coding agent — one task per prompt

- The user opens and **trusts** a local workspace, then submits a coding instruction.
- A single saved central Agent conversation is created and bound to the chosen workspace. The existing **/api/agent** service runs up to 50 configured tool steps per prompt, with its existing tool permissions, approvals and task audit.
- Task progress is polled through **/api/tasks/{id}**; the panel displays events and output, supports individual tool approvals when exposed by the task service, and offers task cancellation.
- After the task completes, fails or is cancelled, the composer returns to **Waiting for next prompt**. **No automatic second prompt** is issued. Conversation history is reused for the next user message.
- The agent is **not** a new unrestricted operating-system agent. Actual edits, terminal/test operations and any external tools depend on the existing AutoMoto Agent's configured capabilities, credentials and safety policies. Risky actions require explicit approval. This version does not add unattended background autonomy, unbounded loops, auto-deployment, automatic publishing or self-approval.
- A cancelled task may already have changed files; the user should review the diff and tests before accepting its work. A tool call running during cancellation may not stop instantaneously.
- The existing review-only Studio Agent handoff remains available separately. It does not gain coding permissions.

### WebAssembly milestone

- Read-only WAT, WIT and WASM evidence inspection, bounded SHA-256 inventories, heuristic declarations and WASI host-access risk indicators.
- Core-module binary magic/version recognition and component-candidate recognition, explicitly **not** validation or proof of safety.
- Inert project manifests and installed tool availability for Wasmtime, wasm-tools, wat2wasm, wasm2wat, wasm-pack and cargo-component.
- No WASM runtime execution, compilation, component linking, package installation, WASI permission grant or network access from the WebAssembly inspection module.
- **Remaining acceptance gap:** the roadmap's real WAT/WASM/WASI/component build and runtime output with approved sandbox boundaries is **not implemented**. Do not label V33 Verified until isolated real toolchain acceptance is designed, implemented and independently reviewed.

### Security and CI

- All existing workspace trust, source editing checksums, bounded agent steps, explicit tool approvals and task audit remain in force.
- V32 CI hardening regression fixed on this branch: use the shared apt-install script and CI path filter rather than direct apt-get or unconditional macOS jobs.
- New tests verify WASM/WIT/WAT inventory, binary magic, source preservation, hash drift, linked manifests, oversized inputs and API authentication.
- CI runs cross-platform Python tests and JS syntax; core CI, Windows app, docs, V18–V32 acceptance and browser smoke must all be green **on the same exact PR head** before human review.
- Manual accessibility, responsive layout, actual AI provider, model credentials, approval workflow, diff/recovery and cancellation behaviour still require installed-app verification.

### Recovery

Close or revert the V33 draft PR. No main-branch changes or production deployment are authorised. Back up a project before granting any agent write or external tool permission. Review agent-generated changes in version control and use independent recovery snapshots when necessary.

### Further roadmap

A subsequent acceptance increment should add independently isolated real Wasmtime and component tooling tests, explicit WASI capability restrictions, runtime-output verification and safe project-level build adapters. Do not represent read-only inspection as completed runtime integration.
