"""Visual Studio v9: private brand library, consent and asset-preserving styling."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from automoto import sandbox, server
from automoto.hosted import path_allowed

TOKEN = {"X-AutoMoto-Token": server.SESSION_TOKEN}
ROOT = "/api/visual/studio/brand-kits"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def palette():
    return {"background": "#F8F9F7", "ink": "#172638", "muted": "#526476",
            "accent": "#246D83", "card": "#FFFFFF", "border": "#DCE5E9",
            "tone0": "#E8F3F1", "tone1": "#E7ECFB", "tone2": "#FFF0CF"}


def kit():
    return {"name": "  Brand identity A  ", "colours": palette(),
            "heading_size": 32, "body_size": 18, "logo": None}


def page():
    return {"name": "Brand introduction", "spec": {
        "layout": "canvas", "artboard_only": True,
        "width": 800, "height": 500, "theme": "editorial-light",
        "title": "", "elements": [{
            "type": "text", "x": 80, "y": 135, "w": 350, "h": 85,
            "text": "Original wording", "font_size": 30, "colour": "#172638",
            "style_role": "heading", "auto_colour": "ink",
        }],
    }}


def test_all_endpoints_require_auth_and_explicit_hosted_permissions(client):
    for path in ("save", "validate"):
        assert client.post(f"{ROOT}/{path}", json=kit()).status_code == 403
        assert path_allowed("POST", f"{ROOT}/{path}")
    assert client.post(f"{ROOT}/delete", json={"path": "test.brand.json"}).status_code == 403
    assert path_allowed("POST", f"{ROOT}/delete")
    for path in ("list", "load"):
        assert client.get(f"{ROOT}/{path}").status_code == 403
        assert path_allowed("GET", f"{ROOT}/{path}")
    assert not path_allowed("DELETE", f"{ROOT}/delete")


def test_save_list_load_delete_are_private_and_do_not_change_design(client):
    original = kit()
    original_copy = copy.deepcopy(original)
    saved = client.post(f"{ROOT}/save", headers=TOKEN, json=original)
    assert saved.status_code == 200, saved.text
    data = saved.json()
    assert data["kit"]["name"] == "Brand identity A"
    assert data["kit"]["colours"]["ink"] == "#172638"
    assert data["kit"]["heading_size"] == 32
    assert original == original_copy
    path = data["path"]
    assert path.startswith("artifacts/visual-studio/brand-kits/")
    assert path.endswith(".brand.json")
    files = client.get(f"{ROOT}/list", headers=TOKEN).json()["kits"]
    assert len(files) == 1 and files[0]["path"] == path
    load = client.get(f"{ROOT}/load", headers=TOKEN, params={"path": path})
    assert load.status_code == 200 and load.json()["kit"] == data["kit"]
    denied = client.get(f"{ROOT}/load", headers=TOKEN,
                        params={"path": "artifacts/visual-studio/elsewhere.design.json"})
    assert denied.status_code == 403
    deletion = client.post(f"{ROOT}/delete", headers=TOKEN, json={"path": path})
    assert deletion.status_code == 200
    assert client.get(f"{ROOT}/list", headers=TOKEN).json()["kits"] == []
    assert client.get(f"{ROOT}/load", headers=TOKEN, params={"path": path}).status_code == 404


def test_brand_validation_rejects_unsafe_colours_and_tampering(client):
    valid = client.post(f"{ROOT}/validate", headers=TOKEN, json=kit())
    assert valid.status_code == 200
    assert valid.json()["kit"]["name"] == "Brand identity A"
    bad = kit()
    bad["colours"]["accent"] = "javascript:alert(1)"
    assert client.post(f"{ROOT}/save", headers=TOKEN, json=bad).status_code == 422
    bad = kit()
    bad["colours"]["ink"] = "#FAFAFA"
    response = client.post(f"{ROOT}/validate", headers=TOKEN, json=bad)
    assert response.status_code == 422 and "contrast" in response.text
    bad = kit()
    bad["colours"]["unknown"] = "#FF00FF"
    assert client.post(f"{ROOT}/validate", headers=TOKEN, json=bad).status_code == 422
    bad = kit()
    bad["heading_size"] = 150
    assert client.post(f"{ROOT}/validate", headers=TOKEN, json=bad).status_code == 422
    folder = sandbox.default_root() / "artifacts" / "visual-studio" / "brand-kits"
    assert not folder.exists(), "invalid kit validation must not create private storage"


def test_user_uploaded_logo_is_original_and_never_copied_or_modified(client):
    root = sandbox.default_root()
    logo = root / "uploads" / "original-brand.png"
    logo.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (120, 80), (31, 98, 145, 255)).save(logo)
    digest = hashlib.sha256(logo.read_bytes()).hexdigest()
    data = kit()
    data["logo"] = "uploads/original-brand.png"
    saved = client.post(f"{ROOT}/save", headers=TOKEN, json=data)
    assert saved.status_code == 200, saved.text
    assert saved.json()["kit"]["logo"] == data["logo"]
    assert hashlib.sha256(logo.read_bytes()).hexdigest() == digest
    loaded = client.get(f"{ROOT}/load", headers=TOKEN, params={"path": saved.json()["path"]})
    assert loaded.status_code == 200
    assert hashlib.sha256(logo.read_bytes()).hexdigest() == digest


def test_logo_outside_uploads_and_non_images_are_blocked(client):
    root = sandbox.default_root()
    external = root / "artifacts" / "visual-studio" / "secret.png"
    external.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 40)).save(external)
    for path in ("../outside.png", "/etc/passwd",
                 "artifacts/visual-studio/secret.png", "uploads/missing.png"):
        data = kit()
        data["logo"] = path
        assert client.post(f"{ROOT}/validate", headers=TOKEN, json=data).status_code == 422
    fake = root / "uploads" / "not-a-logo.png"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text("not an image")
    data = kit()
    data["logo"] = "uploads/not-a-logo.png"
    assert client.post(f"{ROOT}/validate", headers=TOKEN, json=data).status_code == 422


def test_whole_document_validation_is_read_only_and_keeps_page_limits(client):
    url = "/api/visual/studio/document/validate"
    original = [page(), page()]
    before = copy.deepcopy(original)
    root = sandbox.default_root()
    saved_before = list(root.rglob("*.design.json")) if root.exists() else []
    assert client.post(url, json={"pages": original, "name": "Review"}).status_code == 403
    ok = client.post(url, headers=TOKEN, json={"pages": original, "name": "Review"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["page_count"] == 2
    assert before == original
    assert (list(root.rglob("*.design.json")) if root.exists() else []) == saved_before
    broken = copy.deepcopy(original)
    broken[1]["spec"]["elements"][0]["colour"] = "#NOPE"
    failed = client.post(url, headers=TOKEN, json={"pages": broken, "name": "Review"})
    assert failed.status_code == 422 and "page 2" in failed.text
    assert not (root / "artifacts" / "visual-studio" / "brand-kits").exists()
