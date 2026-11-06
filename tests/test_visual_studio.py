"""Visual Studio editor API: authenticated previews, private workspaces and real exports."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageChops

from automoto import sandbox, server
from automoto.hosted import path_allowed

H={"X-AutoMoto-Token":server.SESSION_TOKEN}

@pytest.fixture()
def client(tmp_path,monkeypatch):
    # The request's workspace stays inside a temporary AutoMoto home.
    monkeypatch.setenv("AUTOMOTO_HOME",str(tmp_path/"home"))
    monkeypatch.delenv("AUTOMOTO_MODE",raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT","10000")
    return TestClient(server.app)

def spec():
    return {
        "width":800,"height":500,"theme":"illustrated-workflow",
        "layout":"canvas","title":"Visual Studio test",
        "subtitle":"Real editable scene",
        "elements":[
            {"type":"line","x1":290,"y1":350,"x2":510,"y2":350,"colour":"#25252D","stroke_width":3},
            {"type":"rect","x":80,"y":270,"w":210,"h":160,"fill":"#FFFFFF","stroke":"#25252D"},
            {"type":"text","x":98,"y":314,"w":165,"h":70,"text":"Receive","font_size":28,"colour":"#22252C","bold":True},
            {"type":"rect","x":510,"y":270,"w":210,"h":160,"fill":"#FFFFFF","stroke":"#25252D"},
            {"type":"text","x":529,"y":314,"w":165,"h":70,"text":"Verify","font_size":28,"colour":"#22252C","bold":True},
        ]
    }


def test_editor_requires_auth(client):
    for path in ("/api/visual/studio/presets","/api/visual/studio/list"):
        assert client.get(path).status_code==403
    for path in ("/api/visual/studio/preview","/api/visual/studio/save","/api/visual/studio/export"):
        assert client.post(path,json={"spec":spec()}).status_code==403


def test_preview_matches_png_renderer_without_writing_files(client):
    root=sandbox.default_root()
    before=set(root.rglob("*")) if root.exists() else set()
    r=client.post("/api/visual/studio/preview",headers=H,json={"spec":spec(),"name":"Demo"})
    assert r.status_code==200,r.text
    data=r.json()
    assert data["width"]==800 and data["height"]==500
    assert data["image"].startswith("data:image/png;base64,")
    png=base64.b64decode(data["image"].split(",",1)[1])
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert "structural checks" in data["quality"]
    after=set(root.rglob("*")) if root.exists() else set()
    assert before==after


def test_draft_save_list_load_and_no_cross_directory(client):
    s=spec()
    url="/api/visual/studio"
    saved=client.post(url+"/save",headers=H,json={"spec":s,"name":"Invoice / Workflow"} )
    assert saved.status_code==200,saved.text
    path=saved.json()["path"]
    assert path.startswith("artifacts/visual-studio/") and path.endswith(".design.json")
    entries=client.get(url+"/list",headers=H).json()["designs"]
    assert any(e["path"]==path for e in entries)
    loaded=client.get(url+"/load",headers=H,params={"path":path})
    assert loaded.status_code==200 and loaded.json()["spec"]==s
    assert client.get(url+"/load",headers=H,params={"path":"../outside.design.json"}).status_code==403
    assert client.get(url+"/load",headers=H,params={"path":"uploads/missing.design.json"}).status_code==403


def test_real_gif_export_preserves_editable_draft_and_provenance(client):
    url="/api/visual/studio"
    data={"spec":spec(),"name":"Animation prototype","format":"gif",
          "animation":{"effect":"flow","frames":12,"duration_ms":100,"loop":0}}
    resp=client.post(url+"/export",headers=H,json=data)
    assert resp.status_code==200,resp.text
    result=resp.json()
    output=sandbox.default_root()/result["path"]
    assert output.is_file()
    with Image.open(output) as im:
        assert im.format=="GIF" and im.n_frames>=8 and im.info["loop"]==0
        im.seek(0);a=im.convert("RGB")
        im.seek(im.n_frames//2);b=im.convert("RGB")
        assert ImageChops.difference(a,b).getbbox() is not None
    manifest=json.loads((sandbox.default_root()/result["manifest"]).read_text())
    assert manifest["output_sha256"]==hashlib.sha256(output.read_bytes()).hexdigest()
    reopened=client.get(url+"/load",headers=H,params={"path":result["draft"]})
    assert reopened.status_code==200 and reopened.json()["spec"]==data["spec"]


def test_editable_powerpoint_export(client):
    r=client.post("/api/visual/studio/export",headers=H,json={
        "spec":spec(),"name":"Editable deck","format":"pptx"})
    assert r.status_code==200,r.text
    from pptx import Presentation
    p=sandbox.default_root()/r.json()["path"]
    presentation=Presentation(p)
    assert len(presentation.slides)==1
    assert sum(1 for s in presentation.slides[0].shapes if s.has_text_frame)>2


def test_original_asset_remains_unchanged_and_no_external_reads(client):
    root=sandbox.default_root()
    folder=root/"uploads";folder.mkdir(parents=True,exist_ok=True)
    path=folder/"brand.png"
    Image.new("RGBA",(300,120),(21,85,160,255)).save(path)
    original=hashlib.sha256(path.read_bytes()).hexdigest()
    scene=spec()
    scene["elements"].append({"type":"image","x":330,"y":410,"w":130,"h":70,
                              "path":"uploads/brand.png","alt":"Original logo"})
    r=client.post("/api/visual/studio/export",headers=H,json={
        "spec":scene,"name":"Brand preservation","format":"png"})
    assert r.status_code==200,r.text
    assert hashlib.sha256(path.read_bytes()).hexdigest()==original
    metadata=json.loads((root/r.json()["manifest"]).read_text())
    assert metadata["original_assets"][0]["sha256"]==original

    scene["elements"][-1]["path"]="../../etc/passwd"
    bad=client.post("/api/visual/studio/preview",headers=H,json={"spec":scene})
    assert bad.status_code==422


def test_preview_rejects_bad_colour_and_large_specs(client):
    invalid=spec()
    invalid["elements"][1]["fill"]="#NOPE"
    r=client.post("/api/visual/studio/preview",headers=H,json={"spec":invalid})
    assert r.status_code==422
    huge=spec()
    huge["subtitle"]="x"*(49*1024)
    r=client.post("/api/visual/studio/preview",headers=H,json={"spec":huge})
    assert r.status_code==413
    r=client.post("/api/visual/studio/export",headers=H,json={"spec":spec(),"format":"exe"})
    assert r.status_code==422


def test_unrelated_text_collision_is_blocked_and_grouped_overlap_is_allowed(client):
    from automoto.visual_foundation import compile_scene
    from automoto.visual_renderer import quality
    scene=spec()
    scene["elements"].append({
        "type":"text","x":120,"y":315,"w":200,"h":65,
        "font_size":26,"text":"Accidental overlay","colour":"#22252C"
    })
    compiled=compile_scene(scene)
    assert any("unintended overlap" in issue for issue in quality(compiled))
    refused=client.post("/api/visual/studio/preview",headers=H,json={"spec":scene})
    assert refused.status_code==422
    scene["elements"][-1]["allow_overlap"]=True
    # Intentional overlaps can be explicitly authorised by the designer.
    approved=client.post("/api/visual/studio/preview",headers=H,json={"spec":scene})
    assert approved.status_code==200,approved.text


def test_empty_canvas_is_valid_and_keeps_title_editable(client):
    blank={"layout":"canvas","theme":"editorial-light","width":800,"height":500,
           "title":"New untitled canvas","elements":[]}
    r=client.post("/api/visual/studio/preview",headers=H,json={"spec":blank})
    assert r.status_code==200,r.text


def test_layers_hide_in_export_but_keep_editable_source(client):
    original=spec()
    original["elements"][2]["hidden"]=True
    original["elements"][2]["locked"]=True
    r=client.post("/api/visual/studio/export",headers=H,
                  json={"name":"Layer visibility","spec":original,"format":"pptx"})
    assert r.status_code==200,r.text
    from pptx import Presentation
    presentation=Presentation(sandbox.default_root()/r.json()["path"])
    visible_text="\n".join(
        sh.text for sh in presentation.slides[0].shapes if sh.has_text_frame)
    assert "Receive" not in visible_text and "Verify" in visible_text
    saved=client.get("/api/visual/studio/load",headers=H,
                     params={"path":r.json()["draft"]}).json()
    assert saved["spec"]["elements"][2]["hidden"] is True
    assert saved["spec"]["elements"][2]["locked"] is True


def test_sequence_timeline_previews_have_distinct_frames_and_real_gif(client):
    original=spec()
    original["elements"][1]["group"]="start"
    original["elements"][2]["group"]="start"
    original["elements"][3]["group"]="finish"
    original["elements"][4]["group"]="finish"
    original["elements"][0]["from_group"]="start"
    original["elements"][0]["to_group"]="finish"
    config={"effect":"sequence","frames":12,"duration_ms":90,"loop":0,
            "stages":[{"group":"start","start":0.0},{"group":"finish","start":0.5}]}
    url="/api/visual/studio"
    a=client.post(url+"/preview",headers=H,json={
        "spec":original,"animation":config,"frame":0.1})
    b=client.post(url+"/preview",headers=H,json={
        "spec":original,"animation":config,"frame":0.75})
    assert a.status_code==200,a.text
    assert b.status_code==200,b.text
    assert a.json()["image"]!=b.json()["image"]
    r=client.post(url+"/export",headers=H,json={
        "name":"Timeline GIF","spec":original,"format":"gif","animation":config})
    assert r.status_code==200,r.text
    with Image.open(sandbox.default_root()/r.json()["path"]) as im:
        assert im.n_frames>=2
        im.seek(0);first=im.convert("RGB")
        im.seek(im.n_frames-1);last=im.convert("RGB")
        assert ImageChops.difference(first,last).getbbox()


@pytest.mark.parametrize("stages",[
    [{"group":"unknown","start":0.5}],
    [{"group":"start","start":-0.5}],
    [{"group":"start","start":float("nan")}],
    [{"group":"start","start":0.0},{"group":"start","start":0.5}],
    [{"group":"start","start":"0.3"}],
])
def test_sequence_validation_rejects_invalid_tracks(client,stages):
    original=spec()
    original["elements"][1]["group"]="start"
    config={"effect":"sequence","frames":12,"duration_ms":100,"stages":stages}
    # JSON encodes NaN in the Python test client: Pydantic will reject it,
    # or the renderer will reject non-finite values. Both are safe.
    if any(isinstance(s.get("start"),float) and str(s["start"])=="nan" for s in stages):
        from automoto.visual_renderer import sequence_stages
        from automoto.visual_foundation import compile_scene,VisualError
        with pytest.raises(VisualError):
            sequence_stages(compile_scene(original),config)
        return
    r=client.post("/api/visual/studio/preview",headers=H,json={
        "spec":original,"animation":config,"frame":0.3})
    assert r.status_code==422,r.text


def test_hidden_group_removes_its_connectors_from_pptx(client):
    original=spec()
    original["elements"][0]["from_group"]="source"
    original["elements"][0]["to_group"]="target"
    original["elements"][1]["group"]="source"
    original["elements"][2]["group"]="source"
    original["elements"][3]["group"]="target"
    original["elements"][4]["group"]="target"
    for e in original["elements"][1:3]:
        e["hidden"]=True
    response=client.post("/api/visual/studio/export",headers=H,json={
        "spec":original,"format":"pptx","name":"Hidden source"})
    assert response.status_code==200,response.text
    from pptx import Presentation
    slide=Presentation(sandbox.default_root()/response.json()["path"]).slides[0]
    assert not any(sh.shape_type==9 for sh in slide.shapes) # no connector shape
    assert "Receive" not in "\n".join(sh.text for sh in slide.shapes if sh.has_text_frame)


def test_hosted_routes_are_whitelisted_but_require_user_auth():
    for path in ("presets","list","load"):
        assert path_allowed("GET","/api/visual/studio/"+path)
    for path in ("preview","save","export"):
        assert path_allowed("POST","/api/visual/studio/"+path)
    assert not path_allowed("DELETE","/api/visual/studio/export")
