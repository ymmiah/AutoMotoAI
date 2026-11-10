"""Document Assistant tools call the studio and keep its safety rules."""

import json

from automoto import document_workspace, hosted, tools as tools_mod
from automoto.document_studio_tools import document_export, document_open, document_revise
from automoto.tools import ToolContext

CTX = ToolContext()


def test_registered_levels_and_hosted_filter():
    tools = tools_mod.build()
    assert "document_export" in tools and tools["document_export"].level == "risky"
    assert tools["document_open"].level == "safe" and tools["document_preflight"].level == "safe"
    assert tools["document_revise"].level == "risky"
    hosted_names = hosted.hosted_tools()
    assert "document_export" in hosted_names
    assert "document_ai_review" not in hosted_names
    offline = tools_mod.build()
    assert "document_export" in offline


def test_export_calls_the_studio_and_writes_word(monkeypatch):
    seen = {}
    real = document_workspace.export_document

    def wrap(body, request):
        seen["name"] = body.name
        seen["style"] = body.publication.reference_style
        return real(body, request)

    monkeypatch.setattr(document_workspace, "export_document", wrap)
    out = document_export(CTX, name="Methods chapter",
                          markdown="# Methods\n\nStudy helps [@smith2024].\n",
                          publication={"reference_style": "harvard", "references": [{
                              "id": "smith2024", "authors": "Smith, J.", "year": "2024",
                              "title": "Move more", "type": "book", "publisher": "Health Press"}]})
    assert seen["name"] == "Methods chapter" and seen["style"] == "harvard"
    path = json.loads(out)["path"]
    ok, text = tools_mod.call(tools_mod.build()["read_file"], CTX, {"path": path})
    assert ok and "Smith" in text


def test_revise_keeps_the_original(monkeypatch):
    from automoto import sandbox
    from docx import Document

    folder = sandbox.default_root() / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / "clause.docx"
    doc = Document()
    doc.add_paragraph("Signed wording stays.")
    doc.save(file)
    opened = json.loads(document_open(CTX, "uploads/clause.docx"))
    sha = opened["sha256"]
    before = file.read_bytes()
    out = document_revise(CTX, "uploads/clause.docx", "Signed wording", "Revised wording", sha)
    assert "docx" in out and file.read_bytes() == before
