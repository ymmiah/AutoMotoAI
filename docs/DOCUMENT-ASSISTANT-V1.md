# AutoMoto AI — Document Assistant v1

**Status:** development milestone only. No Microsoft Store publication or public release.

Document Assistant is a dedicated, responsive workspace integrated into AutoMoto AI's desktop navigation, command palette and Files page. It reuses the pre-existing security-checked Office processing engines instead of rebuilding them.

## Included in v1

- **Document library:** lists supported source files in `uploads/` and app outputs in `artifacts/documents/`. Use search, open, refresh, new document and import.
- **Editable source documents:** Markdown-based editor with heading, bold, list and quote shortcuts, exact original source, a safe local writing preview, character count and save-as-new `.document.json` revisions. The preview escapes source HTML, has no external imagery, and is explicitly an approximation rather than a print proof.
- **Native Office publishing:** generate real, editable Word `.docx` documents using existing `office_build`; publish PDF through the existing locally installed LibreOffice converter when available. New exports are separate files, not edits to uploaded originals.
- **Imported document inspection:** read `.docx`, `.pdf`, `.pptx` and `.xlsx` in **read-only extracted-text mode**, with page preview through the existing authenticated file-preview endpoint where local rendering tools are available. Preserve the original file for download. Import `.md` and `.txt` into the editable source editor; saving creates a fresh draft.
- **Safe Word copy revision:** optional exact find-and-replace for imported DOCX or a previously published DOCX. Requires explicit confirmation and the original SHA-256 hash. Creates a new DOCX, refuses stale originals or absent phrases, and never overwrites the source.

The browser has a dedicated Document Assistant sidebar entry and a Files → **Open in Documents** hand-off. The existing file-upload API performs untrusted OOXML ZIP, XXE, macro and external-link inspections.

## API

Authenticated, per-workspace endpoints:

- `GET /api/documents/list` — discover supported user-owned documents.
- `GET /api/documents/open?path=...` — open native draft/editable UTF-8 text or read-only extracted Office/PDF content.
- `POST /api/documents/save` — create-only, bounded native Markdown draft.
- `POST /api/documents/export` — publish a new DOCX or locally converted PDF.
- `POST /api/documents/replace-copy` — copy-only DOCX exact text revision with source checksum precondition.

Hosted-mode permissions are explicitly allowlisted. Document processing is rate-limited and limited to the private `uploads/` and `artifacts/documents/` trees. Source text is bounded to 120,000 characters, previews to a limited extract, and opened files to 20 MB. Output quotas follow the existing multi-user storage policy.

## Scope and known limitations

This is **not** a pixel-perfect Office clone or a lossless Word layout editor. Editable documents use Markdown as their native source and DOCX is a publishing output. Complex imported DOCX, PPTX, XLSX and PDFs remain read-only in this workspace, while the existing Office agent tools still support more advanced operations separately.

Exact copy replacement on DOCX may affect text spans crossing multiple runs; it should always be manually inspected before use. Embedded Markdown image paths, untrusted remote fetches and script/code execution are not supported in v1. Scanned PDFs may contain no extractable text without OCR. PDF publishing and page raster previews depend on LibreOffice/Poppler being present locally; Word output does not. No cloud AI, new model dependency or external CDN is needed.

## Acceptance and tests

- `python -m pytest -q tests/test_document_workspace.py tests/test_office.py`
- `cd apps/desktop && npm run test:ui`
- Full Linux, Windows, macOS, Office, security, installation and Windows-app CI.
- Browser smoke: create and edit source, save/reopen a draft, generate a true OOXML DOCX, re-import and inspect it, and create a new DOCX revision after confirmation.
- Check visual screenshots, tablet/mobile layouts and output documents before merging.

**Next stages:** richer Word editing and document structure, offline local AI assistance, citations and publishing templates, then Document Assistant integration/security acceptance. Microsoft Store publication remains the final AutoMoto AI milestone.
