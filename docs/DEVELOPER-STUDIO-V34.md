# Developer Studio V34 — Guided Workbench UX and Agent Reliability

V34 improves the existing V33 VS Code-inspired workbench without removing the file editor, project controls, language extensions, trust model or agent.

## User experience

- Three-step, context-aware quick start: choose project, trust the project after review, then request a coding task.
- Visible next-step guidance adapts to no project, read-only project, trusted workspace and running Agent states.
- One-click, editable task examples: explain project, fix a bug, improve quality, add tests. **Clicking a suggestion never runs the Agent.**
- Existing project selector and trust controls remain the source of authority; V34 only focuses the appropriate controls.
- Accessible button sizes, focus indicators, mobile layout and no new automatic prompts.

## Critical V33 task lifecycle fix

The real AutoMoto task API reports terminal success as `done`, not `completed`. V34 recognises both, returns to **Waiting for next prompt**, clears busy state and allows the next task. Failed API starts preserve the original prompt instead of losing user input. Conversation history is scoped to the selected workspace; changing projects creates a new conversation. Monitoring retries are bounded and report loss of connection without silently claiming success.

## Verification and limits

- Browser smoke: guide, suggested task, no unintended agent run, and screenshot.
- JS syntax and existing CI must pass on the exact V34 commit.
- Manual acceptance: run a real agent task against a disposable trusted project, approve and deny tools, cancel, change workspaces, simulate network interruption, verify code diffs and keyboard/mobile accessibility.
- This version does not make unsupported agent tools available, bypass approvals, merge branches, publish builds or deploy.
- Recovery: revert the V34 PR. Agent edits to user projects still require normal source-control review and backups.
