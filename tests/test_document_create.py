"""Document Assistant v8: create any document from scratch, and revise
copies of DOCX, PPTX and XLSX (previously DOCX only).

Create is always a new file in the private documents folder; the
find-and-replace revise path is copy-only and SHA-256 pinned, so an
imported original is never overwritten.
"""
from __future__ import annotations

import hashlib
import io

import pytest
from fastapi.testclient import TestClient

from automoto import sandbox, server

BASE = "/api/documents"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
MARKDOWN = "# Quarterly Report\n\n## Summary\n\n- Revenue grew this quarter.\n- Costs stayed flat.\n\n## Next steps\n\n- Review the budget.\n"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def created_path(client, fmt, **kwargs):
    body = {"name": "Quarterly Report", "format": fmt, "markdown": MARKDOWN}
    body.update(kwargs)
    response = client.post(BASE + "/create", headers=AUTH, json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["format"] == fmt
    path = sandbox.default_root() / data["path"]
    assert path.is_file() and path.stat().st_size > 0
    return path, data


def test_create_docx_from_markdown(client):
    path, _ = created_path(client, "docx")
    from docx import Document
    doc = Document(str(path))
    texts = [p.text for p in doc.paragraphs]
    assert "Quarterly Report" in texts
    assert "Summary" in texts
    assert any("Revenue grew" in t for t in texts)


def test_create_pptx_from_markdown(client):
    path, _ = created_path(client, "pptx")
    from pptx import Presentation
    prs = Presentation(str(path))
    assert len(prs.slides) >= 2
    all_text = " ".join(
        shape.text_frame.text for slide in prs.slides for shape in slide.shapes
        if shape.has_text_frame)
    assert "Quarterly Report" in all_text
    assert "Summary" in all_text
    assert "Revenue grew" in all_text


def test_create_xlsx_from_rows(client):
    path, _ = created_path(client, "xlsx", rows=[
        ["Item", "Amount"], ["Revenue", 120000], ["Costs", 80000]])
    from openpyxl import load_workbook
    wb = load_workbook(str(path))
    ws = wb.active
    assert ws["A1"].value == "Item"
    assert ws["B2"].value == 120000
    assert ws["B3"].value == 80000


def test_create_xlsx_from_markdown_table(client):
    markdown = "# Budget\n\n| Item | Amount |\n| --- | --- |\n| Revenue | 120000 |\n| Costs | 80000 |\n"
    path, _ = created_path(client, "xlsx", markdown=markdown)
    from openpyxl import load_workbook
    ws = load_workbook(str(path)).active
    assert ws["A1"].value == "Item"
    assert ws["A2"].value == "Revenue"


def test_create_xlsx_without_rows_or_table_is_rejected(client):
    response = client.post(BASE + "/create", headers=AUTH, json={
        "name": "Empty Sheet", "format": "xlsx", "markdown": "# No table here\n"})
    assert response.status_code == 422, response.text


def test_create_pdf_without_libreoffice(client):
    path, _ = created_path(client, "pdf")
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    assert len(reader.pages) >= 1
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Quarterly Report" in text
    assert "Revenue grew" in text


def test_create_plain_text_formats(client):
    md_path, _ = created_path(client, "md")
    assert md_path.read_text(encoding="utf-8") == MARKDOWN
    txt_path, _ = created_path(client, "txt")
    assert "Quarterly Report" in txt_path.read_text(encoding="utf-8")


def test_create_same_name_twice_makes_two_files(client):
    first, _ = created_path(client, "docx")
    second, _ = created_path(client, "docx")
    assert first != second
    assert first.is_file() and second.is_file()


def test_create_unknown_format_is_rejected(client):
    response = client.post(BASE + "/create", headers=AUTH, json={
        "name": "Bad", "format": "odt", "markdown": "# x\n"})
    assert response.status_code == 422, response.text


def _upload(filename: str, data: bytes):
    root = sandbox.default_root()
    p = root / "uploads" / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_revise_copy_pptx_keeps_original(client):
    original, _ = created_path(client, "pptx")
    # Move the created deck into uploads so it can be revised as an import.
    source = _upload("deck.pptx", original.read_bytes())
    before = _sha(source)
    response = client.post(BASE + "/replace-copy", headers=AUTH, json={
        "path": "uploads/deck.pptx", "sha256": before,
        "find": "Revenue grew", "replace": "Revenue jumped"})
    assert response.status_code == 200, response.text
    assert response.json()["changes"] >= 1
    assert _sha(source) == before, "original must not change"
    revised = sandbox.default_root() / response.json()["path"]
    from pptx import Presentation
    text = " ".join(shape.text_frame.text for slide in Presentation(str(revised)).slides
                    for shape in slide.shapes if shape.has_text_frame)
    assert "Revenue jumped" in text
    assert "Revenue grew" not in text


def test_revise_copy_xlsx_cells_and_text(client):
    original, _ = created_path(client, "xlsx", rows=[
        ["Item", "Amount"], ["Revenue", 120000]])
    source = _upload("budget.xlsx", original.read_bytes())
    before = _sha(source)
    response = client.post(BASE + "/replace-copy", headers=AUTH, json={
        "path": "uploads/budget.xlsx", "sha256": before,
        "find": "Revenue", "replace": "Income",
        "cells": {"Sheet1!B2": 125000}})
    assert response.status_code == 200, response.text
    assert _sha(source) == before, "original must not change"
    revised = sandbox.default_root() / response.json()["path"]
    from openpyxl import load_workbook
    ws = load_workbook(str(revised)).active
    assert ws["A2"].value == "Income"
    assert ws["B2"].value == 125000


def test_revise_copy_pdf_still_refused(client):
    pdf, _ = created_path(client, "pdf")
    source = _upload("report.pdf", pdf.read_bytes())
    response = client.post(BASE + "/replace-copy", headers=AUTH, json={
        "path": "uploads/report.pdf", "sha256": _sha(source),
        "find": "Revenue", "replace": "Income"})
    assert response.status_code == 422, response.text
