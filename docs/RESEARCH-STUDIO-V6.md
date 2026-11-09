# AutoMoto AI — Research Studio V6: Audited Cross-Studio Research Hand-offs

**Milestone 6 of 7. Development-only; Microsoft Store publication remains deferred.**

V6 transfers a fully human-labelled, original-source-verified V3 research comparison into a separate, explicitly approved workspace draft. An optional V5 AI review may be attached, but only observations marked "retain for further research" in a saved, complete human review can be carried forward. **Neither a quotation nor a human retention decision establishes scientific correctness.**

## Supported destinations

| Destination | Actual V6 output | Behaviour |
| --- | --- | --- |
| Document Assistant | New native editable document draft in artifacts/documents | Full verbatim excerpts and provenance in Markdown; no overwrite or Word/PDF publication |
| Visual Studio | New native editable cards design in artifacts/visual-studio | A concise maximum-four-excerpt visual; full quotation/offset/source hashes in the audit; manual design review and export remain necessary |
| Developer review | New Markdown research brief in artifacts/research/handoffs | Available in Files and for later developer review; no command, file patch, build, CI trigger or developer-workspace execution |

The existing repository has no complete dedicated Developer Studio interface in this milestone. Its V6 developer destination is intentionally a **review-only source brief**, not a claim of automated developer integration. Connector execution and remote publication are not implemented.

## User flow

1. In Research Studio, complete and save a V1 research project containing at least two private PDF, DOCX, Markdown or TXT sources.
2. Finish V3 evidence classifications for every excerpt, ensuring the original source documents still match their stored SHA-256 fingerprints.
3. Optionally run V5 locally through an already installed Ollama model and save an independent human review of **every** suggestion. A rejected suggestion is never transferred.
4. Under **Cross-Studio Hand-offs**, select the saved V3 comparison, optionally choose a matching V5 human review, and select Document Assistant, Visual Studio or Developer review.
5. Select **Verify and preview hand-off**. The server reopens and checks the entire V3 comparison against original project/source digests, exact excerpt positions and reviewer classifications. If an optional V5 review is present it verifies its bytes, originating proposal bytes, original comparison, all decisions and current source evidence. Preview writes nothing and calls no AI.
6. Read the preview, inspect original sources, tick the hand-off-specific consent box and confirm the separate create-only save.
7. V6 writes an independent target draft plus an audit snapshot recording target and source checksums, comparison and project identities, individual evidence IDs, exact excerpts, original PDF pages when available, human stances, reviewer rationales, limitations and any human-retained AI observations. Both files are private. Existing research, V3/V5 decisions, V4 reports and imported source files remain untouched.
8. Use the **Historical hand-offs** archive to inspect recorded provenance and current source/destination fingerprints. A changed source or output is flagged; a historical audit does not certify that today's evidence remains current.

## API

All endpoints are authenticated and local-only under the existing hosted-mode default-deny gate:

- GET /api/research/studio/handoff/sources — available completed comparisons and human AI reviews.
- POST /api/research/studio/handoff/preview — no writes, no AI invocation or external requests; validates all source and review identities before constructing a target.
- POST /api/research/studio/handoff/save — requires exact selected comparison and review SHA-256, a hand-off acknowledgement and two separate approval flags; creates target plus audit.
- GET /api/research/studio/handoff/list — private audit history.
- GET /api/research/studio/handoff/open?path=... — historical evidence and source/output freshness status.

Strict filename and directory boundaries reject traversal, unexpected paths and symlinked research archives. No arbitrary model-supplied file paths, DOI entries, URLs or instructions are accepted. Handoff manifests are bounded, private and create-only; a source fingerprint is a **change detector**, not a tamper-proof signature against an administrator who can rewrite both data and hashes.

## Safety and limits

- No automatic AI/model call, public search, crawler, connector action, code execution, publishing, source update, terminal operation or sending data outside the user's own local workspace.
- The comparison's human support/contradiction labels remain **subjective reviewer positions**; they are not presented as independently established facts.
- Untrusted quotes can contain arbitrary text and should be interpreted only as inert data. The UI uses DOM text nodes, never dynamic HTML insertion for source content.
- Visual output presents **truncated** excerpts and can never substitute for checking full quotations in its audit.
- No automatic bibliography, verified peer-review claim, scientific validity guarantee or final academic sign-off.
- V6 review is approval to create a separate working draft, not permission to automatically use it for publication, production code or security action.
- Manifests and archived reports are not digitally signed or externally notarised. Recovering from a partial hardware/filesystem failure requires ordinary workspace backup.
- Source changes after an approved V3 comparison force the next preview/save to fail closed. Cross-studio output does not make a permanently live link to source files.

## Verification

Run the focused tests:

    python -m pytest -q tests/test_research_handoffs.py tests/test_research_ai.py tests/test_research_comparison.py tests/test_research_publishing.py

Then run the full suite and real browser acceptance:

    python -m pytest -q
    cd apps/desktop && npm run test:ui

Release acceptance requires the full GitHub CI matrix across Windows, Linux and macOS, Python versions, browser, Office, security, installers, docs and desktop. Manual checks must include long/hostile source content, Unicode and PDF quotations, native document preview, editable Visual Studio drafts, narrow/mobile layout, keyboard and screen-reader controls, source rights and privacy, comparison-to-output audit, and actual source freshness after edits.

**Next: V7 — Product Hardening and Acceptance.** Performance, recovery, threat modelling, accessibility, large documents, honest manual citation-quality verification and cross-platform release gates. Microsoft Store submission will only follow separately authorised publication work; completing V7 alone does not initiate it.
