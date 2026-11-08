"""Research Studio V3 — real two-source comparisons, no synthetic evidence."""
from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from automoto import document_research, research_comparison, sandbox, server
from automoto.hosted import path_allowed

BASE = "/api/research/studio/compare"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
QUESTION = "What does the audited release process report about deployment security risk?"
SOURCE_A = ("The audited release process reported that deployment security risk was "
            "reduced through an independent evidence review, with a limited local "
            "test sample and no claims about other organisations. ") * 15
SOURCE_B = ("The audited release process reported that deployment security risk was "
            "not reduced because detection missed several relevant changes, with "
            "limited testing and uncertain generalisability. ") * 15


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "research-comparison-home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "private-review-workspace"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def documents(contents=(SOURCE_A, SOURCE_B)):
    root = sandbox.default_root()
    output = []
    for i, body in enumerate(contents, start=1):
        path = root / "uploads" / f"paper-{i}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        output.append({"path": f"uploads/paper-{i}.txt",
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return output


def saved_project(client, docs=None, question=QUESTION):
    docs = docs if docs is not None else documents()
    payload = {
        "title": "Source-audited comparison project",
        "question": question, "mode": "evidence",
        "notes": "Do not assume retrieval establishes causality.", "sources": docs,
    }
    resp = client.post("/api/research/studio/save", headers=AUTH, json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()["path"], docs


def prepared(client, path):
    response = client.post(BASE + "/prepare", headers=AUTH, json={"project_path": path})
    assert response.status_code == 200, response.text
    return response.json()


def body(data):
    return {
        "project_path": data["project_path"], "project_sha256": data["project_sha256"],
        "claim": "Independent review decreased deployment security risk.",
        "annotations": [
            {"evidence_id": e["id"], "stance": "unreviewed", "rationale": ""}
            for e in data["evidence"]
        ],
        "source_reviews": [
            {"source_path": s["path"], "methodology": "not_assessed",
             "quality": "not_assessed", "limitations": ""}
            for s in data["project"]["sources"]
        ],
    }


def add_judgements(data, draft):
    chosen = set()
    for e in data["evidence"]:
        if e["source"] not in chosen:
            chosen.add(e["source"])
            position = "supports" if len(chosen) == 1 else "contradicts"
            mark = next(a for a in draft["annotations"] if a["evidence_id"] == e["id"])
            mark["stance"] = position
            mark["rationale"] = ("This excerpt describes lower risk in this test." if
                                  position == "supports" else
                                  "This excerpt describes failure to reduce risk.")
    assert len(chosen) == 2, "Both source documents should have matching excerpts."
    draft["source_reviews"][0].update({
        "methodology": "observational", "quality": "moderate",
        "limitations": "No randomised control; results limited to tested releases.",
    })
    draft["source_reviews"][1].update({
        "methodology": "experimental", "quality": "low",
        "limitations": "Small sample and incomplete detection coverage.",
    })
    return draft


def test_authentication_hosted_allowlisting_and_no_destructive_routes(client):
    for action in ("list", "open"):
        assert path_allowed("GET", BASE + "/" + action)
        assert client.get(BASE + "/" + action).status_code == 403
    for action in ("prepare", "preview", "save"):
        assert path_allowed("POST", BASE + "/" + action)
    for action in ("ai", "auto-classify", "delete", "change-source", "publish", "score-true"):
        assert not path_allowed("POST", BASE + "/" + action)
    assert client.post(BASE + "/prepare", json={"project_path": "anything"}).status_code == 403


def test_prepare_verifies_exact_extracted_quotes_and_no_network_or_model_calls(client, monkeypatch):
    project, docs = saved_project(client)
    from automoto import netguard
    monkeypatch.setattr(netguard, "request", lambda *a, **kw:
                        pytest.fail("Comparisons must be offline"))
    monkeypatch.setattr(document_research, "_synthesise", lambda *a, **kw:
                        pytest.fail("Comparisons must not call a model"))
    root = sandbox.default_root()
    before = {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
              for p in root.rglob("*") if p.is_file()}
    data = prepared(client, project)
    assert data["source_count"] == 2 and data["evidence_count"] >= 2
    assert data["offline"] and data["no_model"] and not data["source_files_modified"]
    assert len({e["source"] for e in data["evidence"]}) == 2
    assert all(e["sha256"] in {s["sha256"] for s in docs} for e in data["evidence"])
    assert all(state["status"] == "current" for state in data["source_status"])
    for e in data["evidence"]:
        source = root / e["source"]
        content = source.read_text(encoding="utf-8")
        assert content[e["offset"]:e["offset"] + len(e["quote"])] == e["quote"]
    after = {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
             for p in root.rglob("*") if p.is_file()}
    assert before == after


def test_preview_marks_all_unreviewed_and_requires_human_rationale(client):
    project, _ = saved_project(client)
    data = prepared(client, project)
    original = body(data)
    response = client.post(BASE + "/preview", headers=AUTH, json=original)
    assert response.status_code == 200, response.text
    report = response.json()["report"]
    assert report["counts"]["unreviewed"] == data["evidence_count"]
    assert report["counts"]["supports"] == 0
    assert report["counts"]["contradicts"] == 0
    assert report["disagreement_flag"] is False
    assert report["human_labelled"] is True and report["science_verified"] is False
    assert report["automatic_contradiction_detection"] is False
    assert report["ready_for_publication"] is False
    assert report["all_assessed"] is False
    changed = body(data)
    changed["annotations"][0]["stance"] = "supports"
    assert client.post(BASE + "/preview", headers=AUTH, json=changed).status_code == 422
    changed["annotations"][0]["rationale"] = "A specific reviewer explanation."
    assert client.post(BASE + "/preview", headers=AUTH, json=changed).status_code == 200


def test_human_labelled_disagreement_and_source_quality_are_not_automatic(client):
    project, _ = saved_project(client)
    data = prepared(client, project)
    review = add_judgements(data, body(data))
    response = client.post(BASE + "/preview", headers=AUTH, json=review)
    assert response.status_code == 200, response.text
    report = response.json()["report"]
    assert report["disagreement_flag"] is True
    assert report["counts"]["supports"] == 1
    assert report["counts"]["contradicts"] == 1
    assert report["counts"]["unreviewed"] == data["evidence_count"] - 2
    assert {s["methodology"] for s in report["source_coverage"]} == {"observational", "experimental"}
    assert {s["quality"] for s in report["source_coverage"]} == {"low", "moderate"}
    assert not report["science_verified"] and not report["ready_for_publication"]
    assert report["source_count"] == 2 and report["evidence_count"] == data["evidence_count"]
    assert all("source" in row and "sha256" in row and "quote" in row for row in report["matrix"])


def test_save_is_create_only_requires_consent_and_preserves_all_sources(client):
    project, docs = saved_project(client)
    data = prepared(client, project)
    review = add_judgements(data, body(data))
    root = sandbox.default_root()
    originals = {s["path"]:hashlib.sha256((root / s["path"]).read_bytes()).hexdigest() for s in docs}
    original_project = hashlib.sha256((root / project).read_bytes()).hexdigest()
    assert client.post(BASE + "/save", headers=AUTH, json=review).status_code == 422
    rejected = client.post(BASE + "/save", headers=AUTH, json={
        **review, "acknowledgement": "SAVE REVIEW", "confirm_human_classification": False,
    })
    assert rejected.status_code == 422
    approved = {**review, "acknowledgement": "SAVE REVIEW", "confirm_human_classification": True}
    first = client.post(BASE + "/save", headers=AUTH, json=approved)
    assert first.status_code == 200, first.text
    record = first.json()
    assert record["create_only"] and record["saved"]
    assert not record["source_files_modified"] and not record["ready_for_publication"]
    assert record["disagreement_flag"]
    path = record["path"]
    assert path.startswith("artifacts/research/comparisons/")
    snap = root / path
    assert snap.exists()
    assert hashlib.sha256(snap.read_bytes()).hexdigest() == record["sha256"]
    opened = client.get(BASE + "/open", headers=AUTH, params={"path": path})
    assert opened.status_code == 200, opened.text
    report = opened.json()
    assert report["historical_snapshot"]
    assert report["project_status"] == "current"
    assert all(s["status"] == "current" for s in report["source_status"])
    assert report["report"]["disagreement_flag"] is True
    assert report["review"]["claim"] == review["claim"]
    assert "acknowledgement" not in report["review"]
    assert hashlib.sha256((root / project).read_bytes()).hexdigest() == original_project
    assert originals == {s["path"]:hashlib.sha256((root / s["path"]).read_bytes()).hexdigest()
                         for s in docs}
    second = client.post(BASE + "/save", headers=AUTH, json=approved)
    assert second.status_code == 200
    assert second.json()["path"] != path
    assert hashlib.sha256(snap.read_bytes()).hexdigest() == record["sha256"]
    listed = client.get(BASE + "/list", headers=AUTH).json()["comparisons"]
    assert {item["path"] for item in listed} == {path, second.json()["path"]}


def test_changed_source_refused_for_new_review_but_historical_review_is_openable(client):
    project, docs = saved_project(client)
    data = prepared(client, project)
    review = body(data)
    saved = client.post(BASE + "/save", headers=AUTH, json={
        **review, "acknowledgement": "SAVE REVIEW", "confirm_human_classification": True,
    })
    assert saved.status_code == 200, saved.text
    target = sandbox.default_root() / docs[0]["path"]
    target.write_text(SOURCE_A + "Changed after review.", encoding="utf-8")
    assert client.post(BASE + "/prepare", headers=AUTH,
                       json={"project_path": project}).status_code == 409
    assert client.post(BASE + "/preview", headers=AUTH, json=review).status_code == 409
    assert client.post(BASE + "/save", headers=AUTH, json={
        **review, "acknowledgement": "SAVE REVIEW", "confirm_human_classification": True,
    }).status_code == 409
    previous = client.get(BASE + "/open", headers=AUTH,
                          params={"path": saved.json()["path"]})
    assert previous.status_code == 200, previous.text
    assert previous.json()["source_status"][0]["status"] == "changed"
    assert previous.json()["historical_snapshot"]


@pytest.mark.parametrize("field,new_value", [
    ("quote", "Forged excerpt unsupported by the source material."),
    ("offset", 928382),
    ("source", "uploads/unrelated.txt"),
    ("sha256", "0"*64),
    ("page", 1),
    ("id", "S9-09"),
])
def test_forged_v1_evidence_is_rejected(client, field, new_value):
    project, _ = saved_project(client)
    saved = sandbox.default_root() / project
    raw = json.loads(saved.read_text(encoding="utf-8"))
    raw["result"]["evidence"][0][field] = new_value
    saved.write_text(json.dumps(raw), encoding="utf-8")
    response = client.post(BASE + "/prepare", headers=AUTH,
                           json={"project_path": project})
    assert response.status_code == 422, (field, response.text)


def test_project_hash_change_fails_comparison_preview_even_when_sources_unchanged(client):
    project, _ = saved_project(client)
    data = prepared(client, project)
    saved = sandbox.default_root() / project
    raw = json.loads(saved.read_text(encoding="utf-8"))
    raw["project"]["notes"] = "Edited project summary."
    saved.write_text(json.dumps(raw), encoding="utf-8")
    assert client.post(BASE + "/preview", headers=AUTH,
                       json=body(data)).status_code == 409


def test_reject_annotation_omission_duplicates_unknowns_and_quality_forgery(client):
    project, _ = saved_project(client)
    data = prepared(client, project)
    base = body(data)
    assert client.post(BASE + "/preview", headers=AUTH,
                       json={**base, "annotations": base["annotations"][:-1]}).status_code == 422
    assert client.post(BASE + "/preview", headers=AUTH,
                       json={**base, "annotations": base["annotations"]+[base["annotations"][0]]}).status_code == 422
    bogus = [dict(x) for x in base["annotations"]]
    bogus[0]["evidence_id"] = "S5-08"
    assert client.post(BASE + "/preview", headers=AUTH,
                       json={**base, "annotations": bogus}).status_code == 422
    bogus_quality = [dict(x) for x in base["source_reviews"]]
    bogus_quality[0]["source_path"] = "uploads/attacker.txt"
    assert client.post(BASE + "/preview", headers=AUTH,
                       json={**base, "source_reviews": bogus_quality}).status_code == 422
    invalid_method = [dict(x) for x in base["source_reviews"]]
    invalid_method[0]["methodology"] = "randomised_proven"
    assert client.post(BASE + "/preview", headers=AUTH,
                       json={**base, "source_reviews": invalid_method}).status_code == 422
    invalid_chars = [{**x, "stance": "supports", "rationale": "tampered\u0000 input"}
                     if i == 0 else x for i, x in enumerate(base["annotations"])]
    assert client.post(BASE + "/preview", headers=AUTH,
                       json={**base, "annotations": invalid_chars}).status_code == 422


def test_one_source_cannot_claim_cross_source_comparison(client):
    project, _ = saved_project(client, docs=documents()[:1])
    response = client.post(BASE + "/prepare", headers=AUTH,
                           json={"project_path": project})
    assert response.status_code == 422


def test_no_matching_passages_is_visible_not_a_negative_finding(client):
    project, _ = saved_project(client, question="What do astrophysical gamma bursts imply about quasar mass?")
    data = prepared(client, project)
    assert data["evidence_count"] == 0
    response = client.post(BASE + "/preview", headers=AUTH, json=body(data))
    assert response.status_code == 200, response.text
    report = response.json()["report"]
    assert report["matrix"] == []
    assert report["disagreement_flag"] is False
    assert report["all_assessed"] is False
    assert all(item["gap"] == "no_retrieved_excerpt" for item in report["source_coverage"])
    assert any("No passages" in warning for warning in report["warnings"])


@pytest.mark.parametrize("path", [
    "../../etc/passwd", "/tmp/comparison.json",
    "artifacts/research/../../etc/passwd", "artifacts/research/research-aaaa.research.json",
    "artifacts/research/comparisons/comparison-gggggggggggggggggggggggg.comparison.json",
])
def test_invalid_review_paths_refused(client, path):
    response = client.get(BASE + "/open", headers=AUTH, params={"path": path})
    assert response.status_code == 403


def test_saved_comparison_is_tenant_isolated(client, tmp_path, monkeypatch):
    project, _ = saved_project(client)
    data = prepared(client, project)
    record = client.post(BASE + "/save", headers=AUTH, json={
        **body(data), "acknowledgement": "SAVE REVIEW", "confirm_human_classification": True,
    })
    assert record.status_code == 200
    saved_path = record.json()["path"]
    original = sandbox.default_root() / saved_path
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "other-tenant-workspace"))
    assert client.get(BASE + "/list", headers=AUTH).json()["comparisons"] == []
    assert client.get(BASE + "/open", headers=AUTH,
                      params={"path": saved_path}).status_code == 404
    assert original.exists()


def test_corrupt_historical_review_is_rejected(client):
    project, _ = saved_project(client)
    data = prepared(client, project)
    saved = client.post(BASE + "/save", headers=AUTH, json={
        **body(data), "acknowledgement": "SAVE REVIEW", "confirm_human_classification": True,
    })
    assert saved.status_code == 200
    file = sandbox.default_root()/saved.json()["path"]
    stored = json.loads(file.read_text(encoding="utf-8"))
    stored["report"]["counts"]["supports"] = 90
    file.write_text(json.dumps(stored), encoding="utf-8")
    assert client.get(BASE + "/open", headers=AUTH,
                      params={"path": saved.json()["path"]}).status_code == 422
