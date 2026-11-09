"""Developer Studio V10: honest local citations and opt-in DOI provenance."""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from automoto import developer_bibliography as bib
from automoto import sandbox, server
from automoto.hosted import path_allowed

BASE = "/api/developer/studio/bibliography"
H = {"X-AutoMoto-Token": server.SESSION_TOKEN}
CROSSREF_FIXTURE = {
    "DOI": "10.1234/real.2026",
    "title": ["A Safe Study"],
    "author": [{"family": "Smith", "given": "Anna"},
               {"family": "Jones", "given": "John"}],
    "published": {"date-parts": [[2026, 5, 10]]},
    "container-title": ["Journal of Verified Metadata"],
    "publisher": "An Example Publisher",
    "type": "journal-article",
    "volume": "7", "issue": "1", "page": "12-17",
}

@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "citation-study"
    root.mkdir(parents=True)
    (root / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "We cite \\cite{smith2026} and \\cite{roberts2025}.\n"
        "\\bibliography{references,extra}\n"
        "\\end{document}\n", encoding="utf-8")
    (root / "references.bib").write_text(
        "@article{smith2026,\n"
        " author = {Smith, Anna and Jones, John},\n"
        " title = {A Safe Study},\n"
        " year = {2026},\n"
        " journal = {Journal of Verified Metadata},\n"
        " doi = {10.1234/real.2026},\n"
        " volume = {7},\n number = {1},\n pages = {12-17}\n}\n",
        encoding="utf-8")
    (root / "extra.bib").write_text(
        '@book{roberts2025,\n'
        ' title = "Research {Practices} and Citations",\n'
        ' author = {Roberts, Susan},\n'
        ' year = 2025,\n'
        ' publisher = {Example Publisher}\n}\n', encoding="utf-8")
    with bib.EVIDENCE_LOCK:
        bib.EVIDENCE.clear()
    yield TestClient(server.app), root, tmp_path
    with bib.EVIDENCE_LOCK:
        bib.EVIDENCE.clear()


def req(client, path, root, **fields):
    return client.post(BASE + "/" + path, headers=H,
                       json={"project": str(root), "main": "main.tex", **fields})


def test_real_multifile_preflight_and_provenance_not_published(project):
    client, root, _ = project
    before = {x.name: x.read_bytes() for x in root.iterdir()}
    response = req(client, "preflight", root)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["entry_count"] == 2
    assert result["bib_files"] == ["extra.bib", "references.bib"]
    assert result["missing_citations"] == []
    assert result["duplicate_keys"] == []
    assert result["blocking_issues"] is False
    assert result["ready_for_publication"] is False
    assert result["crossref_lookup_automatic"] is False
    assert result["source_modified"] is False
    assert result["source_executed"] is False
    assert result["registry_data_not_proof_of_authenticity"] is True
    study = next(e for e in result["entries"] if e["key"] == "smith2026")
    assert study["doi_normalised"] == "10.1234/real.2026"
    assert study["metadata_verified"] is False
    assert study["preflight"] == "unverified"
    assert study["cited"] is True
    assert {x.name: x.read_bytes() for x in root.iterdir()} == before


def test_bibtex_nested_braces_quotes_comments_and_protected_macros():
    source = (
        "% @article{notreal, title={not cited}}\n"
        "@string{journalname={Synthetic}}\n"
        "@comment{ @article{hijack, title={fake}} }\n"
        "@article{nested2026,\n"
        " title = {A {Nested {Study}}},\n"
        ' author = "Miah, A and Baker, B",\n'
        " year = {2026},\n"
        " note = {Literal \\textbf{TeX}, never evaluated},\n"
        "}\n"
    )
    items, warnings = bib._parse_bib(source, "refs.bib")
    assert not warnings
    assert len(items) == 1
    assert items[0]["key"] == "nested2026"
    assert items[0]["fields"]["title"] == "A {Nested {Study}}"
    assert "\\textbf" in items[0]["fields"]["note"]


def test_biblatex_date_only_and_backend_biber_detection(project):
    client, root, _ = project
    (root / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\usepackage[backend=biber,style=authoryear]{biblatex}\n"
        "\\addbibresource{references.bib}\n"
        "\\begin{document}\\cite{dateonly2026}\\printbibliography\\end{document}\n",
        encoding="utf-8")
    (root / "references.bib").write_text(
        "@online{dateonly2026,\n"
        " title = {A Record With Only a Date},\n"
        " author = {Smith, Anna},\n"
        " date = {2026-11-09},\n"
        " url = {https://example.org}\n}\n", encoding="utf-8")
    result = req(client, "preflight", root).json()
    assert result["bibliography_system"]["system"] == "biblatex"
    assert result["bibliography_system"]["biber_requested"] is True
    assert result["bibliography_system"]["compiler_or_biber_executed"] is False
    assert result["entries"][0]["issues"] == []
    format_result = req(client, "format", root, key="dateonly2026", style="harvard")
    assert format_result.status_code == 200, format_result.text
    assert "(2026)" in format_result.json()["reference"]


def test_unresolved_duplicate_invalid_doi_and_placeholders_are_flagged(project):
    client, root, _ = project
    (root / "main.tex").write_text(
        "\\cite{missing,smith2026}\n\\bibliography{references,extra}\n", encoding="utf-8")
    (root / "extra.bib").write_text(
        "@article{smith2026,title={Replace with a verified publication},"
        "author={Unknown Author},year={2026},doi={invalid}}\n", encoding="utf-8")
    report = req(client, "preflight", root).json()
    assert report["blocking_issues"]
    assert report["missing_citations"] == ["missing"]
    assert report["duplicate_keys"] == ["smith2026"]
    assert any("duplicate citation key" in e["issues"] for e in report["entries"])
    assert any("placeholder citation metadata" in e["issues"] for e in report["entries"])
    assert any("malformed DOI" in e["issues"] for e in report["entries"])
    assert req(client, "format", root, key="smith2026", style="ieee").status_code == 409
    assert req(client, "verify-doi", root, key="smith2026").status_code == 409


def test_bibtex_malformed_entry_and_unsupported_concat_fail_closed():
    text = (
        "@article{broken, title={never closed}, author={A, B}\n"
        "@article{ignored, title={should be skipped}}\n"
    )
    entries, errors = bib._parse_bib(text, "broken.bib")
    assert not entries and errors
    assert errors[0]["code"] == "malformed-entry"
    items, errors = bib._parse_bib(
        "@article{x, title = {A} # {B}, author = {X, Y}, year = 2026}",
        "concat.bib")
    assert items == []
    assert errors[0]["code"] == "malformed-fields"


def test_no_automatic_crossref_call_even_for_doi_and_formatting(project, monkeypatch):
    client, root, _ = project
    def forbidden(_):
        raise AssertionError("No metadata lookup should occur without DOI approval")
    monkeypatch.setattr(bib, "_crossref_fetch", forbidden)
    assert req(client, "preflight", root).status_code == 200
    assert req(client, "format", root, key="smith2026", style="harvard").status_code == 200
    assert client.get(BASE + "/styles", headers=H).status_code == 200
    assert client.get(BASE + "/toolchains", headers=H,
                      params={"project": str(root)}).status_code == 200


def test_verified_crossref_evidence_and_independent_literal_formatting(project, monkeypatch):
    client, root, _ = project
    observed = []
    def fetch(doi):
        observed.append(doi)
        return CROSSREF_FIXTURE.copy()
    monkeypatch.setattr(bib, "_crossref_fetch", fetch)
    result = req(client, "verify-doi", root, key="smith2026")
    assert result.status_code == 200, result.text
    data = result.json()
    assert observed == ["10.1234/real.2026"]
    assert data["registry"]["title"] == "A Safe Study"
    assert data["registry"]["year"] == 2026
    assert data["registry"]["peer_review_verified"] is False
    assert data["publication_authenticity_verified"] is False
    assert data["field_comparison"] == {
        "title": True, "year": True, "first_author_family": True,
    }
    preflight = req(client, "preflight", root).json()
    entry = next(e for e in preflight["entries"] if e["key"] == "smith2026")
    assert entry["metadata_verified"] is True
    assert entry["preflight"] == "registry_checked"
    assert preflight["ready_for_publication"] is False
    harvard = req(client, "format", root, key="smith2026", style="harvard")
    ieee = req(client, "format", root, key="smith2026", style="ieee")
    assert harvard.status_code == 200, harvard.text
    assert ieee.status_code == 200, ieee.text
    assert "Smith, A." in harvard.json()["reference"]
    assert "https://doi.org/10.1234/real.2026" in harvard.json()["reference"]
    assert "[1] A. Smith" in ieee.json()["reference"]
    assert ieee.json()["formal_style_guide_verified"] is False
    assert ieee.json()["ready_for_publication"] is False


def test_registry_doi_mismatch_does_not_record_evidence(project, monkeypatch):
    client, root, _ = project
    monkeypatch.setattr(bib, "_crossref_fetch",
                        lambda doi: {**CROSSREF_FIXTURE, "DOI": "10.9999/not-the-request"})
    reply = req(client, "verify-doi", root, key="smith2026")
    assert reply.status_code == 502
    assert next(e for e in req(client, "preflight", root).json()["entries"]
                if e["key"] == "smith2026")["metadata_verified"] is False


def test_authoritative_metadata_mismatch_is_review_not_verified(project, monkeypatch):
    client, root, _ = project
    monkeypatch.setattr(bib, "_crossref_fetch",
                        lambda doi: {**CROSSREF_FIXTURE,
                                     "title": ["Different Paper"], "published": {"date-parts": [[2021]]}})
    response = req(client, "verify-doi", root, key="smith2026")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["field_comparison"]["title"] is False
    assert body["field_comparison"]["year"] is False
    assert "possible Crossref bibliographic metadata mismatch" in body["possible_mismatches"]
    assert req(client, "format", root, key="smith2026", style="ieee").status_code == 409


def test_invalid_doi_and_missing_doi_cannot_be_verified(project):
    client, root, _ = project
    assert req(client, "verify-doi", root, key="roberts2025").status_code == 422
    (root / "references.bib").write_text(
        "@article{smith2026, title={A Safe Study}, author={Smith, Anna},"
        "year={2026}, doi={http://127.0.0.1/internal}}\n", encoding="utf-8")
    assert req(client, "verify-doi", root, key="smith2026").status_code == 422
    assert bib._normalise_doi("https://doi.org/10.1234/real.2026") == "10.1234/real.2026"
    assert bib._normalise_doi("https://evil.example/10.1234/real.2026") is None


def test_untrusted_source_paths_and_symlinked_bibliography_are_not_read(project, tmp_path):
    client, root, base = project
    outside = base / "private.bib"
    outside.write_text("@article{private, title={Private}}\n", encoding="utf-8")
    link = root / "private.bib"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pass
    (root / "main.tex").write_text(
        "\\cite{private}\\bibliography{../private,private}\n", encoding="utf-8")
    r = req(client, "preflight", root)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["entries"] == []
    assert data["missing_citations"] == ["private"]
    assert data["source_modified"] is False


def test_unsubmitted_edits_are_read_only_and_revalidated(project):
    client, root, _ = project
    before = (root / "main.tex").read_bytes()
    alternative = "\\cite{unknown2026}\\bibliography{references}\n"
    result = req(client, "preflight", root, active_path="main.tex",
                 active_text=alternative)
    assert result.status_code == 200, result.text
    assert result.json()["missing_citations"] == ["unknown2026"]
    assert (root / "main.tex").read_bytes() == before
    assert not req(client, "preflight", root).json()["missing_citations"]


def test_hosted_routes_default_denied_and_auth_required(project):
    client, root, _ = project
    for endpoint in ("preflight", "verify-doi", "format"):
        assert path_allowed("POST", BASE + "/" + endpoint) is False
    for endpoint in ("styles", "toolchains"):
        assert path_allowed("GET", BASE + "/" + endpoint) is False
    assert client.post(BASE + "/preflight", json={"project": str(root),
                "main": "main.tex"}).status_code == 403
    assert req(client, "preflight", root, main="../outside.tex").status_code in (403, 422)


def test_crossref_metadata_is_bounded_and_does_not_certify_truth():
    assert bib._normalise_doi("10.1234/valid") == "10.1234/valid"
    with pytest.raises(HTTPException) as err:
        bib._metadata({**CROSSREF_FIXTURE, "DOI": "10.0000/wrong"},
                      "10.1234/real.2026")
    assert err.value.status_code == 502
    metadata = bib._metadata(CROSSREF_FIXTURE, "10.1234/real.2026")
    assert metadata["source"] == "Crossref registry metadata"
    assert metadata["publication_authenticity_verified"] is False
    assert metadata["peer_review_verified"] is False


def test_evidence_is_scoped_to_project_identity_and_does_not_persist(project, monkeypatch):
    client, root, _ = project
    monkeypatch.setattr(bib, "_crossref_fetch", lambda doi: CROSSREF_FIXTURE)
    assert req(client, "verify-doi", root, key="smith2026").status_code == 200
    evidence = bib._evidence_get(root, "10.1234/real.2026")
    assert evidence["title"] == "A Safe Study"
    with bib.EVIDENCE_LOCK:
        bib.EVIDENCE.clear()
    data = req(client, "preflight", root).json()
    assert next(e for e in data["entries"] if e["key"] == "smith2026")["metadata_verified"] is False


def test_formatting_refuses_incomplete_author_details_and_unverified_numbers(project):
    client, root, _ = project
    (root / "extra.bib").write_text(
        "@book{roberts2025, author={Anonymous}, title={Valid Title},"
        "publisher={Publisher},year={2025}}\n", encoding="utf-8")
    result = req(client, "format", root, key="roberts2025", style="harvard")
    assert result.status_code == 409
    assert req(client, "format", root, key="smith2026", style="ieee").json()["number"] == 2 or \
           req(client, "format", root, key="smith2026", style="ieee").json()["number"] == 1


def test_bounded_report_and_bib_parse_does_not_evaluate_tex_macros(project, monkeypatch):
    client, root, _ = project
    monkeypatch.setattr(bib, "MAX_ENTRIES", 1)
    data = req(client, "preflight", root).json()
    assert data["entry_count"] <= 1
    assert data["truncated"] is True
    assert data["source_executed"] is False
