# AutoMoto AI Research Studio V4 — Academic References & Reports

**Development milestone 4 of 7.** V4 adds an author-reviewed academic report builder with DOI-backed references, Harvard/IEEE formatting, real Word build preflight and private Word/PDF output. It extends V1's SHA-256-pinned extracted source excerpts, V2's saved Crossref metadata and V3's human-labelled comparison records. It does **not** invent papers, verify peer review, validate scientific conclusions, automatically map files to publications or query external services during publication. Microsoft Store publication remains deferred.

## How to use it

1. Use Research Studio V1 to save a research project containing at least two current, checksum-pinned documents.
2. Create and save a V3 human evidence comparison. Each excerpt must have a reviewer-assigned status. A supporting, contradicting or uncertain status requires a human rationale.
3. In V2, verify the actual DOI of each selected document and save its Crossref metadata in the private scholarly source catalogue. Verify author names, publication year, article title, journal, publication status and DOI against the **actual paper** before relying on the information. A metadata record alone does not establish that the local file matches it.
4. Under V4 Academic references & research reports, select the V3 comparison and choose **Verify evidence and references**. The server rereads the original research and current source files and verifies every retained quote, saved SHA and character offset; stale/altered source files or changed V1/V3 records cause a fail-closed error.
5. For each original document, select the **matching** V2 Crossref DOI record and explicitly confirm that association. Each source must have a distinct DOI record. If the true source does not have a usable verified DOI, V4's automated source-bound formal report export remains blocked; do not assign an unrelated paper. Document Assistant already supports author-entered bibliographic details, but V4 never treats those as independently verified.
6. Enter the report title, author, optional institution, original context, interpretation, methodology limitations and a justified conclusion. Choose Harvard or IEEE. The system assembles only the source excerpts and human annotations already in V3, the entered text and DOI metadata; it does not generate external claims.
7. Run **Word & citation preflight**. The existing Document Assistant Office engine builds and validates an actual temporary DOCX without saving a report. The preview shows the structured Markdown, the formatted reference list, recorded source/metadata hashes and explicit warnings. Report exports stay blocked if any V3 excerpt is unreviewed.
8. After reviewing all evidence, source-to-DOI associations and references, tick the confirmation and approve **Save editable report draft**, **Export Word**, or **Export PDF**. Each creates a new file in the authenticated private Document Assistant workspace. Existing source files, V1 projects, V2 bibliographic metadata and V3 reviews are not overwritten.
9. PDF export requires **LibreOffice installed locally**; otherwise the existing exporter returns a clear HTTP 501, while Word remains available. Download and inspect the actual output before submitting it for academic marking or professional publication.

## Citation and provenance checks

- Every selected source is explicitly bound to exactly one saved, SHA-256-verified Crossref metadata record. References come exclusively from V2-saved metadata that were originally retrieved using a direct Crossref DOI check.
- Required bibliographic elements for an automated V4 citation: a valid DOI, title, at least one named author, an actual publication year (year-only and month-only precision retained), an offset-aware metadata retrieval time, and the correct canonical DOI URL. Missing years or authors cause a hard error. Registry creation dates are not substituted for publication dates.
- DOI record hashes, original source file hashes, V3 review hash, exact extracted quotes and character offsets are checked before preflight or export. A SHA-256 check is a consistency condition, not a digital signature: an attacker controlling the stored content and its expected digest can defeat such a check.
- Every bibliography entry is inserted with a server-generated unique reference key and resolved through the existing Document Assistant Harvard/IEEE publisher. IEEE numbers follow order of first appearance. Formatters cannot guarantee all university-specific Harvard variations or accurate surname parsing from registry display names; manually verify the final list.
- The V4 document labels source methodology, source quality, excerpt stances and outcomes explicitly as **human reviewer decisions**. Any excerpt left unreviewed keeps preflight non-ready and blocks formal export and publishable-draft saving.
- No web search, DOI recheck, remote model, online publisher or scientific validity assertion is performed during report preparation or conversion.
- V4 cannot automatically establish whether a saved document is the genuine version of the DOI paper, whether the original paper is still unretracted, or whether the author's claims follow from that paper. Its author-confirmed linkage is deliberately recorded as a declaration rather than a machine verification.

## Publication format

The generated source uses an A4 page, Times New Roman 11 pt, 1.5 line spacing, 2.5 cm margins, cover page, Word contents field, real heading hierarchy and page numbers. The Document Assistant engine generates real OOXML DOCX. When available, local LibreOffice converts Word to PDF. Document Assistant provides editable Markdown reports with stored publication options and verified-source reference markers. Any document re-editing afterwards requires a new review of references and factual claims.

The report contains research boundaries, original research question, author context, reviewer-assessed claim, source-by-source evidence and exact excerpts, original source digests, DOI and metadata retrieval provenance, stance/rationale, documented evidence coverage, author interpretation, limitations, conclusion, citation warning and generated reference list.

## Authentication, limits and privacy

- Authenticated hosted allowlisting for **only** V4 prepare, preflight, save-draft and export. No arbitrary delete, external send, online publish, automatic bibliography insertion, source-write, finance action or AI assertion endpoints.
- All workspace paths remain subject to the existing private workspace, filename, symlink, schema and maximum-size checks. A V4 report requires two to five distinct sources, each supported by a different V2 DOI snapshot.
- Report text and snippets have bounded lengths. Forbidden control characters and user/registry-generated citation markers are rejected. Generated source quotations remain anchored to V3 byte/character positions.
- UI uses safe textContent for dynamic source paths, DOI titles, author details, citation records and report previews. No untrusted source text becomes executable HTML or tool instructions.
- No secrets or financial details are sent to scholarly registries by V4. Preflight is read-only; save-draft/export create new private files.

## Authenticated API

| Method and endpoint | Purpose |
|---|---|
| POST /api/research/studio/publish/prepare | Reverify historical V3 review and original source files; list privately saved V2 Crossref metadata with exact SHA-256 |
| POST /api/research/studio/publish/preflight | Validate explicit per-source DOI assignments, compile report and build temporary DOCX without saving |
| POST /api/research/studio/publish/save-draft | Require author confirmation, create an editable Document Assistant draft with immutable source reference tokens |
| POST /api/research/studio/publish/export | Require author confirmation, create a DOCX or (with local LibreOffice) a PDF |

A publish request supplies the comparison path and SHA, author text, referencing style, and a mapping for **every** original source to a distinct V2 metadata path and its SHA. Each binding requires confirm_same_publication=true. Publishing and draft saving also require the fixed action acknowledgement and confirm_checked_references=true. The server does not trust a client-supplied citation body, bibliography, quote or verified flag.

## Testing and acceptance

    python -m pytest -q tests/test_research_publishing.py tests/test_research_comparison.py tests/test_research_discovery.py
    python -m pytest -q
    cd apps/desktop && npm run test:ui

Python tests exercise real saved V1 and V3 evidence, authentic local DOI snapshot fixtures, both Harvard and IEEE preflight, actual DOCX archive and document output, document draft persistence, missing bibliographic records, changed metadata hashes, forged citations, unsupported HTML/citation control characters, export refusal without consent, unreviewed claims, V3 source/project changes, tenant isolation, and clear PDF dependency behaviour. Real browser tests check explicit source-to-DOI selection, code-safe handling of malicious metadata titles, human confirmation, IEEE citation preview and non-destructive report draft action. Browser tests use deterministic mock metadata to avoid unrelated external service dependencies; the Python tests exercise the real backend and Office engine.

**Manual acceptance needed:** inspect actual source/DOI associations, the accuracy of every quotation and context, scholarly quality and publication status, Harvard/IEEE institutional variants, Word/PDF pagination/links, screen-reader keyboard handling, mobile layouts and metadata copyrights. Passing CI is not independent academic certification.

## Next milestones

- **V5:** approved local-only AI synthesis grounded in evidence IDs, provenance, contradictions and uncertainties; no unsupported claims or auto-source edits.
- **V6:** controlled research hand-off across AutoMoto Document, Visual and Developer Studios, maintaining references and audit.
- **V7:** research reliability, recovery, large-document limits, human accessibility and real publication release acceptance.

Microsoft Store publication remains deferred.
