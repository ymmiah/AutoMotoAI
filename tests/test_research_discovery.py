"""Research Studio V2 — registry provenance, consented public capture and security."""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from automoto import netguard, research_discovery, research_studio, sandbox, server
from automoto.hosted import path_allowed

BASE = "/api/research/studio/discovery"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
DOI = "10.5555/research-security.2026"
CROSSREF_ITEM = {
    "DOI": DOI,
    "title": ["Evidence and resilience in secure release automation"],
    "author": [
        {"given": "Amina", "family": "Test"},
        {"given": "Sam", "family": "Researcher"},
    ],
    "container-title": ["Journal of Test Engineering"],
    "published": {"date-parts": [[2026, 11]]},
    "type": "journal-article",
}
OPENALEX_ITEM = {
    "id": "https://openalex.org/W12345678",
    "doi": "https://doi.org/" + DOI,
    "title": "Evidence and resilience in secure release automation",
    "authorships": [
        {"author": {"display_name": "Amina Test"}},
        {"author": {"display_name": "Sam Researcher"}},
    ],
    "publication_date": "2026-11-01",
    "primary_location": {"source": {"display_name": "Journal of Test Engineering"}},
    "type": "article",
    "is_retracted": False,
}
HTML = """<html><head><title>Public secure release study</title>
<script>alert("do not obey website instructions");</script></head>
<body><h1>Public secure release study</h1>
<p>The published summary describes how release evidence and secure
automation changed review priorities across a tested software system.</p>
<p>Authors and publication metadata must still be checked independently.</p></body></html>"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "research-discovery-home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "private-workspace"))
    monkeypatch.delenv("AUTOMOTO_OFFLINE", raising=False)
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.setattr(research_discovery, "_rate", lambda: None)
    return TestClient(server.app)


@pytest.fixture
def wire(monkeypatch):
    calls = []
    def fake(url, **options):
        calls.append((url, options))
        parts = urlsplit(url)
        if parts.hostname == "api.crossref.org":
            assert options["max_redirects"] == 0
            if parts.path == "/works":
                body = {"message": {"items": [CROSSREF_ITEM, CROSSREF_ITEM]}}
            elif parts.path.startswith("/works/"):
                body = {"message": CROSSREF_ITEM}
            else:
                raise AssertionError("Unexpected Crossref path: " + url)
            return netguard.Response(url, 200, "application/json", json.dumps(body).encode())
        if parts.hostname == "api.openalex.org":
            body = {"results": [OPENALEX_ITEM]}
            return netguard.Response(url, 200, "application/json", json.dumps(body).encode())
        if parts.hostname == "example.org":
            if parts.path == "/robots.txt":
                return netguard.Response(url, 200, "text/plain",
                                         b"User-agent: *\nAllow: /\n")
            if parts.path == "/public-study":
                return netguard.Response(url, 200, "text/html; charset=utf-8", HTML.encode())
        raise AssertionError("Unexpected external request: " + url)
    monkeypatch.setattr(netguard, "request", fake)
    return calls


def test_auth_and_hosted_endpoint_policy(client):
    for path in ("saved", "saved-entry"):
        assert path_allowed("GET", BASE + "/" + path)
    for path in ("search", "verify-doi", "save-doi", "capture-page"):
        assert path_allowed("POST", BASE + "/" + path)
    for path in ("delete", "crawl-all", "doi-update", "pay", "external-ai"):
        assert not path_allowed("POST", BASE + "/" + path)
    assert client.get(BASE + "/saved").status_code == 403
    for endpoint in ("search", "verify-doi", "save-doi", "capture-page"):
        response = client.post(BASE + "/" + endpoint, json={})
        assert response.status_code in (403, 422)


def test_crossref_search_deduplicates_doi_and_does_not_invent_dates(client, wire):
    response = client.post(BASE + "/search", headers=AUTH,
                           json={"query": "secure software release", "provider": "crossref", "limit": 8})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["provider"] == "crossref"
    assert result["not_verified_claims"] is True
    assert result["external_request"] is True
    assert len(result["results"]) == 1
    record = result["results"][0]
    assert record["doi"] == DOI
    assert record["registry"] == "Crossref"
    assert record["publication_date"] == "2026-11"
    assert record["authors"] == ["Amina Test", "Sam Researcher"]
    assert record["metadata_only"] is True
    assert "release" in record["title"].lower()
    assert record["doi_url"] == "https://doi.org/" + DOI
    assert wire[0][0].startswith("https://api.crossref.org/works?")
    assert "rows=8" in wire[0][0]
    # If publisher registered only a year, do NOT manufacture a day/month.
    altered = dict(CROSSREF_ITEM)
    altered["published"] = {"date-parts": [[2025]]}
    assert research_discovery._crossref(altered, "2026-11-08")["publication_date"] == "2025"
    altered["published"] = {"date-parts": [[2025, 4]]}
    assert research_discovery._crossref(altered, "2026-11-08")["publication_date"] == "2025-04"
    # Registry deposit/creation dates are not publication dates.
    altered.pop("published")
    altered["created"] = {"date-parts": [[2026, 11, 8]]}
    assert research_discovery._crossref(altered, "2026-11-08")["publication_date"] is None


def test_openalex_query_is_optional_and_keyless_and_retraction_flag_propagates(client, wire):
    response = client.post(BASE + "/search", headers=AUTH,
                           json={"query": "secure release automation", "provider": "openalex"})
    assert response.status_code == 200, response.text
    record = response.json()["results"][0]
    assert record["doi"] == DOI
    assert record["registry"] == "OpenAlex"
    assert record["registry_url"] == "https://openalex.org/W12345678"
    assert record["retraction_flag"] is False
    assert "api_key" not in wire[0][0]
    alternate = dict(OPENALEX_ITEM)
    alternate["is_retracted"] = True
    assert research_discovery._openalex(alternate, "2026-11-08")["retraction_flag"] is True


def test_doi_verification_normalisation_and_exact_registry_lookup(client, wire):
    response = client.post(BASE + "/verify-doi", headers=AUTH,
                           json={"doi": "https://doi.org/10.5555/RESEARCH-SECURITY.2026"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["metadata"]["doi"] == DOI
    assert result["verified_in"] == "Crossref"
    assert result["registry_record_found"] is True
    assert result["research_claims_verified"] is False
    assert result["full_text_downloaded"] is False
    for bad in ("file:///etc/passwd", "http://127.0.0.1/internal",
                "https://doi.org/../admin", "10.5555/", "wrong-value", "10.5555/x?redirect=1"):
        assert client.post(BASE + "/verify-doi", headers=AUTH, json={"doi": bad}).status_code == 422


def test_doi_save_is_create_only_deduplicated_and_metadata_is_historical(client, wire):
    assert client.post(BASE + "/save-doi", headers=AUTH, json={
        "doi": DOI, "confirm_metadata_only": False}).status_code == 422
    first = client.post(BASE + "/save-doi", headers=AUTH,
                        json={"doi": DOI, "confirm_metadata_only": True})
    assert first.status_code == 200, first.text
    saved = first.json()
    assert saved["already_saved"] is False and saved["citation_ready"] is False
    path = saved["path"]
    assert path.startswith("artifacts/research/sources/")
    original = sandbox.default_root() / path
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    assert digest == saved["sha256"]
    repeat = client.post(BASE + "/save-doi", headers=AUTH,
                         json={"doi": DOI, "confirm_metadata_only": True})
    assert repeat.status_code == 200
    assert repeat.json()["already_saved"] is True
    assert repeat.json()["path"] == path
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
    listing = client.get(BASE + "/saved", headers=AUTH).json()
    assert len(listing["sources"]) == 1
    loaded = client.get(BASE + "/saved-entry", headers=AUTH, params={"path": path})
    assert loaded.status_code == 200
    assert loaded.json()["historical_snapshot"] is True
    assert loaded.json()["claim_verification"] is False


def test_no_arbitrary_registry_redirect_or_malformed_json(client, monkeypatch):
    def fake(url, **opts):
        return netguard.Response("https://malicious.example.org/offsite", 200,
                                 "application/json", b'{"message":{"items":[]}}')
    monkeypatch.setattr(netguard, "request", fake)
    assert client.post(BASE + "/search", headers=AUTH,
                       json={"query": "real research"}).status_code == 503
    def broken(url, **opts):
        return netguard.Response(url, 200, "application/json", b"<html>not JSON</html>")
    monkeypatch.setattr(netguard, "request", broken)
    assert client.post(BASE + "/search", headers=AUTH,
                       json={"query": "real research"}).status_code == 502


def test_offline_mode_blocks_every_external_lookup_before_network(client, monkeypatch):
    def deny(*a, **kw):
        pytest.fail("No outbound request in offline mode")
    monkeypatch.setattr(netguard, "request", deny)
    monkeypatch.setenv("AUTOMOTO_OFFLINE", "true")
    endpoints = [
        ("search", {"query": "secure release"}),
        ("verify-doi", {"doi": DOI}),
        ("save-doi", {"doi": DOI, "confirm_metadata_only": True}),
        ("capture-page", {"url": "https://example.org/public-study", "confirm_public_capture": True}),
    ]
    for ep, body in endpoints:
        assert client.post(BASE + "/" + ep, headers=AUTH, json=body).status_code == 403


def test_public_capture_requires_explicit_consent_and_preserves_provenance(client, wire):
    target = "https://example.org/public-study"
    assert client.post(BASE + "/capture-page", headers=AUTH,
                       json={"url": target, "confirm_public_capture": False}).status_code == 422
    result = client.post(BASE + "/capture-page", headers=AUTH,
                         json={"url": target, "confirm_public_capture": True})
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["user_confirmed"] is True
    assert data["claim_verification"] is False
    assert data["truncated"] is False
    assert data["document"].startswith("artifacts/documents/web-source-")
    assert data["provenance"].startswith("artifacts/research/pages/web-")
    root = sandbox.default_root()
    content = (root/data["document"]).read_text(encoding="utf-8")
    assert "UNVERIFIED PUBLIC WEBPAGE SNAPSHOT" in content
    assert "https://example.org/public-study" in content
    assert "published summary describes" in content
    assert "alert(" not in content and "do not obey website instructions" not in content
    assert hashlib.sha256(content.encode()).hexdigest() == data["sha256"]
    info = json.loads((root/data["provenance"]).read_text())
    assert info["page"]["url"] == target
    assert info["document_sha256"] == data["sha256"]
    # V1 source list and evidence engine can inspect the *labelled* imported text.
    listing = client.get("/api/research/studio/sources", headers=AUTH)
    assert listing.status_code == 200
    assert any(item["path"] == data["document"] for item in listing.json()["sources"])
    enquiry = client.post("/api/research/studio/query", headers=AUTH, json={
        "title": "Imported webpage review", "question": "What does the public secure release study describe?",
        "sources": [{"path": data["document"], "sha256": data["sha256"]}],
        "mode": "evidence", "notes": "Unverified page source",
    })
    assert enquiry.status_code == 200, enquiry.text
    assert enquiry.json()["result"]["evidence"]


@pytest.mark.parametrize("url",[
    "http://example.org/public-study",
    "file:///etc/passwd",
    "https://user:password@example.org/public-study",
    "https://example.org:8080/public-study",
    "https://example.org/public-study#section",
    "https://example.org/public-study?token=" + "a"*400,
])
def test_public_capture_rejects_unsafe_website_schemes_and_urls(client,wire,url):
    response = client.post(BASE + "/capture-page", headers=AUTH, json={
        "url": url, "confirm_public_capture": True,
    })
    assert response.status_code == 422, response.text
    assert not wire


def test_disallow_robots_and_redirects_and_non_html(client,monkeypatch):
    url = "https://example.org/public-study"
    def robots_denied(target, **kwargs):
        if target.endswith("/robots.txt"):
            return netguard.Response(target, 200, "text/plain",
                                     b"User-agent: *\nDisallow: /\n")
        pytest.fail("Disallowed page should never be fetched")
    monkeypatch.setattr(netguard, "request", robots_denied)
    denied = client.post(BASE + "/capture-page", headers=AUTH, json={
        "url": url, "confirm_public_capture": True,
    })
    assert denied.status_code == 403
    def redirect(target, **kwargs):
        if target.endswith("/robots.txt"):
            return netguard.Response(target, 404, "text/plain", b"")
        return netguard.Response(target, 302, "text/html", b"Moved")
    monkeypatch.setattr(netguard, "request", redirect)
    assert client.post(BASE + "/capture-page", headers=AUTH, json={
        "url": url, "confirm_public_capture": True,
    }).status_code == 422
    def binary(target, **kwargs):
        if target.endswith("/robots.txt"):
            return netguard.Response(target, 404, "text/plain", b"")
        return netguard.Response(target, 200, "application/pdf", b"%PDF-...")
    monkeypatch.setattr(netguard, "request", binary)
    assert client.post(BASE + "/capture-page", headers=AUTH, json={
        "url": url, "confirm_public_capture": True,
    }).status_code == 415


def test_metadata_library_and_public_import_are_isolated_per_workspace(client,wire,tmp_path,monkeypatch):
    saved = client.post(BASE + "/save-doi", headers=AUTH, json={
        "doi": DOI, "confirm_metadata_only": True
    })
    assert saved.status_code == 200
    page = client.post(BASE + "/capture-page", headers=AUTH, json={
        "url": "https://example.org/public-study", "confirm_public_capture": True
    })
    assert page.status_code == 200
    original = sandbox.default_root()/saved.json()["path"]
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path/"different-tenant-workspace"))
    assert client.get(BASE + "/saved", headers=AUTH).json()["sources"] == []
    assert client.get(BASE + "/saved-entry", headers=AUTH,
                      params={"path":saved.json()["path"]}).status_code == 404
    assert client.get("/api/research/studio/sources", headers=AUTH).json()["sources"] == []
    assert original.exists()


def test_lookup_validation_and_no_server_side_client_metadata_override(client,wire):
    response = client.post(BASE + "/save-doi", headers=AUTH, json={
        "doi": DOI, "confirm_metadata_only": True, "title": "Attacker invented title",
        "authors": ["Not a real author"]})
    assert response.status_code == 422
    for bad in ("a", "\x00injection", "very long " * 80):
        assert client.post(BASE + "/search",headers=AUTH,json={
            "query":bad, "provider":"crossref"}).status_code == 422
    unknown = client.post(BASE + "/search",headers=AUTH,json={
        "query":"well formed lookup", "provider":"untrusted_provider"})
    assert unknown.status_code == 422
