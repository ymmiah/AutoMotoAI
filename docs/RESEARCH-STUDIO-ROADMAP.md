# AutoMoto AI Research Studio — Seven-Version Development Roadmap

**Overall objective:** a dedicated evidence-first research workspace integrated with AutoMoto AI. A research claim is never treated as verified solely because an AI generated it or a quoted passage exists. All source identities, retrieval dates, citations and limitations must be explicit. Research work must preserve its original sources.

The existing \`automoto/research.py\` library and Document Assistant v6 already provide guarded public retrieval, local document extraction, passage ranking and an optional bounded offline model. Research Studio will reuse these components rather than duplicate them.

| Version | Scope | Acceptance outcome |
|---|---|---|
| **V1 — Private Evidence Workspace** | Dedicated Research Studio UI, saved projects, PDF/DOCX/Markdown/TXT source selection, SHA-256 pinning, local quote-level evidence retrieval, source-state checks, create-only saved snapshots and regression tests | A user can reproduce findings from existing private source files without generating false references or editing documents |
| **V2 — Source Discovery & Ingestion** | User-approved and SSRF-guarded public scholarly/source discovery, DOI and metadata validation, publication and access-date tracking, deduplication and private import. Respect robots.txt, rate limits, permissions and provenance | Users can add verified public sources without arbitrary crawling or synthetic bibliography |
| **V3 — Evidence Comparison & Contradiction Mapping** | Side-by-side studies, claim-to-passage links, support/contradiction/uncertain categories, coverage and methodology limitations, source versioning and conflicts | A review can distinguish agreement, opposing evidence and unsupported claims |
| **V4 — Academic References & Research Reports** | Real bibliographic metadata, DOI verification, Harvard/IEEE reference formatting, report outlines, tables, review-ready Word/PDF publishing and citation preflight | Every generated citation resolves to a user-provided or verifiably retrieved record; no invented references |
| **V5 — Local AI Research Assistant** | Opt-in Ollama synthesis with exact evidence IDs, source trust boundaries, refusal of unsupported claims, transparent uncertainty and human review | Local AI cannot turn unsupported assertions into accepted findings and cannot edit/source-write automatically |
| **V6 — Cross-Studio Research Workflows** | Export research to Document Assistant/Visual Studio/Developer Studio, project context, approved hand-offs, auditable saved snapshots, optional connectors and permissions | Evidence can travel across studios without losing provenance or bypassing approval |
| **V7 — Product Hardening & Acceptance** | End-to-end quality, cache and recovery, performance, threat modelling, cross-platform tests, screen-reader and keyboard checks, large-document limits, manual citation audit and release gating | Production candidacy based on verified automatic and manual acceptance, not a version number |

**Microsoft Store publication is separately authorised and remains deferred.** The seven milestones do not themselves establish that all aspects of research accuracy are automatically verifiable. Each version must pass its CI and have clear limits; no fabricated experimental findings or scholarly references.

## V1 — Private Evidence Workspace (this pull request)

### What it adds

- A new **Research Studio** entry in the AutoMoto sidebar and quick-command palette, using the same authenticated session and dark/light theme.
- A research source browser for *existing uploaded files and saved Document Assistant drafts*; supported formats are PDF, DOCX, TXT, Markdown and the native Document Assistant draft format.
- Explicit source selection of **1–5** documents. Each selected file is verified via the existing Document Assistant \`source-info\` API and pinned by its **SHA-256 digest**.
- Title, question, notes, deterministic **evidence** retrieval and evidence-backed **outline** mode. Both work offline and do not contact cloud models. V1 does not include a new LLM synthesis, remote search or web crawler.
- Quotes show their **source path, fingerprint, excerpt ID, section, offset and actual PDF page number when available**. DOCX, Markdown, TXT and native draft extracts explicitly do not have verified page positions.
- The existing retrieval engine limits source text, document count, page count, quote length and evidence volume. No evidence means **no matching excerpt**, not that a hypothesis is disproved.
- Create-only saved research snapshot JSON in the tenant-private \`artifacts/research/\` folder, with a random server-generated identifier, original question, source SHA-256 values and server-retrieved evidence.
- Opening a saved project checks current source fingerprints: **current**, **changed**, or **missing/unavailable**. Historical results are displayed with explicit freshness warnings; existing source documents and previous project snapshots are never altered.
- Copyable research evidence notes, carrying explicit warnings that internal \`S1-01\`-style excerpt IDs are **not Harvard/IEEE bibliographic citations**.

### Security and privacy boundaries

Every new route is authenticated and included only after hosted route review. Hosted accounts remain segregated by their existing tenant workspace. The server never trusts client-provided quotations or citation IDs: saving reruns existing deterministic research and writes only server-generated evidence.

The existing Document Assistant's source-path verification rejects absolute paths, symlinks, traversal, unsupported formats, oversized files and stale SHA-256 values. The private research directory rejects symlinks and arbitrary opening paths. Project save has a **65 KB cap**, up to **150 saved snapshots** and a maximum of 5 sources per query. All dynamic title, URL/path, question, excerpt and note data are rendered via DOM \`textContent\`, not injected HTML.

No direct outbound network request, local model call, PDF conversion, invoice issue, business action, source editing or academic conclusion verification is performed by Research Studio V1. Any public-site discovery and automatic bibliography validation belong to subsequent milestones.

### Authenticated API

- \`GET /api/research/studio/sources\` — list supported local source candidates.
- \`GET /api/research/studio/list\` — list create-only saved research snapshots.
- \`GET /api/research/studio/open?path=...\` — open a saved result and show present-day source status.
- \`POST /api/research/studio/query\` — retrieve evidence through the existing source-verified Document Assistant engine.
- \`POST /api/research/studio/save\` — rerun retrieval and persist server-produced evidence in a new private snapshot.

### Automated acceptance

\`\`\`bash
python -m pytest -q tests/test_research_studio.py tests/test_document_research.py
python -m pytest -q
cd apps/desktop && npm run test:ui
\`\`\`

Tests cover session authentication and hosted allowlisting, valid source extraction, correct PDF/Word page limitations, source SHA-256 conflicts, duplicate source refusal, no model or Internet calls, immutable snapshots, missing/changed sources, malformed and forged evidence rejection, path traversal, symlink restrictions, tenant isolation, corrupted project handling, and real-browser source pinning/query/save/reopen.

The full GitHub Actions matrix must also pass Linux, macOS, Windows, Office, UI, Docker, Visual Foundation, security, desktop installer and docs workflows.

**Manual acceptance still required:** inspect actual PDFs/DOCX files, confirm accessible keyboard and screen-reader navigation, review long/complex source document behaviour, confirm evidence quotations in context, validate citation metadata before publication and check mobile layout.
