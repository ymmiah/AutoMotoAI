# Developer Studio V51 — Safe patch review

## What is implemented

A new **Safe patch** tool appears under Developer Studio → Tools, and the read-only preview API is at `POST /api/developer/studio/patch/preview`.

The user chooses one existing project-relative source file, provides the exact text to replace and the replacement, then previews a unified diff. The server requires that the original fragment match **exactly once**, checks the disk SHA-256 digest, limits the patch size and refuses protected or linked files. Python files are syntax-checked using the Python AST; other languages are marked **not syntax-checked** rather than claiming full validation.

**Apply patch** is a separate click with confirmation. `POST /patch/apply` checks the preview's single-use identifier, trusted workspace identity and latest file digest, then calls the existing Developer Studio atomic save mechanism. Stale, replayed, oversized and ambiguous edits are refused. This route also refuses calls marked as originating from the central agent: it is designed for human-initiated UI actions.

**Undo applied patch** makes a separate confirmed request to `POST /patch/undo`. A private, permission-restricted undo record stores the original content before the save. Undo is checksum-bound to the exact applied output and refuses to overwrite a file that has changed since. Up to twelve recent records per file are retained. The records survive an ordinary app restart while retained.

## Safety boundaries

- All three routes are local-only and require the existing project sandbox. Applying and undoing additionally require a trusted workspace.
- Protected filenames (including environment files and credential configuration), symlinks and junctions are blocked.
- The preview exists in bounded server memory for up to fifteen minutes. An expired or used preview cannot apply.
- No shell command, language server, package manager, Git push, deployment or sharing is performed.
- Source validation is language-specific. Only Python receives AST syntax validation; the preview is not a comprehensive security review.
- The preview diff is untrusted source text. The frontend uses text nodes rather than HTML parsing.
- The undo snapshot is local private application data, not a permanent version-control history. Existing Git checkpoints remain recommended for long-term recovery.

## Scope limitation

**This build provides the explicit Safe patch workflow**, not a global interception of every existing AI file-write tool. Existing coding-agent edits still use the prior approval-gated tool mechanism and Keep/Undo checkpoint support. Converting all agent-generated edits into V51 patch transactions will require a careful central tool-layer integration, which must be verified before claiming universal enforcement. V52 must not treat the presence of this API as permission to edit unattended.

## Tests and acceptance

`tests/test_developer_safe_patch.py` tests preview without mutation, successful apply and undo, replay refusal, external edits after preview or apply, duplicate fragment ambiguity, Python syntax rejection, oversized replacement, protected file rejection, untrusted roots, request authorisation and agent-originated apply refusal.

Final sign-off requires GitHub Actions, real mobile/desktop panel inspection and an explicit test that source changes can be reverted after a restart.
