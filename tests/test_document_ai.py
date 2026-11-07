"""v3 offline document assistant: non-mutating, local-only review contracts."""
from __future__ import annotations

import hashlib
import json

import pytest
from docx import Document
from fastapi.testclient import TestClient
from fastapi import HTTPException

from automoto import document_ai, local_llm, sandbox, server
from automoto.hosted import path_allowed

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BASE = "/api/documents/ai/review"
SOURCE = "# Research notes\n\nThe annual budget is £150,000. Costs fell by 12% in 2025.\n"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def payload(mode="proofread", text=SOURCE, start=0, end=None):
    return {"mode": mode, "markdown": text, "start": start,
            "end": len(text) if end is None else end,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def _fake_ollama(monkeypatch, answer):
    monkeypatch.setattr(document_ai, "_loopback_ollama", lambda: "http://127.0.0.1:11434")
    monkeypatch.setattr(document_ai, "_selected_model", lambda: "downloaded-local-model")
    monkeypatch.setattr(document_ai, "_ask_model", lambda model, mode, source: answer)


def test_no_auth_and_hosted_are_closed(client):
    assert client.post(BASE, json=payload()).status_code == 403
    assert not path_allowed("POST", BASE), "hosted accounts cannot reach local-only AI"
    assert not path_allowed("GET", BASE)


def test_local_model_must_be_explicitly_enabled(client, monkeypatch):
    monkeypatch.setattr(local_llm, "enabled", lambda name: False)
    response = client.post(BASE, headers=AUTH, json=payload())
    assert response.status_code == 503
    assert "Enable" in response.text
    assert not (sandbox.default_root() / "artifacts" / "documents").exists()


def test_loopback_restriction_rejects_private_lan_and_remote_hosts(monkeypatch):
    for address in ("https://127.0.0.1:11434", "http://192.168.1.20:11434",
                    "http://example.invalid:11434", "http://127.0.0.1:11434/path",
                    "http://alice:secret@localhost:11434"):
        monkeypatch.setattr(local_llm, "ollama_url", lambda: address)
        with pytest.raises(HTTPException) as error:
            document_ai._loopback_ollama()
        assert error.value.status_code == 503
    monkeypatch.setattr(local_llm, "ollama_url", lambda: "http://localhost:11434")
    assert document_ai._loopback_ollama() == "http://localhost:11434"


def test_proofreading_and_rewrite_are_non_destructive_and_reviewable(client, monkeypatch):
    _fake_ollama(monkeypatch, {"proposal": "# Research notes\n\nThe annual budget is £150,000. "
                             "Costs fell by 12% in 2025.\n",
                             "explanation": "No correction needed."})
    result = client.post(BASE, headers=AUTH, json=payload())
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["provider"] == "ollama-local"
    assert data["model"] == "downloaded-local-model"
    assert data["requires_approval"] is True and data["applied"] is False
    assert data["proposal"] == SOURCE and data["changed"] is False
    assert data["selection"] == {"start": 0, "end": len(SOURCE)}
    assert data["sha256"] == payload()["sha256"]
    assert not (sandbox.default_root() / "artifacts" / "documents").exists()
    source = "The data were presented in the report."
    _fake_ollama(monkeypatch, {"proposal": "The report presented the data.",
                             "explanation": "More direct wording."})
    changed = client.post(BASE, headers=AUTH, json=payload("rewrite", source))
    assert changed.status_code == 200
    assert changed.json()["proposal"] == "The report presented the data."
    assert changed.json()["changed"] is True


def test_exact_selected_text_is_sent_to_model(client, monkeypatch):
    seen = []
    def answer(model, mode, source):
        seen.append((mode, source))
        return {"proposal": "Better wording.", "explanation": "Clearer."}
    _fake_ollama(monkeypatch, {})
    monkeypatch.setattr(document_ai, "_ask_model", answer)
    start = SOURCE.index("Costs fell")
    end = SOURCE.index("2025.") + 5
    response = client.post(BASE, headers=AUTH,
                           json=payload("rewrite", SOURCE, start, end))
    assert response.status_code == 200, response.text
    assert seen == [("rewrite", "Costs fell by 12% in 2025.")]
    assert response.json()["selection"] == {"start": start, "end": end}


def test_summary_quotes_verified_against_actual_source(client, monkeypatch):
    quote = "The annual budget is £150,000."
    _fake_ollama(monkeypatch, {"points": [
        {"claim": "The stated budget is £150,000.", "quote": quote},
        {"claim": "There are one million employees.", "quote": "One million employees"},
        {"claim": "Costs fell in 2025.", "quote": "Costs fell by 12% in 2025."},
    ]})
    response = client.post(BASE, headers=AUTH, json=payload("summary"))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["proposal"] is None
    assert len(data["evidence"]) == 2
    assert data["evidence"][0]["quote"] == quote
    assert data["evidence"][0]["offset"] == SOURCE.index(quote)
    assert data["evidence"][1]["offset"] == SOURCE.index("Costs fell")


def test_summary_without_verifiable_evidence_is_rejected(client, monkeypatch):
    _fake_ollama(monkeypatch, {"points": [
        {"claim": "The source proves unusual facts.", "quote": "A fabricated quotation"}
    ]})
    response = client.post(BASE, headers=AUTH, json=payload("summary"))
    assert response.status_code == 422
    assert "evidence" in response.text.lower()


def test_invalid_payloads_and_stale_source_fail_before_model(client, monkeypatch):
    calls = []
    _fake_ollama(monkeypatch, {})
    monkeypatch.setattr(document_ai, "_ask_model", lambda *args: calls.append(args))
    cases = [
        {**payload(), "sha256": "0" * 64},
        {**payload(), "start": 15, "end": 2},
        {**payload(), "start": len(SOURCE) + 1},
        {**payload(), "extra_untrusted_key": "execute this"},
        payload(text="Z" * 12001),
        payload(text=""),
    ]
    for bad in cases:
        response = client.post(BASE, headers=AUTH, json=bad)
        assert response.status_code in (409, 413, 422), response.text
    assert not calls


def test_invalid_and_massive_model_proposals_cannot_be_applied(client, monkeypatch):
    _fake_ollama(monkeypatch, {"proposal": "", "explanation": "no"})
    assert client.post(BASE, headers=AUTH, json=payload()).status_code == 422
    _fake_ollama(monkeypatch, {"proposal": "x" * 12001, "explanation": "no"})
    assert client.post(BASE, headers=AUTH, json=payload()).status_code == 422
    _fake_ollama(monkeypatch, {"proposal": "x" * 1000, "explanation": "no"})
    assert client.post(BASE, headers=AUTH, json=payload(text="Hello.")).status_code == 422


def test_imported_docx_is_server_verified_and_never_modified(client, monkeypatch):
    root = sandbox.default_root()
    original = root / "uploads" / "research.docx"
    original.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    doc.add_heading("Annual report", 1)
    doc.add_paragraph("Costs fell by 12% in 2025.")
    doc.save(original)
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    _fake_ollama(monkeypatch, {"points": [{
        "claim": "The report states costs fell in 2025.",
        "quote": "Costs fell by 12% in 2025.",
    }]})
    response = client.post(BASE, headers=AUTH, json={
        "mode": "summary", "source_path": "uploads/research.docx", "source_sha256": digest})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["source"] == "verified-import"
    assert data["requires_approval"] and not data["applied"]
    assert data["evidence"][0]["quote"] == "Costs fell by 12% in 2025."
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
    wrong = client.post(BASE, headers=AUTH, json={
        "mode": "summary", "source_path": "uploads/research.docx",
        "source_sha256": "0" * 64})
    assert wrong.status_code == 409
    forbidden = client.post(BASE, headers=AUTH, json={
        "mode": "rewrite", "source_path": "uploads/research.docx", "source_sha256": digest})
    assert forbidden.status_code == 422
    outside = client.post(BASE, headers=AUTH, json={
        "mode": "summary", "source_path": "../../secret.docx", "source_sha256": digest})
    assert outside.status_code in (403, 404)
