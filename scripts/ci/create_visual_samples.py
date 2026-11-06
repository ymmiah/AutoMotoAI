"""Build deterministic visual foundation showcase assets for CI and release review."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image,ImageDraw

from automoto import sandbox
from automoto.visual_foundation import compile_scene
from automoto.visual_renderer import render,quality

def make_samples(folder:Path):
    folder=folder.resolve()  # make reference asset paths unambiguous within the workspace
    folder.mkdir(parents=True,exist_ok=True)
    original=folder/"source-original.png"
    # This shape composition is synthetic, not an unlicensed photograph or logo.
    if original.exists():original.unlink()
    img=Image.new("RGBA",(800,520),"#F7F3FA")
    d=ImageDraw.Draw(img)
    for i,color in enumerate(["#DACCF8","#D5EAFE","#FFEBAB","#D7EDBB"]):
        x=55+i*165
        d.rounded_rectangle((x,96,x+135,380),radius=40,fill=color,outline="#23232B",width=5)
        d.ellipse((x+28,152,x+107,231),fill="#FFFFFF",outline="#22252C",width=5)
        d.rounded_rectangle((x+21,265,x+112,282),radius=8,fill="#22252C")
    img.save(original)
    nodes=[
        {"id":"input","title":"Receive data","text":"Keep original evidence","icon":"file"},
        {"id":"parse","title":"Understand","text":"Extract key information","icon":"idea"},
        {"id":"validate","title":"Verify","text":"Check accuracy and provenance","icon":"shield"},
        {"id":"deliver","title":"Create output","text":"Beautiful, editable results","icon":"check"},
    ]
    flow={
        "width":960,"height":540,"theme":"illustrated-workflow","layout":"workflow",
        "title":"From input to outstanding output",
        "subtitle":"Illustrated processing • source fidelity • validation",
        "nodes":nodes,
        "notes":"This is a deterministic, original design-engine demonstration.",
        "footer":"AutoMoto AI · Visual Design Foundation",
    }
    cards={
        "theme":"editorial-light","layout":"cards","width":1280,"height":720,
        "title":"The visual system works as one",
        "subtitle":"Components are reusable, editable and consistent",
        "cards":[
            {"title":"Design system","text":"Professional themes and layouts","icon":"target"},
            {"title":"Original assets","text":"No generative face or logo redraws","icon":"image"},
            {"title":"Editable output","text":"Native PowerPoint and SVG vectors","icon":"chart"},
            {"title":"Real animation","text":"Animated GIF with separate frames","icon":"sparkle"},
        ],
    }
    hero={
        "layout":"hero","theme":"commercial","width":1280,"height":720,
        "title":"Preserve what matters","subtitle":"Original artwork stays original",
        "image":str(original),"text":"Place images without cropping, AI reconstruction or invented wording.",
        "alt":"Original geometric design file"}
    canvas={
        "layout":"canvas","theme":"premium-tech","width":1280,"height":720,
        "title":"Precise geometry, better composition",
        "subtitle":"Editable text, lines, nodes and icons",
        "elements":[
            {"type":"rect","x":72,"y":250,"w":300,"h":210,"fill":"#19283E","stroke":"#56B2FA"},
            {"type":"rect","x":490,"y":250,"w":300,"h":210,"fill":"#19283E","stroke":"#56B2FA"},
            {"type":"rect","x":906,"y":250,"w":300,"h":210,"fill":"#19283E","stroke":"#56B2FA"},
            {"type":"line","x1":372,"y1":355,"x2":490,"y2":355,"colour":"#56B2FA"},
            {"type":"line","x1":790,"y1":355,"x2":906,"y2":355,"colour":"#56B2FA"},
            {"type":"icon","x":110,"y":276,"w":58,"h":58,"name":"file"},
            {"type":"icon","x":532,"y":276,"w":58,"h":58,"name":"settings"},
            {"type":"icon","x":950,"y":276,"w":58,"h":58,"name":"check"},
            {"type":"text","x":110,"y":358,"w":220,"h":45,"text":"Plan","font_size":29,"bold":True},
            {"type":"text","x":532,"y":358,"w":220,"h":45,"text":"Compose","font_size":29,"bold":True},
            {"type":"text","x":950,"y":358,"w":220,"h":45,"text":"Verify","font_size":29,"bold":True},
        ],
        "notes":"All elements are created as native editable PowerPoint objects.",
    }
    flow_scene=compile_scene(flow)
    render(flow_scene,folder/"workflow.png")
    render(flow_scene,folder/"workflow.svg")
    render(flow_scene,folder/"workflow.gif",
           animation={"effect":"flow","frames":24,"duration_ms":100,"loop":0})
    render(compile_scene(cards),folder/"cards.png")
    render(compile_scene(hero),folder/"original-preservation.png")
    # Original three-stage GIF: show groups individually, then the connections.
    # Exact copy, drawn icons and grouped boxes remain native editable objects.
    sequence_elements=[]
    stages=[("receive","Receive","Keep source","file"),
            ("analyse","Analyse","Extract facts","idea"),
            ("deliver","Deliver","Verified result","check")]
    for i,(group,heading,description,icon_name) in enumerate(stages):
        x=65+295*i;y=240
        sequence_elements.extend([
            {"type":"rect","group":group,"x":x,"y":y,"w":245,"h":182,
             "fill":"#FFFFFF","stroke":"#25252D","radius":20},
            {"type":"icon","group":group,"x":x+20,"y":y+24,
             "w":50,"h":50,"name":icon_name,"colour":"#22252C"},
            {"type":"text","group":group,"x":x+82,"y":y+28,"w":148,"h":46,
             "text":heading,"font_size":25,"bold":True,"colour":"#22252C"},
            {"type":"text","group":group,"x":x+23,"y":y+105,"w":197,"h":42,
             "text":description,"font_size":19,"colour":"#5A606B"}
        ])
    sequence_elements=[
        {"type":"line","x1":310,"y1":325,"x2":360,"y2":325,
         "from_group":"receive","to_group":"analyse","colour":"#6350A4","stroke_width":4},
        {"type":"line","x1":605,"y1":325,"x2":655,"y2":325,
         "from_group":"analyse","to_group":"deliver","colour":"#6350A4","stroke_width":4}
    ]+sequence_elements
    sequence_scene=compile_scene({
        "layout":"canvas","theme":"illustrated-workflow","width":960,"height":540,
        "title":"Evidence to a verified visual",
        "subtitle":"A genuinely staged and editable design workflow",
        "elements":sequence_elements
    })
    render(sequence_scene,folder/"workflow-sequence.png")
    render(sequence_scene,folder/"workflow-sequence.gif",animation={
        "effect":"sequence","frames":24,"duration_ms":110,"loop":0,
        "stages":[{"group":"receive","start":0.0},
                  {"group":"analyse","start":0.35},
                  {"group":"deliver","start":0.7}]
    })
    scenes=[compile_scene(s) for s in [hero,cards,flow,canvas]]
    render(scenes[0],folder/"AutoMoto-visual-showcase.pptx",scenes=scenes)
    for f in sorted(folder.iterdir()):print(f.name, f.stat().st_size)

if __name__=="__main__":
    out=Path(sys.argv[1]) if len(sys.argv)>1 else sandbox.root()/"scratch"/"visual-showcase"
    make_samples(out)
