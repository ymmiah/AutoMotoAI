# Developer Studio V54 — Safe creation of new source files

## What is implemented

V54 extends the V53 **bounded, locally approved coding agent** with a second, constrained source-modifying tool: `developer_agent_create`. It can propose a **new** source file in a directory that already exists. It cannot overwrite an existing file, create directories, run shell commands, perform tests or share code.

The existing `developer_agent_patch` continues to handle changes to existing files. The bounded agent still has no unrestricted `write_file`, `edit_file`, `developer_save`, shell, app-run, network, deploy, publishing or tool-expansion access.

### Before any file is created

1. The model proposes a project-relative path and the complete source text, with a 64 KiB / 120-line cap.
2. The V54 server checks the exact trusted project, protected/hidden/generated paths, an approved source-file extension, existing parent directory and absent destination; Python files must parse successfully.
3. `POST /api/developer/studio/create/preview` returns a server-generated unified diff with `--- /dev/null`, the content digest, line count and syntax-check status. Preview **does not write to the project**.
4. The user's chat or classic workbench displays the exact diff with **Create checked file** and **Skip**. A user approval applies to this action once, not any future tool call. A reused model-provided tool-call ID cannot replay approval.
5. The one-use preview token stays in the server. If approved before the V52 time budget expires, the private transaction commits with exclusive OS file creation (`O_CREAT | O_EXCL`). If another process creates the name before approval, the operation fails without overwriting it.
6. A private local undo record captures file identity (device/inode and recorded change time) and SHA-256. `POST /api/developer/studio/create/undo` deletes only the exact file if it is still unchanged and after another explicit human confirmation. Undo refuses a replacement file or later edits.

### Filesystem safeguards

- Source files only; allowed extensions include Python, JavaScript/TypeScript, HTML/CSS, JSON, Markdown and selected compiled languages. Hidden paths, secret files, generated folders and other extensions are refused.
- Parent folders must exist; directory creation is a separate future capability.
- Unix uses `O_DIRECTORY | O_NOFOLLOW` and directory file descriptors for no-link path traversal, plus exclusive creation and `fsync` for file contents. Windows uses exclusive file creation and verified parent identity but lacks the same Unix directory-fd path traversal: **a hostile concurrent reparse-point swap is a residual Windows limitation** and must be hardened through native handles before high-assurance claims.
- One-use previews expire after 15 minutes and are kept in bounded memory. Undo records are private and survive normal process restarts.
- A write failure attempts to remove only its newly created inode; a failure to store the undo record triggers guarded rollback. The tool never silently changes an existing file.
- A concurrent attacker with filesystem modification privileges could still race the final unlink on some platforms. Undo includes a just-before-unlink identity check, but strict atomic identity-conditional unlink is not offered universally by Python.

### Scope boundaries

All protections here apply **only to local, trusted, plan-bound bounded Developer Studio coding runs**. The wider AutoMoto application and independent manually approved test/share controls are separate workflows. This milestone does not make arbitrary test execution safe or introduce mandatory command-level process containment.

V54 remains explicitly **non-executing** inside the bounded agent. The assistant must not claim that a new source file was tested simply because its syntax was checked. JavaScript, PHP, C, and other extensions are not syntax-checked by this feature.

### API

- `POST /api/developer/studio/create/preview` — local-only read-only preview; `project`, `path`, `text`.
- `POST /api/developer/studio/create/apply` — local human-only approval; `project`, `path`, `token`, `confirmed: true`.
- `POST /api/developer/studio/create/undo` — local human-only removal of the exact unchanged created file.

An internal function applies the exact same checked transaction for the bounded agent **only after** per-tool human approval. An ordinary agent-generated call cannot invoke the create/apply endpoint directly.

### Verification

- `tests/test_developer_safe_create.py`: preview without write, exclusive create, preview replay, durable undo, user-modified file refusal, protected/linked destinations, invalid Python, size/line caps, parent swaps, local-only and agent-call restrictions.
- `tests/test_developer_agent_create.py`: bounded tool registry, per-action approval under global auto-approval, denied create, creation race, invalid proposals and rejected legacy direct writes.
- `apps/desktop/test/developer-studio-e2e.cjs`: creation diff is displayed as inert source text; **Skip** does not approve; absent server verification disables Create.

**Do not merge or label release-ready until CI and desktop/phone manual acceptance tests complete.**

## Next milestone

Delivered in [V55](DEVELOPER-STUDIO-V55.md) as bounded agent test runs. Original plan — V55: independently approved **sandboxed test-run adapters** with true subprocess/process-group timeouts, bounded logs, safe cancellation and trustworthy pass/fail evidence. Do not add an unrestricted `run_shell` tool to the bounded agent.
