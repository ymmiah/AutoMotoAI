"""Professional document publication with verified author-entered references."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient

from automoto import sandbox, server
from automoto.hosted import path_allowed
from automoto.document_publishing import PublicationOptions, compile_publication, TEMPLATES

AUTH={"X-AutoMoto-Token":server.SESSION_TOKEN}
BASE="/api/documents"

@pytest.fixture
def client(monkeypatch,tmp_path):
    monkeypatch.setenv("AUTOMOTO_HOME",str(tmp_path/"home"))
    monkeypatch.delenv("AUTOMOTO_MODE",raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT","10000")
    return TestClient(server.app)

def refs(style="harvard"):
    return {
        "reference_style":style,
        "author":"Original author",
        "institution":"Verified organisation",
        "document_date":"7 November 2026",
        "header":"Research report",
        "footer":"Confidential – for review",
        "cover_page":True,
        "contents_page":False,
        "template":"academic-report",
        "references":[
            {"id":"doe2025","authors":"Doe, J.","year":"2025",
             "title":"Source one","type":"journal","journal":"Journal of Examples",
             "volume":"2","issue":"1","pages":"12–24",
             "doi":"10.1234/abcd.2025"},
            {"id":"smith2023","authors":"Smith, A.","year":"2023",
             "title":"Source two","type":"book","publisher":"Example Press"},
        ]
    }

def source(style="harvard"):
    return {"name":"Academic case study",
            "markdown":"# Case study\n\n## Context\n\n"
                       "An author-supported statement [@doe2025]. "
                       "A separate fact [@smith2023].\n",
            "options":{"page_size":"A4","orientation":"portrait","margins_cm":2.5,
                       "font":"Calibri","font_size":11,"line_spacing":1.15,
                       "heading_color":"#1F3864","page_numbers":True},
            "publication":refs(style)}

def test_templates_are_user_scoped_and_do_not_contain_fabricated_sources(client):
    assert client.get(BASE+"/templates").status_code==403
    assert path_allowed("GET",BASE+"/templates")
    result=client.get(BASE+"/templates",headers=AUTH)
    assert result.status_code==200,result.text
    templates=result.json()["templates"]
    assert {item["id"] for item in templates}==set(TEMPLATES)
    for item in templates:
        assert item["source"].startswith("# ")
        assert "[" in item["source"],"editable placeholders must remain explicit"
        assert "[@" not in item["source"],"never fabricate citations"


def test_v4_harvard_real_word_export_has_user_sources_and_cover(client):
    report=client.post(BASE+"/export",headers=AUTH,json={**source(),"format":"docx"})
    assert report.status_code==200,report.text
    file=sandbox.default_root()/report.json()["path"]
    assert file.suffix==".docx" and file.is_file()
    doc=Document(file)
    text="\n".join(p.text for p in doc.paragraphs)
    assert "(Doe, 2025)" in text and "(Smith, 2023)" in text
    assert "Source one" in text and "Source two" in text
    assert "Journal of Examples" in text and "10.1234/abcd.2025" in text
    assert "[@" not in text
    assert "Original author" in text and "Verified organisation" in text
    assert "References" in text
    assert "Confidential" in doc.sections[0].footer.paragraphs[0].text
    assert "Research report" in doc.sections[0].header.paragraphs[0].text
    assert doc.core_properties.author=="Original author"


def test_v4_ieee_numbers_in_order_first_cited_and_reference_list(client):
    data=source("ieee")
    data["markdown"]="# Example\n\nFirst [@smith2023], later [@doe2025]."
    result=client.post(BASE+"/export",headers=AUTH,
                       json={**data,"format":"docx"})
    assert result.status_code==200,result.text
    doc=Document(sandbox.default_root()/result.json()["path"])
    text="\n".join(p.text for p in doc.paragraphs)
    assert "First [1], later [2]." in text
    assert '[1] Smith, A., "Source two,"' in text
    assert '[2] Doe, J., "Source one,"' in text
    assert text.index('[1] Smith')<text.index('[2] Doe')


def test_v4_saved_draft_v3_schema_persists_publication_and_legacy_remains(client):
    data=source()
    saved=client.post(BASE+"/save",headers=AUTH,json=data)
    assert saved.status_code==200,saved.text
    path=sandbox.default_root()/saved.json()["path"]
    obj=json.loads(path.read_text(encoding="utf-8"))
    assert obj["schema"]==3
    assert obj["publication"]["references"][0]["id"]=="doe2025"
    from automoto.document_workspace import _draft
    direct=_draft(path)
    assert direct["publication"]==obj["publication"], (
        "direct draft validation lost UTF-8: "+repr(direct["publication"]["footer"]))
    opened=client.get(BASE+"/open",headers=AUTH,
                      params={"path":saved.json()["path"]})
    assert opened.status_code==200
    assert opened.json()["publication"]==obj["publication"], (
        "UTF-8 mismatch after HTTP response. File: "+repr(obj["publication"]["footer"])+
        " Direct: "+repr(direct["publication"]["footer"])+
        " HTTP: "+repr(opened.json()["publication"]["footer"]))
    assert opened.json()["markdown"]==data["markdown"]
    older=client.post(BASE+"/save",headers=AUTH,
                      json={"name":"Older draft","markdown":"# Unchanged"})
    assert older.status_code==200
    old=json.loads((sandbox.default_root()/older.json()["path"]).read_text())
    assert old["schema"]==1 and "publication" not in old


def test_v4_preflight_creates_no_files_and_counts_real_word_structure(client):
    data=source()
    before=list((sandbox.default_root()/"artifacts"/"documents").glob("*")) if (
        sandbox.default_root()/"artifacts"/"documents").exists() else []
    result=client.post(BASE+"/preflight",headers=AUTH,json=data)
    assert result.status_code==200,result.text
    info=result.json()
    assert info["ready"] is True and info["no_files_saved"] is True
    assert info["reference_count"]==2
    assert info["headings"]>=2 and info["word_bytes"]>1000
    assert "limitations" in info
    after=list((sandbox.default_root()/"artifacts"/"documents").glob("*")) if (
        sandbox.default_root()/"artifacts"/"documents").exists() else []
    assert before==after
    assert path_allowed("POST",BASE+"/preflight")


def test_v4_contents_field_present_and_no_unverified_page_number_claim(client,monkeypatch):
    from automoto import office, office_build
    # publishing_spec calls the name imported into office_build, not office.lo_available.
    monkeypatch.setattr(office,"lo_available",lambda:False)
    monkeypatch.setattr(office_build,"lo_available",lambda:False)
    data=source()
    data["publication"]["contents_page"]=True
    result=client.post(BASE+"/preflight",headers=AUTH,json=data)
    assert result.status_code==200,result.text
    assert result.json()["contents_page"] is True
    assert any("page numbers" in w for w in result.json()["warnings"])
    # The Word TOC field is genuine; page numbers await local update.
    word=client.post(BASE+"/export",headers=AUTH,json={**data,"format":"docx"})
    assert word.status_code==200,word.text
    output=Document(sandbox.default_root()/word.json()["path"])
    assert "TOC \\o" in output._element.xml


def test_v4_uncited_sources_are_warnings_not_invented_in_text(client):
    data=source()
    data["markdown"]="# Report\n\nNo citations are cited in this text."
    result=client.post(BASE+"/preflight",headers=AUTH,json=data)
    assert result.status_code==200,result.text
    assert any("uncited" in w for w in result.json()["warnings"])


@pytest.mark.parametrize("bad",[
    lambda p:p["references"].append(dict(p["references"][0])),
    lambda p:p["references"][0].update(id="Bad!!!"),
    lambda p:p["references"][0].update(year="1800BC"),
    lambda p:p["references"][0].update(url="http://example.com"),
    lambda p:p["references"][0].update(url="https://user:pass@example.com"),
    lambda p:p["references"][0].update(doi="malicious<script>"),
    lambda p:p.update(reference_style="invented"),
    lambda p:p.update(unexpected="unvalidated Office property"),
])
def test_v4_rejects_untrusted_reference_metadata(client,bad):
    data=source()
    bad(data["publication"])
    response=client.post(BASE+"/preflight",headers=AUTH,json=data)
    assert response.status_code==422,response.text


@pytest.mark.parametrize("markdown",[
    "# Report\n\nUnknown reference [@missing].",
    "# Report\n\nMalformed reference [@CAPS].",
    "# Report\n\nA malformed reference [@with spaces].",
])
def test_v4_unknown_or_malformed_citations_cannot_export(client,markdown):
    data=source()
    data["markdown"]=markdown
    result=client.post(BASE+"/export",headers=AUTH,
                       json={**data,"format":"docx"})
    assert result.status_code==422,result.text


def test_v4_no_external_lookups_and_no_mutation_by_citation_compiler():
    settings=PublicationOptions.model_validate(refs())
    original="# Report\n\nA claim [@doe2025] and [@smith2023]."
    compiled,items,warnings=compile_publication(original,settings)
    assert "[@doe2025]" in original
    assert "(Doe, 2025)" in compiled
    assert items[0]["type"]=="references"
    assert len(items[0]["items"])==2
    assert not warnings
