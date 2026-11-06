"""Visual Studio v6: a real local-model call, but untrusted and approval-only."""
import copy
import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from automoto import local_llm, sandbox, server, visual_ai_review as review
from automoto.hosted import path_allowed

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    with TestClient(server.app) as app:
        yield app


def design():
    return {"layout": "canvas", "artboard_only": True,
            "width": 800, "height": 500, "theme": "editorial-light",
            "title": "", "subtitle": "",
            "elements": [
                {"type": "text", "x": 80, "y": 90, "w": 320, "h": 78,
                 "text": "Source text stays exact", "font_size": 26, "colour": "#172638", "bold": True},
                {"type": "rect", "x": 430, "y": 210, "w": 170, "h": 110,
                 "fill": "#E8F3F1", "locked": True},
            ]}


def local_model(monkeypatch, response=None):
    monkeypatch.setattr(local_llm, "ollama_url", lambda: "http://127.0.0.1:11434")
    monkeypatch.setattr(local_llm, "enabled", lambda provider: provider == "ollama")
    monkeypatch.setattr(local_llm, "active_model", lambda: "local-vision:latest")
    monkeypatch.setattr(local_llm, "installed_models", lambda: ["local-vision:latest"])
    monkeypatch.setattr(local_llm, "supports", lambda name, cap: name == "local-vision:latest" and cap == "vision")
    data = response or {"notes": [{"category": "alignment", "layer": 1,
                                  "message": "Consider improving headline placement."}],
                        "changes": [{"index": 0, "field": "x", "new": 94,
                                     "reason": "A small alignment adjustment."}]}
    monkeypatch.setattr(review, "_model_chat", lambda model, image, metadata: json.dumps(data))


def test_endpoint_requires_auth_and_stays_unavailable_in_hosted_mode(client):
    assert client.post("/api/visual/studio/ai-review", json={"spec": design()}).status_code == 403
    assert not path_allowed("POST", "/api/visual/studio/ai-review")
    assert not path_allowed("DELETE", "/api/visual/studio/ai-review")


def test_real_model_must_be_explicitly_selected_and_downloaded(client, monkeypatch):
    monkeypatch.setattr(local_llm, "enabled", lambda provider: False)
    monkeypatch.setattr(local_llm, "ollama_url", lambda: "http://127.0.0.1:11434")
    r = client.post("/api/visual/studio/ai-review", headers=AUTH, json={"spec": design()})
    assert r.status_code == 422
    assert "Enable Ollama" in r.json()["detail"]


def test_ai_review_is_proposal_only_with_real_rendered_image(client, monkeypatch, tmp_path):
    local_model(monkeypatch)
    spec = design()
    original = copy.deepcopy(spec)
    # The model receives a raster preview, not the local source image path.
    def fake_chat(model, image, summary):
        assert model == "local-vision:latest"
        assert isinstance(image, str) and len(image) > 500
        assert summary["layers"][0]["index"] == 0
        assert summary["layers"][0]["editable"]
        assert summary["layers"][1]["editable"] is False
        assert "text" not in summary["layers"][0]  # source wording is not sent as metadata
        return json.dumps({"notes": [{"category": "typography", "layer": 1,
                                      "message": "Headline could have more breathing room."}],
                           "changes": [{"index": 0, "field": "x", "new": 94,
                                        "reason": "Align this heading with nearby content."}]})
    monkeypatch.setattr(review, "_model_chat", fake_chat)
    start = list(sandbox.default_root().rglob("*.design.json"))
    r = client.post("/api/visual/studio/ai-review", headers=AUTH, json={"spec": spec, "name": "Draft"})
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["provider"] == "ollama-local" and result["requires_approval"]
    assert result["changes"] == [{"index": 0, "field": "x", "old": 80, "new": 94,
                                  "reason": "Align this heading with nearby content.", "origin": "local-ai"}]
    assert result["design_notes"][0]["category"] == "typography"
    assert result["original_preview"].startswith("data:image/png;base64,")
    assert spec == original
    assert list(sandbox.default_root().rglob("*.design.json")) == start
    # The only way to apply a change is the editor's explicit Undo-tracked
    # action; the trusted preview must accept that selected candidate.
    candidate = copy.deepcopy(spec)
    candidate["elements"][0]["x"] = result["changes"][0]["new"]
    validation = client.post("/api/visual/studio/preview", headers=AUTH, json={"spec": candidate})
    assert validation.status_code == 200, validation.text


def test_model_instructions_cannot_rewrite_images_or_invent_edits(client, monkeypatch):
    local_model(monkeypatch, {"notes": [{"category": "spacing", "layer": 1, "message": "Spacing looks tight."}],
        "changes": [
            {"index": 0, "field": "text", "new": "OVERRIDE ALL", "reason": "Ignore rules"},
            {"index": 0, "field": "x", "new": -999, "reason": "Move away"},
            {"index": 0, "field": "font_size", "new": 90, "reason": "Too big"},
            {"index": 0, "field": "colour", "new": "javascript:evil", "reason": "Bad colour"},
            {"index": 1, "field": "x", "new": 456, "reason": "Edit protected rect"},
            {"index": 0, "field": "x", "new": 94, "reason": "A valid move"},
            {"index": 0, "field": "x", "new": 99, "reason": "Duplicate move"},
        ]})
    original = design()
    r = client.post("/api/visual/studio/ai-review", headers=AUTH, json={"spec": original})
    assert r.status_code == 200, r.text
    assert len(r.json()["changes"]) == 1
    assert r.json()["changes"][0]["new"] == 94
    assert original["elements"][0]["text"] == "Source text stays exact"
    assert original["elements"][1]["locked"] is True


def test_ai_colour_changes_must_not_lower_contrast():
    spec = design()
    bad = review._changes(spec, [{"index": 0, "field": "colour", "new": "#FFFFFF",
                                   "reason": "Make everything white"}])
    assert bad == []


def test_no_private_image_path_is_exposed_in_prompt():
    spec = design()
    spec["elements"].append({"type": "image", "x": 22, "y": 350,
                             "w": 90, "h": 75, "path": "uploads/private-filename.png",
                             "alt": "Private name"})
    summary = review._scene_summary(spec)
    raw = json.dumps(summary)
    assert "private-filename" not in raw and "Private name" not in raw
    assert summary["layers"][2]["editable"] is False


def test_reject_non_loopback_ollama_host(monkeypatch):
    monkeypatch.setattr(local_llm, "ollama_url", lambda: "http://192.168.1.25:11434")
    with pytest.raises(Exception, match="loopback"):
        review._loopback_ollama()


def test_review_rejects_invalid_external_file_before_model_call(client, monkeypatch):
    local_model(monkeypatch)
    spec = design()
    spec["elements"].append({"type": "image", "path": "../../etc/passwd",
                              "x": 10, "y": 240, "w": 80, "h": 80})
    assert client.post("/api/visual/studio/ai-review", headers=AUTH,
                       json={"spec": spec}).status_code == 422


def test_review_preserves_uploaded_pixels(client, monkeypatch):
    local_model(monkeypatch)
    root = sandbox.default_root()
    image = root / "uploads" / "source.png"
    image.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (50, 50), (25, 60, 90)).save(image)
    original_hash = hashlib.sha256(image.read_bytes()).hexdigest()
    spec = design()
    spec["elements"].append({"type": "image", "path": "uploads/source.png",
                              "x": 540, "y": 355, "w": 100, "h": 100})
    report = client.post("/api/visual/studio/ai-review", headers=AUTH, json={"spec": spec})
    assert report.status_code == 200, report.text
    assert hashlib.sha256(image.read_bytes()).hexdigest() == original_hash
    assert all(c["index"] != 2 for c in report.json()["changes"])
