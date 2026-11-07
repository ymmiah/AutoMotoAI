# Document Assistant v6 — Offline Academic Evidence and Research

**Development milestone.** This does not publish AutoMoto AI to the Microsoft Store.

## What v6 adds

Document Assistant now offers a dedicated, source-grounded research workflow for up to **five existing private documents**: DOCX, PDF, Markdown, UTF-8 TXT or its own editable `.document.json` drafts. Supported files appear inside **Academic Research · Offline multi-document evidence**.

The process is deliberate and source-first:

1. Select up to five documents from the existing private workspace. Documents are identified with their SHA-256 checksums before searching.
2. Enter a specific research question, then choose one of:
   - **Find exact evidence:** deterministic, model-free relevance ranking using only the extracted local source text.
   - **Evidence and literature-review outline:** the same passages plus a cautious, five-section writing scaffold: research question, method, synthesis, contradictions/gaps and references.
   - **Optional local-AI synthesis:** the same retrieved passages with an explicitly enabled, pre-installed **local Ollama** model. Its output is allowed only if every interpretive sentence links to actual server-assigned passage IDs.
3. Inspect each quoted passage, source path, original SHA-256, section offset and verified **PDF page number** where available.
4. Review the read-only, copyable evidence notes. Nothing is inserted into the active document, added to bibliography or saved automatically.

### Source and evidence fidelity

Source IDs such as `S1-01` refer only to *this research request*. They are not peer-reviewed citations, Harvard references or IEEE bibliography entries. For a formal assignment the author must still verify author, title, date, source location, page context and correct reference details, then enter them in v4 Professional Publishing.

- The retrieval engine uses bounded textual chunks with overlap and deterministic lexical relevance (not semantic truth verification). Each quotation is a literal contiguous substring of the locally extracted section.
- For PDFs, the page number is derived from the page being extracted by pypdf. It is **never guessed** for DOCX or Markdown. Word page layout can shift with fonts and rendering.
- A document's SHA-256 is checked before extraction, immediately afterwards, and again after evidence processing and optional inference. A changed file invalidates the review with HTTP 409.
- Large sources are bounded to 180,000 extracted characters each; PDFs are further limited to 200 pages. The response lists partially extracted sources, and it never pretends the entire document was searched when truncated.
- Scanned PDFs and images may have no extractable text. Missing results mean no passage matched the extracted text, not that the idea is absent from the real-world document.
- Evidence retrieval is read-only, ephemeral and requires **no embeddings, vector database, cloud service or model download**.

### Optional offline synthesis

Only the local-only Ollama connector from v3 is used. This feature does not automatically connect to a remote model, download new models, access external websites or generate formal reference metadata.

The model receives a bounded set of already-retrieved passages and a research question, with explicit instructions to ignore commands inside sources and respond in strict JSON. Every returned observation must contain at least one *real* evidence ID drawn from the current server-generated set. Observations referencing invented IDs are filtered; if no valid grounded observations remain, the synthesis fails instead of presenting unsupported paragraphs.

**Important:** attaching a real quotation to an AI interpretation does not prove the interpretation or claim is true. The author must compare full source context, document credibility and conflicting findings. The workflow is designed for research assistance, not automatic academic submissions.

### Privacy and safety

- Authenticated endpoints: `GET /api/documents/research/source-info` and `POST /api/documents/research/query`.
- Strict body schema, 1–5 unique pinned sources, maximum question length, bounded extraction/chunks, evidence counts, quote size and model response limits.
- Path confinement to the existing user's `uploads` and `artifacts/documents` folders, refusal of symlink paths/out-of-scope resources, and Office ZIP/DTD/entity inspection where applicable.
- Default evidence and outline search is usable in hosted or desktop workspaces under their established permissions, with no model requests. Ollama synthesis is **blocked** in multi-user hosting.
- No disk indexes, generated research files, direct edits, remote source retrieval or automatic bibliography creation.
- All source and model text is displayed through text-only DOM nodes; strings cannot be interpreted as scripts or HTML by the research view.

### Verification

```bash
python -m pytest -q tests/test_document_research.py tests/test_document_ai.py tests/test_document_workspace.py
cd apps/desktop && npm run test:ui
```

Full CI covers Windows, Linux, macOS, Office, security, document workspace, browser UI, and Windows app packaging.

Specific tests cover real extracted DOCX, genuine two-page PDF text and page attribution, existing drafts, simultaneous source comparison, long-source truncation, empty/scanned searches, stale and changed checksums, invalid paths, no-write guarantees, deterministic model-free retrieval, rejection of fabricated model evidence IDs, and browser-level evidence display and source preservation.

### Known limitations and next milestone

This is a small-source, deterministic research assistant, not a web-connected systematic review tool. It does not assess scientific quality, resolve contradictory claims automatically, infer bibliographic identities or validate the factual truth of papers. Retrieval is lexical, so synonyms and paraphrases can be missed. References from v4 remain author-owned.

**v7 is the final Document Assistant milestone**: full cross-platform hardening, accessibility, security, recovery, performance, document-fidelity and acceptance testing. After genuinely verified v7 is merged, stop development. Microsoft Store publication remains deferred.
