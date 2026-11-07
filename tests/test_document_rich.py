"""Real DOCX structure edits must preserve source package and rich formatting."""
from __future__ import annotations

import hashlib
import io

import pytest
from docx import Document
from docx.shared import Cm
from fastapi.testclient import TestClient
from PIL import Image

from automoto import sandbox, server
from automoto.hosted import path_allowed

BASE="/api/documents/docx"
AUTH={"X-AutoMoto-Token":server.SESSION_TOKEN}

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME",str(tmp_path/"home"))
    monkeypatch.delenv("AUTOMOTO_MODE",raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT","10000")
    return TestClient(server.app)

def original_word():
    root=sandbox.default_root()
    folder=root/"uploads"
    folder.mkdir(parents=True,exist_ok=True)
    logo=folder/"logo.png"
    Image.new("RGB",(320,160),(38,74,123)).save(logo)
    doc=Document()
    doc.core_properties.title="Unmodified original Word file"
    first=doc.add_paragraph(style="Normal")
    bold=first.add_run("Important ")
    bold.bold=True
    italic=first.add_run("mixed-format text")
    italic.italic=True
    doc.add_heading("Original heading",level=2)
    doc.add_paragraph("The baseline paragraph stays intact.")
    table=doc.add_table(rows=2,cols=2)
    table.style="Light Shading Accent 1"
    table.cell(0,0).text="Item"
    table.cell(0,1).text="Value"
    table.cell(1,0).text="Rent"
    table.cell(1,1).text="100"
    doc.sections[0].header.paragraphs[0].text="Original header text"
    doc.sections[0].footer.paragraphs[0].text="Original footer text"
    doc.add_picture(str(logo),width=Cm(3.5))
    source=folder/"mixed-format.docx"
    doc.save(source)
    return source,logo

def request_ops(path,operations):
    return {"path":"uploads/mixed-format.docx",
            "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
            "operations":operations}

def word(client,path):
    response=client.get(BASE+"/structure",params={"path":"uploads/mixed-format.docx"},headers=AUTH)
    assert response.status_code==200,response.text
    return response.json()

def test_authentication_and_hosted_allowlist(client):
    assert client.get(BASE+"/structure",params={"path":"uploads/x.docx"}).status_code==403
    assert client.post(BASE+"/revise",json={"path":"uploads/x.docx",
        "sha256":"0"*64,"operations":[{"kind":"set_style","paragraph":0,"style":"Heading 1"}]}).status_code==403
    assert path_allowed("GET",BASE+"/structure")
    assert path_allowed("POST",BASE+"/revise")
    assert not path_allowed("DELETE",BASE+"/revise")

def test_structure_exposes_real_word_runs_tables_images_and_metadata(client):
    source,logo=original_word()
    result=word(client,source)
    assert result["sha256"]==hashlib.sha256(source.read_bytes()).hexdigest()
    assert result["images"]==1
    assert result["sections"]==1
    assert result["paragraphs"][0]["runs"][0]["bold"] is True
    assert result["paragraphs"][0]["runs"][1]["italic"] is True
    assert result["paragraphs"][1]["style"]=="Heading 2"
    assert result["tables"][0]["preview"][1][0]=="Rent"
    assert result["tables"][0]["preview"][1][1]=="100"
    assert result["truncated"] is False

def test_replace_one_run_preserves_other_runs_styles_images_and_original(client):
    source,logo=original_word()
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    response=client.post(BASE+"/revise",headers=AUTH,json=request_ops(source,[{
        "kind":"replace_run","paragraph":0,"run":1,
        "expected":"mixed-format text","text":"updated word content"}]))
    assert response.status_code==200,response.text
    data=response.json()
    assert data["operations"]==1
    copy=sandbox.default_root()/data["path"]
    assert copy!=source and copy.is_file()
    assert hashlib.sha256(source.read_bytes()).hexdigest()==sha
    old=Document(source)
    revised=Document(copy)
    assert old.paragraphs[0].text=="Important mixed-format text"
    assert revised.paragraphs[0].text=="Important updated word content"
    assert revised.paragraphs[0].runs[0].bold is True
    assert revised.paragraphs[0].runs[1].italic is True
    assert revised.paragraphs[1].style.name=="Heading 2"
    assert revised.tables[0].cell(1,0).text=="Rent"
    assert len(revised.inline_shapes)==1
    assert revised.sections[0].header.paragraphs[0].text=="Original header text"
    assert revised.sections[0].footer.paragraphs[0].text=="Original footer text"
    assert revised.core_properties.title=="Unmodified original Word file"

def test_batch_real_table_row_style_cell_and_image(client):
    source,logo=original_word()
    actions=[
        {"kind":"set_style","paragraph":2,"style":"Heading 3"},
        {"kind":"table_cell","table":0,"row":1,"cell":1,"expected":"100","text":"125"},
        {"kind":"append_row","table":0,"values":["Utilities","45"]},
        {"kind":"insert_image","paragraph":2,"image_path":"uploads/logo.png","width_cm":4.5}
    ]
    response=client.post(BASE+"/revise",headers=AUTH,json=request_ops(source,actions))
    assert response.status_code==200,response.text
    revised=Document(sandbox.default_root()/response.json()["path"])
    assert revised.paragraphs[2].style.name=="Heading 3"
    assert revised.tables[0].cell(1,1).text=="125"
    assert revised.tables[0].cell(2,0).text=="Utilities"
    assert revised.tables[0].cell(2,1).text=="45"
    assert len(revised.inline_shapes)==2
    assert revised.sections[0].header.paragraphs[0].text=="Original header text"
    assert revised.sections[0].footer.paragraphs[0].text=="Original footer text"
    assert len(Document(source).tables[0].rows)==2
    assert len(Document(source).inline_shapes)==1

def test_stale_source_hash_makes_zero_changes(client):
    source,logo=original_word()
    payload=request_ops(source,[{"kind":"replace_run","paragraph":0,"run":0,
                              "expected":"Important ","text":"Changed " }])
    payload["sha256"]="0"*64
    response=client.post(BASE+"/revise",headers=AUTH,json=payload)
    assert response.status_code==409
    folder=sandbox.default_root()/"artifacts"/"documents"
    assert not folder.exists() or not list(folder.glob("*.docx"))

def test_incorrect_expected_run_refuses_without_writing(client):
    source,logo=original_word()
    payload=request_ops(source,[{"kind":"replace_run","paragraph":0,"run":0,
                               "expected":"something else","text":"New text"}])
    response=client.post(BASE+"/revise",headers=AUTH,json=payload)
    assert response.status_code==409
    assert Document(source).paragraphs[0].runs[0].text=="Important "

@pytest.mark.parametrize("operation",[
    {"kind":"replace_run","paragraph":0,"run":12,"expected":"x","text":"y"},
    {"kind":"replace_run","paragraph":0,"run":0,"expected":"Important ","text":"Important "},
    {"kind":"set_style","paragraph":2,"style":"MacroDanger"},
    {"kind":"set_style","paragraph":500,"style":"Heading 1"},
    {"kind":"table_cell","table":0,"row":99,"cell":0,"expected":"x","text":"y"},
    {"kind":"append_row","table":0,"values":["Only one value"]},
    {"kind":"insert_image","paragraph":0,"image_path":"../outside.jpg","width_cm":3},
    {"kind":"insert_image","paragraph":0,"image_path":"uploads/logo.png","width_cm":100},
    {"kind":"set_style","paragraph":0,"style":"Heading 1","evil":"arbitrary"},
])
def test_rejects_invalid_edits_without_publishing(client,operation):
    source,logo=original_word()
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    response=client.post(BASE+"/revise",headers=AUTH,
                         json=request_ops(source,[operation]))
    assert response.status_code in (403,409,413,422),response.text
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    folder=sandbox.default_root()/"artifacts"/"documents"
    assert not folder.exists() or not list(folder.glob("*.docx"))

def test_only_private_docx_can_be_modified(client):
    source,logo=original_word()
    data=request_ops(source,[{"kind":"set_style","paragraph":0,"style":"Title"}])
    for invalid in ("../settings.json","uploads/logo.png","settings.json",
                    "artifacts/visual-studio/other.docx"):
        r=client.post(BASE+"/revise",headers=AUTH,json={**data,"path":invalid})
        assert r.status_code in (403,404,415,422),r.text

def test_linked_macro_word_does_not_bypass_scan(client):
    source,logo=original_word()
    from zipfile import ZipFile,ZIP_DEFLATED
    import shutil
    malicious=source.with_name("macro.docx")
    with ZipFile(source) as old,ZipFile(malicious,"w",ZIP_DEFLATED) as new:
        for entry in old.infolist():
            new.writestr(entry,old.read(entry.filename))
        new.writestr("word/vbaProject.bin",b"malicious VBA stub")
    digest=hashlib.sha256(malicious.read_bytes()).hexdigest()
    response=client.post(BASE+"/revise",headers=AUTH,json={
        "path":"uploads/macro.docx","sha256":digest,
        "operations":[{"kind":"set_style","paragraph":0,"style":"Heading 1"}]})
    assert response.status_code==422

def test_invalid_image_bytes_are_never_inserted(client):
    source,logo=original_word()
    broken=sandbox.default_root()/"uploads"/"broken.png"
    broken.write_bytes(b"fake png")
    response=client.post(BASE+"/revise",headers=AUTH,
       json=request_ops(source,[{"kind":"insert_image","paragraph":1,
               "image_path":"uploads/broken.png","width_cm":2.0}]))
    assert response.status_code==422
    assert len(Document(source).inline_shapes)==1
