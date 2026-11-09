# AutoMoto Research Studio V5 — Opt-in Offline AI Research Analysis

**Milestone 5 of 7.** This version operates on the already-merged V1–V4 Research Studio source evidence, verified V3 reviewer comparisons, and V4 reference/report safeguards. It does not publish or rewrite research.

## Research workflow

1. Create and save a V1 research project from one to five private source files, with SHA-256 checksums. For V5, use **at least two sources** and finish the V3 reviewer comparison by classifying every retrieved excerpt. 
2. In **Research Studio → Offline AI research analysis**, choose the saved V3 comparison and select **Verify source context**. The server rechecks the comparison's SHA-256, its original research project, each saved quote at its original extracted source offset, and source-file fingerprints. This step uses **no model or network**.
3. To ask for synthesis, first enable an **installed Ollama model** under Settings → Offline AI and explicitly tick the inference consent box. The confirmation shows that your source excerpts are being sent only to the computer's local Ollama service. No model installation, download, remote provider or cloud fallback occurs automatically.
4. The model is given at most eight exact source excerpts, their internally verified evidence IDs, original human stance labels and your human-authored comparison claim. Excerpts are supplied as untrusted JSON **data**, not as developer/system instructions or tool commands. The model is instructed to respond with a small JSON array of tentative observations and explicit uncertainty.
5. The server validates the entire response. Every tentative claim needs one to four **actual** evidence IDs. Invalid or repeated IDs, oversized/malformed output, unsupported fields, introduced numerical claims, external links or DOI/citation markers and obviously unrelated wording cause the complete generation to be rejected. A syntactically valid link is **not a semantic proof**: human verification is mandatory.
6. Only after successful checks, AutoMoto stores a new private, **unapproved** suggestion snapshot in \`artifacts/research/ai/proposals/\`. It does **not** change any V1 sources, V3 reviewer decisions, V4 report drafts, Word/PDF files or citation bindings.
7. Inspect each model suggestion alongside the original excerpt, source path, fingerprint, offset and known PDF page. Select **Retain for further research** or **Reject** and write a unique rationale for each proposal. After a separate human confirmation, the server revalidates the saved draft, current original documents and entire V3 comparison before storing another create-only **human decision snapshot** under \`artifacts/research/ai/reviews/\`.
8. Retained observations are still **not scientific conclusions** and cannot automatically feed V4 publication. Later integration in V6 must preserve exact evidence provenance and require another explicit human decision.

## API

- \`POST /api/research/studio/ai/prepare\` — no model, exact source and reviewer-comparison revalidation.
- \`POST /api/research/studio/ai/generate\` — explicit consent, already-installed loopback-only Ollama JSON response, bounded evidence-checked draft creation.
- \`GET /api/research/studio/ai/list\` — list private AI proposals, historically unapproved.
- \`GET /api/research/studio/ai/open?path=...\` — view a historical proposal and flag changed/unavailable comparisons.
- \`POST /api/research/studio/ai/save-review\` — save independent, human-authored decisions after verifying all source/draft hashes and required consent.

**Hosted accounts:** The V5 routes are intentionally **not** in the multi-user hosted allowlist because arbitrary hosted workers are not authorised to connect to the host's local Ollama instance or share its context across tenants. V5 is a desktop/local-workspace-only capability in this milestone. A separately isolated tenant-native model environment and privacy review are required before hosted AI access can be considered.

## Model and security boundaries

- Loopback URL validation is reused from Document Assistant's local-only AI. The model must be explicitly enabled and installed; connecting does **not** download a model. HTTP redirects and environment proxies are disabled on the V5 request.
- One request per user action. No background inference, search, crawler, remote model, cloud logging or automated retries.
- Bounded model response: 24 KB, at most six observations, up to four source IDs per claim and an explicit limitation for each observation; limited context and generation tokens. The V3 evidence limit is at most eight passages. Model errors fail closed without saving anything.
- The validation includes exact source IDs, lexical overlap and rejecting new numeric tokens not found in the cited quotes. It **cannot** reliably determine semantic entailment, statistical correctness or whether a quotation is misleading. Do not claim automated hallucination elimination.
- Historic model proposals and human decisions are private, create-only artifacts. SHA-256 is used to detect changes against the provided expected digest, not as a digitally signed or externally notarised record.
- If an underlying source or V3 comparison changes between generation start and end, the model output is refused without saving. Saving human decisions repeats the original verification.
- Source text and model suggestions are rendered using DOM text nodes, not injected as HTML. URLs or dangerous instructions inside retrieved text are neither executed nor treated as trusted commands.
- An accepted human decision indicates **retain for further investigation**, not publication readiness, scientific certification or automatic adoption as an academic finding.

## Automated and manual testing

Run:

\`\`\`bash
python -m pytest -q tests/test_research_ai.py tests/test_research_publishing.py tests/test_research_comparison.py
python -m pytest -q
cd apps/desktop && npm run test:ui
\`\`\`

Automated tests use deterministic mocked model responses and include source verification, refusal of incomplete V3 review, authorisation and hosted blocking, no cloud fallback, explicit Ollama consent, exact evidence IDs, injected unsupported statistics and external links, prompt-injection boundary, model JSON contract, no-proxy/no-redirect loopback transport, draft creation, human decisions, tampering, changed sources and workspace isolation.

**Manual requirements:** Test a real, downloaded Ollama model on Windows, Linux and macOS; inspect original article context and human interpretation; screen-reader and keyboard navigation, mobile layouts, long-response/timeout handling, citation accuracy and source rights. CI without a model cannot certify real-model performance.

**Next:** V6 cross-studio research hand-offs with provenance and approvals, then V7 quality/recovery/accessibility/release hardening. **Microsoft Store publication remains deferred**.
