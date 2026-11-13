# AutoMoto AI — Developer Studio V10: Bibliography & Citations

**Milestone:** Phase 3, V10/64 · [Notion tracker](https://app.notion.com/p/4131cc3365d681919531c8d587d39a30)

**Dependency:** V9 is merged into the Developer Studio V6 development branch. V10 is a dependent feature branch, not a mainline release.

## Implemented

V10 adds authenticated, local-only citation preflight and explicitly requested DOI metadata checks to the V9 multi-file LaTeX thesis workspace.

- Scans locally referenced BibTeX and BibLaTeX .bib files within approved project roots. Uses bounded, nested-brace-aware literal parsing for standard fields; supports quoted values, comments, entry types and BibLaTeX date fields.
- Compares cited keys from the V9 LaTeX graph with parsed bibliography keys. Reports missing citations, duplicate keys, malformed entries/DOIs, missing author/title/date, obvious placeholder metadata and incomplete scans. It does not silently fabricate missing references.
- Detects basic BibTeX and BibLaTeX/Biber source configuration **statically**, including an explicit backend=biber option. Lists separately installed bibtex, biber, texlab, latexmk and tectonic executables found on PATH without executing them or claiming version compatibility.
- For an individual operator-selected citation with a valid DOI, an explicit **Check DOI with Crossref** action contacts the fixed Crossref Works API endpoint over HTTPS. Only the DOI is sent; no thesis, project file, prompt or user account information is uploaded by this action. Redirects, oversized responses and unexpected DOI results are rejected. A Crossref response is bibliographic registry metadata, not proof that a paper exists as described or has undergone peer review.
- Temporarily caches a bounded amount of DOI registry evidence in engine memory, scoped to exact project filesystem identity, with a 30-minute TTL. No verified metadata is written to project files or persisted as a permanent trust grant.
- Provides clearly labelled **illustrative** Harvard and IEEE bibliography previews using local literal metadata. Incomplete/placeholder/contradictory fields are rejected. Neither exact institutional Harvard variants nor IEEE numbering after real TeX macro expansion are certified. A full BibTeX/Biber/CSL render and publication audit remain separate.
- Integrates with the existing editor as a responsive, accessible bibliography panel. Tool results, reference text and Crossref metadata render as inert text. Browser confirmation is separate from registration and static preflight. No automatic network lookup, file write or TeX compilation occurs.

## API

- POST /api/developer/studio/bibliography/preflight — project, main, optional active_path and active_text. Returns bounded structured bibliography entries, source fields, citation use, unresolved and duplicate keys, diagnostic issues, registry evidence status and explicit not-publication-ready flags.
- POST /api/developer/studio/bibliography/verify-doi — same project scope plus a unique citation key. The only route that contacts Crossref. Validates returned DOI and conservatively compares title, publication year and first author surname; reports possible discrepancies without claiming publication authenticity or peer review.
- POST /api/developer/studio/bibliography/format — project, main, key and style (harvard or ieee). Returns a read-only copy-ready preview only when locally recorded fields pass the basic checks; no network access.
- GET /api/developer/studio/bibliography/styles — preview formats and limitations.
- GET /api/developer/studio/bibliography/toolchains?project=... — non-executing discovery of installed bibliography/TeX tool names. Does not check versions, run Biber or install packages.

All routes use the existing Developer Studio local-only authorisation and approved project root protection; hosted routes remain default-denied. External DOI lookups require a separately confirmed click and do not run project commands. Crossref metadata is used as evidence only, not treated as guaranteed accuracy.

## Supported input and limits

The parser accepts bounded common BibTeX/BibLaTeX literal entry forms, including nested braced titles, quoted values, author fields, year/date, journal/journaltitle, volume, issue/number, pages, DOI, publisher and common publication types. It rejects malformed entries/fields and unsupported string concatenation, rather than inventing expanded values. BibTeX string macros, @preamble evaluation, complex TeX transformations, xdata/crossref inheritance, BibLaTeX sourcemaps and highly specialised name/date syntax are not implemented in V10.

Source boundaries inherit V9 limits: 64 included .tex files, 96 KiB per source, 2 MiB aggregate, and approved-root traversal. V10 bibliography parsing is additionally bounded to 200 records, 120 returned findings and 96 KiB per .bib input; read failures, external symlinks, generated/private paths and oversized items are not followed. Partial scans are clearly labelled.

DOI lookup uses the fixed HTTPS Crossref Works API hostname with a 5-second timeout, disabled redirects and 256-KiB maximum response. It performs no scraping, citation synthesis or automatic retries. DOI labels and metadata are validated and escaped; external response text cannot become executable HTML.

**Scholarly integrity:** Existence of a Crossref record does not prove the work is genuine, peer reviewed, the publisher is reputable or the citation is accurate. V10 flags some suspicious metadata but cannot definitively classify all invented, retracted, predatory or misattributed publications. Academic authors must still check the original publication, publisher and required referencing style.

## Automated tests

tests/test_developer_bibliography.py exercises real nested/quoted bibliography parsing, comments and BibLaTeX date values; missing and duplicated citations; placeholders, malformed DOIs and unsupported concatenation; explicitly mocked Crossref responses and DOI mismatch rejection; per-project memory-only evidence; Harvard/IEEE preview boundaries; local/hosted security; symlinked bibliography blocking; unsaved content; and bounded parse behaviour.

apps/desktop/test/ui-smoke.cjs uses the real browser UI and API to confirm local preflight/formatting cause zero external DOI requests, a rejected confirmation causes no request, an accepted confirmation sends exactly one mocked lookup, registry text is rendered inertly and bibliography files remain unchanged.

## Remaining acceptance

Exact-head CI on Python 3.10/3.13 for Ubuntu, Windows and macOS, real browser regression, Office/VS Code/security/Docker and packaging checks, plus Windows desktop and docs builds must pass. Real Crossref connectivity and genuine DOI record comparisons with recorded provenance, independently approved Biber/BibLaTeX compilation, project-specific Harvard/IEEE guidelines, human scholarly inspection, accessibility and security review are mandatory for Verified.

## Rollback

Remove the V10 router and UI mount to return to V9. V10 has no project migrations or file writes; DOI evidence expires in memory or can be cleared by restarting the engine. Existing V1–V9 editor, academic source and user data remain unchanged. No mainline merge, TeX compilation, store publication or production deployment is part of V10.
