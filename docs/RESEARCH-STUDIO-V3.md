# AutoMoto Research Studio V3 — Evidence Comparison & Contradiction Mapping

**Development milestone 3 of 7.** Built on V1 private, source-pinned evidence projects and V2 public DOI discovery. V3 is a **human review workspace**, not automatic scientific truth detection.

## Real workflow

1. Create a V1 research project from at least two distinct source documents (PDF, DOCX, Markdown, TXT or Document Assistant drafts). Existing V2 public webpage snapshots are supported as unverified TXT sources.
2. Select the saved project under Research Studio > Compare evidence across sources. The server verifies the saved V1 project SHA-256 and checks every quotation against the *exact extracted section, page and offset* of the original SHA-256-pinned document. Changed source files, forged quotes, wrong offsets or IDs and invented PDF pages cause a fail-closed rejection. No original documents are edited.
3. Review quoted passages side-by-side, assigning one of four positions: supports, contradicts, uncertain or unreviewed. The application **never chooses a position automatically**. A reviewed position requires a rationale; unchanged excerpts default to unreviewed.
4. For every selected source, record optional reviewer-assessed methodology (experimental, observational, review, other or not assessed), subjective quality (low, moderate, high, not assessed) and methodological limitations. Missing excerpts and partial extraction are explicitly marked as coverage gaps, not negative findings.
5. Preview the comparison matrix. A disagreement is flagged only when the human reviewer labels a passage in one source supporting and a passage in a different source contradicting the claim. **That flag does not prove contradiction or determine scientific truth.** It reports only the user's classification.
6. Save a new private snapshot with explicit human-judgement acknowledgement and a confirmation action. Revalidation checks every original source, project fingerprint, quote identity and reviewer field. No source, project or prior review is overwritten or deleted.
7. Reopen historical comparisons read-only. Their source documents and the V1 project are checked for changed/missing fingerprints. Previous judgements are not silently made current.

## Source integrity, limits and privacy

- Maximum 5 sources, 8 saved evidence excerpts per source-linked V1 research project, 150 saved V3 comparisons, 100 KB per snapshot. Source-extraction page/character limits are inherited from Document Assistant.
- Read-only, source-offset-verified evidence; 100% local deterministic checks. No network, language model, invented citation, artificial position, business action, source modification or financial posting.
- Every excerpt ID must be included exactly once in the user review, even if marked unreviewed; every selected source must have exactly one source-quality record. Unknown IDs, duplicate annotations, wrong paths, unsupported values and hidden control characters are refused.
- Compare/preview/save verify original V1 project SHA-256 and reread every source. Changed files require creating a fresh V1 snapshot.
- Saved review details are checked against a recomputed internal matrix when opened. This catches inconsistencies, but does not constitute independent signed/notarised integrity.
- Metadata and source statements are untrusted. Frontend renders all user-supplied passages, titles and file names using safe text DOM methods. Internal S1-01 IDs are **not academic bibliographic citations**; verified Harvard/IEEE output belongs to V4.
- Tenant scope and authentication reuse AutoMoto's existing private workspace and origin/CSRF controls; hosted route allowlisting is exact. There are no delete/publish/auto-classify routes.

## V3 authenticated endpoints

- POST /api/research/studio/compare/prepare — load, source-verify and check quotations in a V1 two-source project.
- POST /api/research/studio/compare/preview — validate positions and methodology notes and compute a human-labelled matrix without saving.
- GET /api/research/studio/compare/list — list private saved comparisons.
- GET /api/research/studio/compare/open — read the original human snapshot, verify its internal consistency and report source freshness.
- POST /api/research/studio/compare/save — explicit acknowledgement, final source revalidation and create-only independent review snapshot.

## Acceptance and tests

Focused test suite:
    python -m pytest -q tests/test_research_comparison.py tests/test_research_studio.py tests/test_research_discovery.py tests/test_document_research.py

Full test suite:
    python -m pytest -q

Browser UI:
    cd apps/desktop && npm run test:ui

Automated tests cover real two-document quotation extraction, exact offset matches, forged IDs/quotes/offset/page/hash rejection, source/project staleness, reviewer-only labels and justifications, source-quality input limits, default unknown/uncertain status, incomplete coverage, cross-source label discrepancy, unchanged sources, create-only saves, historical comparisons, corruption refusal, hosted authentication, tenant isolation and denial of network/AI access.

Browser tests create an actual V1 two-source research project, verify excerpts, record two opposing human labels, preview, deny unacknowledged saves, save a distinct review and reopen its historical matrix. Windows/Linux/macOS Python, Office, UI, Docker, security, Visual Foundation, installers and documentation must all pass before merge.

## Outstanding requirements and roadmap

Scientific claim truth, original study methodology, dependence between studies, reviewer bias, data representativeness and scientific significance cannot be certified automatically by this component. Human inspection of original documents and manual keyboard/screen-reader testing remain essential.

V4: verified bibliographic citations, Harvard/IEEE references and report publishing. V5: optional local evidence-linked synthesis. V6: cross-studio human-approved workflows. V7: final hardening and acceptance.

**Microsoft Store publication remains deferred.**
