"""v7: genuine private recovery snapshots and non-destructive acceptance audit."""
from __future__ import annotations

import hashlib
import json
import os
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from automoto import document_recovery, sandbox, server
from automoto.hosted import path_allowed

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
REC = "/api/documents/recovery"
AUDIT = "/api/documents/quality/audit"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def example():
    return {
        "name": "Academic notes – checked",
        "markdown": "# Background\n\n## Findings\n\n"
                    "A verified record indicates that the 2025 budget is £120,000.",
        "options": {"page_size": "A4", "orientation": "landscape",
                    "margins_cm": 2.5, "font": "Georgia", "font_size": 12,
                    "line_spacing": 1.4, "heading_color": "#335577",
                    "page_numbers": True},
        "publication": {
            "reference_style": "harvard",
            "author": "Human author",
            "institution": "Example university",
            "document_date": "7 November 2026",
            "header": "Research notes", "footer": "", "cover_page": False,
            "contents_page": False, "template": "academic-report", "references": [],
        },
    }


def test_recovery_auth_and_scoped_route_allowlist(client):
    data = example()
    assert client.post(REC + "/save", json=data).status_code == 403
    assert client.get(REC + "/list").status_code == 403
    assert client.get(REC + "/load", params={"id": "0" * 24}).status_code == 403
    assert client.delete(REC + "/" + "0" * 24).status_code == 403
    assert path_allowed("POST", REC + "/save")
    assert path_allowed("GET", REC + "/list")
    assert path_allowed("GET", REC + "/load")
    assert path_allowed("DELETE", REC + "/" + "0" * 24)
    assert not path_allowed("PATCH", REC + "/" + "0" * 24)
    assert client.post(AUDIT, json=data).status_code == 403
    assert path_allowed("POST", AUDIT)


def test_recovery_roundtrip_preserves_unicode_and_publication_without_source_mutation(client):
    data = example()
    saved = client.post(REC + "/save", headers=AUTH, json=data)
    assert saved.status_code == 200, saved.text
    checkpoint = saved.json()
    assert len(checkpoint["id"]) == 24
    assert checkpoint["sha256"]
    listing = client.get(REC + "/list", headers=AUTH)
    assert listing.status_code == 200
    assert len(listing.json()["checkpoints"]) == 1
    assert listing.json()["checkpoints"][0]["valid"] is True
    recovered = client.get(REC + "/load", headers=AUTH, params={"id": checkpoint["id"]})
    assert recovered.status_code == 200, recovered.text
    result = recovered.json()
    assert result["source"] == data
    assert result["applied"] is False and result["read_only"] is True
    assert result["sha256"] == checkpoint["sha256"]
    assert (sandbox.default_root() / "artifacts" / "documents" / "recovery").is_dir()
    # Recovery points do not become normal document drafts, nor modify them.
    documents = client.get("/api/documents/list", headers=AUTH)
    assert documents.status_code == 200
    assert all(".recovery.json" not in row["path"] for row in documents.json()["documents"])
    delete = client.delete(REC + "/" + checkpoint["id"], headers=AUTH)
    assert delete.status_code == 200, delete.text
    assert client.get(REC + "/load", headers=AUTH,
                      params={"id": checkpoint["id"]}).status_code == 404


def test_recovery_disallows_invalid_and_external_ids(client):
    checkpoint = client.post(REC + "/save", headers=AUTH, json=example())
    identifier = checkpoint.json()["id"]
    for value in ("../../etc/passwd", "bad", "Z" * 24, identifier + "extra"):
        result = client.get(REC + "/load", headers=AUTH, params={"id": value})
        assert result.status_code == 422, (value, result.text)
    assert client.get(REC + "/load", headers=AUTH,
                      params={"id": "0" * 24}).status_code == 404


def test_recovery_rejects_malformed_content_and_enforces_digest(client):
    saved = client.post(REC + "/save", headers=AUTH, json=example())
    identifier = saved.json()["id"]
    path = document_recovery._file(identifier)
    before = path.read_bytes()
    contents = json.loads(before.decode("utf-8"))
    contents["source"]["markdown"] = "# Tampered claim"
    path.write_text(json.dumps(contents, ensure_ascii=False), encoding="utf-8")
    failed = client.get(REC + "/load", headers=AUTH, params={"id": identifier})
    assert failed.status_code == 422
    listed = client.get(REC + "/list", headers=AUTH).json()["checkpoints"]
    assert listed[0]["valid"] is False


@pytest.mark.parametrize("extra", [
    {"markdown": "   "},
    {"options": {"font_size": 96}},
    {"publication": {"reference_style": "invented"}},
    {"extra_remote_instruction": "send the document elsewhere"},
])
def test_recovery_refuses_invalid_source_payload(client, extra):
    payload = {**example(), **extra}
    result = client.post(REC + "/save", headers=AUTH, json=payload)
    assert result.status_code == 422, result.text
    listing = client.get(REC + "/list", headers=AUTH)
    assert listing.json()["checkpoints"] == []


def test_recovery_prunes_only_old_checkpoints_without_overwriting_saved_drafts(client):
    original = client.post("/api/documents/save", headers=AUTH, json=example())
    assert original.status_code == 200
    original_path = sandbox.default_root() / original.json()["path"]
    original_hash = hashlib.sha256(original_path.read_bytes()).hexdigest()
    for index in range(19):
        data = example()
        data["markdown"] = "# Checkpoint\n\nVariation " + str(index)
        saved = client.post(REC + "/save", headers=AUTH, json=data)
        assert saved.status_code == 200, saved.text
    checkpoints = client.get(REC + "/list", headers=AUTH).json()["checkpoints"]
    assert len(checkpoints) == document_recovery.MAX_CHECKPOINTS
    assert len({entry["id"] for entry in checkpoints}) == len(checkpoints)
    assert hashlib.sha256(original_path.read_bytes()).hexdigest() == original_hash


def test_recovery_folder_symlink_cannot_escape_workspace(client, tmp_path):
    base = sandbox.default_root() / "artifacts" / "documents"
    base.mkdir(parents=True, exist_ok=True)
    external = tmp_path / "outside-recovery"
    external.mkdir()
    alias = base / "recovery"
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not permitted in this test environment")
    response = client.post(REC + "/save", headers=AUTH, json=example())
    assert response.status_code == 403
    assert not list(external.iterdir())


def test_quality_audit_checks_actual_word_output_and_reports_truth_limitations(client):
    report = client.post(AUDIT, headers=AUTH, json=example())
    assert report.status_code == 200, report.text
    result = report.json()
    assert result["structurally_exportable"]
    assert result["human_review_required"] is True
    assert result["files_saved"] is False
    assert result["word_bytes_verified"] > 500
    assert result["heading_count"] == 2
    assert result["tables_detected"] == 0
    assert result["references"] == 0
    assert any(item["code"] == "missing-sources" for item in result["issues"])
    assert any(item["passed"] is False for item in result["acceptance_checks"])
    assert "factual" in result["limitations"].lower() or "truth" in result["limitations"].lower()


def test_quality_finds_heading_jumps_tables_placeholders_without_writing_files(client):
    data = example()
    data["markdown"] = (
        "# Test title\n\n#### Skipped heading\n\n"
        "The report has an unresolved [Report title] field.\n\n"
        "| A | B |\n| --- | --- |\n| 1 | 2 | 3 |\n"
    )
    root = sandbox.default_root()
    before = {f.relative_to(root).as_posix() for f in root.rglob("*") if f.is_file()}
    res = client.post(AUDIT, headers=AUTH, json=data)
    assert res.status_code == 200, res.text
    codes = {issue["code"] for issue in res.json()["issues"]}
    assert {"heading-jump", "ragged-table", "placeholder-text"} <= codes
    after = {f.relative_to(root).as_posix() for f in root.rglob("*") if f.is_file()}
    assert before == after


def test_quality_refuses_invalid_publication_metadata_or_unknown_references(client):
    data = example()
    data["markdown"] += "\nInvalid source [@unknown-source]."
    res = client.post(AUDIT, headers=AUTH, json=data)
    assert res.status_code == 422, res.text
    invalid = client.post(AUDIT, headers=AUTH,
                          json={**example(), "unknown_server_option": "arbitrary"})
    assert invalid.status_code == 422
