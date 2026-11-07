"""Document Assistant v6: source-grounded offline academic evidence and safety."""
from __future__ import annotations

import hashlib
import io
import json

import pytest
from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject, DictionaryObject, NameObject, NumberObject
)

from automoto import document_research, sandbox, server
from automoto.hosted import path_allowed

BASE = "/api/documents/research"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
QUESTION = "What evidence is available about the research budget?"

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


def pinned(p):
    return {"path": "uploads/" + p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}


def request(query=QUESTION, sources=None, mode="evidence"):
    return {"query": query, "sources": sources or [], "mode": mode}


def test_requires_auth_and_scoped_hosted_routes(client):
    assert client.get(BASE + "/source-info", params={"path": "uploads/a.txt"}).status_code == 403
    p = make_text("a.txt", "The source confirms the research budget is £120,000.")
    assert client.post(BASE + "/query", json=request(sources=[pinned(p)])).status_code == 403
    assert path_allowed("GET", BASE + "/source-info")
    assert path_allowed("POST", BASE + "/query")
    assert not path_allowed("DELETE", BASE + "/query")


def test_deterministic_local_retrieval_never_calls_model_or_writes_files(client, monkeypatch):
    p = make_text("paper.txt", "The annual research budget for 2025 was £120,000. " * 40)
    root = sandbox.default_root()
    before_files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    info = client.get(BASE + "/source-info", params={"path": "uploads/paper.txt"}, headers=AUTH)
    assert info.status_code == 200, info.text
    assert info.json()["sha256"] == pinned(p)["sha256"]
    assert info.json()["read_only"]
    def reject_model(*a, **k):
        raise AssertionError("Local evidence retrieval must not invoke an AI model")
    monkeypatch.setattr(document_research, "_synthesise", reject_model)
    response = client.post(BASE + "/query", headers=AUTH,
                           json=request(sources=[pinned(p)]))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["read_only"] and body["applied"] is False
    assert body["source_count"] == 1 and body["has_verifiable_matches"]
    assert body["synthesis"] == [] and body["outline"] == []
    assert body["evidence"][0]["id"] == "S1-01"
    assert body["evidence"][0]["source"] == "uploads/paper.txt"
    assert body["evidence"][0]["sha256"] == pinned(p)["sha256"]
    assert body["evidence"][0]["page"] is None
    assert body["evidence"][0]["quote"] in p.read_text(encoding="utf-8")
    after_files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    assert after_files == before_files, "Search must not write or index any research files"


def test_two_sources_have_unique_verified_ids_and_search_relevance(client):
    a = make_text("alpha.md",
                  "# Data\n\nThe research budget for 2026 is £250,000. Evidence includes programme grants.\n")
    b = make_text("beta.txt",
                  "A separate study says that the research budget was £190,000 in 2024. "
                  "Funding restrictions caused delays.")
    result = client.post(BASE + "/query", headers=AUTH,
                         json=request(sources=[pinned(a), pinned(b)], mode="outline"))
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["has_verifiable_matches"] and data["source_count"] == 2
    assert len(data["outline"]) == 5
    assert {entry["source"] for entry in data["evidence"]} == {"uploads/alpha.md", "uploads/beta.txt"}
    assert len({entry["id"] for entry in data["evidence"]}) == len(data["evidence"])
    for item in data["evidence"]:
        path = sandbox.default_root() / item["source"]
        assert item["quote"] in path.read_text(encoding="utf-8")
        assert item["matching_terms"]


def test_word_and_draft_extracts_have_grounded_offsets_no_fabricated_page(client):
    root = sandbox.default_root()
    file = root / "uploads" / "research.docx"
    file.parent.mkdir(parents=True, exist_ok=True)
    word = Document()
    word.add_heading("Evidence review", level=1)
    word.add_paragraph("The university research budget was reduced by eight per cent in 2025. " * 4)
    word.save(file)
    draft = root / "artifacts" / "documents" / "my-report.document.json"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(json.dumps({
        "schema": 1, "name": "my report",
        "markdown": "# Sources\nThe department research budget was £350,000 in 2023. "
                    "The figures are unverified and must be checked."}), encoding="utf-8")
    sources = [
        {"path": file.relative_to(root).as_posix(), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()},
        {"path": draft.relative_to(root).as_posix(), "sha256": hashlib.sha256(draft.read_bytes()).hexdigest()}
    ]
    result = client.post(BASE + "/query", headers=AUTH,
                         json=request("What is the research budget for the university and department?", sources))
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["source_count"] == 2
    for evidence in data["evidence"]:
        assert evidence["page"] is None
        assert evidence["section"] in ("Extracted Word text", "Editable draft")
        assert evidence["quote"]
    assert hashlib.sha256(file.read_bytes()).hexdigest() == sources[0]["sha256"]


def test_pdf_passages_provide_real_page_numbers(client):
    p = sandbox.default_root() / "uploads" / "pages.pdf"
    p.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for text in ["The first page describes community services.",
                 "The second page gives the research budget of 480000 pounds."]:
        page = writer.add_blank_page(width=612, height=792)
        resources = DictionaryObject()
        font = DictionaryObject()
        font_obj = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        font[NameObject("/F1")] = writer._add_object(font_obj)
        resources[NameObject("/Font")] = font
        page[NameObject("/Resources")] = resources
        stream = DecodedStreamObject()
        stream.set_data(("BT /F1 12 Tf 72 680 Td (" + text + ") Tj ET").encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    with p.open("wb") as handle:
        writer.write(handle)
    result = client.post(BASE + "/query", headers=AUTH,
                         json=request("Which page gives the research budget?", [pinned(p)]))
    assert result.status_code == 200, result.text
    evidence = result.json()["evidence"]
    assert evidence
    assert evidence[0]["page"] == 2
    assert "research budget" in evidence[0]["quote"]


def test_no_source_match_or_scanned_pdf_is_reported_without_invented_citations(client):
    p = make_text("empty-findings.txt", "This contains meeting notes about attendance. " * 6)
    response = client.post(BASE + "/query", headers=AUTH,
                           json=request("quantum entanglement oscillator", [pinned(p)]))
    assert response.status_code == 200
    data = response.json()
    assert not data["has_verifiable_matches"]
    assert data["evidence"] == [] and data["synthesis"] == []


def test_stale_source_rejected_before_and_after_read(client, monkeypatch):
    p = make_text("changing.txt", "The research budget is 100 pounds. " * 6)
    old = pinned(p)
    p.write_text("The research budget is now 200 pounds.", encoding="utf-8")
    failed = client.post(BASE + "/query", headers=AUTH, json=request(sources=[old]))
    assert failed.status_code == 409
    current = pinned(p)
    previous = document_research._snapshot
    def mutate(*args, **kwargs):
        result = previous(*args, **kwargs)
        p.write_text("Changed during research processing.", encoding="utf-8")
        return result
    monkeypatch.setattr(document_research, "_snapshot", mutate)
    response = client.post(BASE + "/query", headers=AUTH, json=request(sources=[current]))
    assert response.status_code == 409


@pytest.mark.parametrize("bad_path", [
    "../../etc/passwd", "settings.json", "/etc/passwd", "uploads/../secrets.txt",
    "artifacts/visual-studio/file.docx", "uploads/picture.jpg"
])
def test_paths_cannot_escape_documents_workspace(client, bad_path):
    result = client.get(BASE + "/source-info", headers=AUTH, params={"path": bad_path})
    assert result.status_code in (403, 404, 415, 422), (bad_path, result.text)


def test_reject_duplicate_sources_and_invalid_inputs(client):
    p = make_text("source.txt", "The research budget was 95,000. " * 8)
    same = pinned(p)
    cases = [
        request(sources=[same, same]),
        request("the and for with", [same]),
        request(sources=[{"path": same["path"], "sha256": "x" * 64}]),
        request(sources=[same] * 6),
        request(sources=[]),
    ]
    for body in cases:
        response = client.post(BASE + "/query", headers=AUTH, json=body)
        assert response.status_code == 422, (body, response.text)


def test_extracted_large_document_is_capped_with_honest_warning(client):
    p = make_text("large.md", ("Research budget allocation is described here.\n" * 8_000))
    response = client.post(BASE + "/query", headers=AUTH,
                           json=request(sources=[pinned(p)]))
    assert response.status_code == 200, response.text
    assert response.json()["partial_sources"] == ["uploads/large.md"]
    assert len(response.json()["evidence"]) <= 8


def test_draft_is_read_only_and_no_reference_metadata_created(client):
    p = make_text("notes.md", "# Introduction\nThe programme research budget is 2000. " * 7)
    report = client.post(BASE + "/query", headers=AUTH,
                         json=request("research budget programme", [pinned(p)], "outline"))
    assert report.status_code == 200
    assert "author" not in report.json()["evidence"][0]
    assert "bibliography" not in report.json()
    assert p.read_text(encoding="utf-8").startswith("# Introduction")


def test_optional_local_synthesis_accepts_only_real_ids(client, monkeypatch):
    p = make_text("argument.md", "Verified records show the research budget was 20000 pounds. " * 5)
    monkeypatch.setattr(document_research, "_loopback_ollama",
                        lambda: "http://localhost:11434")
    monkeypatch.setattr(document_research, "_selected_model",
                        lambda: "downloaded-local-test-model")
    def stub_response(payload):
        return io.BytesIO(json.dumps({"message": {"content": json.dumps(payload)}}).encode())
    monkeypatch.setattr(document_research.urllib.request, "urlopen",
                        lambda *args, **kwargs: stub_response({"points": [
                            {"claim": "The document describes a specific research budget.",
                             "evidence_ids": ["S1-01"]},
                            {"claim": "Unsupported claims cannot use new references.",
                             "evidence_ids": ["MADE-UP"]},
                        ]}))
    result = client.post(BASE + "/query", headers=AUTH,
                         json=request("research budget", [pinned(p)], "synthesis"))
    assert result.status_code == 200, result.text
    assert result.json()["synthesis"] == [{
        "claim": "The document describes a specific research budget.",
        "evidence_ids": ["S1-01"],
    }]
    assert result.json()["applied"] is False


def test_unsupported_model_citations_never_return_synthesis(client, monkeypatch):
    p = make_text("citations.txt", "The research budget is one thousand pounds. " * 8)
    monkeypatch.setattr(document_research, "_loopback_ollama", lambda: "http://127.0.0.1:11434")
    monkeypatch.setattr(document_research, "_selected_model", lambda: "local-model")
    monkeypatch.setattr(document_research.urllib.request, "urlopen", lambda *a, **kw:
        io.BytesIO(b'{"message":{"content":"{\\"points\\":[{\\"claim\\":\\"This citation was fabricated by a model.\\",\\"evidence_ids\\":[\\"fake\\"]}]}"}}'))
    result = client.post(BASE + "/query", headers=AUTH,
                         json=request("research budget", [pinned(p)], "synthesis"))
    assert result.status_code == 422, result.text


def test_no_local_ai_call_when_retrieval_finds_nothing(client, monkeypatch):
    p = make_text("no-matches.txt", "Birmingham council meeting record. " * 8)
    monkeypatch.setattr(document_research, "_synthesise", lambda *a:
                        (_ for _ in ()).throw(AssertionError("unnecessary AI call")))
    result = client.post(BASE + "/query", headers=AUTH,
                         json=request("the telescope observatory", [pinned(p)], "synthesis"))
    assert result.status_code == 200
    assert result.json()["synthesis"] == []


def test_source_change_during_ai_synthesis_invalidates_answer(client, monkeypatch):
    p = make_text("ai-change.md", "The research budget was 15000. " * 6)
    data = pinned(p)
    def mutate(*a):
        p.write_text("Document changed while the model was reviewing.", encoding="utf-8")
        return [{"claim": "Budget", "evidence_ids": ["S1-01"]}]
    monkeypatch.setattr(document_research, "_synthesise", mutate)
    result = client.post(BASE + "/query", headers=AUTH,
                         json=request("research budget", [data], "synthesis"))
    assert result.status_code == 409
