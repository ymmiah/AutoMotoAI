"""Research Studio V4: actual DOI-backed reports and fail-closed publication gates."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import urllib.request
import zipfile

import pytest
from docx import Document
from fastapi.testclient import TestClient

from automoto import (
    document_workspace, office, research_discovery, sandbox, server,
)
from automoto.hosted import path_allowed

BASE = "/api/research/studio/publish"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
QUESTION = "What did the audited release study say about deployment risk?"
A = ("The audited release study reported lower deployment risk after signed "
     "build checks. This was a limited case study and no external causal "
     "conclusions were established. ") * 15
B = ("The audited release study reported unresolved deployment risk after "
     "monitoring gaps. Observed outcomes were limited and the controls "
     "could not generalise to all deployments. ") * 15


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "publishing-home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "research-workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    return TestClient(server.app)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _post(client, suffix, value):
    return client.post(BASE + suffix, headers=AUTH, json=value)


def _source_files():
    base = sandbox.default_root() / "uploads"
    base.mkdir(parents=True, exist_ok=True)
    result = []
    for index, body in enumerate((A, B), start=1):
        file = base / f"study-{index}.txt"
        file.write_text(body, encoding="utf-8")
        result.append({"path": "uploads/" + file.name, "sha256": _sha(file)})
    return result


def _metadata(title, doi, author, year):
    return {
        "doi": doi, "title": title, "authors": [author], "venue": "Journal of Real-Source Checks",
        "publication_date": year, "type": "journal-article",
        "registry": "Crossref",
        "doi_url": "https://doi.org/" + doi,
        "registry_url": "https://api.crossref.org/works/" + doi,
        "retrieved_at": "2026-11-08T12:00:00+00:00",
        "metadata_only": True,
        "provenance": "Previously verified member-deposited Crossref metadata.",
    }


def _meta_file(meta):
    folder = research_discovery._folder("sources", create=True)
    target = folder / f"source-{secrets.token_hex(12)}.source.json"
    raw = json.dumps({"schema": "research-source-v2", "metadata": meta,
                      "saved_at": "2026-11-08T12:00:00+00:00"}).encode()
    document_workspace._atomic_file(target, raw)
    return {"path": target.relative_to(sandbox.default_root()).as_posix(),
            "sha256": _sha(target)}


def _fixture(client, *, reviewed=True):
    sources = _source_files()
    project = client.post("/api/research/studio/save", headers=AUTH, json={
        "title": "V4 source research", "question": QUESTION, "sources": sources,
        "mode": "evidence", "notes": "Two explicit source comparisons.",
    })
    assert project.status_code == 200, project.text
    project_path = project.json()["path"]
    prepared = client.post("/api/research/studio/compare/prepare", headers=AUTH,
                           json={"project_path": project_path})
    assert prepared.status_code == 200, prepared.text
    details = prepared.json()
    assert len({e["source"] for e in details["evidence"]}) == 2
    annotations = [
        {"evidence_id": e["id"], "stance": (
            "supports" if e["source"] == sources[0]["path"] else "contradicts"
        ) if reviewed else "unreviewed",
         "rationale": (
            "Source text explicitly supports the limited reviewer judgement." if
            e["source"] == sources[0]["path"] else
            "Source text raises questions about the reviewed claim."
         ) if reviewed else ""}
        for e in details["evidence"]
    ]
    review = client.post("/api/research/studio/compare/save", headers=AUTH, json={
        "project_path": project_path, "project_sha256": details["project_sha256"],
        "claim": "The audited release process decreased deployment risk in this case study.",
        "annotations": annotations,
        "source_reviews": [
            {"source_path": s["path"], "methodology": "observational",
             "quality": "not_assessed",
             "limitations": "Small sample; conclusions not generalisable."}
            for s in sources
        ],
        "acknowledgement": "SAVE REVIEW", "confirm_human_classification": True,
    })
    assert review.status_code == 200, review.text
    comparison_path = review.json()["path"]
    first = _meta_file(_metadata(
        "Evaluating Signed Release Checks", "10.5555/release-checks.2025",
        "M. Patel", "2025-09"))
    second = _meta_file(_metadata(
        "Investigating Build Monitoring Gaps", "10.5555/monitoring-gaps.2026",
        "M. Akhtar", "2026"))
    records = [first, second]
    bindings = [
        {
            "source_path": s["path"], "source_sha256": s["sha256"],
            "metadata_path": m["path"], "metadata_sha256": m["sha256"],
            "confirm_same_publication": True,
        } for s, m in zip(sources, records)
    ]
    body = {
        "comparison_path": comparison_path,
        "comparison_sha256": _sha(sandbox.default_root() / comparison_path),
        "title": "Evidence-led review of release automation",
        "author": "A. Student",
        "institution": "Computing Department",
        "introduction": "This report compares source-linked evidence on deployment risk.",
        "interpretation": "The observations suggest different outcomes in the two selected studies.",
        "limitations": "The selected studies have small samples and the source-to-paper association requires human verification.",
        "conclusion": "These reported findings warrant further investigation before stronger claims are made.",
        "style": "harvard", "bindings": bindings,
    }
    return body, sources, project_path, records


def test_private_authenticated_route_allowlist(client):
    for action in ("prepare", "preflight", "save-draft", "export"):
        assert path_allowed("POST", BASE + "/" + action)
        assert _post_anon(client, action).status_code in (403, 422)
    for action in ("publish-online", "delete", "email", "auto-cite", "accept-ai", "upload"):
        assert not path_allowed("POST", BASE + "/" + action)


def _post_anon(client, action):
    return client.post(BASE + "/" + action, json={})


def test_prepare_exposes_pinned_source_and_saved_doi_identity_without_network(client, monkeypatch):
    body, sources, _, _ = _fixture(client)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw:
                        pytest.fail("V4 must not request external sources"))
    from automoto import netguard
    monkeypatch.setattr(netguard, "request", lambda *a, **kw:
                        pytest.fail("V4 must not query external scholarly registries"))
    before = {p.relative_to(sandbox.default_root()).as_posix(): _sha(p)
              for p in sandbox.default_root().rglob("*") if p.is_file()}
    response = _post(client, "/prepare", {"comparison_path": body["comparison_path"]})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["comparison_sha256"] == body["comparison_sha256"]
    assert data["claim"].startswith("The audited release process")
    assert data["review_complete"]
    assert data["no_network_requests"]
    assert len(data["metadata_records"]) == 2
    assert len(data["sources"]) == 2
    assert all(src["path"] in [s["path"] for s in sources] for src in data["sources"])
    assert all(s["status"] == "current" for s in data["source_status"])
    after = {p.relative_to(sandbox.default_root()).as_posix(): _sha(p)
             for p in sandbox.default_root().rglob("*") if p.is_file()}
    assert before == after


@pytest.mark.parametrize("style", ["harvard", "ieee"])
def test_real_word_preflight_uses_only_saved_metadata_and_valid_citations(client, style):
    body, sources, _, _ = _fixture(client)
    body["style"] = style
    response = _post(client, "/preflight", body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ready"]
    assert data["word_build_valid"]
    assert data["word_bytes"] > 1500
    assert data["reference_count"] == 2
    assert data["citation_style"] == style
    assert len(data["formatted_references"]) == 2
    assert not data["science_verified"]
    assert data["no_files_saved"]
    assert data["no_network_requests"]
    assert all("doi" in ref.lower() or "10.5555" in ref for ref in data["formatted_references"])
    assert all("[@r" not in ref for ref in data["formatted_references"])
    markdown = data["report_markdown"]
    assert "[@r1]" in markdown and "[@r2]" in markdown
    assert "10.5555/release-checks.2025" in markdown
    assert "10.5555/monitoring-gaps.2026" in markdown
    assert "SOURCE" not in markdown[:200]
    assert "Research comparison SHA-256" in markdown
    assert "Reviewer" in markdown or "reviewer" in markdown
    assert len(data["source_bindings"]) == 2
    if style == "ieee":
        assert data["formatted_references"][0].startswith("[1]")
        assert data["formatted_references"][1].startswith("[2]")
    else:
        assert any("Patel" in ref for ref in data["formatted_references"])
    assert all(source["sha256"] in markdown for source in sources)


def test_actual_docx_export_contains_real_references_and_original_files_remain(client):
    body, sources, project, records = _fixture(client)
    root = sandbox.default_root()
    initial = {s["path"]: _sha(root/s["path"]) for s in sources}
    project_sha = _sha(root/project)
    comparison_sha = _sha(root/body["comparison_path"])
    no_consent = _post(client, "/export", {**body, "format": "docx"})
    assert no_consent.status_code == 422
    req = {**body, "format": "docx",
           "acknowledgement": "EXPORT REVIEW", "confirm_checked_references": True}
    outcome = _post(client, "/export", req)
    assert outcome.status_code == 200, outcome.text
    result = outcome.json()
    assert result["format"] == "docx"
    assert result["reference_count"] == 2
    assert not result["source_files_modified"]
    assert result["manual_reference_check_required"] is True
    assert result["science_verified"] is False
    file = root / result["path"]
    assert file.is_file() and file.read_bytes()[:2] == b"PK"
    with zipfile.ZipFile(file) as archive:
        assert "word/document.xml" in archive.namelist()
    document = Document(file)
    paragraphs = "\n".join(p.text for p in document.paragraphs)
    assert "Evidence-led review of release automation" in paragraphs
    assert "Evaluating Signed Release Checks" in paragraphs
    assert "Investigating Build Monitoring Gaps" in paragraphs
    assert "10.5555/release-checks.2025" in paragraphs
    assert "Research comparison SHA-256" in paragraphs
    assert {s["path"]: _sha(root/s["path"]) for s in sources} == initial
    assert _sha(root/project) == project_sha
    assert _sha(root/body["comparison_path"]) == comparison_sha


def test_editable_report_saved_separately_for_document_assistant(client):
    body, sources, _, _ = _fixture(client)
    response = _post(client, "/save-draft", {
        **body, "acknowledgement": "SAVE DRAFT",
        "confirm_checked_references": True})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["create_only"] is True
    assert result["editable_in"] == "Document Assistant"
    assert result["reference_count"] == 2
    assert result["path"].endswith(".document.json")
    opened = client.get("/api/documents/open", headers=AUTH,
                        params={"path": result["path"]})
    assert opened.status_code == 200, opened.text
    doc = opened.json()
    assert doc["publication"]["reference_style"] == "harvard"
    assert len(doc["publication"]["references"]) == 2
    assert doc["options"]["page_size"] == "A4"
    assert "[@r1]" in doc["markdown"]
    assert not result["source_files_modified"]


def test_unreviewed_claims_are_flagged_and_block_formal_export(client):
    body, _, _, _ = _fixture(client, reviewed=False)
    result = _post(client, "/preflight", body)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["word_build_valid"]
    assert data["ready"] is False
    assert any("Unreviewed" in w for w in data["warnings"])
    assert _post(client, "/export", {
        **body, "format": "docx", "acknowledgement": "EXPORT REVIEW",
        "confirm_checked_references": True}).status_code == 422
    assert _post(client, "/save-draft", {
        **body, "acknowledgement": "SAVE DRAFT",
        "confirm_checked_references": True}).status_code == 422


def test_unknown_or_missing_doi_binding_is_not_a_formal_citation(client):
    body, sources, _, records = _fixture(client)
    missing = {**body, "bindings": body["bindings"][:-1]}
    assert _post(client, "/preflight", missing).status_code == 422
    duplicate = [dict(x) for x in body["bindings"]]
    duplicate[1]["metadata_path"] = duplicate[0]["metadata_path"]
    duplicate[1]["metadata_sha256"] = duplicate[0]["metadata_sha256"]
    assert _post(client, "/preflight", {**body, "bindings": duplicate}).status_code == 422
    mismatched = [dict(x) for x in body["bindings"]]
    mismatched[0]["source_sha256"] = "0"*64
    assert _post(client, "/preflight", {**body, "bindings": mismatched}).status_code == 409
    no_permission = [dict(x) for x in body["bindings"]]
    no_permission[0]["confirm_same_publication"] = False
    assert _post(client, "/preflight", {**body, "bindings": no_permission}).status_code == 422
    forbidden_path = [dict(x) for x in body["bindings"]]
    forbidden_path[0]["metadata_path"] = "../../secrets.json"
    assert _post(client, "/preflight", {**body, "bindings": forbidden_path}).status_code in (403, 422)


def test_tampered_or_incomplete_scholarly_metadata_refused(client):
    body, _, _, records = _fixture(client)
    target = sandbox.default_root() / records[0]["path"]
    original = json.loads(target.read_text())
    original["metadata"]["title"] = "Unverified new title"
    target.write_text(json.dumps(original))
    assert _post(client, "/preflight", body).status_code == 409
    bindings = [dict(x) for x in body["bindings"]]
    bindings[0]["metadata_sha256"] = _sha(target)
    assert _post(client, "/preflight", {**body, "bindings": bindings}).status_code == 200
    # A privileged local editor can replace metadata and digest; SHA is not
    # a digital signature. Even so, inconsistent identifiers and missing fields
    # fail the existing validation.
    original["metadata"]["publication_date"] = None
    target.write_text(json.dumps(original))
    bindings[0]["metadata_sha256"] = _sha(target)
    assert _post(client, "/preflight", {**body, "bindings": bindings}).status_code == 422
    original["metadata"]["publication_date"] = "2025"
    original["metadata"]["doi_url"] = "https://evil.example/not-the-article"
    target.write_text(json.dumps(original))
    bindings[0]["metadata_sha256"] = _sha(target)
    assert _post(client, "/preflight", {**body, "bindings": bindings}).status_code == 422
    original["metadata"]["doi_url"] = "https://doi.org/10.5555/release-checks.2025"
    original["metadata"]["registry"] = "Not Crossref"
    target.write_text(json.dumps(original))
    bindings[0]["metadata_sha256"] = _sha(target)
    assert _post(client, "/preflight", {**body, "bindings": bindings}).status_code == 422


def test_changed_comparison_and_source_file_rejected(client):
    body, sources, _, _ = _fixture(client)
    comparison = sandbox.default_root()/body["comparison_path"]
    saved = json.loads(comparison.read_text())
    saved["review"]["claim"] = "Changed reviewer claim after comparison selection."
    comparison.write_text(json.dumps(saved))
    assert _post(client, "/preflight", body).status_code == 409
    comparison.write_text(json.dumps(saved))
    updated = {**body, "comparison_sha256": _sha(comparison)}
    assert _post(client, "/preflight", updated).status_code == 422


def test_modified_source_refused_without_mutation(client):
    body, sources, _, _ = _fixture(client)
    source = sandbox.default_root()/sources[0]["path"]
    source.write_text(A + "Different text after comparison.", encoding="utf-8")
    response = _post(client, "/preflight", body)
    assert response.status_code == 409, response.text


def test_malformed_author_sections_and_citation_injection_refused(client):
    body, _, _, _ = _fixture(client)
    for field, invalid in (("introduction", "[@fake] misleading bibliography"),
                           ("conclusion", "Bad\u0000control"),
                           ("title", "<escape>[@r2]</escape>"),
                           ("author", " \t")):
        response = _post(client, "/preflight", {**body, field: invalid})
        assert response.status_code == 422, (field, response.text)
    assert _post(client, "/preflight", {**body, "style": "fabricated"}).status_code == 422
    assert _post(client, "/export", {**body, "format": "exe",
                                   "acknowledgement": "EXPORT REVIEW",
                                   "confirm_checked_references": True}).status_code == 422


def test_tenant_workspace_privacy(client, tmp_path, monkeypatch):
    body, _, _, _ = _fixture(client)
    original = sandbox.default_root() / body["comparison_path"]
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "other-tenants"))
    response = _post(client, "/prepare", {"comparison_path": body["comparison_path"]})
    assert response.status_code == 404
    assert original.is_file()


def test_pdf_has_explicit_local_libreoffice_dependency(client):
    body, _, _, _ = _fixture(client)
    if office.lo_available():
        pytest.skip("PDF conversion is exercised by the native Office CI and manual release acceptance.")
    result = _post(client, "/export", {
        **body, "format": "pdf", "acknowledgement": "EXPORT REVIEW",
        "confirm_checked_references": True})
    assert result.status_code == 501, result.text
