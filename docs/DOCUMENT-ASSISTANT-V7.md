# Document Assistant v7 — Final Reliability and Acceptance Milestone

**Scope:** This is the seventh and final planned Document Assistant development milestone. AutoMoto AI's broader modules remain independent. **Microsoft Store publication is expressly deferred.**

## What is added

### Private, opt-in document recovery

Under **Document safety → Recovery and publication readiness**, the user can save a private recovery point or explicitly enable automatic recovery while editing. Automatic recovery is **off by default** and applies only to this editing session. When enabled, a new checkpoint is created after 15 seconds without an edit. The feature does not synchronise to the cloud, fetch external sources or use an AI model.

Each recovery snapshot records the original editable Markdown, document title, page/typography settings and publication/reference metadata in a **checksum-verified, write-once** JSON file. At most 16 checkpoints are retained in the user's private `artifacts/documents/recovery/` directory. Saving a new checkpoint succeeds before old checkpoints are pruned. Invalid, oversized, corrupted, symlinked or out-of-workspace checkpoints are rejected. Saved native document drafts and imported Word/PDF documents are never overwritten.

The recovery list offers **Restore into editor** and **Delete checkpoint** actions. Both require explicit confirmation where destructive/conflicting data is possible. Restoration loads recovered text and settings into the editing surface, creates an Undo/Redo history entry and requires a separate **Save draft** action to persist a new native document. This is **not** an automatic overwrite or silent recovery of an imported Office file.

### Read-only publishing acceptance audit

**Run document acceptance audit** validates the actual Word XML generation via the pre-existing, temporary DOCX preflight engine, without saving a document or contacting remote services. A separate deterministic editorial audit identifies:

- Missing or skipped heading levels that may harm navigation and accessibility.
- Inconsistent column counts in Markdown tables.
- Possible unresolved document template placeholders.
- Missing author details on selected cover pages and a missing source library on the academic template.
- Page-numbering and long-source review reminders.

The report gives concrete Word document structure counts, editorial warnings and a checklist of what still requires human verification. It does **not** claim that quotations, research facts, licences, mathematics or printed pages are verified simply because the file opens.

### Security and performance boundaries

- Private authenticated, request-limited `POST /api/documents/recovery/save`, `GET /list`, `GET /load`, `DELETE /{id}` and `POST /api/documents/quality/audit`.
- Recovery IDs are opaque 24-digit lowercase hex strings. File paths are generated server-side, confined to the private Document Assistant folder, never accepted from the client and never used to replace an existing document.
- The saved source's canonical UTF-8 SHA-256 is verified before restoration.
- Model validation forbids unexpected fields and retains existing document size, page-setting and reference-library limits; checkpoints have an additional 750 kB cap.
- Automatic recovery is disabled unless manually opted in; a short debounce and unchanged-content check prevent duplicate checkpoint writes.
- Recovery is not included in the normal document library. The user can delete checkpoints individually.
- The audit uses the existing real OOXML builder in a temporary directory and saves no user files.

## Acceptance and verification

The project should not be described as production-ready based only on a version number. Required automated gates:

1. Python tests across Ubuntu, macOS and Windows (Python 3.10 and 3.13), including all existing document workspace, rich DOCX, local AI, academic source retrieval, Word publishing and security regressions.
2. Actual `python-docx`/OOXML Word export and original-file hash preservation.
3. A browser-level UI test for recovery save/restore, optional auto-save, genuine preflight, deleted checkpoint and Undo/Redo after recovery.
4. Security, Visual Foundation, Docker and UI checks, plus installers and separate Windows app smoke.
5. Documentation build and an explicit pass/fail summary in PR.

Additional manual release checks remain essential: visual inspection of rendered Word/PDF pages; keyboard and screen-reader walkthroughs; LibreOffice/Word fidelity assessment on documents with complex fields, tables and images; actual local Ollama runtime test, and crash/low-storage simulations on intended hardware. These cannot be claimed complete solely through mocked CI tests. Unsupported complex DOCX operations remain explicitly out of scope, as documented in v5.

## Instructions for using recovery

Open Document Assistant → **Document safety**. Select **Save recovery point** once, or enable **automatic private recovery** to capture future editing changes. To recover, press **Restore into editor** beside a checkpoint, review the restored contents, and **Save draft** to create a new independent document. To remove retained private data, delete each checkpoint using the accompanying button. Do not assume deleting a checkpoint deletes previously published DOCX/PDF files.

## Feature freeze

Upon passing the required automated gates, completing the available user-facing quality review and merging the v7 PR, **stop major Document Assistant development**. No v8 and no Microsoft Store publication follow from this instruction. Any unverified manual or hardware checks must be transparently reported rather than marked complete.
