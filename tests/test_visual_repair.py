"""Visual Studio repair proposals: safe changes, approval boundary and integrity."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from automoto import sandbox, server
from automoto.visual_repair import propose
from automoto.visual_foundation import compile_scene,VisualError
from automoto.visual_renderer import quality
from automoto.hosted import path_allowed

AUTH={"X-AutoMoto-Token":server.SESSION_TOKEN}

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME",str(tmp_path/"home"))
    monkeypatch.delenv("AUTOMOTO_MODE",raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT","10000")
    with TestClient(server.app) as app:
        yield app

def artboard():
    return {"width":800,"height":500,"theme":"editorial-light",
        "layout":"canvas","artboard_only":True,"title":"","subtitle":"",
        "elements":[
          {"type":"text","x":80,"y":90,"w":270,"h":70,
           "text":"Source evidence","font_size":29,"colour":"#172638","bold":True},
          {"type":"text","x":120,"y":105,"w":270,"h":70,
           "text":"Verified results","font_size":28,"colour":"#172638","bold":True}
        ]
    }

def test_collision_repair_never_mutates_input_and_passes_quality():
    spec=artboard()
    original=copy.deepcopy(spec)
    assert any("unintended overlap" in msg for msg in quality(compile_scene(spec)))
    r=propose(spec)
    assert spec==original
    assert r["changed"] and r["ready_to_apply"] and not r["remaining_issues"]
    assert r["proposed_spec"]["elements"][0]["text"]=="Source evidence"
    assert r["proposed_spec"]["elements"][1]["text"]=="Verified results"
    assert any(c["field"] in ("x","y") for c in r["changes"])
    assert quality(compile_scene(r["proposed_spec"]))==[]

def test_repair_api_returns_actual_preview_without_saving_or_mutating(client):
    path=sandbox.default_root()
    original=artboard()
    before=list(path.rglob("*.design.json")) if path.exists() else []
    response=client.post("/api/visual/studio/repair",headers=AUTH,json={
        "spec":original,"name":"Unapproved"})
    assert response.status_code==200,response.text
    report=response.json()
    assert report["requires_approval"] and report["ready_to_apply"]
    assert report["preview"].startswith("data:image/png;base64,")
    # The original remains invalid, until an explicit client-side Apply.
    assert client.post("/api/visual/studio/preview",headers=AUTH,json={"spec":original}).status_code==422
    validated=client.post("/api/visual/studio/preview",headers=AUTH,json={
        "spec":report["proposed_spec"]})
    assert validated.status_code==200,validated.text
    after=list(path.rglob("*.design.json")) if path.exists() else []
    assert before==after

def test_low_contrast_fix_only_changes_text_colour():
    spec={"width":800,"height":500,"layout":"canvas","artboard_only":True,
        "theme":"premium-tech","title":"","subtitle":"","elements":[
          {"type":"text","x":80,"y":80,"w":620,"h":80,"text":"Keep exact text",
           "font_size":32,"bold":True,"colour":"#0D1729"}
        ]}
    r=propose(spec)
    assert r["ready_to_apply"],r
    after=r["proposed_spec"]["elements"][0]
    assert after["text"]=="Keep exact text"
    assert after["colour"]=="#FFFFFF"
    assert "colour" in [e["field"] for e in r["changes"]]
    assert quality(compile_scene(r["proposed_spec"]))==[]

def test_locked_group_and_photo_remain_identical(client):
    root=sandbox.default_root()
    p=root/"uploads"/"original.png"
    p.parent.mkdir(parents=True,exist_ok=True)
    Image.new("RGB",(400,250),(23,80,162)).save(p)
    digest=hashlib.sha256(p.read_bytes()).hexdigest()
    spec={"width":800,"height":500,"layout":"canvas","artboard_only":True,
          "theme":"editorial-light","title":"","subtitle":"","elements":[
          {"type":"image","x":40,"y":40,"w":260,"h":180,"path":"uploads/original.png",
           "alt":"Original photo","group":"original-photo"},
          {"type":"text","x":40,"y":45,"w":240,"h":80,"text":"Do not move",
           "font_size":28,"colour":"#172638","locked":True,"group":"protected-title"},
          {"type":"text","x":370,"y":100,"w":360,"h":80,"text":"Adjustable label",
           "font_size":28,"colour":"#172638"}
          ]}
    original=copy.deepcopy(spec)
    result=client.post("/api/visual/studio/repair",headers=AUTH,json={"spec":spec})
    assert result.status_code==200,result.text
    candidate=result.json()["proposed_spec"]
    assert candidate["elements"][0]==original["elements"][0]
    assert candidate["elements"][1]==original["elements"][1]
    assert candidate["elements"][2]["text"]=="Adjustable label"
    assert hashlib.sha256(p.read_bytes()).hexdigest()==digest

def test_explicit_allowed_overlap_is_not_moved():
    spec=artboard()
    spec["elements"][1]["allow_overlap"]=True
    result=propose(spec)
    assert not result["changed"]
    assert result["proposed_spec"]==spec

def test_unrepairable_text_returns_manual_review_not_false_success():
    spec={"width":800,"height":500,"layout":"canvas","artboard_only":True,
          "title":"","subtitle":"","elements":[
             {"type":"text","x":40,"y":40,"w":120,"h":22,
              "font_size":56,"text":"UnbreakableSuperlongWordThatCannotFit",
              "colour":"#172638"}
          ]}
    r=propose(spec)
    assert not r["ready_to_apply"]
    assert r["remaining_issues"]
    assert r["proposed_spec"]["elements"][0]["text"]==spec["elements"][0]["text"]

def test_canvas_boundary_is_repaired_only_for_unlocked_objects():
    spec={"width":800,"height":500,"layout":"canvas","artboard_only":True,
          "title":"","subtitle":"","elements":[
             {"type":"rect","x":790,"y":460,"w":150,"h":110,"fill":"#FFFFFF"},
             {"type":"rect","x":785,"y":450,"w":150,"h":110,"fill":"#FFFFFF","locked":True}
          ]}
    proposed=propose(spec)
    assert proposed["proposed_spec"]["elements"][0]["x"]==650
    assert proposed["proposed_spec"]["elements"][0]["y"]==390
    assert proposed["proposed_spec"]["elements"][1]==spec["elements"][1]
    assert not proposed["ready_to_apply"] # locked object still needs manual repositioning

def test_repair_requires_auth_and_is_hosted_allowlisted(client):
    assert client.post("/api/visual/studio/repair",json={"spec":artboard()}).status_code==403
    assert path_allowed("POST","/api/visual/studio/repair")
    assert not path_allowed("DELETE","/api/visual/studio/repair")

def test_repair_rejects_untrusted_external_paths(client):
    spec=artboard()
    spec["elements"].append({"type":"image","x":10,"y":200,"w":100,"h":80,
                             "path":"../../etc/passwd"})
    r=client.post("/api/visual/studio/repair",headers=AUTH,json={"spec":spec})
    assert r.status_code==422

def test_non_canvas_repair_disallowed():
    with pytest.raises(VisualError,match="canvas"):
        propose({"layout":"hero","image":"unknown.png","title":"Sample"})
