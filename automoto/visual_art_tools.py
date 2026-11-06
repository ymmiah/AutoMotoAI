"""AutoMoto visual-design tool interface, shared by graphic and slide workflows."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from automoto import sandbox
from automoto.tools import I,S,Tool,ToolContext,ToolFailed,_obj
from automoto.visual_foundation import THEMES,VisualError,compile_scene
from automoto.visual_renderer import render,quality

def _spec(value: Any) -> dict:
    if isinstance(value,str):
        try:value=json.loads(value)
        except (ValueError,TypeError) as exc:
            raise ToolFailed(f"design spec is not valid JSON: {exc}") from None
    if not isinstance(value,dict):raise ToolFailed("design spec must be a JSON object")
    return value

def visual_presets(ctx:ToolContext) -> str:
    return ("Design presets: "+", ".join(THEMES)+
            ". Layouts: workflow (nodes + optional links), cards (2-6 cards), "
            "hero (existing image + text) and canvas (positioned elements). "
            "Export formats: PNG, JPEG, SVG, PDF, editable PPTX and animated GIF. "
            "GIF effects: flow, pulse, float, reveal, sequence; 8-48 frames, 50-500ms each. "
            "Sequence uses grouped canvas elements and animation.stages:[{group,start:0.0-0.9}]. "
            "The renderer uses native drawing; AI artwork still requires an installed image model.")

def visual_create(ctx:ToolContext,path:str,spec:Any,animation:dict|None=None,
                  output_mode:str="flat") -> str:
    from automoto.visual_projects import mode
    mode(output_mode)
    out=sandbox.resolve(path,allow_outside=True)
    if out.suffix.lower() not in {".png",".jpg",".jpeg",".svg",".gif",".pptx",".pdf"}:
        raise ToolFailed("output path must end with .png, .jpg, .svg, .gif, .pptx or .pdf")
    if out.exists():raise ToolFailed("output already exists; choose a new path")
    manifest=out.with_name(out.name+".visual.json")
    if manifest.exists():
        raise ToolFailed("design manifest already exists; choose a new filename")
    spec=_spec(spec)
    slides=spec.get("slides")
    if slides is not None:
        if out.suffix.lower()!=".pptx" or not isinstance(slides,list) or not 1<=len(slides)<=40:
            raise ToolFailed("slides must contain 1-40 slide specs and require a .pptx output")
        themes={k:v for k,v in spec.items() if k in {"width","height","theme","colours"}}
        scenes=[]
        for raw in slides:
            if not isinstance(raw,dict):raise ToolFailed("each slide must be an object")
            scenes.append(compile_scene({**themes,**raw}))
    else:
        scenes=[compile_scene(spec)]
    project_spec=None
    if output_mode=="layered":
        if len(scenes)!=1:
            raise ToolFailed("Visual Studio layered projects currently support one canvas; "
                             "use editable PowerPoint for multi-slide designs")
        from automoto.visual_projects import scene_project
        try:
            # Already-authored editor canvases are the source of truth: preserve
            # even hidden/locked objects, grouped layers and animation timing.
            project_spec = spec if spec.get("layout")=="canvas" else scene_project(scenes[0])
            if out.suffix.lower()==".gif":
                # Preserve the selected motion sequence when the agent passes
                # timing as a tool argument, not only as a spec field.
                project_spec = {**project_spec,
                                "animation":animation or spec.get("animation") or
                                {"effect":"flow","frames":20,"duration_ms":110,"loop":0}}
        except (VisualError,OSError,ValueError) as exc: raise ToolFailed(str(exc)) from None
    try:
        render(scenes[0],out,scenes=scenes,animation=animation or spec.get("animation"))
    except (VisualError,OSError,ValueError,ImportError) as exc:
        raise ToolFailed(str(exc)) from None
    project=None
    if project_spec:
        from automoto.visual_projects import save_project
        try: project=save_project(project_spec,out.stem)
        except (VisualError,OSError,ValueError) as exc:
            out.unlink(missing_ok=True)
            raise ToolFailed("Could not prepare editable layered project: "+str(exc)) from None
    names=sorted({f["path"]:f for s in scenes for f in s["assets"]}.values(),key=lambda v:v["path"])
    from hashlib import sha256
    metadata={
        "schema_version":1,
        "format":out.suffix.lower()[1:],
        "scene_count":len(scenes),
        "themes":[s["theme"] for s in scenes],
        "dimensions":[{"width":s["width"],"height":s["height"]} for s in scenes],
        "original_assets":names,
        "output_mode":output_mode,
        "editable_project":project,
        "text_fitting_repairs":[s.get("text_repairs",[]) for s in scenes],
        "output_sha256":sha256(out.read_bytes()).hexdigest(),
        "animation":(animation or spec.get("animation") or {}) if out.suffix.lower()==".gif" else None,
        "quality":{"structural_check":"passed","visual_manual_review":"required"}
    }
    try:
        # New sidecar only. Do not modify or overwrite any input asset.
        with manifest.open("x",encoding="utf-8") as stream:
            json.dump(metadata,stream,indent=2,ensure_ascii=False)
    except OSError as exc:
        out.unlink(missing_ok=True)
        if project:
            (sandbox.default_root()/project).unlink(missing_ok=True)
        raise ToolFailed(f"failed to save visual provenance manifest: {exc}") from None
    return (f"Created {sandbox.rel(out)} and {sandbox.rel(manifest)}: "
            + (f"Editable Visual Studio layered project: {project}. " if project else "Single exported file (no editable project requested). ")
            + f"{len(scenes)} design scene(s), {len(names)} protected original asset(s), "
            f"theme {scenes[0]['theme']}, format {out.suffix.lower()[1:]}. "
            "Bounds, text fitting, contrast and source-file integrity passed. "
            "Manually review final appearance and font rendering. "
            + ("GIF output uses genuine multi-frame animation with moving elements."
             if out.suffix.lower()==".gif" else "This is a static exported artwork."))

def visual_check(ctx:ToolContext,path:str) -> str:
    p=sandbox.resolve(path,allow_outside=True)
    if not p.is_file():raise ToolFailed("file does not exist")
    ext=p.suffix.lower()
    if ext==".gif":
        from PIL import Image,ImageChops
        with Image.open(p) as im:
            count=getattr(im,"n_frames",1)
            im.seek(0);first=im.convert("RGB")
            im.seek(count//2);middle=im.convert("RGB")
            distinct=ImageChops.difference(first,middle).getbbox() is not None
            return (f"{sandbox.rel(p)}: {im.width}×{im.height}, {count} GIF frames, "
                    f"loop={im.info.get('loop','not set')}, "
                    f"frame_duration_ms={im.info.get('duration','unknown')}, "
                    f"visible_motion={'yes' if distinct else 'not detected between sampled frames'}.")
    if ext==".pptx":
        import pptx
        from automoto.office_check import check_pptx
        prs=pptx.Presentation(str(p))
        warnings=[msg for level,msg in check_pptx(p) if level=="warn"]
        return (f"{sandbox.rel(p)}: {len(prs.slides)} editable PowerPoint slide(s), "
                f"{sum(len(s.shapes) for s in prs.slides)} shapes, "
                f"{len(warnings)} layout warnings."
                + ("\n"+"\n".join(warnings[:15]) if warnings else ""))
    if ext in {".png",".jpg",".jpeg",".pdf",".svg"}:
        if ext in {".png",".jpg",".jpeg"}:
            from PIL import Image
            with Image.open(p) as im:return f"{sandbox.rel(p)}: {im.width}×{im.height} {im.format} image"
        return f"{sandbox.rel(p)}: {p.stat().st_size} bytes; inspect visually before publishing"
    raise ToolFailed("visual_check supports rendered GIF, PNG, JPEG, SVG, PDF and PPTX")

TOOLS=[
    Tool("visual_presets","List built-in visual design themes, editable layouts and GIF animation effects.",
         _obj({}),"safe",visual_presets,"visual"),
    Tool("visual_create","Create an original premium infographic, linked workflow, cards, slide, poster "
         "or ACTUAL animated GIF using one validated spec. Supports editable PPTX, SVG, PNG, JPG, PDF, GIF. "
         "Ask whether the user wants output_mode='layered' (a separate Visual Studio editable design "
         "with original text/icons/shapes as layers) or output_mode='flat' (only the exported artwork). "
         "GIF is a format choice and also supports optional layers; never create every variant by default. "
         "For workflow use layout:'workflow',title,nodes:[{id,title,text,icon}],optional links:[{from,to}]; "
         "cards: layout:'cards',cards:[{title,text,icon}]; "
         "hero: layout:'hero',image:'uploads/source.png',text; "
         "canvas: layout:'canvas',elements:[{type:'rect'|'text'|'icon'|'image'|'line',x,y,w,h,...}]. "
         "Optional width,height,theme:'editorial-light'|'illustrated-workflow'|'premium-tech'|'commercial', "
         "footer,notes. For PPTX use slides:[{layout,title,...}] to produce multiple slides. "
         "For GIF animation={effect:'flow'|'pulse'|'float'|'reveal'|'sequence',frames:20,duration_ms:110,loop:0}; "
         "sequence adds stages:[{group:'stage0',start:0},{group:'stage1',start:0.5}]. "
         "All photo/logo sources remain untouched, with aspect-fit and source hashes; exact wording "
         "is kept in editable text wherever supported. Never promise the image is generatively created "
         "when the tool only draws vector shapes.",
         _obj({"path":S,"spec":{"type":"object"},"animation":{"type":"object"},
               "output_mode":S},["path","spec"]),
         "risky",visual_create,"visual"),
    Tool("visual_check","Inspect GIF frame count and visible motion or check shape count and overflow "
         "in an editable PPTX. Check after every visual_create output.",
         _obj({"path":S},["path"]),"safe",visual_check,"visual"),
]
