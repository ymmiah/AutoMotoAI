"""Visual Studio v8 — genuine multi-page PDF / editable PowerPoint and private drafts."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader
from pptx import Presentation

from automoto import sandbox, server
from automoto.hosted import path_allowed

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BASE = "/api/visual/studio"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def page(index):
    return {"name": f"Slide {index}", "spec": {
        "layout": "canvas", "artboard_only": True,
        "width": 800, "height": 500, "theme": "editorial-light",
        "title": f"Source {index}",
        "elements": [{
            "type": "text", "x": 65, "y": 100, "w": 550, "h": 90,
            "text": f"Distinct editable content {index}",
            "font_size": 30, "colour": "#172638", "bold": True,
        }],
    }}


def body(count=3):
    return {"name": "A real presentation", "pages": [page(i) for i in range(1, count + 1)]}


def test_document_endpoints_require_auth_and_are_explicitly_hosted(client):
    for action in ("save", "export"):
        url = f"{BASE}/document/{action}"
        assert client.post(url, json=body()).status_code == 403
        assert path_allowed("POST", url)
        assert not path_allowed("DELETE", url)


def test_save_load_and_page_names_preserve_original_specs(client):
    doc = body()
    doc["pages"][1]["spec"]["elements"][0]["locked"] = True
    saved = client.post(BASE + "/document/save", headers=AUTH, json=doc)
    assert saved.status_code == 200, saved.text
    result = saved.json()
    assert result["page_count"] == 3
    assert result["path"].startswith("artifacts/visual-studio/")
    raw = json.loads((sandbox.default_root() / result["path"]).read_text(encoding="utf-8"))
    assert raw["schema"] == 2 and raw["pages"] == doc["pages"]
    listing = client.get(BASE + "/list", headers=AUTH).json()["designs"]
    assert any(v["path"] == result["path"] for v in listing)
    loaded = client.get(BASE + "/load", headers=AUTH, params={"path": result["path"]})
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["schema"] == 2
    assert loaded.json()["pages"] == doc["pages"]
    assert loaded.json()["pages"][1]["spec"]["elements"][0]["locked"]
    assert client.get(BASE + "/load", headers=AUTH,
                      params={"path": "../outside.design.json"}).status_code == 403


def test_multi_slide_powerpoint_is_native_editable_and_retains_page_order(client):
    doc = body(3)
    saved = client.post(BASE + "/document/export", headers=AUTH, json={
        **doc, "format": "pptx", "output_mode": "layered",
    })
    assert saved.status_code == 200, saved.text
    data = saved.json()
    assert data["page_count"] == 3 and data["draft"]
    root = sandbox.default_root()
    prs = Presentation(root / data["path"])
    assert len(prs.slides) == 3
    for slide, i in zip(prs.slides, range(1, 4)):
        text = "\n".join(shape.text for shape in slide.shapes if shape.has_text_frame)
        assert f"Distinct editable content {i}" in text
        assert sum(shape.has_text_frame for shape in slide.shapes) >= 1
    reopened = client.get(BASE + "/load", headers=AUTH, params={"path": data["draft"]})
    assert reopened.status_code == 200 and reopened.json()["pages"] == doc["pages"]
    manifest = json.loads((root / data["manifest"]).read_text())
    assert manifest["scene_count"] == 3
    assert manifest["page_names"] == ["Slide 1", "Slide 2", "Slide 3"]
    assert manifest["editable_project"] == data["draft"]
    assert manifest["output_sha256"] == hashlib.sha256((root / data["path"]).read_bytes()).hexdigest()


def test_multi_page_pdf_contains_real_separate_pages_not_one_long_image(client):
    doc = body(4)
    r = client.post(BASE + "/document/export", headers=AUTH, json={
        **doc, "format": "pdf", "output_mode": "layered",
    })
    assert r.status_code == 200, r.text
    result = r.json()
    reader = PdfReader(sandbox.default_root() / result["path"])
    assert len(reader.pages) == 4
    assert all(float(p.mediabox.width) > 0 for p in reader.pages)
    reopened = client.get(BASE + "/load", headers=AUTH, params={"path": result["draft"]})
    assert reopened.status_code == 200
    assert reopened.json()["pages"] == doc["pages"]
    assert result["path"] != result["draft"]


def test_original_logo_pixels_and_layer_settings_are_never_changed(client):
    root = sandbox.default_root()
    img = root / "uploads" / "original-logo.png"
    img.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (80, 60), (23, 80, 162, 255)).save(img)
    before = hashlib.sha256(img.read_bytes()).hexdigest()
    document = body(2)
    document["pages"][0]["spec"]["elements"].append({
        "type": "image", "x": 330, "y": 300, "w": 135, "h": 90,
        "path": "uploads/original-logo.png", "alt": "Source logo", "locked": True,
    })
    original = copy.deepcopy(document)
    for fmt in ("pdf", "pptx"):
        r = client.post(BASE + "/document/export", headers=AUTH, json={
            **document, "format": fmt, "output_mode": "layered",
        })
        assert r.status_code == 200, r.text
        assert hashlib.sha256(img.read_bytes()).hexdigest() == before
        reopened = client.get(BASE + "/load", headers=AUTH, params={"path": r.json()["draft"]})
        assert reopened.json()["pages"] == document["pages"]
        manifest = json.loads((root / r.json()["manifest"]).read_text())
        assert any(entry["sha256"] == before for entry in manifest["original_assets"])
    assert document == original


def test_invalid_second_page_is_rejected_without_any_output(client):
    doc = body(2)
    doc["pages"][1]["spec"]["elements"][0]["colour"] = "#INVALID"
    root = sandbox.default_root() / "artifacts" / "visual-studio"
    before = set(root.iterdir()) if root.exists() else set()
    for action in ("save", "export"):
        r = client.post(BASE + f"/document/{action}", headers=AUTH, json=doc)
        assert r.status_code == 422
        assert "page 2" in r.text
    assert (set(root.iterdir()) if root.exists() else set()) == before


def test_document_rejects_over_limit_and_source_path_escape(client):
    too_many = body(21)
    assert client.post(BASE + "/document/save", headers=AUTH, json=too_many).status_code == 422
    invalid = body(2)
    invalid["pages"][1]["spec"]["elements"].append({
        "type": "image", "path": "../../outside.png", "x": 180, "y": 300,
        "w": 100, "h": 80,
    })
    r = client.post(BASE + "/document/export", headers=AUTH, json={
        **invalid, "format": "pptx",
    })
    assert r.status_code == 422
    assert "page 2" in r.text
    assert client.post(BASE + "/document/export", headers=AUTH, json={
        **body(), "format": "exe",
    }).status_code == 422


def test_legacy_single_canvas_drafts_still_load(client):
    original = page(1)["spec"]
    saved = client.post(BASE + "/save", headers=AUTH, json={
        "name": "Legacy design", "spec": original,
    })
    assert saved.status_code == 200, saved.text
    loaded = client.get(BASE + "/load", headers=AUTH,
                        params={"path": saved.json()["path"]})
    assert loaded.status_code == 200
    assert loaded.json()["schema"] == 1
    assert loaded.json()["spec"] == original
