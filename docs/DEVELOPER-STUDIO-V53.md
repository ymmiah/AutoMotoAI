# Developer Studio V53 — Transactional agent patches

## What changed

V53 closes the most important write-path gap left by V52 for **bounded Developer Studio coding sessions**. Instead of giving the coding agent access to the generic file-write, shell, app, network, share and developer-save tools (even with per-action confirmation), V53 gives it only audited read-only project tools and one dedicated `developer_agent_patch` capability for an **existing** source file.

The model supplies a project-relative path, the exact SHA-256 obtained from a previous read, one uniquely matching original fragment, and the proposed replacement. It cannot directly write, create, execute or publish anything using those tools.

### Transaction lifecycle

1. **Prepare:** inside the trusted project, the server asks V51's `preview` API to validate the original file and create a bounded unified diff. Python replacements are syntax-checked. Missing, protected, linked, stale, too-large and ambiguous replacements fail before an approval request.
2. **Review:** only the server-produced path, original and resulting file digests, numbered change count and exact diff go to the waiting task's approval card. The one-use preview token stays inside the server-side agent call and is never supplied to the model or browser. The chat and classic workbench offer **Apply checked patch / Skip**.
3. **Apply:** only if that specific tool call was approved, and before the V52 deadline expires, the bounded loop invokes V51's private checked transaction. Its existing atomic save checks the same original digest again, preventing stale or conflicting overwrites.
4. **Recover:** the same V51 private undo snapshot is produced. The standard Undo UI can restore it, provided the resulting file still has the expected checksum.

Global auto-approval does **not** override a bounded coding patch approval. If the user denies the request, the patch does not write. An unknown or retired write tool is absent from the bounded registry and cannot execute.

### Security architecture

- **Default-deny capabilities:** the bounded coding tool registry contains only selected read-only project tools plus `developer_agent_patch`. It has no `run_shell`, `run_app`, `write_file`, `edit_file`, `developer_save`, `developer_run`, `more_tools`, memory mutation, website/network tools or remote-share tools.
- **V51 protection remains:** trust, relative path checks, symlink/junction checks, protected files, file size/diff limits, one-use tokens, same-project identity, SHA-256 conflicts, atomic saves and private undo.
- **No direct commit API for the agent:** the existing `POST /api/developer/studio/patch/apply` remains human-UI only. V53 has a private Python transaction helper that is called only from the bounded agent loop *after* the TaskManager approves the matching server-created diff.
- **Untrusted source:** retrieved project text stays fenced as data, not instructions. The proposed patch is validated by the V51 engine and must be explicitly approved.
- **Fixed budget:** V52's step count, tool-call count, time checks, individual approval and task cancellation still apply.

### Explicit limitations

- This is a **patch-only** coding-agent mode for *existing files*. Creating a brand-new source file through the agent is deliberately unavailable until a similarly reviewed no-clobber creation transaction is implemented.
- The bounded agent cannot execute builds or tests in this mode. Use existing independently approved test controls, and report that tests were not run by the agent. Hard process-level sandboxing and cancellation need separate engineering.
- Global/unbounded AutoMoto agents outside Developer Studio retain their existing tool set and approval configuration. V53's restriction applies only when `coding_budget` is present.
- V53 does not claim that a manually approved external test, extension, editor or OS process cannot write files; those execution paths are outside this patch-only agent tool registry.
- Model planning and its interpretation of source may still be wrong. Human approval and deterministic validation guard the mutation but do not guarantee correctness.

## Verification

`tests/test_developer_agent_patch.py` checks the exact registry, denied legacy write tools, approval under global auto mode, approved edit/undo, a stale change made during approval, syntax rejection, protected files and ambiguous snippets.

The existing V51/V52 tests must remain passing. Browser review must confirm that the chat and classic workbench show the server-produced diff and that **Skip** never modifies a file.

## Release order

V49 merged to main, while V50/V51 and V52 are still being integrated through draft PRs #112 and #111. V53 is stacked on V52 and must not be merged or advertised as released until its dependencies, CI and end-to-end manual review pass.

## Next milestone

V54 should add separately reviewed no-clobber **new-file creation** and a safe, process-enforced test adapter rather than restoring unrestricted shell or generic write tools.
