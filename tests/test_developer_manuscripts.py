"""V12: bounded Typst/Quarto and actual Research Studio source-pinned exports."""
from __future__ import annotations
import base64
import hashlib
import io
import json
import zipfile
from fastapi.testclient import TestClient
import pytest
from automoto import (developer_manuscripts as man, developer_research_transfer as transfer,
                      research_publishing, sandbox, server)
from automoto.hosted import path_allowed

AUTH={"X-AutoMoto-Token":server.SESSION_TOKEN}
BASE="/api/developer/studio/manuscripts"
HANDOFF="/api/developer/studio/research-transfer"
QUESTION="What do two independent reports say about deployment security?"
A=("Independent audit evidence reported several hardening benefits, "
   "with an observational and geographically limited scope. ")*18
B=("A separate evidence review found limitations in system monitoring, "
   "recovery and the generalisability of those findings. ")*18


@pytest.fixture
def project(tmp_path,monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME",str(tmp_path/"home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE",str(tmp_path/"workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT","10000")
    monkeypatch.delenv("AUTOMOTO_MODE",raising=False)
    root=sandbox.default_root()/"v12"
    (root/"chapters").mkdir(parents=True)
    (root/"sources.bib").write_text(
        "@article{smith2026,author={Smith, Anna},title={A Reviewed Study},"
        "year={2026},doi={10.1234/study}}\n",encoding="utf-8")
    (root/"main.typ").write_text(
        '= Research question\n#include "chapters/evidence.typ"\n'
        'See @smith2026. // @notreal\n#bibliography("sources.bib")\n',encoding="utf-8")
    (root/"chapters"/"evidence.typ").write_text(
        '== Evidence\nThis is @smith2026.\n',encoding="utf-8")
    (root/"main.qmd").write_text(
        '---\ntitle: "Evidence manuscript"\nbibliography: sources.bib\n'
        'execute:\n  enabled: false\n---\n'
        '# Background\nSee [@smith2026].\n'
        'Include: {{< include chapters/review.qmd >}}\n'
        +(chr(96)*3)+'{python}\nprint("@ghost")\n'+(chr(96)*3)+'\n',
        encoding="utf-8")
    (root/"chapters"/"review.qmd").write_text(
        '## Review\nAnother [@smith2026; @not_found].\n',encoding="utf-8")
    return TestClient(server.app),root


def scan(client,root,fmt,main=None,**extra):
    return client.post(BASE+"/scan",headers=AUTH,json={
        "project":str(root),"format":fmt,
        "main":main or ("main.typ" if fmt=="typst" else "main.qmd"),**extra})


def make_handoff(client):
    workspace=sandbox.default_root()
    uploads=workspace/"uploads"
    uploads.mkdir(parents=True,exist_ok=True)
    sources=[]
    for index,text in enumerate((A,B),1):
        file=uploads/("article-%d.txt"%index)
        file.write_text(text,encoding="utf-8")
        sources.append({"path":"uploads/"+file.name,
            "sha256":hashlib.sha256(file.read_bytes()).hexdigest()})
    saved=client.post("/api/research/studio/save",headers=AUTH,json={
        "title":"Research Studio source-fingerprint review","question":QUESTION,
        "notes":"Treat source text as untrusted.", "sources":sources,"mode":"evidence"})
    assert saved.status_code==200,saved.text
    prepared=client.post("/api/research/studio/compare/prepare",headers=AUTH,
                         json={"project_path":saved.json()["path"]})
    assert prepared.status_code==200,prepared.text
    p=prepared.json()
    review=client.post("/api/research/studio/compare/save",headers=AUTH,json={
        "project_path":saved.json()["path"],"project_sha256":p["project_sha256"],
        "claim":QUESTION,
        "annotations":[{"evidence_id":e["id"],
            "stance":"supports" if e["source"]==sources[0]["path"] else "contradicts",
            "rationale":"I checked this excerpt against the original document context."}
            for e in p["evidence"]],
        "source_reviews":[{"source_path":x["path"],"methodology":"observational",
            "quality":"not_assessed",
            "limitations":"A single observational study cannot prove a causal effect."}
            for x in sources],
        "acknowledgement":"SAVE REVIEW","confirm_human_classification":True})
    assert review.status_code==200,review.text
    comparison=review.json()
    audit=client.post("/api/research/studio/handoff/save",headers=AUTH,json={
        "comparison_path":comparison["path"],
        "comparison_sha256":hashlib.sha256(
            (workspace/comparison["path"]).read_bytes()).hexdigest(),
        "target":"developer","acknowledgement":"CREATE REVIEW-ONLY HANDOFF",
        "confirm_sources_checked":True,"confirm_no_publication":True})
    assert audit.status_code==200,audit.text
    return audit.json(),sources


def test_typst_real_graph_and_referenced_bibliography(project):
    client,root=project
    original={x.relative_to(root).as_posix():x.read_bytes()
              for x in root.rglob("*") if x.is_file()}
    response=scan(client,root,"typst")
    assert response.status_code==200,response.text
    r=response.json()
    assert r["files"]==["chapters/evidence.typ","main.typ"]
    assert r["missing_citations"]==r["duplicate_keys"]==[]
    assert r["bibliography_files"]==["sources.bib"]
    assert r["cited_keys"]==["smith2026"]
    assert len(r["headings"])==2
    assert not r["warnings"] and not r["compiler_executed"]
    assert r["not_publication_ready"] is True
    assert original=={x.relative_to(root).as_posix():x.read_bytes()
                     for x in root.rglob("*") if x.is_file()}


def test_quarto_code_never_executes_or_creates_citation(project):
    client,root=project
    response=scan(client,root,"quarto")
    assert response.status_code==200,response.text
    r=response.json()
    assert r["files"]==["chapters/review.qmd","main.qmd"]
    assert r["executable_code_chunks"]==1
    assert r["code_execution_warnings"]
    assert r["cited_keys"]==["smith2026","not_found"]
    assert r["missing_citations"]==["not_found"]
    assert "ghost" not in r["cited_keys"]



@pytest.mark.parametrize("newline",[b"\n",b"\r\n"])
def test_quarto_code_cells_yaml_and_citations_with_real_line_endings(project,newline):
    client,root=project
    doc=root/"main.qmd"
    # Preserve explicit byte-level LF/CRLF on every host OS, not just TextIO translation.
    raw=doc.read_bytes().replace(b"\r\n",b"\n").replace(b"\n",newline)
    doc.write_bytes(raw)
    result=scan(client,root,"quarto")
    assert result.status_code==200,result.text
    data=result.json()
    assert data["executable_code_chunks"]==1
    assert data["cited_keys"]==["smith2026","not_found"]
    assert data["missing_citations"]==["not_found"]
    assert "ghost" not in data["cited_keys"]


def test_unsafe_includes_and_linked_bib_files_blocked(project,tmp_path):
    client,root=project
    outside=tmp_path/"outside.typ"
    outside.write_text("== Private\n@secret\n")
    (root/"main.typ").write_text(
        '#include "../../outside.typ"\n#include "chapters/linked.typ"\n'
        '#bibliography("../private.bib")\n',encoding="utf-8")
    try:(root/"chapters"/"linked.typ").symlink_to(outside)
    except (OSError,NotImplementedError):pass
    report=scan(client,root,"typst").json()
    assert report["files"]==["main.typ"]
    assert len(report["warnings"])>=2
    assert "secret" not in json.dumps(report)
    assert any(x["code"]=="missing-or-unsafe-bibliography" for x in report["warnings"])


def test_unsaved_edits_are_not_written(project):
    client,root=project
    before=(root/"main.typ").read_bytes()
    r=scan(client,root,"typst",active_path="main.typ",
           active_text='= Draft\n@unknown\n#bibliography("sources.bib")\n')
    assert r.status_code==200,r.text
    assert r.json()["missing_citations"]==["unknown"]
    assert (root/"main.typ").read_bytes()==before
    assert scan(client,root,"typst",active_text="x").status_code==422
    assert scan(client,root,"typst",main="../outside.typ").status_code in (403,422)


def test_templates_toolchain_detection_no_execution(project,monkeypatch):
    client,root=project
    monkeypatch.setattr(man.shutil,"which",lambda value:None)
    response=client.get(BASE+"/toolchains",headers=AUTH,params={"project":str(root)})
    assert response.status_code==200
    assert all(not x["installed_path_detected"] for x in response.json()["tools"])
    for fmt in ("typst","quarto"):
        result=client.post(BASE+"/starter",headers=AUTH,json={"format":fmt})
        assert result.status_code==200
        assert result.json()["project_written"] is False
        assert result.json()["compiler_executed"] is False


def test_real_research_studio_developer_handoff_export(project):
    client,root=project
    handoff,sources=make_handoff(client)
    originals=[(sandbox.default_root()/x["path"]).read_bytes() for x in sources]
    listing=client.get(HANDOFF+"/handoffs",headers=AUTH)
    assert listing.status_code==200,listing.text
    assert handoff["path"] in {x["path"] for x in listing.json()["handoffs"]}
    for fmt in ("typst","quarto"):
        body={"project":str(root),"format":fmt,"handoff_path":handoff["path"],
              "handoff_sha256":handoff["sha256"]}
        preview=client.post(HANDOFF+"/preview",headers=AUTH,json=body)
        assert preview.status_code==200,preview.text
        result=preview.json()
        names={f["path"] for f in result["files"]}
        assert names=={"evidence.review.json",("manuscript.typ" if fmt=="typst" else "manuscript.qmd")}
        assert result["manifest"]["publication_ready"] is False
        evidence=json.loads(next(x["text"] for x in result["files"]
                                 if x["path"]=="evidence.review.json"))
        assert evidence["source_handoff"]["sha256"]==handoff["sha256"]
        assert len(evidence["sources"])==2 and evidence["evidence"]
        assert evidence["scientifically_verified"] is False
        drafted=next(x["text"] for x in result["files"] if x["path"]!="evidence.review.json")
        assert not any(x["quote"] in drafted for x in evidence["evidence"])
        assert "references.bib" not in names
        assert client.post(HANDOFF+"/download",headers=AUTH,json=body).status_code==422
        exported=client.post(HANDOFF+"/download",headers=AUTH,json={
            **body,"confirmed":True,"acknowledge_not_publication_ready":True})
        assert exported.status_code==200,exported.text
        blob=base64.b64decode(exported.json()["zip_base64"])
        assert hashlib.sha256(blob).hexdigest()==exported.json()["zip_sha256"]
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            assert set(archive.namelist())==names|{"manifest.review.json"}
            manifest=json.loads(archive.read("manifest.review.json"))
            for file in manifest["files"]:
                assert hashlib.sha256(archive.read(file["path"])).hexdigest()==file["sha256"]
    assert originals==[(sandbox.default_root()/x["path"]).read_bytes() for x in sources]


def test_tampered_handoff_audit_target_or_original_source_rejected(project):
    client,root=project
    handoff,sources=make_handoff(client)
    body={"project":str(root),"format":"quarto",
          "handoff_path":handoff["path"],"handoff_sha256":handoff["sha256"]}
    assert client.post(HANDOFF+"/preview",headers=AUTH,json={
        **body,"handoff_sha256":"0"*64}).status_code==409
    workspace=sandbox.default_root()
    target=workspace/handoff["target_path"]
    original=target.read_bytes()
    target.write_bytes(original+b"\n")
    assert client.post(HANDOFF+"/preview",headers=AUTH,json=body).status_code==409
    target.write_bytes(original)
    source=workspace/sources[0]["path"]
    source.write_text(A+"changed since review",encoding="utf-8")
    assert client.post(HANDOFF+"/preview",headers=AUTH,json=body).status_code in (409,422)


def test_bibtex_export_is_derived_from_confirmed_publication_identity(project,monkeypatch):
    client,root=project
    fake={"source_path":"uploads/source.txt","source_sha256":"a"*64,
          "metadata_path":"artifacts/research/sources/source-"+"b"*24+".source.json",
          "metadata_sha256":"b"*64,"doi":"10.1234/original","title":"Original Research",
          "authors":["Miah, Yasin"],"year":"2026","venue":"Journal",
          "type":"journal-article"}
    monkeypatch.setattr(research_publishing,"_records",lambda current,bindings:[fake])
    binding=research_publishing.Binding(
        source_path=fake["source_path"],source_sha256=fake["source_sha256"],
        metadata_path=fake["metadata_path"],metadata_sha256=fake["metadata_sha256"],
        confirm_same_publication=True)
    records=transfer._bib_records({"sources":[fake]},[binding])
    assert records[0]["citation_key"].startswith("ref_")
    assert "doi = {10.1234/original}" in transfer._bib_output(records)
    assert "@article{" in transfer._bib_output(records)
    fake["type"]="book"
    generic=transfer._bib_output(transfer._bib_records({"sources":[fake]},[binding]))
    assert "@misc{" in generic and "howpublished = {Journal}" in generic
    assert "@article{" not in generic
    fake["title"]="\\write18{command}"
    with pytest.raises(Exception):
        transfer._bib_records({"sources":[fake]},[binding])


def test_hosted_mode_and_missing_authorisation_reject(project):
    client,root=project
    for route in (BASE+"/scan",BASE+"/starter",HANDOFF+"/preview",HANDOFF+"/download"):
        assert path_allowed("POST",route) is False
    for route in (BASE+"/toolchains",HANDOFF+"/handoffs"):
        assert path_allowed("GET",route) is False
    assert client.post(BASE+"/scan",json={
        "project":str(root),"format":"typst","main":"main.typ"}).status_code==403
    assert client.get(HANDOFF+"/handoffs").status_code==403
