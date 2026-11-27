# Document Assistant v8 — Local RAG Index and Create-Any-Document

**Scope:** user-directed extension past the v7 feature freeze. V7 said "stop
major Document Assistant development" and "no v8". The user explicitly asked
to fix the gap against issue #10 and to make Document Assistant able to edit,
build and create any document, so this milestone proceeds on that instruction.
Microsoft Store publication remains deferred.

## The gap it fixes

Issue #10, Phase 1 specified Document Assistant RAG with **local embeddings
and a local vector index** (SQLite FTS5 or FAISS; Chroma/Qdrant optional
adapters, never Pinecone), ranked retrieval, grounded answers with
document/page citations, Word/PDF/PPTX exports, and ≥20 diverse fixture
files. V1–V7 shipped deterministic lexical retrieval only: no embeddings,
no vector database, no persistent index, at most five documents per
request, and every search re-extracted its sources.

## What v8 adds

### Persistent local index (`automoto/document_index.py`)

- SQLite index in the user's private workspace,
  `artifacts/documents/index/document_index.sqlite3` (stdlib `sqlite3` only).
  One FTS5 table gives lexical/BM25 search; one float32 vector per chunk
  gives vector search. The two rankings are fused with reciprocal-rank
  fusion, so a query benefits from both exact terms and vector similarity.
- **Default adapter: hashed embeddings.** Deterministic, dependency-free
  (384-dimension hashing trick over tokens, TF-weighted, L2-normalised).
  No model download, no cloud service, no new mandatory dependency. It is
  lexical information in vector form — it does not understand synonyms.
- **Optional neural adapters, opt-in only:**
  - `ollama` — the loopback-only local Ollama `/api/embeddings` endpoint,
    reusing the same checks as Document AI. The model must already be
    installed; nothing is downloaded.
  - `sentence-transformers` — used only when that package is already
    installed. It is deliberately **not** added to `requirements.txt`.
  - Anything else (including Pinecone) is rejected.
- Citations stay grounded: every chunk keeps source path, SHA-256, section,
  PDF page number where available and character offset, and every quote is
  a verbatim substring of the extracted source text.
- **Stale sources are excluded, never silently searched.** A source whose
  file changed after indexing is reported in `stale_sources` and in
  `GET /api/documents/research/index/status` until it is re-indexed.
- User-controlled: `DELETE /api/documents/research/index` removes one
  document or the whole index. Re-indexing the same sources rebuilds them.
- Bounds: 50 documents per index call, 1,200 chunks and 180,000 characters
  per source, 200 PDF pages — the same bounds as v6 research.
- Indexing is opt-in. The existing ephemeral `POST /research/query` path
  is unchanged and still writes no files; pass `"use_index": true` to
  search the persistent index instead.

### Create any document (`POST /api/documents/create`)

Previously Document Assistant could only create Markdown drafts
(`.document.json`) and export them as DOCX/PDF, even though the Office
engines could already build PPTX and XLSX — the agent tools exposed them,
Document Assistant did not. Now one endpoint creates a new file from
scratch in **DOCX, PPTX, XLSX, PDF, MD or TXT**:

- DOCX: the existing Word engine and Markdown spec (same as export).
- PPTX: Markdown headings become slides — H1 is the title slide, each H2
  a bullets slide, tables become table slides.
- XLSX: explicit `rows`, or the first Markdown table in the source.
- PDF: built with reportlab from the Markdown, so it works even where
  LibreOffice is absent (PDF export of a draft still uses LibreOffice).
- MD/TXT: the plain source text.
- Every create is a new uniquely-named file; nothing is overwritten.

### Revise copies for PPTX and XLSX (`POST /api/documents/replace-copy`)

Find-and-replace copies previously covered DOCX only. They now cover
**DOCX, PPTX and XLSX**, using the same `office_build.edit` engine the
agent tools use, with the same SHA-256 precondition and copy-only rule.
XLSX also accepts `cells` (for example `{"Sheet1!B2": 125000}`). PDF stays
read-only: it has no lossless text layer to edit in place.

## What is still missing

- **PDF editing:** no lossless PDF text edit exists; PDFs are read-only
  (create a new PDF from source instead, or revise a DOCX and re-export).
- **Legacy formats** (`.doc`, `.xls`, `.ppt`, `.odt`, `.rtf`, `.ods`):
  read-only extraction; editing requires conversion first.
- **No desktop/web UI yet** for create-any-format, the index, or
  PPTX/XLSX revise — the REST endpoints and agent tools exist; the
  Document Assistant page still only offers Markdown drafts and DOCX/PDF
  export. That UI work is the next step.
- **No true semantic search by default.** The hashed adapter ranks
  lexical overlap in vector form. Semantic (synonym/paraphrase) search
  needs the Ollama or sentence-transformers adapter.
- **No index UI for >50 documents at once** (cap per index call) and no
  background/queued indexing; large libraries are indexed in batches.
- **No document delete/rename in Document Assistant** — saves remain
  create-only by design; deletion is via the Files page.

## Verification

```bash
python -m pytest -q tests/test_document_index.py tests/test_document_create.py \
  tests/test_document_workspace.py tests/test_document_ai.py \
  tests/test_document_research.py tests/test_document_publishing.py \
  tests/test_document_rich.py tests/test_document_recovery.py
```

New tests cover deterministic hashed embeddings, index build/search/
delete, stale-source exclusion, rebuild after change, 20-source search,
and create/revise for every format. The pre-existing v6 test that
ephemeral research writes no files is unchanged and still passes.
