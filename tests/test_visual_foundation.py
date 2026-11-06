"""End-to-end tests of the common design scene, native PPTX, source fidelity and animated GIF."""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from automoto import planner,sandbox,tools
from automoto.visual_foundation import THEMES,VisualError,compile_scene
from automoto.visual_renderer import raster,render,svg_string,quality
from automoto.visual_art_tools import visual_create,visual_check,visual_presets


@pytest.fixture()
def work():
    folder=sandbox.root()/"scratch"/("visual-foundation-"+uuid.uuid4().hex[:9])
    folder.mkdir(parents=True,exist_ok=True)
    return folder

def flow(**kwargs):
    result={"width":960,"height":540,"theme":"illustrated-workflow",
            "layout":"workflow","title":"Invoice processing",
            "subtitle":"From original input to validated output",
            "nodes":[
              {"id":"source","title":"Source document","text":"Keep the original","icon":"file"},
              {"id":"extract","title":"Extract text","text":"OCR or embedded text","icon":"image"},
              {"id":"verify","title":"Validate","text":"Check the values","icon":"shield"},
              {"id":"export","title":"Produce output","text":"Export after review","icon":"check"}
            ],"footer":"AutoMoto AI • Design verification"}
    result.update(kwargs)
    return result

def test_themes_and_bounds():
    for name in THEMES:
        compiled=compile_scene(flow(theme=name))
        assert compiled["theme"]==name
        assert quality(compiled)==[]
        assert len(compiled["elements"])>=20
        assert any(e["type"]=="icon" for e in compiled["elements"])
        assert any(e["type"]=="line" for e in compiled["elements"])
        png=raster(compiled)
        assert png.size==(960,540)

def test_real_multiframe_gif_motion_and_loops(work):
    scene=compile_scene(flow())
    dest=work/"workflow.gif"
    render(scene,dest,animation={"frames":16,"duration_ms":90,"loop":0,"effect":"flow"})
    assert dest.stat().st_size>2000
    with Image.open(dest) as image:
        assert image.format=="GIF"
        assert image.n_frames>=8
        assert image.info["loop"]==0
        assert image.info["duration"]==90
        image.seek(0);first=image.convert("RGB")
        image.seek(image.n_frames//2);middle=image.convert("RGB")
        assert ImageChops.difference(first,middle).getbbox() is not None
    info=visual_check(tools.ToolContext(),str(dest))
    assert "visible_motion=yes" in info and "GIF frames" in info

@pytest.mark.parametrize("effect",["reveal","pulse","float"])
def test_animated_cards_have_motion(work,effect):
    spec={"width":800,"height":500,"layout":"cards","theme":"premium-tech",
          "title":"Capabilities","cards":[{"title":"Secure","text":"Local first","icon":"shield"},
                                         {"title":"Visual","text":"Editable","icon":"image"}]}
    dest=work/f"cards-{effect}.gif"
    render(compile_scene(spec),dest,animation={"frames":10,"duration_ms":120,"effect":effect})
    with Image.open(dest) as im:
        assert im.n_frames>1
        im.seek(0);a=im.convert("RGB")
        im.seek(im.n_frames//2);b=im.convert("RGB")
        assert ImageChops.difference(a,b).getbbox()

def test_hero_animated_without_nodes(work):
    p=work/"original.png"
    Image.new("RGB",(100,70),(180,60,100)).save(p)
    spec={"layout":"hero","width":800,"height":500,"title":"Original source",
          "image":str(p),"text":"Preserve the original image"}
    dest=work/"hero.gif"
    render(compile_scene(spec),dest,animation={"frames":10,"duration_ms":100})
    with Image.open(dest) as im:assert im.n_frames>1

def test_reference_source_fidelity_and_svg_safety(work):
    p=work/"source.png";Image.new("RGBA",(301,127),(17,92,180,255)).save(p)
    before=hashlib.sha256(p.read_bytes()).hexdigest()
    spec={"width":960,"height":540,"theme":"editorial-light","layout":"hero",
          "title":"Exact identity","text":"Keep this text <script>alert(1)</script>",
          "image":str(p),"image_side":"right","alt":"Untouched original"}
    # Very long source text may fail a narrow text box - test the source is
    # never altered even when a composition fails before output.
    scene=compile_scene(spec)
    svg=svg_string(scene)
    assert "&lt;script&gt;" in svg and "<script>" not in svg
    assert "data:image/png;base64," in svg
    assert 'preserveAspectRatio="xMidYMid meet"' in svg
    assert scene["assets"][0]["sha256"]==before
    dest=work/"reference.svg"
    render(scene,dest)
    assert hashlib.sha256(p.read_bytes()).hexdigest()==before

def test_original_pptx_editable_and_speaker_notes(work):
    pytest.importorskip("pptx")
    from pptx import Presentation
    specs=[
        flow(width=1280,height=720,notes="Explain the connected process."),
        {"width":1280,"height":720,"layout":"cards","title":"Our principles",
         "theme":"editorial-light","cards":[
             {"title":"Accuracy","text":"Real evidence","icon":"target"},
             {"title":"Precision","text":"Editable elements","icon":"chart"},
             {"title":"Security","text":"Protected sources","icon":"shield"}]}
    ]
    path=work/"editability.pptx"
    scenes=[compile_scene(s) for s in specs]
    render(scenes[0],path,scenes=scenes)
    prs=Presentation(path)
    assert len(prs.slides)==2
    assert len(prs.slides[0].shapes)>15
    assert sum(1 for sh in prs.slides[0].shapes if sh.has_text_frame and sh.text_frame.text.strip())>=6
    assert "Explain the connected process" in prs.slides[0].notes_slide.notes_text_frame.text
    assert any(sh.shape_type==1 for sh in prs.slides[1].shapes)
    assert "2 editable PowerPoint" in visual_check(tools.ToolContext(),str(path))

def test_visual_create_exposed_in_planner_and_registry(work):
    tl=tools.build(local_apps=False)
    assert "visual_create" in tl and "visual_check" in tl and "visual_presets" in tl
    p=planner.plan("create a GIF animation for my business",tl)
    assert "visual_create" in p.tools
    assert "illustrated-workflow" in visual_presets(tools.ToolContext())
    out=work/"tool-output.gif"
    answer=visual_create(tools.ToolContext(),str(out),flow(),
                         {"frames":12,"duration_ms":100})
    assert out.exists() and "genuine multi-frame" in answer
    manifest=out.with_name(out.name+".visual.json")
    assert manifest.exists()
    import json
    metadata=json.loads(manifest.read_text(encoding="utf-8"))
    assert metadata["output_sha256"]==hashlib.sha256(out.read_bytes()).hexdigest()
    assert metadata["format"]=="gif" and metadata["quality"]["structural_check"]=="passed"

def test_invalid_specs_fail_without_partial_output(work):
    with pytest.raises(VisualError,match="unique"):
        compile_scene(flow(nodes=[{"id":"same","title":"First"},
                                 {"id":"same","title":"Second"}]))
    with pytest.raises(VisualError,match="unsupported icon"):
        compile_scene(flow(nodes=[{"title":"A","icon":"made-up"},
                                 {"title":"B","icon":"check"}]))
    with pytest.raises(VisualError,match="outside"):
        compile_scene({"layout":"canvas","title":"Bad","elements":[
            {"type":"rect","x":1200,"y":180,"w":350,"h":50}]})
    valid=compile_scene(flow())
    path=work/"invalid.gif"
    with pytest.raises(VisualError,match="8-48 frames"):
        render(valid,path,animation={"frames":80})
    assert not path.exists()
    with pytest.raises(VisualError,match="already exists"):
        image=work/"exists.png"
        image.write_bytes(b"existing")
        render(valid,image)

def test_contrast_gate_rejects_invisible_text():
    spec=flow(colours={"ink":"#FAFAF6"})
    scene=compile_scene(spec)
    assert any("low contrast" in msg for msg in quality(scene))

def test_safe_source_access(work):
    with pytest.raises(Exception):
        compile_scene({"layout":"hero","title":"Unsafe",
                       "image":"/etc/passwd","text":"No external files"})
