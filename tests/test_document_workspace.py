"""Document Assistant v1 — real Office files, private drafts and non-destructive edits."""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json

import pytest
from docx import Document
from fastapi.testclient import TestClient

from automoto import office, office_build, sandbox, server
from automoto.hosted import path_allowed

BASE = "/api/documents"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def create_import(name="incoming.docx"):
    root = sandbox.default_root()
    folder = root / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / name
    document = Document()
    document.add_heading("Original contract", 1)
    document.add_paragraph("This phrase belongs to the original file.")
    document.add_paragraph("Signed wording is preserved until a separate revision is approved.")
    document.save(str(file))
    return file


def test_endpoints_require_auth_and_hosted_allowlist(client):
    assert client.get(BASE + "/list").status_code == 403
    assert client.get(BASE + "/open", params={"path": "uploads/x.docx"}).status_code == 403
    payload = {"name": "New report", "markdown": "# Hello\n\nContent"}
    for action in ("save", "export"):
        assert client.post(BASE + "/" + action, json=payload).status_code == 403
        assert path_allowed("POST", BASE + "/" + action)
    assert client.post(BASE + "/replace-copy", json={
        "path": "uploads/x.docx", "sha256": "0" * 64, "find": "x", "replace": "y",
    }).status_code == 403
    assert path_allowed("POST", BASE + "/replace-copy")
    assert path_allowed("GET", BASE + "/open")
    assert path_allowed("GET", BASE + "/list")
    assert not path_allowed("DELETE", BASE + "/save")


def test_save_reopen_markdown_source_without_altering_other_documents(client):
    original = create_import()
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    data = {"name": "Research outline", "markdown": "# Research outline\n\n## Background\n\nAccurate original text."}
    r = client.post(BASE + "/save", headers=AUTH, json=data)
    assert r.status_code == 200, r.text
    path = r.json()["path"]
    assert path.startswith("artifacts/documents/") and path.endswith(".document.json")
    stored = json.loads((sandbox.default_root() / path).read_text())
    assert stored == {"schema": 1, **data}
    opened = client.get(BASE + "/open", headers=AUTH, params={"path": path})
    assert opened.status_code == 200
    assert opened.json()["editable"] is True
    assert opened.json()["markdown"] == data["markdown"]
    assert opened.json()["name"] == data["name"]
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before
    all_documents = client.get(BASE + "/list", headers=AUTH).json()["documents"]
    assert any(v["path"] == path for v in all_documents)
    assert any(v["path"] == "uploads/incoming.docx" for v in all_documents)
    second = client.post(BASE + "/save", headers=AUTH, json=data)
    assert second.status_code == 200
    assert second.json()["path"] != path, "saved revisions are create-only"


def test_word_export_builds_real_editable_heading_and_paragraph(client):
    data = {"name": "Research Report", "markdown": "# Introduction\n\nThis is editable Word content.\n\n## Findings\n\n- Evidence one\n- Evidence two"}
    response = client.post(BASE + "/export", headers=AUTH, json={**data, "format": "docx"})
    assert response.status_code == 200, response.text
    file = sandbox.default_root() / response.json()["path"]
    assert file.is_file() and file.suffix == ".docx"
    document = Document(str(file))
    rendered = "\n".join(p.text for p in document.paragraphs)
    assert "Introduction" in rendered
    assert "This is editable Word content" in rendered
    assert "Findings" in rendered
    assert "Evidence one" in rendered
    assert document.core_properties.title == "Research Report"
    assert any(p.style.name.startswith("Heading") for p in document.paragraphs)
    downloaded = client.get("/api/files/download", headers=AUTH,
                            params={"path": response.json()["path"]})
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"PK"), "DOCX must be a genuine OOXML package"


def test_imported_word_is_read_only_and_copy_edit_preserves_original(client):
    original = create_import()
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    opened = client.get(BASE + "/open", headers=AUTH,
                        params={"path": "uploads/incoming.docx"})
    assert opened.status_code == 200, opened.text
    value = opened.json()
    assert value["editable"] is False
    assert value["sha256"] == digest
    assert "Original contract" in value["extracted_text"]
    request = {"path": value["path"], "sha256": digest, "find": "This phrase",
               "replace": "That sentence"}
    updated = client.post(BASE + "/replace-copy", headers=AUTH, json=request)
    assert updated.status_code == 200, updated.text
    new_path = updated.json()["path"]
    assert new_path.startswith("artifacts/documents/")
    assert updated.json()["changes"] == 1
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
    new_doc = Document(str(sandbox.default_root() / new_path))
    all_text = "\n".join(p.text for p in new_doc.paragraphs)
    assert "That sentence belongs" in all_text
    assert "Signed wording is preserved" in all_text
    assert "This phrase belongs" not in all_text
    assert new_doc.paragraphs[0].style.name == "Heading 1"
    assert new_doc.paragraphs[1].style.name == "Normal"


def test_revision_rejects_stale_digest_and_unmatched_phrase(client):
    original = create_import()
    before = original.read_bytes()
    payload = {"path": "uploads/incoming.docx", "sha256": "0" * 64,
               "find": "Original contract", "replace": "Changed"}
    assert client.post(BASE + "/replace-copy", headers=AUTH, json=payload).status_code == 409
    payload["sha256"] = hashlib.sha256(before).hexdigest()
    payload["find"] = "This phrase does not exist"
    failed = client.post(BASE + "/replace-copy", headers=AUTH, json=payload)
    assert failed.status_code == 422
    assert original.read_bytes() == before
    folder = sandbox.default_root() / "artifacts" / "documents"
    assert not list(folder.glob("*.docx")), "a no-match copy must not appear as a successful revision"


@pytest.mark.parametrize("path", [
    ".", "uploads/..", "../outside.docx", "/etc/passwd", "settings.json",
    "artifacts/visual-studio/private.docx", "uploads/../../other.docx",
    "uploads/.secret.json",
])
def test_open_rejects_out_of_scope_paths(client, path):
    r = client.get(BASE + "/open", headers=AUTH, params={"path": path})
    assert r.status_code in (403, 404, 415), (path, r.text)


def test_plain_text_can_be_loaded_but_original_remains_unchanged(client):
    root = sandbox.default_root()
    target = root / "uploads" / "notes.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# My heading\n\nUnmodified local notes.\n")
    result = client.get(BASE + "/open", headers=AUTH, params={"path": "uploads/notes.md"})
    assert result.status_code == 200 and result.json()["editable"] is True
    assert "Unmodified local notes" in result.json()["markdown"]
    save = client.post(BASE + "/save", headers=AUTH, json={
        "name": "New revision", "markdown": "# Different content"})
    assert save.status_code == 200
    assert "Unmodified local notes" in target.read_text()


def test_untrusted_import_is_refused_without_mutating_original(client):
    root = sandbox.default_root()
    uploaded = root / "uploads" / "unsafe.docx"
    uploaded.parent.mkdir(parents=True, exist_ok=True)
    uploaded.write_bytes(b"not an OOXML document")
    response = client.get(BASE + "/open", headers=AUTH,
                          params={"path": "uploads/unsafe.docx"})
    assert response.status_code == 422
    assert uploaded.read_bytes() == b"not an OOXML document"


def test_limits_and_external_image_references_are_rejected(client):
    too_long = {"name": "oversized", "markdown": "x" * 120001}
    assert client.post(BASE + "/save", headers=AUTH, json=too_long).status_code == 422
    image = {"name": "image attempt", "markdown": "![remote logo](https://example.invalid/photo.png)"}
    r = client.post(BASE + "/export", headers=AUTH, json={**image, "format": "docx"})
    assert r.status_code == 422
    assert "image paths" in r.text
    assert client.post(BASE + "/save", headers=AUTH,
                       json={"name": "   ", "markdown": "hi"}).status_code == 422


def test_pdf_export_uses_existing_local_office_converter(client, monkeypatch):
    monkeypatch.setattr(office, "lo_available", lambda: False)
    response = client.post(BASE + "/export", headers=AUTH,
                           json={"name": "PDF", "markdown": "# Report", "format": "pdf"})
    assert response.status_code == 501, response.text
    assert not list((sandbox.default_root() / "artifacts" / "documents").glob("*.pdf")) if (
        sandbox.default_root() / "artifacts" / "documents").exists() else True


def test_pdf_powerpoint_and_excel_imports_are_explicitly_read_only(client):
    from pypdf import PdfWriter
    from pptx import Presentation
    from pptx.util import Inches
    from openpyxl import Workbook

    root = sandbox.default_root() / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    with (root / "source.pdf").open("wb") as stream:
        writer.write(stream)
    slides = Presentation()
    slide = slides.slides.add_slide(slides.slide_layouts[5])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1)).text = "Original slide caption"
    slides.save(str(root / "source.pptx"))
    workbook = Workbook()
    workbook.active["A1"] = "Original spreadsheet cell"
    workbook.save(str(root / "source.xlsx"))
    for name, excerpt in [("source.pdf", "PDF: 1 page"),
                          ("source.pptx", "Original slide caption"),
                          ("source.xlsx", "Original spreadsheet cell")]:
        response = client.get(BASE + "/open", headers=AUTH,
                              params={"path": f"uploads/{name}"})
        assert response.status_code == 200, (name, response.text)
        data = response.json()
        assert data["editable"] is False
        assert excerpt in data["extracted_text"]
        assert data["sha256"] == hashlib.sha256((root / name).read_bytes()).hexdigest()
        assert "read-only extraction" in data["notice"].lower()


def _v2_options():
    return {"page_size": "Letter", "orientation": "landscape", "margins_cm": 3.1,
            "font": "Georgia", "font_size": 13, "line_spacing": 1.5,
            "heading_color": "#345678", "page_numbers": False}


def test_v2_draft_persists_page_settings_and_is_backward_compatible(client):
    source = {"name": "Document settings", "markdown": "# Report\n\nContent",
              "options": _v2_options()}
    saved = client.post(BASE + "/save", headers=AUTH, json=source)
    assert saved.status_code == 200, saved.text
    target = sandbox.default_root() / saved.json()["path"]
    stored = json.loads(target.read_text(encoding="utf-8"))
    assert stored["schema"] == 2 and stored["options"] == source["options"]
    loaded = client.get(BASE + "/open", headers=AUTH,
                        params={"path": saved.json()["path"]})
    assert loaded.status_code == 200 and loaded.json()["options"] == source["options"]
    old = client.post(BASE + "/save", headers=AUTH, json={
        "name": "Version one", "markdown": "# Legacy source"})
    assert old.status_code == 200
    legacy_file = sandbox.default_root() / old.json()["path"]
    assert json.loads(legacy_file.read_text()) == {
        "schema": 1, "name": "Version one", "markdown": "# Legacy source"}
    reopened = client.get(BASE + "/open", headers=AUTH,
                          params={"path": old.json()["path"]})
    assert reopened.status_code == 200
    assert reopened.json()["options"] is None
    assert reopened.json()["markdown"] == "# Legacy source"


def test_v2_word_export_applies_page_orientation_font_margins_and_table(client):
    source = {"name": "Structured Word", "options": _v2_options(), "markdown":
              "# Executive summary\n\n## Financial performance\n\n"
              "| Metric | Actual | Budget |\n"
              "| --- | --- | --- |\n"
              "| Revenue | 150 | 120 |\n"
              "| Costs | 60 | 70 |\n"}
    response = client.post(BASE + "/export", headers=AUTH,
                           json={**source, "format": "docx"})
    assert response.status_code == 200, response.text
    output = Document(str(sandbox.default_root() / response.json()["path"]))
    from docx.enum.section import WD_ORIENT
    from docx.shared import Cm
    section = output.sections[0]
    assert section.orientation == WD_ORIENT.LANDSCAPE
    assert abs(section.page_width - Cm(27.94)) < Cm(0.15)
    assert abs(section.page_height - Cm(21.59)) < Cm(0.15)
    assert abs(section.left_margin - Cm(3.1)) < Cm(0.15)
    assert output.styles["Normal"].font.name == "Georgia"
    assert round(output.styles["Normal"].font.size.pt, 1) == 13
    assert round(output.styles["Normal"].paragraph_format.line_spacing, 2) == 1.5
    assert str(output.styles["Heading 1"].font.color.rgb) == "345678"
    assert len(output.tables) == 1
    table = output.tables[0]
    assert [cell.text for cell in table.rows[0].cells] == ["Metric", "Actual", "Budget"]
    assert table.cell(1, 1).text == "150"
    assert table.cell(2, 2).text == "70"
    assert any(p.style.name == "Heading 2" and p.text == "Financial performance"
               for p in output.paragraphs)
    footer_xml = section.footer._element.xml
    assert "PAGE" not in footer_xml and "NUMPAGES" not in footer_xml


@pytest.mark.parametrize("bad", [
    {"page_size": "Tabloid"},
    {"orientation": "upside-down"},
    {"margins_cm": 0.1},
    {"margins_cm": 10},
    {"margins_cm": "nan"},
    {"font": "<script>alert(1)</script>"},
    {"font_size": 40},
    {"line_spacing": -1},
    {"heading_color": "#BAD; background:url(javascript:1)"},
    {"page_numbers": "not a boolean"},
    {"unknown_option": "arbitrary office injection"},
])
def test_v2_rejects_malicious_or_out_of_bounds_layout(client, bad):
    payload = {"name": "Bad source", "markdown": "# Heading",
               "options": {**_v2_options(), **bad}}
    for action in ("save", "export"):
        if action == "export":
            payload["format"] = "docx"
        result = client.post(BASE + "/" + action, headers=AUTH, json=payload)
        assert result.status_code == 422, (action, bad, result.text)
