"""User-selected image delivery: flat outputs, editable native layers, or GIF."""
import hashlib
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from automoto import sandbox, server, visual_tools
from automoto.tools import ToolContext, ToolFailed
from automoto.visual_art_tools import visual_create

AUTH={"X-AutoMoto-Token":server.SESSION_TOKEN}

@pytest.fixture
def home(tmp_path,monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME",str(tmp_path/"home"))
    monkeypatch.delenv("AUTOMOTO_MODE",raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT","10000")
    base=sandbox.default_root()
    base.mkdir(parents=True,exist_ok=True)
    return base

def canvas():
    return {"width":800,"height":500,"layout":"canvas","theme":"editorial-light",
            "artboard_only":True,"title":"","subtitle":"","elements":[
      {"type":"rect","x":0,"y":0,"w":800,"h":500,"fill":"#FFFFFF"},
      {"type":"text","x":100,"y":130,"w":550,"h":100,
       "text":"Exact editable wording","colour":"#172638","font_size":35,"bold":True},
      {"type":"icon","x":110,"y":280,"w":65,"h":65,"name":"check","colour":"#246D83"}
    ]}

def test_flat_visual_export_creates_no_editor_project(home):
    out=home/"artifacts"/"flat.png"
    result=visual_create(ToolContext(),str(out),canvas(),output_mode="flat")
    assert "no editable project requested" in result
    assert out.is_file()
    side=json.loads(out.with_name(out.name+".visual.json").read_text())
    assert side["output_mode"]=="flat" and side["editable_project"] is None
    assert not list((home/"artifacts"/"visual-studio").glob("*.design.json")) if (home/"artifacts"/"visual-studio").exists() else True


def test_layered_visual_export_keeps_text_icon_and_shape_independent(home):
    out=home/"artifacts"/"layered.png"
    text="Exact editable wording"
    result=visual_create(ToolContext(),str(out),canvas(),output_mode="layered")
    side=json.loads(out.with_name(out.name+".visual.json").read_text())
    assert "Editable Visual Studio layered project" in result
    assert side["output_mode"]=="layered"
    draft=home/side["editable_project"]
    assert draft.is_file()
    saved=json.loads(draft.read_text())
    elems=saved["spec"]["elements"]
    assert [e["type"] for e in elems]==["rect","text","icon"]
    assert elems[1]["text"]==text
    with TestClient(server.app) as web:
        loaded=web.get("/api/visual/studio/load",headers=AUTH,
                       params={"path":side["editable_project"]})
        assert loaded.status_code==200,loaded.text
        assert loaded.json()["spec"]["elements"][1]["text"]==text


@pytest.mark.parametrize("format",["png","jpg","gif"])
@pytest.mark.parametrize("layered",[False,True])
def test_visual_studio_export_mode_and_format_are_independent(home,format,layered):
    with TestClient(server.app) as web:
        inp={"name":"My one output","spec":canvas(),"format":format,
             "output_mode":"layered" if layered else "flat"}
        if format=="gif":
            inp["animation"]={"effect":"pulse","frames":10,"duration_ms":100,"loop":0}
        response=web.post("/api/visual/studio/export",headers=AUTH,json=inp)
        assert response.status_code==200,response.text
        result=response.json()
        assert (home/result["path"]).is_file()
        assert result["output_mode"]==inp["output_mode"]
        assert bool(result["draft"])==layered
        if layered:
            assert (home/result["draft"]).is_file()
        if format=="gif":
            with Image.open(home/result["path"]) as gif:
                assert gif.n_frames>1


def test_import_flattened_ai_art_is_one_image_layer_not_fake_object_layers(home):
    uploaded=home/"uploads"/"fresh-ai-image.webp";uploaded.parent.mkdir(parents=True)
    Image.new("RGB",(720,480),(45,119,210)).save(uploaded)
    before=hashlib.sha256(uploaded.read_bytes()).hexdigest()
    with TestClient(server.app) as web:
        resp=web.post("/api/visual/studio/import",headers=AUTH,
                      json={"path":"uploads/fresh-ai-image.webp"})
        assert resp.status_code==200,resp.text
        imported=resp.json()
        assert imported["layer_source"]=="raster"
        elems=imported["spec"]["elements"]
        assert len(elems)==1 and elems[0]["type"]=="image"
        assert elems[0]["path"]=="uploads/fresh-ai-image.webp"
        assert "single image layer" in imported["note"]
        assert (home/imported["draft"]).is_file()
        preview=web.post("/api/visual/studio/preview",headers=AUTH,
                         json={"spec":imported["spec"]})
        assert preview.status_code==200,preview.text
        assert hashlib.sha256(uploaded.read_bytes()).hexdigest()==before


def test_native_image_import_recovers_earlier_separate_editor_layers(home):
    out=home/"artifacts"/"native-work.png"
    visual_create(ToolContext(),str(out),canvas(),output_mode="layered")
    with TestClient(server.app) as web:
        imported=web.post("/api/visual/studio/import",headers=AUTH,
                          json={"path":"artifacts/native-work.png"})
        assert imported.status_code==200,imported.text
        info=imported.json()
        assert info["layer_source"]=="native"
        assert len(info["spec"]["elements"])==3
        assert any(x["type"]=="text" for x in info["spec"]["elements"])


def test_gif_flat_import_uses_one_static_preview_frame_without_modifying_source(home):
    src=home/"uploads"/"demo.gif";src.parent.mkdir(parents=True)
    frames=[Image.new("RGB",(800,480),(255,20,40)),
            Image.new("RGB",(800,480),(20,40,255))]
    frames[0].save(src,save_all=True,append_images=frames[1:],duration=100,loop=0)
    before=hashlib.sha256(src.read_bytes()).hexdigest()
    with TestClient(server.app) as web:
        resp=web.post("/api/visual/studio/import",headers=AUTH,
                      json={"path":"uploads/demo.gif"})
        assert resp.status_code==200,resp.text
        imported=resp.json()
        assert imported["layer_source"]=="raster"
        assert imported["spec"]["elements"][0]["path"].endswith(".png")
        assert (home/imported["spec"]["elements"][0]["path"]).is_file()
        assert hashlib.sha256(src.read_bytes()).hexdigest()==before


def test_import_cannot_read_private_host_paths_and_rejects_unsupported_files(home):
    (home/"uploads").mkdir(exist_ok=True)
    (home/"uploads"/"a.txt").write_text("not a picture")
    with TestClient(server.app) as web:
        for path in ("/etc/passwd","../../etc/passwd","uploads/a.txt","uploads/missing.png"):
            r=web.post("/api/visual/studio/import",headers=AUTH,json={"path":path})
            assert r.status_code==422,(path,r.text)
        assert web.post("/api/visual/studio/import",json={"path":"uploads/a.txt"}).status_code==403


def test_generated_ai_raster_layer_mode_from_local_model(home,monkeypatch):
    from automoto import visual_tools
    out=home/"artifacts"/"real-model-output.png"
    image=io.BytesIO()
    Image.new("RGB",(640,640),(210,80,120)).save(image,format="PNG")
    raw=image.getvalue()
    run_id="b"*32
    def fake_json(base,route,payload=None):
        if route=="/models/checkpoints":return ["local-test.safetensors"]
        if route=="/prompt":return {"prompt_id":run_id}
        if route=="/history/"+run_id:
            return {run_id:{"outputs":{"9":{"images":[
               {"filename":"AutoMoto_01.png","subfolder":"","type":"output"}
            ]}}}}
        raise AssertionError(route)
    monkeypatch.setattr(visual_tools,"_json",fake_json)
    monkeypatch.setattr(visual_tools,"_req",lambda *a,**kw:raw)
    output=visual_tools.generate_image(ToolContext(),str(out),
       "Original landscape with a river",output_mode="layered")
    assert "Open editable layer project" in output
    draft=list((home/"artifacts"/"visual-studio").glob("*.design.json"))
    assert len(draft)==1
    source=json.loads(draft[0].read_text())
    assert source["spec"]["elements"][0]["type"]=="image"
    assert source["spec"]["elements"][0]["path"]=="artifacts/real-model-output.png"
    assert out.read_bytes()==raw


def test_photo_composition_layer_mode_preserves_original_assets(home):
    root=home/"uploads";root.mkdir(exist_ok=True)
    photo=root/"photo.png";logo=root/"logo.png"
    Image.new("RGB",(900,600),(50,110,190)).save(photo)
    Image.new("RGBA",(300,140),(160,40,60,255)).save(logo)
    before=[hashlib.sha256(x.read_bytes()).hexdigest() for x in (photo,logo)]
    out=home/"artifacts"/"source-compose.png"
    result=visual_tools.compose_image(ToolContext(),str(out),str(photo),
                                      title="Verified visual",
                                      subtitle="Keep the brand unchanged",
                                      logo=str(logo),output_mode="layered")
    assert "Editable Visual Studio layered project" in result
    metadata=json.loads(out.with_name(out.name+".visual.json").read_text())
    project=json.loads((home/metadata["editable_project"]).read_text())["spec"]
    elems=project["elements"]
    assert sum(e["type"]=="image" for e in elems)==2
    assert [e["text"] for e in elems if e["type"]=="text"]==[
       "Verified visual","Keep the brand unchanged"]
    assert before==[hashlib.sha256(x.read_bytes()).hexdigest() for x in (photo,logo)]


def test_invalid_image_mode_fails_before_creating_output(home):
    with pytest.raises(Exception,match="output_mode"):
        visual_create(ToolContext(),str(home/"invalid.png"),canvas(),output_mode="magic")
    assert not (home/"invalid.png").exists()
