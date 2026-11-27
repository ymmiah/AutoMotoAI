"""Document Assistant v8 — persistent local RAG index (issue #10, Phase 1).

Issue #10 asked for Document Assistant retrieval over local embeddings and a
local vector index. V1–V7 shipped deterministic lexical retrieval only: no
embeddings, no vector database, no persistent index, at most five documents
per request, and every search re-extracted its sources from scratch.

This module closes that gap within the issue #10 constraints:

* Offline-first, local-only by default. The default adapter is a
  dependency-free deterministic hashed embedding (no model download, no
  cloud service, no Pinecone, no new mandatory dependency). Neural
  embeddings are pluggable and opt-in only: a loopback-only Ollama
  ``/api/embeddings`` adapter, and a ``sentence-transformers`` adapter
  that is used only when that package is already installed.
* Persistent local index in SQLite (stdlib ``sqlite3``): an FTS5 table
  for lexical/BM25 search plus a float32 vector column per chunk, fused
  with reciprocal-rank fusion. The index lives inside the user's own
  private workspace (``artifacts/documents/index/``), so tenant and
  workspace isolation follow the existing sandbox rules.
* Citations stay grounded: every chunk keeps its source path, SHA-256,
  section label, PDF page number where available and character offset,
  and every returned quote is a verbatim substring of the extracted
  source text. A source whose file changed after indexing is stale: it
  is excluded from results and reported, never silently searched.
* User-controlled: the index can be deleted in whole or per document,
  and rebuilt explicitly. Indexing is opt-in — the existing ephemeral
  ``/research/query`` path is unchanged and still writes no files.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import struct
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException

from automoto import office, sandbox

INDEX_DIR = "artifacts/documents/index"
INDEX_FILE = "document_index.sqlite3"
MAX_INDEX_DOCS = 50
MAX_INDEX_CHUNKS = 20_000
MAX_SOURCE_CHARS = 180_000
MAX_PDF_PAGES = 200
CHUNK_SIZE = 1100
CHUNK_STRIDE = 900
MAX_CHUNKS_PER_DOC = 1200
MAX_EVIDENCE = 8
EMBED_DIM = 384
_RRF_K = 60

_STOP = frozenset(("about across after again against also among before being between could does "
                   "from have into more must other over should some such than that their there "
                   "these this those through under what when where which while with would were "
                   "your evidence document research study says said according into our and are "
                   "the for how why who its can did not was use using").split())
_TERMS = re.compile(r"[^\W_]{3,}", re.UNICODE)


def _tokenise(value: str) -> list[str]:
    """Same token rules as document_research, so lexical and vector ranking agree."""
    return [t for t in _TERMS.findall(value.casefold()) if t not in _STOP]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _index_path() -> Path:
    folder = sandbox.resolve(INDEX_DIR, base=sandbox.default_root().resolve(),
                             allow_outside=False)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / INDEX_FILE


# ---------------------------------------------------------------------------
# Embedding adapters
# ---------------------------------------------------------------------------

def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


class HashedEmbeddingAdapter:
    """Deterministic, dependency-free embedding.

    Each token is hashed into a fixed 384-dimension vector (hashing trick,
    with a signed second hash to reduce collisions), weighted by term
    frequency and L2-normalised. This is lexical information in vector
    form: it ranks paraphrases and repeated terms better than raw keyword
    counts and needs no model, download or network. It does not understand
    synonyms — that is what the optional neural adapters are for.
    """
    name = "hashed"
    dim = EMBED_DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for token, count in Counter(_tokenise(text)).items():
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                index = int.from_bytes(digest[:4], "little") % self.dim
                sign = 1.0 if digest[4] & 1 else -1.0
                vec[index] += sign * (1.0 + math.log(count))
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


class OllamaEmbeddingAdapter:
    """Local Ollama embeddings (loopback only, opt-in).

    Mirrors the loopback-only checks in document_ai: the Ollama endpoint
    must be plain HTTP on localhost, with no credentials. The model must
    already be installed; nothing is downloaded and nothing leaves the
    machine.
    """
    name = "ollama"

    def __init__(self) -> None:
        from automoto.document_ai import _loopback_ollama, _selected_model
        self._url = _loopback_ollama() + "/api/embeddings"
        self._model = _selected_model()
        self.dim = 0  # discovered from the first response

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 16):
            batch = texts[start:start + 16]
            payload = {"model": self._model, "input": batch}
            request = urllib.request.Request(
                self._url, method="POST",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=120) as response:  # nosec B310
                    raw = response.read(4_194_304)
            except (OSError, TimeoutError, urllib.error.URLError):
                raise HTTPException(
                    503, "Local Ollama embeddings were unavailable; use the hashed adapter.") from None
            try:
                data = json.loads(raw)
                batch_vectors = data["embeddings"]
            except (ValueError, KeyError, TypeError):
                raise HTTPException(422, "Local Ollama did not return usable embeddings.") from None
            if not batch_vectors or any(not isinstance(v, list) for v in batch_vectors):
                raise HTTPException(422, "Local Ollama did not return usable embeddings.") from None
            if self.dim == 0:
                self.dim = len(batch_vectors[0])
            for vec in batch_vectors:
                norm = math.sqrt(sum(v * v for v in vec)) or 1.0
                vectors.append([v / norm for v in vec])
        return vectors


class SentenceTransformerEmbeddingAdapter:
    """Local sentence-transformers embeddings (opt-in, package must exist).

    No new dependency is added to requirements.txt: this adapter is only
    constructed when the user explicitly asks for it and the package is
    already installed in their environment.
    """
    name = "sentence-transformers"

    def __init__(self, model_name: str | None = None) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError:
            raise HTTPException(
                422, "sentence-transformers is not installed; use the hashed adapter "
                     "or a local Ollama embedding model.") from None
        import os
        self._model = SentenceTransformer(model_name or os.environ.get(
            "AUTOMOTO_EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True,
                                     show_progress_bar=False)
        return [[float(v) for v in row] for row in vectors]


def get_adapter(name: str):
    """Return an embedding adapter by name. ``hashed`` is the default."""
    if name in (None, "", "hashed"):
        return HashedEmbeddingAdapter()
    if name == "ollama":
        return OllamaEmbeddingAdapter()
    if name == "sentence-transformers":
        return SentenceTransformerEmbeddingAdapter()
    raise HTTPException(422, "Unknown embedding adapter. Use 'hashed', 'ollama' "
                             "or 'sentence-transformers'.")


# ---------------------------------------------------------------------------
# Extraction (mirrors document_research._snapshot; kept separate so the
# ephemeral research path stays untouched and writes no files)
# ---------------------------------------------------------------------------

def _extract_sections(path: Path) -> tuple[list[tuple[str, int | None, str]], bool]:
    """Extract (section label, PDF page or None, text) sections, bounded."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    from automoto.document_workspace import _allowed_source, _draft

    source = _allowed_source(path.relative_to(sandbox.default_root().resolve()).as_posix())
    if not source.name.endswith(".document.json") and source.suffix.lower() not in \
            {".docx", ".pdf", ".txt", ".md"}:
        raise HTTPException(422, "Indexing supports native drafts, Markdown, TXT, DOCX and PDF only.")
    partial = False
    try:
        if source.name.endswith(".document.json"):
            sections = [("Editable draft", None, _draft(source)["markdown"])]
        elif source.suffix.lower() in {".md", ".txt"}:
            sections = [("Plain text", None, source.read_text(encoding="utf-8"))]
        elif source.suffix.lower() == ".docx":
            facts = office.inspect_file(source)
            if facts["macros"]:
                raise HTTPException(422, "Macro-containing sources are not accepted for indexing.")
            sections = [("Extracted Word text", None, office.read_docx(source))]
        else:
            reader = PdfReader(str(source))
            if reader.is_encrypted:
                raise HTTPException(422, "Encrypted PDFs require an independently unlocked copy.")
            total = len(reader.pages)
            partial = total > MAX_PDF_PAGES
            sections = []
            for i in range(min(total, MAX_PDF_PAGES)):
                text = reader.pages[i].extract_text() or ""
                sections.append((f"Page {i + 1}", i + 1, text))
                if sum(len(part[2]) for part in sections) >= MAX_SOURCE_CHARS:
                    partial = True
                    break
    except HTTPException:
        raise
    except (OSError, ValueError, TypeError, UnicodeError, KeyError, IndexError,
            EOFError, PdfReadError) as exc:
        raise HTTPException(422, "Could not safely extract this source: " + str(exc)[:160]) from None
    bounded: list[tuple[str, int | None, str]] = []
    remaining = MAX_SOURCE_CHARS
    for title, page, text in sections:
        if remaining <= 0:
            partial = True
            break
        if len(text) > remaining:
            bounded.append((title, page, text[:remaining]))
            partial = True
            break
        bounded.append((title, page, text))
        remaining -= len(text)
    return bounded, partial


def _chunks(sections: list[tuple[str, int | None, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for label, page, text in sections:
        if not text.strip():
            continue
        for start in range(0, len(text), CHUNK_STRIDE):
            if len(out) >= MAX_CHUNKS_PER_DOC:
                return out
            piece = text[start:start + CHUNK_SIZE]
            if len(piece.strip()) >= 24:
                out.append({"section": label, "page": page, "offset": start, "text": piece})
            if start + CHUNK_SIZE >= len(text):
                break
    return out


# ---------------------------------------------------------------------------
# Persistent index
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, title TEXT NOT NULL,
    adapter TEXT NOT NULL, dim INTEGER NOT NULL,
    indexed_at TEXT NOT NULL, chunk_count INTEGER NOT NULL, partial INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, doc_path TEXT NOT NULL,
    chunk_no INTEGER NOT NULL, section TEXT NOT NULL, page INTEGER,
    offset INTEGER NOT NULL, text TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, content='chunks', content_rowid='id');
CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id INTEGER PRIMARY KEY, vector BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS chunks_doc_idx ON chunks(doc_path);
"""


@dataclass
class IndexedSource:
    path: str
    sha256: str


class DocumentIndex:
    """SQLite FTS5 + vector index for Document Assistant sources."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _index_path()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SCHEMA)
        return conn

    # -- writes ---------------------------------------------------------
    def index_sources(self, sources: list[IndexedSource],
                      adapter_name: str = "hashed") -> dict[str, Any]:
        if not sources:
            raise HTTPException(422, "Select at least one document to index.")
        if len(sources) > MAX_INDEX_DOCS:
            raise HTTPException(422, f"Index at most {MAX_INDEX_DOCS} documents at once.")
        adapter = get_adapter(adapter_name)
        root = sandbox.default_root().resolve()
        from automoto.document_workspace import _allowed_source
        indexed: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        with self._connect() as conn:
            for src in sources:
                rel = src.path
                try:
                    # Confine to uploads/ or the Document Assistant folder
                    # before reading anything, as in document_workspace.
                    _allowed_source(rel)
                    path = root / rel
                    if _sha(path) != src.sha256:
                        skipped.append({"path": rel, "reason": "source changed; reselect it"})
                        continue
                    sections, partial = _extract_sections(path)
                    if _sha(path) != src.sha256:
                        skipped.append({"path": rel, "reason": "source changed during extraction"})
                        continue
                    chunks = _chunks(sections)
                    if not chunks:
                        skipped.append({"path": rel, "reason": "no extractable text"})
                        continue
                    self._delete_document(conn, rel)
                    import datetime
                    conn.execute(
                        "INSERT INTO documents(path, sha256, title, adapter, dim, indexed_at,"
                        " chunk_count, partial) VALUES (?,?,?,?,?,?,?,?)",
                        (rel, src.sha256, Path(rel).name, adapter.name, adapter.dim,
                         datetime.datetime.now(datetime.timezone.utc).isoformat(),
                         len(chunks), 1 if partial else 0))
                    texts = [c["text"] for c in chunks]
                    vectors = adapter.embed(texts)
                    for number, (chunk, vector) in enumerate(zip(chunks, vectors)):
                        cur = conn.execute(
                            "INSERT INTO chunks(doc_path, chunk_no, section, page, offset, text)"
                            " VALUES (?,?,?,?,?,?)",
                            (rel, number, chunk["section"], chunk["page"],
                             chunk["offset"], chunk["text"]))
                        rowid = cur.lastrowid
                        conn.execute("INSERT INTO chunks_fts(rowid, text) VALUES (?,?)",
                                     (rowid, chunk["text"]))
                        conn.execute("INSERT INTO embeddings(chunk_id, vector) VALUES (?,?)",
                                     (rowid, _pack([float(v) for v in vector])))
                    indexed.append({"path": rel, "sha256": src.sha256,
                                    "chunks": len(chunks), "partial": partial,
                                    "adapter": adapter.name})
                except HTTPException as exc:
                    skipped.append({"path": rel, "reason": str(exc.detail)[:160]})
            conn.commit()
        return {"indexed": indexed, "skipped": skipped,
                "adapter": adapter.name, "index": self.path.name}

    def _delete_document(self, conn: sqlite3.Connection, rel: str) -> int:
        rows = conn.execute("SELECT id FROM chunks WHERE doc_path=?", (rel,)).fetchall()
        ids = [r[0] for r in rows]
        for rowid in ids:
            conn.execute("DELETE FROM chunks_fts WHERE rowid=?", (rowid,))
            conn.execute("DELETE FROM embeddings WHERE chunk_id=?", (rowid,))
        conn.execute("DELETE FROM chunks WHERE doc_path=?", (rel,))
        cur = conn.execute("DELETE FROM documents WHERE path=?", (rel,))
        return cur.rowcount

    def delete(self, path: str | None = None) -> dict[str, Any]:
        """Delete one indexed document, or the whole index when path is None."""
        if path is None:
            try:
                self.path.unlink(missing_ok=True)
                for suffix in ("-wal", "-shm"):
                    Path(str(self.path) + suffix).unlink(missing_ok=True)
            except OSError as exc:
                raise HTTPException(422, f"Could not delete the index: {exc}") from None
            return {"deleted": "index", "documents": 0}
        with self._connect() as conn:
            removed = self._delete_document(conn, path)
            conn.commit()
        if not removed:
            raise HTTPException(404, "That document is not in the index.")
        return {"deleted": path, "documents": 1}

    # -- reads ----------------------------------------------------------
    def status(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"exists": False, "documents": [], "chunks": 0, "adapters": [],
                    "bytes": 0, "stale": []}
        root = sandbox.default_root().resolve()
        with self._connect() as conn:
            docs = conn.execute(
                "SELECT path, sha256, adapter, dim, indexed_at, chunk_count, partial"
                " FROM documents ORDER BY indexed_at").fetchall()
            total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        stale: list[str] = []
        entries = []
        for path, sha, adapter, dim, indexed_at, count, partial in docs:
            current = None
            try:
                current = _sha(root / path)
            except OSError:
                current = None
            is_stale = current != sha
            if is_stale:
                stale.append(path)
            entries.append({"path": path, "sha256": sha, "adapter": adapter, "dim": dim,
                            "indexed_at": indexed_at, "chunks": count,
                            "partial": bool(partial), "stale": is_stale})
        return {"exists": True, "documents": entries, "chunks": total,
                "adapters": sorted({d["adapter"] for d in entries}),
                "bytes": self.path.stat().st_size if self.path.exists() else 0,
                "stale": stale}

    def search(self, query: str, top_k: int = MAX_EVIDENCE,
               paths: list[str] | None = None) -> dict[str, Any]:
        tokens = _tokenise(query)
        if not tokens:
            raise HTTPException(422, "Use a search question with meaningful terms.")
        if not self.path.exists():
            raise HTTPException(404, "No document index exists yet; index sources first.")
        root = sandbox.default_root().resolve()
        with self._connect() as conn:
            docs = conn.execute("SELECT path, sha256, adapter FROM documents").fetchall()
        stale: list[str] = []
        live: dict[str, tuple[str, str]] = {}
        for path, sha, adapter in docs:
            if paths is not None and path not in paths:
                continue
            try:
                current = _sha(root / path)
            except OSError:
                current = None
            if current != sha:
                stale.append(path)
            else:
                live[path] = (sha, adapter)
        if not live:
            return {"results": [], "stale_sources": stale, "adapter": None,
                    "retrieval": "hybrid-index", "live_sources": 0}
        adapter_name = next(iter({a for _, a in live.values()}), "hashed")
        adapter = get_adapter(adapter_name)
        query_vector = adapter.embed([query])[0]
        with self._connect() as conn:
            placeholders = ",".join("?" for _ in live)
            rows = conn.execute(
                f"SELECT id, doc_path, chunk_no, section, page, offset, text FROM chunks"
                f" WHERE doc_path IN ({placeholders}) ORDER BY id LIMIT ?",
                (*live.keys(), MAX_INDEX_CHUNKS)).fetchall()
            id_set = {r[0] for r in rows}
            # Lexical ranking via FTS5 BM25.
            fts_query = " OR ".join(f'"{t}"' for t in sorted(set(tokens)))
            try:
                lexical = conn.execute(
                    "SELECT rowid, bm25(chunks_fts) FROM chunks_fts"
                    " WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT 200",
                    (fts_query,)).fetchall()
            except sqlite3.OperationalError:
                lexical = []
            lexical_rank = {rowid: rank for rank, (rowid, _score)
                            in enumerate(r for r in lexical if r[0] in id_set)}
            # Vector ranking via cosine similarity.
            vector_rank: dict[int, int] = {}
            try:
                import numpy as np
                ids = [r[0] for r in rows]
                blobs = conn.execute(
                    f"SELECT chunk_id, vector FROM embeddings WHERE chunk_id IN "
                    f"({','.join('?' for _ in ids)})", (*ids,)).fetchall() if ids else []
                by_id = {cid: _unpack(blob) for cid, blob in blobs}
                matrix = np.array([by_id[i] for i in ids if i in by_id], dtype=np.float32)
                kept = [i for i in ids if i in by_id]
                if len(kept):
                    q = np.array(query_vector, dtype=np.float32)
                    sims = matrix @ q
                    order = sorted(range(len(kept)), key=lambda k: -float(sims[k]))
                    vector_rank = {kept[k]: rank for rank, k in enumerate(order[:200])}
            except ImportError:
                scored = []
                for row in rows:
                    blob = conn.execute("SELECT vector FROM embeddings WHERE chunk_id=?",
                                        (row[0],)).fetchone()
                    if blob:
                        scored.append((_cosine(query_vector, _unpack(blob[0])), row[0]))
                scored.sort(key=lambda item: -item[0])
                vector_rank = {rowid: rank for rank, (_s, rowid)
                               in enumerate(scored[:200])}
        # Reciprocal-rank fusion of lexical and vector rankings.
        fused: dict[int, float] = {}
        for rowid, rank in lexical_rank.items():
            fused[rowid] = fused.get(rowid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        for rowid, rank in vector_rank.items():
            fused[rowid] = fused.get(rowid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        by_id_row = {r[0]: r for r in rows}
        ordered = sorted(fused.items(), key=lambda item: (-item[1], item[0]))
        results: list[dict[str, Any]] = []
        per_source: Counter[int] = Counter()
        source_numbers = {path: number for number, path in
                          enumerate(sorted(live), start=1)}
        last_offsets: dict[tuple[str, str], list[int]] = {}
        for rowid, score in ordered:
            row = by_id_row.get(rowid)
            if row is None:
                continue
            _id, doc_path, _chunk_no, section, page, offset, text = row
            source_index = source_numbers[doc_path]
            if per_source[source_index] >= 4:
                continue
            location = (doc_path, section)
            if any(abs(offset - previous) < CHUNK_STRIDE
                   for previous in last_offsets.get(location, [])):
                continue
            match_positions = [m.start() for m in _TERMS.finditer(text)
                               if m.group().casefold() in set(tokens)]
            first = min(match_positions) if match_positions else 0
            from_index = min(max(0, first - 90), max(0, len(text) - 450))
            quote = text[from_index:from_index + 450].strip()
            if len(quote) < 20:
                continue
            actual_offset = offset + text.find(quote)
            results.append({
                "id": f"S{source_index}-{per_source[source_index] + 1:02d}",
                "source": doc_path, "sha256": live[doc_path][0],
                "section": section, "page": page, "offset": actual_offset,
                "quote": quote,
                "matching_terms": sorted(set(_tokenise(quote)) & set(tokens)),
                "retrieval_score": round(score, 4),
                "retrieval": "hybrid-index", "adapter": adapter_name,
            })
            per_source[source_index] += 1
            last_offsets.setdefault(location, []).append(offset)
            if len(results) >= top_k:
                break
        return {"results": results, "stale_sources": stale, "adapter": adapter_name,
                "retrieval": "hybrid-index", "live_sources": len(live)}
