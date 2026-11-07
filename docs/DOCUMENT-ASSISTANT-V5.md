# Document Assistant v5 — Structure-Aware Word Copy Editing

**Development milestone; no production or Microsoft Store release.**

This milestone adds a non-destructive editing path for imported, genuine `.docx` files. Previous Markdown drafting, publishing templates, Harvard/IEEE references and local AI suggestions remain available.

## Real Word editing actions

After opening a Word file in Document Assistant, expand **Advanced Word copy editing**. A structural inspector loads visible body paragraphs, individual text runs with bold/italic properties, Word style names, real table rows/cells, image count and section count.

The supported operations are deliberately explicit and bounded:

- **Replace a text run:** edit the selected exact `python-docx` run. Other runs, fonts, inline images, surrounding text, paragraph styles, headers and tables remain untouched.
- **Change paragraph style:** choose Normal, Title, Subtitle, Quote or Heading 1–6. The entire paragraph's text and run formatting are kept.
- **Edit a simple table cell:** replace a single paragraph's existing text while retaining its first run formatting. Complex merged or multi-paragraph cells are refused rather than destructively flattened.
- **Append a simple table row:** provide one value per existing column. Tables with merged cells, more than 12 columns or 100 rows are refused. Newly appended row styling may need manual review.
- **Insert an uploaded image:** choose your private PNG/JPEG (max 8 MB and 24 megapixels), select a body paragraph and insertion width. The new image is inserted after that paragraph in the copy. Existing images remain intact.

The API permits a short, explicitly declared batch of operations (up to 15), while the v5 browser interface exposes a single approved operation at a time to reduce accidental changes.

## Source preservation

Every edit is copy-only. The client supplies the source file path and SHA-256 digest from the authenticated structure inspector. The API verifies that the file belongs to the current user's `uploads/` or `artifacts/documents/` tree, rejects symlinks/outside paths, scans Office ZIP contents for excessive expansion and malicious parts, refuses macros and digital signatures, and rechecks the original digest before committing a new file.

The source remains byte-for-byte unchanged; revised `.docx` files receive unique, create-only paths. All operations are validated against the current original run/paragraph/table structure. A stale source, incorrect expected text or unsupported formatting is rejected before any output is published.

The revision is saved only after `python-docx` successfully serialises a real Word package, the Office inspector passes again, and a second Word parse succeeds. It does not fetch external images, execute macros, contact AI models or write over an original document.

## Limitations

This is **not** a 100% fidelity Microsoft Word clone or a desktop WYSIWYG document editor. Unsupported complex structures (tracked changes, fields, merged cells, content controls, signing metadata and advanced table layouts) need editing in Microsoft Word or other compatible office software. A simple run replacement preserves ordinary formatting but may affect field-heavy paragraphs; the user should check every revised copy before publishing. Page previews still require a local rendering engine such as LibreOffice/Poppler; layout comparison remains advisory, not a claim of pixel-exact fidelity. A `.docx` with third-party extensions may have compatibility issues even if it opens.

## Verification

- `python -m pytest -q tests/test_document_rich.py tests/test_document_workspace.py tests/test_document_publishing.py tests/test_office.py`
- `cd apps/desktop && npm run test:ui`
- Full Windows/macOS/Linux Python regression matrix, real Word output and source checksum invariants, security checks, browser UI, installer and Windows app smoke.

Tests cover genuine mixed bold/italic run editing, original header/footer and image preservation, table and style changes, image insertion, stale-source hashes, imported-file path restrictions, macro-laden OOXML refusal, invalid/broken image rejection, and unchanged source bytes.

**Next:** v6 will focus on long-document evidence retrieval and offline academic work. Stop major Document Assistant feature additions once v7 has completed and passed acceptance tests; Microsoft Store publication is still deferred.
