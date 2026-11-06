# AutoMoto Visual Studio v8 — multi-page documents and slide decks

**Development status:** feature branch `feature/visual-studio-v8-multipage-editor`, not a public or Microsoft Store release.

Visual Studio now treats a design as an ordered collection of **1–20 editable canvases**. Each page has its own independent source specification, layers, original image references, animation metadata and Undo/Redo history for the active editing session. Switching pages keeps the work on every page; saving a document preserves all pages and their names in one `schema:2` JSON draft.

## Editor workflow

1. Open Visual Studio. The first page appears in the new **Document pages** strip.
2. Select **New page** for a blank canvas with the current page's dimensions/theme, or **Duplicate page** to copy the current page's native elements without flattening.
3. Give each page a name. Select any tab to edit that page. **Move earlier/later** reorders pages without changing their native layer specifications; **Remove page** asks for confirmation and cannot delete the final page.
4. Editing, grouping, AI inspection and undo actions operate on the selected page only. Page names and page ordering are document-level changes; they do not appear in per-page Undo.
5. Select **Save draft** to save all current page definitions together. Previously saved `schema:1` single-canvas drafts remain readable, and are promoted into a one-page editing session when opened.
6. For a multi-page project, select **Editable PowerPoint** or **PDF** to export **all pages** in their current order. PPTX contains native editable text and shapes; PDF is a separate *flattened* page per canvas. Enabling **Editable layers + file** additionally saves a reloadable multi-page `.design.json` draft.
7. PNG, JPEG, SVG and animated GIF continue to export the **currently selected page only**. The interface explicitly indicates when an export includes one page rather than the entire document.

## Guarantees and limits

- Every saved/exported page undergoes the same authenticated workspace image-path checks and authoritative structural/contrast/text-fitting checks as the existing single-page editor.
- The source image files are never rewritten during rendering. PPTX keeps text and shape objects native; source raster images remain inserted image objects. PDF is intentionally flattened (not a native editable design document).
- A multi-page document is limited to **20 pages**, **512 KiB of JSON**, and the existing per-page 48 KiB and canvas/element quotas. Storage quotas remain enforced in hosted mode.
- A failed page validation blocks the **entire** multi-page save/export. A failed export cleans partial output and sidecar files.
- Page-specific Undo/Redo history is in memory only. Saving/reopening retains exact native content and ordering, not editing-history stacks.
- Each page remains one independently editable canvas; **master pages, global brand styles, arbitrary slide transitions, editable multi-page PDF objects and cross-page drag-and-drop** are future development tasks.

## Endpoints

- `POST /api/visual/studio/document/save`: save a `schema:2` draft.
- `POST /api/visual/studio/document/export`: export ordered pages as `pdf` or `pptx`.
- Existing `GET /api/visual/studio/list` and `GET /api/visual/studio/load` now accept both legacy `schema:1` drafts and multi-page `schema:2` projects.
- Existing single-page preview, repair, offline Ollama design review and image/GIF exports remain unchanged.

## Validation

Run `python -m pytest -q tests/test_visual_documents.py tests/test_visual_studio.py tests/test_visual_repair.py` plus `cd apps/desktop && npm run test:ui`.

Tests verify a real four-page PDF, native editable three-slide PowerPoint, all-page draft reopen, stable page order, original-image hashes, hidden/locked metadata, unauthorised requests, invalid secondary pages, forbidden paths and compatibility with legacy single-page draft files. Playwright exercises the real editor page tabs and multi-page export flow.

**Release policy:** This increment is a GitHub development pull request only. Microsoft Store submission and public application publication remain deferred until the remaining AutoMoto AI milestones are completed and accepted.
