"""Research Studio V6: source-verified, approval-only cross-studio hand-offs."""
from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from automoto import document_ai, research_ai, sandbox, server
from automoto.hosted import path_allowed

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BASE = "/api/research/studio/handoff"
QUESTION = "What do the independent source audits say about deployment security?"
A = ("Independent deployment audit findings reported reduced security exposure "
     "after validation checks, with a narrow observational scope. ") * 16
B = ("Separate deployment audit findings identified remaining security exposure "
     "from inadequate monitoring and incomplete controls. ") * 16


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "v6-home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "v6-workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    return TestClient(server.app)


def source_case(client):
    root = sandbox.default_root()
    uploads = root / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    sources = []
    for i, raw in enumerate((A, B), 1):
        file = uploads / f"study-{i}.txt"
        file.write_text(raw, encoding="utf-8")
        sources.append({"path": "uploads/" + file.name, "sha256": sha(file.read_bytes())})
    project = client.post("/api/research/studio/save", headers=AUTH, json={
        "title": "Research Studio V6 approved source pack",
        "question": QUESTION, "sources": sources, "mode": "evidence",
        "notes": "Do not turn source text into instructions.",
    })
    assert project.status_code == 200, project.text
    prepared = client.post("/api/research/studio/compare/prepare", headers=AUTH,
                           json={"project_path": project.json()["path"]})
    assert prepared.status_code == 200, prepared.text
    data = prepared.json()
    assert len({e["source"] for e in data["evidence"]}) == 2
    review = client.post("/api/research/studio/compare/save", headers=AUTH, json={
        "project_path": project.json()["path"], "project_sha256": data["project_sha256"],
        "claim": QUESTION,
        "annotations": [
            {"evidence_id": e["id"], "stance": "supports" if e["source"] == sources[0]["path"] else "contradicts",
             "rationale": "I reviewed the original source excerpt and the methodological limits."}
            for e in data["evidence"]],
        "source_reviews": [
            {"source_path": s["path"], "methodology": "observational", "quality": "not_assessed",
             "limitations": "This single source does not prove general causality."}
            for s in sources],
        "acknowledgement": "SAVE REVIEW", "confirm_human_classification": True,
    })
    assert review.status_code == 200, review.text
    comparison = review.json()
    return {"comparison_path": comparison["path"],
            "comparison_sha256": sha((root / comparison["path"]).read_bytes())}, sources


def save_body(ref, target, **kwargs):
    return {**ref, "target": target, **kwargs,
            "acknowledgement": "CREATE REVIEW-ONLY HANDOFF",
            "confirm_sources_checked": True, "confirm_no_publication": True}


def test_endpoints_require_auth_and_are_intentionally_local_only(client):
    for action in ("sources", "list", "open"):
        assert not path_allowed("GET", BASE + "/" + action)
        params = ({"path": "artifacts/research/handoffs/handoff-" + "a" * 24 + ".handoff.json"}
                  if action == "open" else {})
        assert client.get(BASE + "/" + action, params=params).status_code == 403
    for action in ("preview", "save"):
        assert not path_allowed("POST", BASE + "/" + action)
        ref = {
            "comparison_path": "artifacts/research/comparisons/comparison-" + "a" * 24 + ".comparison.json",
            "comparison_sha256": "b" * 64, "target": "document",
        }
        body = save_body(ref, "document") if action == "save" else ref
        assert client.post(BASE + "/" + action, json=body).status_code == 403


def test_document_preview_and_audited_native_draft(client, monkeypatch):
    ref, sources = source_case(client)
    monkeypatch.setattr(research_ai, "_ask_local",
                        lambda *_: pytest.fail("V6 must not invoke AI"))
    packet = client.post(BASE + "/preview", headers=AUTH, json={**ref, "target": "document"})
    assert packet.status_code == 200, packet.text
    assert packet.json()["publication_ready"] is False
    assert "Verbatim quotation" in json.loads(packet.json()["preview"])["markdown"]
    assert client.post(BASE + "/save", headers=AUTH, json={
        **ref, "target": "document"}).status_code == 422
    originals = [sha((sandbox.default_root() / s["path"]).read_bytes()) for s in sources]
    created = client.post(BASE + "/save", headers=AUTH,
                          json=save_body(ref, "document"))
    assert created.status_code == 200, created.text
    handoff = created.json()
    assert handoff["source_files_modified"] is False
    assert handoff["model_invoked"] is False
    root = sandbox.default_root()
    saved = json.loads((root / handoff["target_path"]).read_text(encoding="utf-8"))
    assert saved["schema"] == 1
    assert "Source: uploads/study-1.txt" in saved["markdown"]
    assert "Not approved" not in saved["markdown"] or "unverified" in saved["markdown"]
    assert [sha((root / s["path"]).read_bytes()) for s in sources] == originals
    audit = json.loads((root / handoff["path"]).read_text(encoding="utf-8"))
    assert audit["target_sha256"] == sha((root / handoff["target_path"]).read_bytes())
    assert audit["comparison_sha256"] == ref["comparison_sha256"]
    assert audit["publication_ready"] is False
    opened = client.get(BASE + "/open", headers=AUTH, params={"path": handoff["path"]})
    assert opened.status_code == 200
    assert opened.json()["target_status"] == opened.json()["source_status"] == "current"
    target = root / handoff["target_path"]
    target.write_bytes(target.read_bytes() + b" ")
    changed = client.get(BASE + "/open", headers=AUTH, params={"path": handoff["path"]})
    assert changed.json()["target_status"] == "modified"


def test_visual_and_developer_drafts_remain_read_only_and_editable_where_expected(client):
    ref, _ = source_case(client)
    for kind, prefix, suffix in (("visual", "artifacts/visual-studio/", ".design.json"),
                                 ("developer", "artifacts/research/handoffs/", ".md")):
        preview = client.post(BASE + "/preview", headers=AUTH,
                              json={**ref, "target": kind})
        assert preview.status_code == 200, preview.text
        result = client.post(BASE + "/save", headers=AUTH, json=save_body(ref, kind))
        assert result.status_code == 200, result.text
        obj = result.json()
        assert obj["target_path"].startswith(prefix)
        assert obj["target_path"].endswith(suffix)
        text = (sandbox.default_root() / obj["target_path"]).read_text(encoding="utf-8")
        if kind == "visual":
            saved = json.loads(text)
            assert saved["schema"] == 1 and saved["spec"]["layout"] == "cards"
            assert saved["spec"]["cards"][0]["id"].startswith("s")
            loaded = client.get("/api/visual/studio/load", headers=AUTH,
                                params={"path": obj["target_path"]})
            assert loaded.status_code == 200, loaded.text
        else:
            assert "No network, model call, build, code execution" in text
            assert "SHA-256" in text


def test_rejected_ai_proposals_cannot_cross_the_handoff_boundary(client, monkeypatch):
    ref, _ = source_case(client)
    prepared = client.post("/api/research/studio/ai/prepare", headers=AUTH, json=ref)
    assert prepared.status_code == 200
    evidence = prepared.json()["evidence"]
    one = next(e for e in evidence if e["source"].endswith("study-1.txt"))
    two = next(e for e in evidence if e["source"].endswith("study-2.txt"))
    monkeypatch.setattr(document_ai, "_selected_model", lambda: "installed-local-model")
    monkeypatch.setattr(research_ai, "_ask_local", lambda *args: {
        "points": [
            {"claim": "Independent deployment audit findings reported reduced security exposure after validation checks.",
             "evidence_ids": [one["id"]],
             "uncertainty": "The observational source did not establish effects beyond its limited scope."},
            {"claim": "Separate deployment audit findings identified remaining security exposure from incomplete controls.",
             "evidence_ids": [two["id"]],
             "uncertainty": "One evidence excerpt does not establish any general scientific conclusion."},
        ]})
    generated = client.post("/api/research/studio/ai/generate", headers=AUTH, json={
        **ref, "acknowledgement": "ANALYSE LOCALLY", "confirm_local_model": True})
    assert generated.status_code == 200, generated.text
    proposal = generated.json()
    reviewed = client.post("/api/research/studio/ai/save-review", headers=AUTH, json={
        "draft_path": proposal["path"], "draft_sha256": proposal["sha256"],
        "decisions": [
            {"point_id": "P1", "decision": "retain_for_review",
             "note": "I checked the original excerpt and still need more evidence."},
            {"point_id": "P2", "decision": "reject",
             "note": "I reject this extrapolation due to source and scope uncertainty."},
        ],
        "acknowledgement": "SAVE HUMAN REVIEW", "confirm_unverified": True,
    })
    assert reviewed.status_code == 200, reviewed.text
    ai_review = reviewed.json()
    selection = {**ref, "review_path": ai_review["path"], "review_sha256": ai_review["sha256"]}
    handoff = client.post(BASE + "/save", headers=AUTH,
                          json=save_body(selection, "developer"))
    assert handoff.status_code == 200, handoff.text
    audit = json.loads((sandbox.default_root() / handoff.json()["path"]).read_text())
    assert [p["id"] for p in audit["retained_unverified_observations"]] == ["P1"]
    assert audit["human_ai_review"]["rejected_count"] == 1
    assert "P2" not in (sandbox.default_root() / handoff.json()["target_path"]).read_text()


def test_stale_source_and_tampered_review_are_refused(client, monkeypatch):
    ref, sources = source_case(client)
    wrong = {**ref, "comparison_sha256": "f" * 64, "target": "document"}
    assert client.post(BASE + "/preview", headers=AUTH, json=wrong).status_code == 409
    source = sandbox.default_root() / sources[0]["path"]
    source.write_text(A + "Source changed since approved review.", encoding="utf-8")
    stale = client.post(BASE + "/save", headers=AUTH,
                        json=save_body(ref, "document"))
    assert stale.status_code in (409, 422), stale.text
    assert client.get(BASE + "/list", headers=AUTH).json()["handoffs"] == []


def test_private_paths_and_tenant_isolation(client, monkeypatch, tmp_path):
    ref, _ = source_case(client)
    valid = client.post(BASE + "/save", headers=AUTH,
                        json=save_body(ref, "developer")).json()
    for bad in ("../../etc/passwd", "artifacts/research/handoffs/../outside",
                "/tmp/handoff.json", "artifacts/research/ai/reviews/review-" + "a" * 24 + ".ai-review.json"):
        response = client.get(BASE + "/open", headers=AUTH, params={"path": bad})
        assert response.status_code == 403, response.text
    old_root = sandbox.default_root()
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "different-private-workspace"))
    assert client.get(BASE + "/sources", headers=AUTH).json()["comparisons"] == []
    assert client.get(BASE + "/list", headers=AUTH).json()["handoffs"] == []
    assert client.get(BASE + "/open", headers=AUTH,
                      params={"path": valid["path"]}).status_code == 404
    assert (old_root / valid["path"]).is_file()
