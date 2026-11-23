# Developer Studio V50 — Task planner

## User workflow

When a trusted project's chat receives a coding request (for example, "Add a login page"), the assistant **does not start immediately**. The local planning API prepares up to six suggested steps. The chat displays a readable plan card with:

- Numbered steps, descriptions and a check to confirm each step's intended result.
- Optional **Open source** links for actual files found in the project. If no relevant source matched, the UI says so rather than inventing a file.
- Checkboxes marked **reviewed** (not completed); they record only which proposed steps the user has personally read, not claims of successful implementation.
- **Review & start task**, **Edit request** and **Dismiss** actions.

Review & start invokes the existing task confirmation and tool-by-tool approvals. Before that click, nothing is written, run or shared. When a coding task completes, existing Keep/Undo checkpoints remain the only decision about retaining work. Quick local actions such as Test my app or Share to GitHub retain their own explicit confirmation flows, and read-only explanation requests go straight to the normal read-only task process.

## Technical contracts

- `POST /api/developer/studio/task-plan` accepts a local project path and a task request of 5–2,000 characters. It uses the existing local-only Developer Studio access check, not the hosted API.
- The endpoint uses V49's capped read-only source lookup. Results are a deterministic, checksum-bound suggestion list with no executable commands and no source excerpt text.
- Path hints are **evidence, not authority**: suggested tasks can be wrong, evidence can be incomplete, and no source match does not imply a feature is missing.
- The returned `plan_id` is a SHA-256 digest of project identity, request, plan and source evidence; it is not an authorisation token.
- On approving a plan, the UI verifies that the workspace path still matches and remains trusted. A final run confirmation and normal high-risk tool prompts still apply. A different workspace invalidates a preview.
- The plan is not stored in a cloud service or persistent project file. A ticked checkbox does not trigger an agent operation.
- No automatic edits, running, deployment, merging, publishing or sharing have been added.

## Known limitations

This is a **deterministic intent-aware planner**, not a model that invents a custom multi-file implementation roadmap. The evidence matcher is lexical and capped. Version 52 will need explicit agent-run budgets and stronger server-side binding between an approved plan and the actual subsequent steps; the current plan token is informational only.

## Verification

The backend tests cover login, debugging, no-source, stability, source and secret boundaries, local-only access and no mutation. UI regression tests cover plan preview, independent review checkboxes and confirmation gating in the ordinary chat and Edit, test & share workspace. Final acceptance requires green GitHub Actions, desktop/mobile inspection and review.

**Dependencies:** V49 source evidence API. The V50 pull request initially targets the V49 feature branch; it must be rebased or retargeted to main after V49 is merged.
