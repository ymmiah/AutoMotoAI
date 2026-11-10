---
name: document-assistant
description: Write a thesis chapter or report in the Document Assistant, with Harvard or IEEE references, and export a new Word file.
category: office
tools: document_open, document_preflight, document_save, document_export, document_revise, document_ai_review
status: live
---
# Document Assistant

Finish the document. Do not stop after an outline unless the user only asked for one.

1. If they attached a file, `document_open` it first. Keep `sha256`. Imported Office files are read-only.
2. Write the chapter in markdown. Citations look like `[@smith2024]`. Every id must exist in `publication.references` with the author, year and title the user supplied. Never invent a source.
3. `document_preflight` when the piece is long, then `document_export` format `docx` (or `pdf` when LibreOffice is installed). Harvard is `publication.reference_style` `harvard`.
4. Small wording changes to an existing DOCX use `document_revise` with the checksum from `document_open`. That writes a new copy. The original stays.
5. `document_ai_review` is the local model only. It returns a proposal and does not save. Do not paste the proposal back into the file unless the user asks for that edit.
6. End with the new file's path and what it contains.
