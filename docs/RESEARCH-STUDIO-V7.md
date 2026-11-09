# AutoMoto AI — Research Studio V7: Acceptance, Integrity and Private Recovery

**Milestone 7 of 7 — development build only. Microsoft Store submission and new application release are NOT authorised by completing this milestone.**

This final development milestone adds a read-only, source-revalidating Research Studio acceptance audit and explicit private recovery workflow. It does not claim that academic research is scientifically true, that all metadata or references are correct, or that a passed CI matrix is sufficient to release a commercial application.

## What is shipped in V7

**Evidence chain revalidation.** The user selects a completed, original-source-pinned V3 comparison and, optionally, a V5 human-reviewed local AI proposal and a V6 cross-studio transfer. The server uses the actual V3/V5/V6 verification functions, reopens original project/source records, checks SHA-256 fingerprints and exact evidence quotations at the saved extraction offsets, and verifies each applicable human decision. A V6 hand-off is checked against its original reviewed evidence and saved destination file digest. Changed or invalid records fail closed.

**Bounded recovery copy.** After the user reviews the audit and explicitly confirms, a private create-only ZIP archive stores selected verified original files, comparison, project and any selected reviewed AI and hand-off documents. Each contained file retains its original logical path, role, SHA-256, byte count and a safe, generated member name. The archive holds only real source bytes, not a model-generated reconstruction. It is intentionally stored **on the same machine** and must not be called an off-device or disaster-proof backup.

**Archive verification and safe staging.** The user can independently trigger a checksum audit of each archive and its metadata. Any unexpected, duplicate, missing, renamed or unsafe archive member, modified digest, oversized payload or unsupported compression causes rejection. After a second explicit approval, V7 extracts verified files into a **new isolated private staging folder**, each with a flattened safe member filename and an accompanying manifest that maps it back to the original location. It never overwrites uploads, imported documents, saved research projects, V3 human classifications, V4 reports, V5 AI proposals, V6 hand-offs, or existing studio drafts.

**Readiness gates with honest status.** V7 displays selected-source integrity results and a separate list of mandatory manual checks. Every manual gate remains **not certified by software**, regardless of the hash results. There is no “publish” or “release now” button, no automatic approval and no false academic validity claim.

## API (authentication required)

The V7 routes remain **local-owner only**: they are not added to the hosted/multiuser allowlist or exposed as cross-user endpoints. All expensive V7 POST operations use AutoMoto's established request throttling, source directory boundaries and workspace quotas.

| Endpoint | Purpose | Side effects |
| --- | --- | --- |
| POST /api/research/studio/acceptance/audit | Re-verify selected V3/V5/V6 source and artifact chain, checksums, size and declared limitations | None |
| POST /api/research/studio/acceptance/snapshot | Requires exact selected hashes and explicit authorisation; writes a bounded private recovery ZIP and separate JSON manifest | Create-only private files |
| GET /api/research/studio/acceptance/list | List saved private recovery metadata (up to 16 archives) | None |
| POST /api/research/studio/acceptance/verify | Re-hash archive, record and each file against exact manifest entries | None |
| POST /api/research/studio/acceptance/stage | Requires exact archive identity and new approval; revalidates before writing flat members into a newly created private staging folder | Create-only private staging files |

Backing paths:
- Recovery archives and records: \`artifacts/research/recovery/snapshots/\`
- Staged isolated copies: \`artifacts/research/recovery/staging/stage-<random>/files/\`
- Staging manifest: \`staged-manifest.json\` (original path, digest, role, size and source archive ID)

V7 limits at the API layer: 5 pinned research sources under existing research constraints, maximum **16 MB per copied file**, **40 MB per total selected recovery bundle**, **14 archive members** and **16 private recovery snapshots**. Too-large research collections must be split or backed up through another reviewed mechanism. V7 does not silently drop source records to fit.

The ZIP uses \`ZIP_STORED\` with a fixed server-generated flat file-entry namespace and rejects unknown archive members before any extraction. The two artifacts' SHA-256 hashes detect unexpected byte changes against user-selected values. This is **not** a digital signature, secure remote storage, or a defence against a privileged actor capable of rewriting all artifacts and hashes. Operator backups and restore drills remain necessary.

## Threat model and design boundaries

| Risk | Mitigation | Explicit limitation |
| --- | --- | --- |
| Document, comparison or human-review tampering | Current-source revalidation and expected SHA-256 checks | Hashes are not externally notarised |
| Path traversal or malicious symlinks | Reject unexpected path shapes, escape attempts and symlinked archive roots; staging member names are generated on the server | A local OS administrator can still modify the filesystem |
| ZIP bombs / unbounded copies | Exact file-member roster, fixed compression, archive/entry/total caps | Large datasets may be refused |
| Partial or stale source extraction | Existing extraction caps and preserved warning list; explicit human audit | No OCR, no exhaustive proof that search found all relevant text |
| Prompt injection in source material | Data treated as untrusted, no model/external action; browser renders selected paths, hashes and evidence with \`textContent\` | Human review remains essential |
| Automatic publication of uncertain AI material | No publish-ready status, release flag or external action; V5 rejected points are not adopted by V6 | People must still verify retained points |
| Failed staging write | Best-effort cleanup of newly generated isolated staging directory; original files are untouched | Filesystem-level disaster recovery needs separate backup |
| Multiuser leakage | Auth and private workspace controls; hosted-mode default-deny for V7 endpoints | No hosted/multi-tenant recovery workflow in V7 |
| Accidental overwrite | Create-only random names and isolated staging; existing project/workspace paths never used as extraction targets | Restoration into a real project remains a separate human task |

## Verification commands

From the repository root:

\`\`\`bash
python -m pytest -q tests/test_research_acceptance.py tests/test_research_handoffs.py tests/test_research_ai.py tests/test_research_comparison.py tests/test_research_publishing.py
python -m pytest -q
cd apps/desktop
npm run test:ui
\`\`\`

Run the GitHub Actions matrix on **the exact final pull request commit**: Python 3.10 and 3.13 on Linux, macOS and Windows, Office functionality, UI/Playwright, security, Docker, Visual Foundation, VS Code compatibility, Windows desktop installer and documentation. Passing tests is necessary but not sufficient for release.

### Manual acceptance record — deliberately NOT marked complete

1. Open genuine PDF and DOCX papers, including complex tables, scanned/partially extractable content and passages at the extraction limits; compare every quoted section and actual PDF page against the original documents.
2. Verify external Crossref and DOI metadata against the original publisher record with author and date, and manually check Harvard/IEEE references, copyright permissions, report exports and reference associations.
3. Exercise Windows desktop, Linux and macOS installations with genuine local documents and offline model settings; verify hosted denial and privacy across distinct workspaces.
4. Check navigation by keyboard, visible focus, labels, errors, status announcements and screen-reader semantics; review small-screen, long-filename and high-zoom presentations. Run both automated accessibility checks and human WCAG 2.2 review.
5. Benchmark the app with realistic large-document collections, verify no unbounded memory spikes, and confirm size-cap errors are understandable and non-destructive.
6. Create a recovery archive, verify hashes, deliberately corrupt a copy to confirm rejection, stage clean files into isolation and manually compare against genuine original material. Create and restore an **independent off-device backup** as a separate operator task.
7. Perform prompt-injection and local URL safety review of V2 discovery, V5 Ollama and the V6 hand-off chain, including negative tests, consent and changed-source races.
8. Confirm the exact installed release candidate, CI head SHA, source commit, installer artefacts, licences, user documentation, accessibility/privacy evidence and release-owner sign-off.

No manual result is inferred from a successful automated test. A true production candidate must be separately reviewed and approved after this checklist is completed. V7 does not tag, deploy or upload to the Microsoft Store.

## Research Studio milestone outcome

The seven-version **Research Studio development roadmap** is complete in scope when V7 is implemented, reviewed and merged. This is different from universal product readiness: Visual Studio, Document Assistant, invoice and spreadsheet intelligence, hosting, installers and other AutoMoto modules have independent acceptance and deployment needs. Microsoft Store publication remains explicitly deferred.
