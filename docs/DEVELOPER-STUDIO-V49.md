# Developer Studio V49 — Source-grounded AI help

## Implemented

V49 adds a read-only `POST /api/developer/studio/grounding` route and a central chat tool named `developer_sources`. Given a project path and a question, the route reads actual source text and returns project-relative paths, numbered excerpts and SHA-256 file digests. The chat-first **Explain my project** action now requests file-and-line evidence instead of an unsupported summary.

This is **bounded lexical retrieval** rather than proof that an answer is correct. A source citation establishes where the text came from; the assistant still needs to interpret the code carefully. The API returns an explicit no-match result if it finds no relevant lines.

The route reuses the existing Developer Studio local-only authentication, project root confinement, indexer exclusions for hidden credentials, linked files and directories, binary files and oversized source files. The scan has a 160-file and 3 MiB budget; output is capped to eight excerpts, with a maximum of two per file and 240 characters per line. Common credential assignments and bearer tokens are redacted from excerpts. **Caution:** arbitrary source code can contain other confidential information; users must consider their chosen AI provider before allowing model access.

No project code is executed, edited or shared by V49. Retrieved source is untrusted data and must never override the user's instructions or the existing approval rules.

## Planned screens for V49–V52

- **V49 — Source evidence:** answer plus precise `path:Lx-Ly` references. Open source to inspect the line. If no evidence is found, show "Not verified in this project".
- **V50 — Task planner:** concise numbered steps and their dependencies, status checkboxes and tests. Plan review before any action.
- **V51 — Safe patch engine:** file path, exact original SHA-256, a compact unified diff and Apply, Skip, Undo controls. Server rejects stale, conflicting and oversized edits.
- **V52 — Bounded coding agent:** explicit step and operation limits; visible progress, per-action human approval, Stop, and test evidence. Never apply, run or share without specific approval.

Existing Keep/Undo, checksum-gated saves, local run approvals and Git controls remain the authority. V50–V52 are not implemented in the V49 branch.

## Verification

Automated checks in `tests/test_developer_grounding.py` cover real source locations and digests, explicit no-match, excluded secrets, rejected external roots and origins, refusal of symlinks and read-only behaviour. The branch must pass GitHub Actions and manual approval checks before merging.
