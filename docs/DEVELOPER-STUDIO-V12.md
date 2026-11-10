# AutoMoto AI — Developer Studio V12: Typst, Quarto & Research Studio Hand-offs

**Milestone:** Phase 3, V12 of 64. Notion: https://app.notion.com/p/4131cc3365d681d18ec4c73d179414bb

**Dependency:** V11 PR #64 was merged into the Developer Studio V6 development branch, with successful exact-head CI, Windows desktop and documentation workflows. V12 remains a dependent feature branch, not a release or merge into main.

## Delivered scope

V12 adds two separate, conservative manuscript workflows. It does not claim TeX, Typst and Quarto have interchangeable rendering engines, citations, macros or project formats.

### Typst and Quarto static project intelligence

- Inspect existing project-local Typst (.typ) and Quarto (.qmd) source files, including bounded local Typst includes and Quarto QMD/Markdown include directives.
- Discover headings, citations and local BibTeX targets through V10's bounded bibliography parser. Identify unresolved keys, duplicate keys, placeholder metadata, unreadable or unsafe included files, and incomplete scans.
- Mask common Quarto executable code fences, Markdown inline code, HTML comments and Typst comments for lexical citation search. Warn about executable Quarto code chunks. Never execute any Quarto cell.
- Support unsaved manuscript buffers without rewriting project sources. Preserve source locations as UTF-16 offsets for later editor navigation.
- Detect installed Typst, Quarto and Pandoc tool names on PATH without running version commands, downloading dependencies or rendering source.
- Preview original, copy-only Typst and Quarto document scaffolds. The Quarto starter includes execute.enabled: false, but external Quarto rendering remains a separately assessed risk.

Limits: 32 source files, include depth 8, 96 KiB per text file, 1 MiB aggregate source and bibliography budget, 12 local bibliography references and 120 returned items per category. Restricted, linked, hidden and outside-project paths remain excluded through the existing V1 and V7 source reader. No file mutation, network calls, code execution or automatic build.

Static scanning is not semantic Typst parsing, full YAML/Quarto interpretation, Pandoc/CSL rendering or proof that a manuscript will compile. Template source must be edited and reviewed by the author.

### Existing Research Studio provenance-preserving hand-offs

V12 uses existing, saved Research Studio V6 developer hand-off audits, not fabricated evidence. At preview and again at export, it:

1. Validates the private hand-off audit and exact SHA-256.
2. Checks the original developer hand-off draft file and its recorded SHA-256.
3. Calls the original Research Studio V6 source revalidation, itself based on the V3 comparison with original source fingerprints and human-reviewed AI decisions.
4. Rejects changed original sources, changed audit/draft, mismatched human review, or non-developer transfer targets.
5. Produces an original manuscript.typ or manuscript.qmd starter and a separate evidence.review.json. All original source paths/checksums, comparison identity, exact extracted excerpts and human reviewer labels remain in the JSON. No quotation is automatically turned into executable source or an unsupported manuscript claim.
6. Optionally accepts exactly one Research Studio V4 confirmed Crossref metadata association per original source. It reuses V4's saved-record fingerprint and source-to-publication identity validator, plus explicitly confirmed same-publication association. Without this complete review, it does NOT create a bibliography or citation keys.
7. When full V4 associations exist, produces conservative references.bib records with deterministic DOI-derived citation keys. Records containing BibTeX-control metacharacters or other unsupported metadata are rejected for manual handling instead of guessing or dangerously reformatting.
8. Lists SHA-256 for every package member in a review-only manifest. Explicitly confirmed ZIP export reruns source revalidation before assembling the short bounded archive in memory.

A hash establishes equality to a selected source; it does not prove scientific correctness. A Crossref record does not prove peer review, publication authenticity or absence of retraction. Review quotations, copyright, methodology, publisher, DOI, claim validity and institutional referencing style before use. No source files are overwritten or published.

### Authenticated local-only API

- POST /api/developer/studio/manuscripts/scan — read-only project inspection.
- GET /api/developer/studio/manuscripts/toolchains — installed-name detection only.
- POST /api/developer/studio/manuscripts/starter — copy-only Typst/Quarto starter.
- GET /api/developer/studio/research-transfer/handoffs — saved source-reviewed developer hand-offs.
- POST /api/developer/studio/research-transfer/preview — hand-off source revalidation, optional V4 bindings, copy-only package files.
- POST /api/developer/studio/research-transfer/download — same with literal confirmed=true and acknowledge_not_publication_ready=true, producing a ZIP for explicit local download.

Hosted-mode permissions remain default-denied. No new database migration, AI model, external metadata call, background process, third-party account write or automatic compilation was added. UI renders untrusted source text in inert controls, not executable markup.

### Tests and release acceptance

tests/test_developer_manuscripts.py exercises real nested Typst, Quarto and BibTeX files plus an authentic Research Studio V1→V3→V6 hand-off through existing APIs. It checks the exact source fingerprints, review ZIP manifest, changed research record and source rejection, citation-binding literal safety, bounded code-cell scans, source-path traversal and hosted access denial.

The desktop browser smoke checks the UI's static scan, starter previews, tools without execution, no Crossref use, inert review text and separate approval for ZIP exports.

Remaining required acceptance includes exact-head Python 3.10/3.13 CI on Ubuntu, Windows and macOS; browser UI, security, Office, Docker, VS Code, visual foundation and installers; Windows desktop and docs builds; installed Typst/Quarto/Pandoc compatibility and rendered manuscripts; real bibliography and original DOI/source checks; keyboard/screen-reader accessibility; and independent security review. Quarto and Typst execution is deliberately not enabled in this milestone, so live rendering is not claimed.

**Status policy:** Review after implementation and automated-test evidence; Verified only after all manual and scientific/toolchain gates. Never merge into main or publish automatically.

### Recovery

Remove V12's routers and Developer Studio panel to return to V11. No persistent V12 state, source edits or migrations are involved. Downloaded review ZIPs remain under user control; deleting one does not alter the original research.
