"""Visual Studio v10: real keyframe transforms, preview, GIF and safety."""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageChops

from automoto import sandbox, server
from automoto.hosted import path_allowed
from automoto.visual_foundation import VisualError, compile_scene
from automoto.visual_motion import interpolate, motion_raster, validate_keyframes

H = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BASE = "/api/visual/studio"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def spec():
    return {
        "layout": "canvas", "artboard_only": True,
        "width": 800, "height": 500, "theme": "editorial-light",
        "title": "", "elements": [
            {"type": "rect", "x": 96, "y": 164, "w": 215, "h": 155,
             "group": "left", "fill": "#E8F3F1", "stroke": "#246D83"},
            {"type": "text", "x": 118, "y": 200, "w": 165, "h": 65,
             "group": "left", "text": "Original headline",
             "font_size": 23, "colour": "#172638"},
            {"type": "rect", "x": 470, "y": 164, "w": 215, "h": 155,
             "group": "right", "fill": "#E7ECFB", "stroke": "#526476"},
            {"type": "text", "x": 492, "y": 200, "w": 165, "h": 65,
             "group": "right", "text": "Unmodified words",
             "font_size": 23, "colour": "#172638"},
        ],
    }


def key(at, dx=0, dy=0, scale=1, opacity=1, rotation=0, easing="linear"):
    return {"at": at, "dx": dx, "dy": dy, "scale": scale,
            "opacity": opacity, "rotation": rotation, "easing": easing}


def motion():
    return {"effect": "keyframes", "frames": 12, "duration_ms": 100, "loop": 0,
            "tracks": [
                {"group": "left", "keyframes": [
                    key(0, dx=-68, dy=20, scale=.75, opacity=.1,
                        rotation=-12, easing="ease-in-out"),
                    key(.5, dx=-12, dy=4, scale=1.03, opacity=.9,
                        rotation=8, easing="ease-out"),
                    key(1),
                ]},
                {"group": "right", "keyframes": [
                    key(0, dx=50, dy=-24, scale=.9, opacity=.15),
                    key(1, dx=0, dy=0, scale=1, opacity=1),
                ]},
            ]}


def image_response(response):
    assert response.status_code == 200, response.text
    return Image.open(io.BytesIO(base64.b64decode(response.json()["image"].split(",", 1)[1]))).convert("RGB")


def test_auth_and_hosted_route_rules(client):
    assert client.post(BASE + "/animation-preview", json={"spec": spec()}).status_code == 403
    assert path_allowed("POST", BASE + "/animation-preview")
    assert not path_allowed("GET", BASE + "/animation-preview")


def test_interpolation_and_easing_exact_endpoints():
    track = motion()["tracks"][0]["keyframes"]
    assert interpolate(track, 0)["dx"] == -68
    assert interpolate(track, 1)["dx"] == 0
    assert interpolate(track, .5)["dx"] == -12
    assert interpolate(track, .25)["dx"] < -40
    assert interpolate(track, .75)["opacity"] > .9


def test_real_motion_preview_differs_across_scrub(client):
    s, animation = spec(), motion()
    original = copy.deepcopy(s)
    start = client.post(BASE + "/preview", headers=H,
                        json={"spec": s, "frame": .05, "animation": animation})
    end = client.post(BASE + "/preview", headers=H,
                      json={"spec": s, "frame": .95, "animation": animation})
    first, last = image_response(start), image_response(end)
    assert first.size == last.size == (800, 500)
    assert ImageChops.difference(first, last).getbbox() is not None
    assert s == original
    # Static export still renders the original untransformed native scene.
    static = image_response(client.post(BASE + "/preview", headers=H, json={"spec": s}))
    assert ImageChops.difference(first, static).getbbox() is not None


def test_playback_is_real_gif_and_never_creates_a_file(client):
    root = sandbox.default_root()
    before = set(root.rglob("*")) if root.exists() else set()
    r = client.post(BASE + "/animation-preview", headers=H,
                    json={"spec": spec(), "animation": motion()})
    assert r.status_code == 200, r.text
    content = base64.b64decode(r.json()["image"].split(",", 1)[1])
    assert r.json()["frames"] == 12
    with Image.open(io.BytesIO(content)) as gif:
        assert gif.format == "GIF" and gif.n_frames >= 8
        gif.seek(0)
        a = gif.convert("RGB")
        gif.seek(gif.n_frames - 1)
        b = gif.convert("RGB")
        assert ImageChops.difference(a, b).getbbox() is not None
    after = set(root.rglob("*")) if root.exists() else set()
    assert before == after


def test_keyframe_gif_export_has_actual_motion_and_editable_source(client):
    s, animation = spec(), motion()
    r = client.post(BASE + "/export", headers=H,
                    json={"spec": s, "name": "Motion test", "format": "gif",
                          "output_mode": "layered", "animation": animation})
    assert r.status_code == 200, r.text
    data = r.json()
    root = sandbox.default_root()
    with Image.open(root / data["path"]) as gif:
        assert gif.n_frames >= 8
        gif.seek(0)
        start = gif.convert("RGB")
        gif.seek(gif.n_frames - 1)
        end = gif.convert("RGB")
        assert ImageChops.difference(start, end).getbbox() is not None
    draft_path = data.get("draft") or data.get("editable_project")
    assert draft_path, data
    opened = client.get(BASE + "/load", headers=H,
                        params={"path": draft_path})
    assert opened.status_code == 200, opened.text
    saved = opened.json()["spec"]
    assert saved["elements"] == s["elements"]
    assert saved["animation"] == animation


@pytest.mark.parametrize("mutation", [
    lambda m: m["tracks"][0]["keyframes"][1].update({"dx": 500}),
    lambda m: m["tracks"][0]["keyframes"][0].update({"rotation": -90}),
    lambda m: m["tracks"][0]["keyframes"][0].update({"scale": 0}),
    lambda m: m["tracks"][0]["keyframes"][0].update({"opacity": 2}),
    lambda m: m["tracks"][0]["keyframes"][0].update({"easing": "__import__('os')"}),
    lambda m: m["tracks"][0]["keyframes"][0].update({"at": .2}),
    lambda m: m["tracks"][0]["keyframes"][1].update({"at": 0}),
    lambda m: m["tracks"][0].update({"group": "not-there"}),
    lambda m: m["tracks"].append(copy.deepcopy(m["tracks"][0])),
    lambda m: m["tracks"][0]["keyframes"][0].update({"evil": "open(file)"}),
    lambda m: m.update({"evil": "unsafe extension"}),
    lambda m: m["tracks"][0]["keyframes"][1].update({"dx": True}),
])
def test_rejects_untrusted_motion_inputs(client, mutation):
    s, animation = spec(), motion()
    mutation(animation)
    with pytest.raises(VisualError):
        validate_keyframes(compile_scene(s), animation)
    for endpoint in ("preview", "animation-preview"):
        payload = {"spec": s, "animation": animation}
        if endpoint == "preview":
            payload["frame"] = .25
        r = client.post(BASE + "/" + endpoint, headers=H, json=payload)
        assert r.status_code == 422, (endpoint, r.text)


def test_source_image_hash_not_modified_by_motion(client):
    root = sandbox.default_root()
    path = root / "uploads" / "original-photo.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (80, 50), (33, 97, 186, 255)).save(path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    s = spec()
    s["elements"].append({"type": "image", "path": "uploads/original-photo.png",
                          "alt": "Original asset", "x": 500, "y": 320,
                          "w": 96, "h": 64, "group": "right"})
    r = client.post(BASE + "/animation-preview", headers=H,
                    json={"spec": s, "animation": motion()})
    assert r.status_code == 200, r.text
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    scene = compile_scene(s)
    validate_keyframes(scene, motion())
    assert scene["assets"], "source provenance remains embedded in original scene"


def test_motion_tracks_do_not_modify_compiled_scene():
    scene = compile_scene(spec())
    copy_scene = copy.deepcopy(scene)
    image = motion_raster(scene, .65, motion())
    assert image.size == (800, 500)
    assert scene == copy_scene
