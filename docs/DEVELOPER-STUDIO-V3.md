# Developer Studio V3 — Safe Editing Lifecycle

**Milestone:** V3 of 64 · **Status:** Development / review, not production accepted.  
**Repository:** [AutoMoto AI](https://github.com/ymmiah/AutoMotoAI) · [V3 PR #56](https://github.com/ymmiah/AutoMotoAI/pull/56) · [Notion milestone](https://app.notion.com/p/4131cc3365d6812d9c5aea213caed732)

## Scope and implementation

V3 builds on V1's local-only authenticated project sandbox and V2's offline Monaco editor, trust, encoding, SHA-256 preconditions and atomic existing-file saves. It does not introduce a separate cloud editor or permission mechanism.

- **Editing lifecycle:** Native Monaco per-file undo/redo, Alt+Click multi-cursor, split editing (both panes share the same tab model), keyboard editing, tab state and mobile accessible textarea fallback. Split editing does not bypass trusted-project restrictions.
- **Diff review:** Confirmed local-only API compares the source on disk against unsaved working-copy text, with exact original checksum, bounded unified diff and a text-only safe UI (no execution or HTML interpretation). A changed disk checksum produces HTTP 409 rather than a misleading diff.
- **File creation:** Explicitly confirmed empty source creation below an approved, trusted project; parents must already exist. Atomic O_EXCL means existing files cannot be replaced.
- **Rename:** Existing-source SHA-256 expected value, no-clobber hardlink to destination and verification before removing the old pathname. Unsupported filesystems fail closed; existing destination is never overwritten. Source files are not run.
- **Recoverable archive:** A verified private copy of an existing source is written and fsynced before its original name is removed. Recovery is manual, authenticated, explicit and no-clobber; it stages an exact copy before making it visible using an exclusive hardlink.
- **Crash recovery snapshots:** Private local unsaved working copies, SHA-256-anchored to the opened file, kept under the AutoMoto home directory with restrictive permissions and a maximum of three snapshots per source path. Save Recovery is explicit; optional Local Recovery uses an 8-second idle debounce and requires consent for the current session. Opening a recovery copy does **not** overwrite the disk file.
- **Safety:** All V3 routes call V1's local-only authorisation and path guard, and all mutations require the currently trusted exact project and `confirmed: true`. Existing V2 save semantics remain authoritative.

## How to use

1. Start AutoMoto locally and open **Developer Studio**. Select an already approved project root.
2. Open a file. Review in untrusted mode; explicitly trust the project only before editing or file operations.
3. Use Monaco **Undo**, **Redo** and **Split**. Alt+Click adds cursors; ordinary editor keyboard shortcuts remain available.
4. Modify a source file and use **Review diff** to inspect changes against the last disk version. If the underlying file has changed, the diff will be rejected instead of displaying stale evidence.
5. Choose **Save recovery** to preserve an unsaved working copy privately without modifying source, or enable **Local recovery** for periodic snapshots. Select **Recover** after a crash/restart to load a copy as *unsaved* text; review before using V2's existing confirmed Save.
6. Under Explorer, use **New**, **Rename** or **Archive** only after resolving dirty editor tabs. Archive is reversible: use **Restore** and supply the project-relative path. A new or existing file with that path is never silently overwritten.

## V3 endpoints

| Method | Path | Outcome |
| --- | --- | --- |
| POST | `/api/developer/studio/operation` | `create`, `rename` or `trash`; requires trust + confirmation |
| POST | `/api/developer/studio/restore-trash` | Confirmed no-clobber restore from local private archive |
| GET | `/api/developer/studio/trash-archives` | List private archive identifiers for a specified project-relative path |
| POST | `/api/developer/studio/diff` | Review bounded source-versus-working-copy differences without writes |
| POST | `/api/developer/studio/snapshot` | Save a bounded private crash recovery copy, never source edits |
| GET | `/api/developer/studio/snapshots` | Discover up to three retained recovery copies |
| GET | `/api/developer/studio/recovery` | Retrieve private unsaved text; never auto-restore to disk |
| POST | `/api/developer/studio/discard-snapshot` | Explicitly discard one private snapshot |

The path and expected SHA-256 are validated on the server for each operation. The browser's project selector and trust badge are *not* security authority.

## Integrity, privacy and crash behaviour

- Source file operations are limited to regular, small source files within approved project boundaries. Symlink/junction paths, restricted names, relative traversal, untrusted projects, missing expected checksums and ambiguous destinations are rejected.
- V2's existing file saves still use a sibling temporary file, fsync, original checksum/inode check and atomic replacement.
- Recovery snapshots are private to the AutoMoto home folder, outside the source project; files and folders use restrictive local permissions on POSIX. Snapshots can contain secrets present in source files, so automatic snapshots require explicit consent. The UI does not upload them.
- A crash during private snapshot writing leaves the previous committed records intact; staged temporary records can remain and should be cleaned by a future maintenance cycle. A crash during a no-clobber restore cannot publish a partially written destination because the destination is linked only after fsync completes.
- Archive and rename are not guaranteed to be atomic as a *multi-step transaction* on every filesystem. There may briefly be two hardlinked pathnames during rename; an externally raced, independently mutating process can still require manual reconciliation. Do **not** claim full cross-process transactional safety.
- V3 does not perform recursive directory deletion, bulk editing, force overwrites, Git modifications, command execution, auto-recovery to disk or irreversible delete.

## Quality gates

CI must pass the repository's full Python 3.10/3.13 matrix on Windows/macOS/Linux, browser UI with real Monaco, desktop packaging, installers, security, Office, Docker, VS Code and docs.

Additional manual acceptance is required for network drives, real Windows rename/hardlink policies, external filesystem race conditions, crash injection, permissions/ACLs, keyboard/IME, screen-reader operation, multi-cursor and split layout, 320px fallback, stale source recovery and disk-space exhaustion. A CI-green draft is not sufficient evidence for production release.

Run focused tests:

```sh
python -m pytest -q tests/test_developer_lifecycle.py tests/test_developer_editor.py tests/test_developer_studio.py
cd apps/desktop && npm run test:ui
```

**Next milestone after acceptance:** V4 — Project Navigation & UX. No hosted editing, Store publication or source execution is authorised by V3.
