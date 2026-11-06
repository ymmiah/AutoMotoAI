"""Visual Repair: bounded, reversible changes, no source-image or copy mutations."""
from __future__ import annotations

from copy import deepcopy
import hashlib

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from automoto import sandbox, server
from automoto.visual_repair import inspect, repair

AUTH={"X-AutoMoto-Token":server.SESSION_TOKEN}


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME",str(tmp_path/"home"))
    monkeypatch.delenv("AUTOMOTO_MODE",raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT","10000")
    root=sandbox.default_root()
    root.mkdir(parents=True,exist_ok=True)
    return root


def art(*elements):
    return {
        "layout":"canvas", "theme":"editorial-light","artboard_only":True,
        "width":800,"height":500,"title":"","subtitle":"",
        "elements":[{"type":"rect","x":0,"y":0,"w":800,"h":500,
                     "fill":"#FFFFFF","radius":0}, *elements],
    }


def text_obj(x=90,y=130,colour="#172638",wording="Precise editable text",
             size=24,w=350,h=80,locked=False):
    return {"type":"text","x":x,"y":y,"w":w,"h":h,"text":wording,
            "font_size":size,"bold":True,"colour":colour,"locked":locked}


def test_inspect_is_read_only_and_repairs_contrast(workspace):
    original=art(text_obj(colour="#FFFFFF"))
    snapshot=deepcopy(original)
    findings=inspect(original)
    assert any(i["code"]=="contrast" for i in findings["issues"])
    result=repair(original)
    assert original==snapshot
    assert result["changed"]
    assert any(c["field"]=="colour" for c in result["changes"])
    assert result["spec"]["elements"][1]["colour"]!=" #FFFFFF"
    assert result["after"]["passed"], result["after"]
    assert result["spec"]["elements"][1]["text"]==original["elements"][1]["text"]


def test_long_exact_text_is_shrunk_but_not_reworded(workspace):
    original=art(text_obj(wording="A measured visual headline",
                          size=48,w=315,h=53))
    assert any(i["code"]=="text-fit" for i in inspect(original)["issues"])
    result=repair(original)
    assert result["spec"]["elements"][1]["text"]==original["elements"][1]["text"]
    assert result["spec"]["elements"][1]["font_size"]<48
    assert all(i["code"]!="text-fit" for i in result["after"]["issues"])


def test_two_independent_text_layers_are_unoverlapped(workspace):
    source=art(text_obj(x=85,y=180,w=185,h=60,wording="First label"),
               text_obj(x=120,y=190,w=185,h=60,wording="Second label"))
    assert any(i["code"]=="collision" for i in inspect(source)["issues"])
    result=repair(source)
    assert not any(i["code"]=="collision" for i in result["after"]["issues"])
    for original,repaired in zip(source["elements"][1:],result["spec"]["elements"][1:]):
        assert original["text"]==repaired["text"]


def test_locked_bad_contrast_is_reported_but_not_modified(workspace):
    source=art(text_obj(colour="#FFFFFF",locked=True))
    result=repair(source)
    assert not result["changed"]
    assert result["spec"]==source
    assert not result["after"]["passed"]


def test_independent_original_photo_remains_unmodified(workspace):
    photo=workspace/"uploads"/"reference.png"
    photo.parent.mkdir(parents=True)
    Image.new("RGB",(420,230),(55,113,188)).save(photo)
    h=hashlib.sha256(photo.read_bytes()).hexdigest()
    source=art({"type":"image","x":420,"y":100,"w":320,"h":220,
                "path":"uploads/reference.png","alt":"Original reference"},
               text_obj(x=50,y=140,colour="#FFFFFF",w=260))
    result=repair(source)
    assert result["changed"]
    assert result["spec"]["elements"][1]==source["elements"][1]
    assert hashlib.sha256(photo.read_bytes()).hexdigest()==h


def test_outside_canvas_moved_without_resize(workspace):
    source=art(text_obj(x=760,y=450,w=180,h=48,wording="Move inside"))
    assert not inspect(source)["passed"]
    result=repair(source)
    fixed=result["spec"]["elements"][1]
    assert fixed["x"]==620 and fixed["y"]==450
    assert fixed["w"]==180 and fixed["text"]=="Move inside"
    assert result["after"]["passed"],result["after"]


def test_unsupported_canvas_and_non_repairable_image_are_not_falsely_fixed(workspace):
    with pytest.raises(ValueError,match="individual editable canvases"):
        repair({"layout":"workflow","nodes":[]})
    source=art({"type":"image","x":0,"y":0,"w":900,"h":480,
                "path":"uploads/not-found.png"})
    result=repair(source)
    assert not result["changed"]
    assert not result["after"]["passed"]


def test_authenticated_api_proposals_have_no_side_effects(workspace):
    source=art(text_obj(colour="#FFFFFF"))
    with TestClient(server.app) as client:
        for route in ("inspect","repair"):
            r=client.post("/api/visual/studio/"+route,json={"spec":source})
            assert r.status_code==403
        before=set(workspace.rglob("*"))
        report=client.post("/api/visual/studio/inspect",headers=AUTH,json={"spec":source})
        proposal=client.post("/api/visual/studio/repair",headers=AUTH,json={"spec":source})
        assert report.status_code==200,report.text
        assert proposal.status_code==200,proposal.text
        assert report.json()["issue_count"]>=1
        assert proposal.json()["changed"]
        assert proposal.json()["after"]["passed"]
        assert set(workspace.rglob("*"))==before


def test_bad_input_is_rejected_and_preserves_editor(workspace):
    with TestClient(server.app) as client:
        r=client.post("/api/visual/studio/repair",headers=AUTH,json={
            "spec":{"layout":"workflow","nodes":[]}})
        assert r.status_code==422,r.text
        malformed=art(text_obj())
        malformed["elements"].append({"type":"image","x":5,"y":5,
           "w":100,"h":70,"path":"../../etc/passwd"})
        r=client.post("/api/visual/studio/repair",headers=AUTH,json={"spec":malformed})
        assert r.status_code==422,r.text
