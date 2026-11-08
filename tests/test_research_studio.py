"""Research Studio V1: evidence-first private projects and regression safeguards."""
from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from automoto import document_research, sandbox, server
from automoto.hosted import path_allowed

BASE = "/api/research/studio"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
TEXT = (
    "The verified local project audit recorded 42 inspected documents and a "
    "documented review budget of GBP 120000 for the 2026 reporting period. "
    "The observations are specific to the source and do not independently "
    "establish whether the programme's reported outcomes are true. "
) * 6


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "research-home"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def source(name="evidence.txt", content=TEXT):
    p = sandbox.default_root() / "uploads" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def pinned(path):
    return {"path": "uploads/" + path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def project(path, question="What is the documented review budget for the project?", **overrides):
    return {
        "title": "Research audit project", "question": question,
        "notes": "Compare source excerpts without inventing references.",
        "sources": [pinned(path)], "mode": "evidence", **overrides
    }


def test_authentication_and_hosted_allowlist(client):
    for endpoint in ("sources", "list", "open"):
        assert path_allowed("GET", BASE + "/" + endpoint)
    for endpoint in ("query", "save"):
        assert path_allowed("POST", BASE + "/" + endpoint)
    for action in ("delete", "crawl", "search-online", "publish", "edit-source", "ai"):
        assert not path_allowed("POST", BASE + "/" + action)
    assert client.get(BASE + "/sources").status_code == 403
    assert client.get(BASE + "/list").status_code == 403
    path = source()
    assert client.post(BASE + "/save", json=project(path)).status_code == 403


def test_private_source_catalogue_and_read_only_evidence(client, monkeypatch):
    file = source()
    monkeypatch.setattr(document_research, "_synthesise",
                        lambda *args: pytest.fail("V1 must never call an LLM"))
    catalogue = client.get(BASE + "/sources", headers=AUTH)
    assert catalogue.status_code == 200, catalogue.text
    assert catalogue.json()["internet_used"] is False
    assert any(item["path"] == "uploads/evidence.txt"
               for item in catalogue.json()["sources"])
    response = client.post(BASE + "/query", headers=AUTH, json=project(file))
    assert response.status_code == 200, response.text
    data = response.json()
    result = data["result"]
    assert result["read_only"] is True and result["applied"] is False
    assert result["source_count"] == 1
    assert result["has_verifiable_matches"]
    assert result["evidence"]
    assert result["evidence"][0]["id"] == "S1-01"
    assert result["evidence"][0]["sha256"] == pinned(file)["sha256"]
    assert result["evidence"][0]["source"] == "uploads/evidence.txt"
    assert result["evidence"][0]["page"] is None
    assert data["no_cloud_model"] and data["source_files_modified"] is False


def test_create_only_project_save_open_and_historical_evidence(client):
    file = source()
    before = file.read_bytes()
    first = client.post(BASE + "/save", headers=AUTH, json=project(file))
    assert first.status_code == 200, first.text
    first_data = first.json()
    assert first_data["create_only"] and first_data["verified_citations_only"]
    assert first_data["evidence_count"] >= 1
    rel = first_data["path"]
    assert rel.startswith("artifacts/research/") and rel.endswith(".research.json")
    saved = sandbox.default_root() / rel
    assert saved.is_file()
    assert hashlib.sha256(saved.read_bytes()).hexdigest() == first_data["sha256"]
    loaded = client.get(BASE + "/open", headers=AUTH, params={"path": rel})
    assert loaded.status_code == 200, loaded.text
    data = loaded.json()
    assert data["project"]["question"] == project(file)["question"]
    assert data["source_status"][0]["status"] == "current"
    assert data["historical_evidence"] is True
    assert data["result"]["evidence"][0]["source"] == "uploads/evidence.txt"
    assert file.read_bytes() == before
    second = client.post(BASE + "/save", headers=AUTH, json=project(file))
    assert second.status_code == 200
    assert second.json()["path"] != rel
    assert hashlib.sha256(saved.read_bytes()).hexdigest() == first_data["sha256"]
    listed = client.get(BASE + "/list", headers=AUTH).json()["projects"]
    assert {item["path"] for item in listed} == {rel, second.json()["path"]}


def test_changed_or_deleted_sources_are_flagged_in_historical_snapshot(client):
    file = source()
    snapshot = client.post(BASE + "/save", headers=AUTH, json=project(file)).json()
    file.write_text(TEXT + "Changed after saving.", encoding="utf-8")
    stale = client.get(BASE + "/open", headers=AUTH,
                       params={"path": snapshot["path"]}).json()
    assert stale["source_status"][0]["status"] == "changed"
    refreshed = client.post(BASE + "/query", headers=AUTH, json=project(file))
    assert refreshed.status_code == 200, refreshed.text
    # Supplying the original fingerprint after modification fails safely.
    prior = snapshot["sha256"]
    original = stale["project"]
    assert original["sources"][0]["sha256"] != pinned(file)["sha256"]
    conflict = client.post(BASE + "/query", headers=AUTH, json=original)
    assert conflict.status_code == 409
    file.unlink()
    missing = client.get(BASE + "/open", headers=AUTH,
                         params={"path": snapshot["path"]}).json()
    assert missing["source_status"][0]["status"] == "missing_or_unavailable"


def test_saving_does_not_accept_fabricated_client_evidence(client):
    file = source()
    body = {**project(file), "result": {"evidence": [{
        "quote": "An invented statement", "page": 1, "source": "fake"
    }]}}
    assert client.post(BASE + "/save", headers=AUTH, json=body).status_code == 422
    body.pop("result")
    real = client.post(BASE + "/save", headers=AUTH, json=body)
    assert real.status_code == 200
    saved = json.loads((sandbox.default_root()/real.json()["path"]).read_text())
    assert not any(item.get("quote") == "An invented statement"
                   for item in saved["result"]["evidence"])


def test_missing_hash_duplicate_and_invalid_questions_refused(client):
    file = source()
    original = project(file)
    bad_hash = {**original, "sources": [{**pinned(file), "sha256": "0"*64}]}
    assert client.post(BASE + "/query", json=bad_hash, headers=AUTH).status_code == 409
    same_twice = {**original, "sources": [pinned(file), pinned(file)]}
    assert client.post(BASE + "/save", json=same_twice, headers=AUTH).status_code == 422
    for invalid in ("x", "and or the", "\u0000unsafe source question"):
        response = client.post(BASE + "/query", headers=AUTH,
                               json={**original, "question": invalid})
        assert response.status_code == 422, response.text
    assert client.post(BASE + "/query", headers=AUTH,
                       json={**original, "mode": "synthesis"}).status_code == 422


@pytest.mark.parametrize("bad", [
    "../../etc/passwd", "/tmp/test.research.json",
    "uploads/example.pdf", "artifacts/research/../x.research.json",
    "artifacts/research/research-abcdefghijklaaaaaaaaaaaa.research.json",
])
def test_project_open_never_leaves_private_research_folder(client, bad):
    response = client.get(BASE + "/open", headers=AUTH, params={"path": bad})
    assert response.status_code == 403, (bad, response.text)


def test_source_symlink_outside_workspace_is_rejected(client, tmp_path):
    victim = tmp_path / "other-person.txt"
    victim.write_text(TEXT, encoding="utf-8")
    link = sandbox.default_root() / "uploads" / "linked.txt"
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(victim)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unsupported on this platform.")
    response = client.post(BASE + "/save", headers=AUTH, json={
        **project(source()), "sources": [{
            "path": "uploads/linked.txt",
            "sha256": hashlib.sha256(victim.read_bytes()).hexdigest(),
        }]
    })
    assert response.status_code == 403, response.text


def test_research_is_tenant_workspace_scoped(client, tmp_path, monkeypatch):
    file = source()
    initial = client.post(BASE + "/save", headers=AUTH, json=project(file))
    assert initial.status_code == 200, initial.text
    initial_path = initial.json()["path"]
    saved = sandbox.default_root() / initial_path
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "second-workspace"))
    other = client.get(BASE + "/list", headers=AUTH)
    assert other.status_code == 200
    assert other.json()["projects"] == []
    assert client.get(BASE + "/open", headers=AUTH,
                      params={"path": initial_path}).status_code == 404
    assert saved.exists()


def test_read_only_query_does_not_write_files_or_contact_external_services(client, monkeypatch):
    file = source()
    import urllib.request
    def deny(*args, **kwargs):
        raise AssertionError("No network calls permitted in V1 evidence retrieval.")
    monkeypatch.setattr(urllib.request, "urlopen", deny)
    root = sandbox.default_root()
    before = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in root.rglob("*") if p.is_file()}
    response = client.post(BASE + "/query", headers=AUTH, json=project(file))
    assert response.status_code == 200, response.text
    after = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in root.rglob("*") if p.is_file()}
    assert before == after


def test_saved_project_schema_tampering_is_refused(client):
    file = source()
    response = client.post(BASE + "/save", headers=AUTH, json=project(file))
    assert response.status_code == 200, response.text
    saved = sandbox.default_root()/response.json()["path"]
    payload = json.loads(saved.read_text(encoding="utf-8"))
    payload["schema"] = "research-studio-v999"
    saved.write_text(json.dumps(payload), encoding="utf-8")
    assert client.get(BASE + "/open", headers=AUTH,
                      params={"path": response.json()["path"]}).status_code == 422
