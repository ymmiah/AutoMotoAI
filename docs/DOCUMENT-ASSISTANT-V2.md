# Document Assistant v2 — Structured source editing and publication settings

**Development-only milestone.** No Microsoft Store submission or production release.

## Added to the existing Document Assistant

- Six levels of **Markdown headings**, changed in place and shown in a clickable outline with source navigation.
- **Markdown tables**: insert a native, three-column table or add another editable row to a table containing the caret. Tables appear as readable, safely escaped HTML in the approximate writing preview and are exported as real editable Word tables with a header row.
- **Page and typography controls**: A4/Letter paper, portrait/landscape orientation, margins from 1.2–4 cm, six allowlisted fonts, body text 9–16 pt, line spacing 1–2, six-digit heading colour and optional page numbers. The Word publishing engine applies these settings to actual OOXML page sections, fonts, heading styles and footer fields.
- **Undo/Redo** of document text, title, formatting and layout preferences, including Ctrl/Cmd+Z, Ctrl+Y and Ctrl/Cmd+Shift+Z. Typing actions coalesce within 700 ms and history is limited to 80 revisions, with a new history for each opened draft.
- **Persisted settings** in a backwards-compatible v2 Markdown draft. Existing v1 source drafts remain readable with default A4 settings and can be re-saved without overwriting originals.

## Safety and quality constraints

The editor remains **source-first**, not a pixel-perfect WYSIWYG Word clone. The writing preview is a typographical approximation, not a pagination or print proof. Its HTML is derived from escaped source text only; embedded scripts, external images and active content are not executed. Only the server's `office_build` engine determines final Word layout.

Untrusted options are rejected server-side with explicit allowed values, finite number ranges and no unknown fields. Drafts and exported documents are create-only in the existing user-isolated workspace. The original Office/PDF import remains read-only; explicitly authorised DOCX find-and-replace still creates a separate copy with an original SHA-256 precondition. No additional cloud model or service dependency is introduced.

## Verification

- `python -m pytest -q tests/test_document_workspace.py tests/test_office.py`
- `cd apps/desktop && node test/document-editor-model.cjs`
- `cd apps/desktop && npm run test:ui` (pure model tests and Playwright)
- Full CI across Windows, Linux and macOS plus Office, Visual Foundation, security and installer checks.
- Browser tests cover heading levels, table insertion and row extension, page setting changes, undo/redo and saving/reopening v2 layout metadata.
- Word engine regression covers physical Letter landscape page dimensions, margins, fonts, heading colour, table data and optional page-number footer.

**Limitations:** v2 does not offer lossless edits to imported DOCX layouts, arbitrary fonts, on-screen exact pagination, complex table-cell merging or track-changes collaboration. That scope requires subsequent engineering with additional fidelity testing.

## Next planned milestone

Document Assistant v3 will integrate optional local AI proofreading, rewriting, source-grounded summaries and controlled insertion, without external calls by default. **Microsoft Store publication remains the final AutoMoto AI milestone.**
