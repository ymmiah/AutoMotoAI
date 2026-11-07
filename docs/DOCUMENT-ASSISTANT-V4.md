# Document Assistant v4 — Professional Publishing

**Scope:** polished document templates, author-owned bibliography, Harvard/IEEE citations, cover pages, headers/footers, a contents field and real Word publication checks. No new cloud dependency, source overwrites or Microsoft Store publication.

## Templates

Four original, locally bundled document outlines are available under **Professional publishing → Document template**: Academic report, Business proposal, Meeting minutes and Formal letter. These contain visible placeholders, not names, amounts, research results or fabricated citations. Applying a template requires explicit confirmation and is Undo-capable. The selected template is only a source scaffold; there are no external template downloads.

## Human-supplied references

The source library is entirely supplied by the author, up to 60 entries. Each needs a unique lowercase identifier, author(s), year and actual title. Optional journal/publisher/volume/issue/pages/DOI/HTTPS URL/access date are validated server-side.

Insert a citation using **Insert citation** in the reference library, which adds a plain-text `[@identifier]` marker to the source. On DOCX/PDF export:

- **Harvard:** marker becomes `(Author label, year)` using the exact author details supplied. The bibliography is sorted by author/year and uses the existing Harvard Office renderer.
- **IEEE:** marker becomes `[1]`, `[2]` and so on, numbered in *first citation order*, and the bibliography uses precisely matching reference numbers.
- Unknown, malformed or duplicated reference markers are rejected before publication, rather than guessed or silently removed.
- Uncited reference entries are included and reported as warnings. The author must check that all source information, links and interpretations are authentic.

References are part of **v3 native-draft schema**, preserving all previous v1/v2 document drafts. Reference IDs and author-supplied source data survive reopening. No source resolver, model citation generator or automatic online lookup is used.

## Professional layout

An optional cover page records only the author/institution/date actually provided. Entered page headers/footers and existing Word page-number fields are preserved. A contents page uses an actual Word TOC field. If local LibreOffice is available, page positions are derived from a locally rendered temporary PDF before rebuilding the document; otherwise the user must update the TOC field in Word and warnings explain that page numbers are not ready.

## Real publication preflight

Select **Check Word publication** before exporting. This runs `POST /api/documents/preflight` behind the existing session and request-rate checks. It creates a real DOCX in a temporary folder, validates the output via existing Office document inspection, and reports headings/tables/reference counts and any outstanding warnings. It does **not** create a saved artefact or modify any imported document.

A successful preflight validates structural output, **not** factual correctness, pagination, copyright, source authenticity or print appearance. Word/PDF export remains explicit. PDF publishing requires installed local LibreOffice.

## Privacy and security

- No automatic remote resource fetch, insecure citation URL or dynamic templates.
- Strict server-side Pydantic models, bounded names, IDs, year syntax, DOI/HTTPS validation, reference limits and cited-source matching.
- User input is rendered only as document data, not executed HTML or instructions.
- Every publication is a new file under the user's own Document Assistant folder.
- Existing offline AI review remains optional and separate; it never creates or edits citations.
- Imported Word/PDF/Excel/PowerPoint files remain read-only in this workspace unless an explicitly approved copy-only operation applies.

## Tests and review

`python -m pytest -q tests/test_document_publishing.py tests/test_document_workspace.py tests/test_office.py`

`cd apps/desktop && npm run test:ui`

CI must pass Python on Windows/macOS/Linux, Office, security, browser smoke, Docker, docs, installers and Windows build. Tests verify physical DOCX properties, Harvard/IEEE reference ordering, all templates, invalid citation rejection, create-only drafts, real preflight without saved output, and full browser publishing flow.

## Next stage

**v5** focuses on rich Word editing and import fidelity: non-destructive document-structure editing in true DOCX, tracked source checksum, images, tables, header/footer preservation and a tested editable-copy pathway. Do not advertise full Microsoft Word-compatible round-trip until validated on representative real-world documents.

**v7 remains the stop milestone.** No Microsoft Store publication or further feature versions are authorised after validated v7.
