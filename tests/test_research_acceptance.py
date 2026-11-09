"""Research Studio V7 acceptance: archive integrity, source staleness and recovery safety."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from automoto import research_acceptance, research_ai, sandbox, server
from automoto.hosted import path_allowed

H = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BASE = "/api/research/studio/acceptance"
QUESTION = "What did the independent system audits report about deployment security?"
A = ("The independent security audit observed lower deployment exposure after "
     "build verification, within one limited team. ") * 18
B = ("A separate audit observed security exposure from insufficient monitoring "
     "and unresolved control failures, within its limited sample. ") * 18


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "v7-home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "v7-workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    return TestClient(server.app)


def approved_comparison(client):
    root = sandbox.default_root()
    uploads = root / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    sources = []
    for i, sample in enumerate((A, B), 1):
        file = uploads / f"audit-{i}.txt"
        file.write_text(sample, encoding="utf-8")
        sources.append({"path": "uploads/" + file.name, "sha256": sha(file.read_bytes())})
    saved = client.post("/api/research/studio/save", headers=H, json={
        "title": "Research V7 recovery verification",
        "question": QUESTION, "notes": "Read-only research acceptance.",
        "sources": sources, "mode": "evidence",
    })
    assert saved.status_code == 200, saved.text
    prepare = client.post("/api/research/studio/compare/prepare", headers=H,
                          json={"project_path": saved.json()["path"]})
    assert prepare.status_code == 200, prepare.text
    result = prepare.json()
    review = client.post("/api/research/studio/compare/save", headers=H, json={
        "project_path": saved.json()["path"], "project_sha256": result["project_sha256"],
        "claim": QUESTION,
        "annotations": [
            {"evidence_id": e["id"],
             "stance": "supports" if e["source"] == sources[0]["path"] else "contradicts",
             "rationale": "I verified the quotation but did not verify its causal implications."}
            for e in result["evidence"]],
        "source_reviews": [
            {"source_path": s["path"], "methodology": "observational",
             "quality": "not_assessed",
             "limitations": "Unverified in wider academic literature."}
            for s in sources],
        "acknowledgement": "SAVE REVIEW", "confirm_human_classification": True,
    })
    assert review.status_code == 200, review.text
    path = review.json()["path"]
    return {"comparison_path": path,
            "comparison_sha256": sha((root / path).read_bytes())}, sources


def copy_body(ref):
    return {**ref, "acknowledgement": "SAVE PRIVATE RESEARCH RECOVERY",
            "confirm_no_publication": True}


def test_protected_paths_and_hosted_default_deny(client):
    for method, endpoint in (("POST", "audit"), ("POST", "snapshot"), ("POST", "verify"),
                             ("POST", "stage"), ("GET", "list")):
        assert not path_allowed(method, BASE + "/" + endpoint)
    sample = {"comparison_path": "artifacts/research/comparisons/comparison-" + "a" * 24 + ".comparison.json",
              "comparison_sha256": "f" * 64}
    for endpoint in ("audit", "snapshot"):
        req = copy_body(sample) if endpoint == "snapshot" else sample
        assert client.post(BASE + "/" + endpoint, json=req).status_code == 403
    ref = {"path": "artifacts/research/recovery/snapshots/backup-" + "b" * 24 + ".recovery.json",
           "sha256": "f" * 64}
    assert client.post(BASE + "/verify", json=ref).status_code == 403
    assert client.post(BASE + "/stage", json={**ref,
        "acknowledgement": "STAGE FILES WITHOUT OVERWRITING",
        "confirm_no_original_changes": True}).status_code == 403
    assert client.get(BASE + "/list").status_code == 403


def test_audit_proves_byte_identity_but_never_auto_approves_academics(client, monkeypatch):
    ref, sources = approved_comparison(client)
    monkeypatch.setattr(research_ai, "_ask_local",
                        lambda *args: pytest.fail("V7 audit cannot invoke a model"))
    before = {s["path"]: sha((sandbox.default_root() / s["path"]).read_bytes())
              for s in sources}
    audit = client.post(BASE + "/audit", headers=H, json=ref)
    assert audit.status_code == 200, audit.text
    info = audit.json()
    assert info["integrity"] == "verified_against_selected_sha256"
    assert info["checked_source_count"] == 2
    assert len(info["checked_artifacts"]) == 4
    assert all(i["status"] == "not_certified_by_software" for i in info["manual_acceptance"])
    assert not info["science_verified"] and not info["publication_ready"] and not info["store_release_approved"]
    assert info["no_model_invocation"] and info["no_network_request"]
    assert {s["path"]: sha((sandbox.default_root() / s["path"]).read_bytes()) for s in sources} == before
    assert client.get(BASE + "/list", headers=H).json()["snapshots"] == []


def test_recovery_snapshot_verified_stage_preserves_originals(client):
    ref, sources = approved_comparison(client)
    root = sandbox.default_root()
    original = {s["path"]: (root / s["path"]).read_bytes() for s in sources}
    assert client.post(BASE + "/snapshot", headers=H, json=ref).status_code == 422
    creation = client.post(BASE + "/snapshot", headers=H, json=copy_body(ref))
    assert creation.status_code == 200, creation.text
    record = creation.json()
    assert record["file_count"] == 4 and record["create_only"]
    assert (root / record["archive_path"]).is_file()
    selected = {"path": record["path"], "sha256": record["sha256"]}
    found = client.get(BASE + "/list", headers=H)
    assert any(item["path"] == record["path"] for item in found.json()["snapshots"])
    verify = client.post(BASE + "/verify", headers=H, json=selected)
    assert verify.status_code == 200, verify.text
    assert verify.json()["valid_against_recorded_hashes"]
    assert not verify.json()["restored"]
    assert client.post(BASE + "/stage", headers=H, json=selected).status_code == 422
    staged = client.post(BASE + "/stage", headers=H, json={
        **selected, "acknowledgement": "STAGE FILES WITHOUT OVERWRITING",
        "confirm_no_original_changes": True,
    })
    assert staged.status_code == 200, staged.text
    stage_folder = root / staged.json()["staging_path"]
    assert stage_folder.is_dir()
    assert len(list((stage_folder / "files").glob("*"))) == 4
    manifest = json.loads((stage_folder / "staged-manifest.json").read_text())
    assert manifest["restored_into_trusted_locations"] is False
    for entry in manifest["files"]:
        recovered = (stage_folder / entry["member"]).read_bytes()
        assert sha(recovered) == entry["sha256"]
    assert all((root / path).read_bytes() == contents for path, contents in original.items())
    assert staged.json()["original_files_modified"] is False


def test_zip_corruption_is_detected_and_staging_fails_closed(client):
    ref, _ = approved_comparison(client)
    snapshot = client.post(BASE + "/snapshot", headers=H, json=copy_body(ref)).json()
    root = sandbox.default_root()
    path = root / snapshot["archive_path"]
    path.write_bytes(path.read_bytes() + b"tampered archive")
    result = client.post(BASE + "/verify", headers=H, json={
        "path": snapshot["path"], "sha256": snapshot["sha256"]})
    assert result.status_code == 409, result.text
    rejected = client.post(BASE + "/stage", headers=H, json={
        "path": snapshot["path"], "sha256": snapshot["sha256"],
        "acknowledgement": "STAGE FILES WITHOUT OVERWRITING",
        "confirm_no_original_changes": True})
    assert rejected.status_code == 409
    assert not list((root / "artifacts/research/recovery/staging").glob("stage-*")) if (
        root / "artifacts/research/recovery/staging").exists() else True


def test_archive_member_injection_is_detected_even_if_hashes_rewritten(client):
    ref, _ = approved_comparison(client)
    saved = client.post(BASE + "/snapshot", headers=H, json=copy_body(ref)).json()
    root = sandbox.default_root()
    zip_path = root / saved["archive_path"]
    record_path = root / saved["path"]
    record = json.loads(record_path.read_text())
    with zipfile.ZipFile(io.BytesIO(zip_path.read_bytes())) as existing:
        originals = [(info.filename, existing.read(info)) for info in existing.infolist()]
    evil = io.BytesIO()
    with zipfile.ZipFile(evil, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in originals:
            archive.writestr(name, data)
        archive.writestr("../escape.txt", b"should never be staged")
    zip_path.write_bytes(evil.getvalue())
    record["archive_sha256"] = sha(evil.getvalue())
    record_path.write_text(json.dumps(record))
    attempt = client.post(BASE + "/verify", headers=H, json={
        "path": saved["path"], "sha256": sha(record_path.read_bytes())})
    assert attempt.status_code == 422, attempt.text
    assert not (root / "escape.txt").exists()


def test_changed_source_limits_and_bad_selection_refused(client, monkeypatch):
    ref, sources = approved_comparison(client)
    bad = {**ref, "review_path": "artifacts/research/ai/reviews/review-" + "f" * 24 + ".ai-review.json"}
    assert client.post(BASE + "/audit", headers=H, json=bad).status_code == 422
    monkeypatch.setattr(research_acceptance, "MAX_TOTAL_BYTES", 100)
    assert client.post(BASE + "/audit", headers=H, json=ref).status_code == 413
    monkeypatch.setattr(research_acceptance, "MAX_TOTAL_BYTES", 40 * 1024 * 1024)
    file = sandbox.default_root() / sources[0]["path"]
    file.write_text(file.read_text() + "changed after human review")
    response = client.post(BASE + "/audit", headers=H, json=ref)
    assert response.status_code in (409, 422), response.text
    assert client.post(BASE + "/snapshot", headers=H, json=copy_body(ref)).status_code in (409, 422)


def test_v6_handoff_audit_must_match_reviewed_evidence_and_output(client):
    ref, _ = approved_comparison(client)
    created = client.post("/api/research/studio/handoff/save", headers=H, json={
        **ref, "target": "developer",
        "acknowledgement": "CREATE REVIEW-ONLY HANDOFF",
        "confirm_sources_checked": True, "confirm_no_publication": True})
    assert created.status_code == 200, created.text
    result = created.json()
    selection = {**ref, "handoff_path": result["path"], "handoff_sha256": result["sha256"]}
    audit = client.post(BASE + "/audit", headers=H, json=selection)
    assert audit.status_code == 200, audit.text
    assert len(audit.json()["checked_artifacts"]) == 6
    output = sandbox.default_root() / result["target_path"]
    output.write_text(output.read_text() + "modified after transfer", encoding="utf-8")
    refused = client.post(BASE + "/snapshot", headers=H, json=copy_body(selection))
    assert refused.status_code == 409, refused.text


def test_recovery_path_guards_and_workspace_separation(client, tmp_path, monkeypatch):
    ref, _ = approved_comparison(client)
    snapshot = client.post(BASE + "/snapshot", headers=H, json=copy_body(ref)).json()
    for path in ("../escape", "artifacts/research/recovery/snapshots/../out",
                 "/tmp/backup.json", "artifacts/research/comparisons/comparison-" + "a"*24 + ".comparison.json"):
        rejected = client.post(BASE + "/verify", headers=H, json={
            "path": path, "sha256": snapshot["sha256"]})
        assert rejected.status_code in (403, 422), rejected.text
    root = sandbox.default_root()
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "other-workspace"))
    assert client.get(BASE + "/list", headers=H).json()["snapshots"] == []
    assert client.post(BASE + "/verify", headers=H, json={
        "path": snapshot["path"], "sha256": snapshot["sha256"]}).status_code == 404
    assert (root / snapshot["archive_path"]).is_file()
