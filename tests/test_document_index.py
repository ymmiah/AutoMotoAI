"""Document Assistant v8: persistent local RAG index (issue #10, Phase 1).

Covers: hashed embeddings are deterministic, the SQLite FTS5 + vector
index is built, searched and deleted by the owner, quotes stay verbatim
with source SHA-256 / page / offset citations, changed sources go stale
instead of being searched, and indexed research works across 20+ sources.
"""
from __future__ import annotations

import hashlib
import io

import pytest
from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject, DictionaryObject, NameObject, NumberObject
)

from automoto import document_index, sandbox, server

BASE = "/api/documents/research"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def make_text(filename: str, text: str):
    p = sandbox.default_root() / "uploads" / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def make_docx(filename: str, text: str):
    p = sandbox.default_root() / "uploads" / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    doc.add_paragraph(text)
    doc.save(str(p))
    return p


def make_pdf(filename: str, text: str):
    from pypdf import PdfWriter
    p = sandbox.default_root() / "uploads" / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    page = writer.add_blank_page(612, 792)
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    resources = DictionaryObject()
    font = DictionaryObject()
    font.update({NameObject("/F1"): DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica")})})
    resources[NameObject("/Font")] = font
    page[NameObject("/Resources")] = resources
    writer.add_page(page)
    with p.open("wb") as fh:
        writer.write(fh)
    return p


def pinned(p):
    return {"path": "uploads/" + p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}


def test_hashed_embeddings_are_deterministic_and_local():
    adapter = document_index.HashedEmbeddingAdapter()
    first = adapter.embed(["The research budget is £120,000."])
    second = adapter.embed(["The research budget is £120,000."])
    assert first == second
    assert len(first[0]) == document_index.EMBED_DIM
    other = adapter.embed(["Completely unrelated cooking recipes."])
    assert first[0] != other[0]
    assert document_index._cosine(first[0], first[0]) == pytest.approx(1.0)
    assert document_index._cosine(first[0], other[0]) < 0.9


def test_unknown_adapter_is_rejected():
    with pytest.raises(Exception):
        document_index.get_adapter("pinecone")


def test_index_status_empty_before_indexing(client):
    response = client.get(BASE + "/index/status", headers=AUTH)
    assert response.status_code == 200, response.text
    assert response.json()["exists"] is False
    assert response.json()["documents"] == []


def test_query_with_index_but_no_index_is_404(client):
    p = make_text("a.txt", "The research budget is £120,000.")
    response = client.post(BASE + "/query", headers=AUTH, json={
        "query": "What is the research budget?", "sources": [pinned(p)],
        "mode": "evidence", "use_index": True})
    assert response.status_code == 404, response.text


def test_build_search_and_delete_index(client):
    txt = make_text("paper.txt", "The annual research budget for 2025 was £120,000. " * 40)
    docx = make_docx("notes.docx", "The fieldwork schedule depends on the spring timetable. " * 20)
    pdf = make_pdf("memo.pdf", "The research budget committee meets in March.")
    build = client.post(BASE + "/index", headers=AUTH, json={
        "sources": [pinned(txt), pinned(docx), pinned(pdf)], "adapter": "hashed"})
    assert build.status_code == 200, build.text
    assert len(build.json()["indexed"]) == 3
    assert build.json()["skipped"] == []
    assert build.json()["adapter"] == "hashed"

    status = client.get(BASE + "/index/status", headers=AUTH)
    assert status.status_code == 200
    body = status.json()
    assert body["exists"] is True
    assert len(body["documents"]) == 3
    assert body["chunks"] >= 3
    assert body["stale"] == []

    response = client.post(BASE + "/query", headers=AUTH, json={
        "query": "What is the research budget?", "sources": [pinned(txt)],
        "mode": "evidence", "use_index": True})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["retrieval"] == "hybrid-index"
    assert data["has_verifiable_matches"]
    assert data["stale_sources"] == []
    first = data["evidence"][0]
    assert first["source"] == "uploads/paper.txt"
    assert first["sha256"] == pinned(txt)["sha256"]
    assert first["page"] is None
    assert first["quote"] in txt.read_text(encoding="utf-8")
    assert first["adapter"] == "hashed"

    deleted = client.request("DELETE", BASE + "/index", headers=AUTH,
                             json={"path": "uploads/notes.docx"})
    assert deleted.status_code == 200, deleted.text
    assert client.get(BASE + "/index/status", headers=AUTH).json()["chunks"] < body["chunks"]

    wiped = client.request("DELETE", BASE + "/index", headers=AUTH, json={})
    assert wiped.status_code == 200, wiped.text
    assert client.get(BASE + "/index/status", headers=AUTH).json()["exists"] is False


def test_changed_source_goes_stale_not_searched(client):
    p = make_text("paper.txt", "The research budget is £120,000. " * 40)
    assert client.post(BASE + "/index", headers=AUTH,
                       json={"sources": [pinned(p)]}).status_code == 200
    p.write_text("This document now says something entirely different. " * 40,
                 encoding="utf-8")
    status = client.get(BASE + "/index/status", headers=AUTH).json()
    assert status["stale"] == ["uploads/paper.txt"]
    assert status["documents"][0]["stale"] is True
    response = client.post(BASE + "/query", headers=AUTH, json={
        "query": "What is the research budget?", "sources": [pinned(p)],
        "mode": "evidence", "use_index": True})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["stale_sources"] == ["uploads/paper.txt"]
    assert data["evidence"] == []
    assert data["has_verifiable_matches"] is False


def test_index_rebuild_after_change(client):
    p = make_text("paper.txt", "The research budget is £120,000. " * 40)
    assert client.post(BASE + "/index", headers=AUTH,
                       json={"sources": [pinned(p)]}).status_code == 200
    p.write_text("The revised research budget is £95,000. " * 40, encoding="utf-8")
    build = client.post(BASE + "/index", headers=AUTH,
                        json={"sources": [pinned(p)]})
    assert build.status_code == 200, build.text
    assert build.json()["indexed"][0]["sha256"] == pinned(p)["sha256"]
    response = client.post(BASE + "/query", headers=AUTH, json={
        "query": "What is the revised research budget?", "sources": [pinned(p)],
        "mode": "evidence", "use_index": True})
    assert response.status_code == 200, response.text
    assert response.json()["has_verifiable_matches"]
    assert "£95,000" in response.json()["evidence"][0]["quote"]


def test_index_scales_to_twenty_sources(client):
    # Twenty near-identical documents would tie under the tokeniser, so
    # each briefing gets a distinct topic word the query can discriminate.
    topics = ["harbour", "orchard", "meadow", "quarry", "vineyard", "harbourmaster",
              "cobalt", "marble", "willow", "granite", "copper", "saffron",
              "timber", "velvet", "zephyr", "quartz", "bazaar", "lantern",
              "compass", "anchor"]
    sources = []
    for i, topic in enumerate(topics):
        text = (f"This is the briefing on {topic}. The {topic} allocation is "
                f"£{1000 + i * 37}. " * 12)
        sources.append(pinned(make_text(f"brief-{i:02d}.txt", text)))
    build = client.post(BASE + "/index", headers=AUTH,
                        json={"sources": sources, "adapter": "hashed"})
    assert build.status_code == 200, build.text
    assert len(build.json()["indexed"]) == 20
    response = client.post(BASE + "/query", headers=AUTH, json={
        "query": "What is the allocation for lantern?",
        "sources": sources, "mode": "evidence", "use_index": True})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["has_verifiable_matches"]
    assert any(e["source"] == "uploads/brief-17.txt" for e in data["evidence"])
    assert any("lantern" in e["quote"] for e in data["evidence"])
    # Whole-index search: no pinned sources searches every live document.
    whole = client.post(BASE + "/query", headers=AUTH, json={
        "query": "What is the allocation for lantern?",
        "sources": [], "mode": "evidence", "use_index": True})
    assert whole.status_code == 200, whole.text
    assert whole.json()["source_count"] == 20
    assert any(e["source"] == "uploads/brief-17.txt"
               for e in whole.json()["evidence"])
