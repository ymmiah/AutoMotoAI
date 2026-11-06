"""Conservative, review-first repairs for AutoMoto Visual Studio canvases.

Never changes wording, original image paths or pixels, source asset hashes,
logos, lock/hidden flags, group membership, or GIF timeline metadata.
Only repairs editable text size/colour and non-locked standalone object geometry.
All changes are proposed as a new JSON spec: the caller must explicitly apply.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from automoto.visual_foundation import THEMES, VisualError, compile_scene
from automoto.visual_renderer import _contrast, _text_lines, quality

MAX_CHANGES = 30
GAP = 12

def _xybox(item: dict) -> tuple[float,float,float,float] | None:
    if item.get("type") not in {"text","icon","image","rect"}:
        return None
    try:
        x,y,w,h=(float(item[key]) for key in ("x","y","w","h"))
    except (TypeError,ValueError,KeyError):
        return None
    if not all(math.isfinite(z) for z in (x,y,w,h)) or min(w,h)<=0:
        return None
    return x,y,w,h

def _intersects(a: tuple,b: tuple,padding: float=0) -> bool:
    x,y,w,h=a
    q,r,s,t=b
    return x < q+s+padding and x+w+padding > q and y < r+t+padding and y+h+padding > r

def _edit(changes: list,idx: int,key: str,old: Any,new: Any,why: str):
    if old!=new and len(changes)<MAX_CHANGES:
        changes.append({"index":idx,"field":key,"old":old,"new":new,"reason":why})

def _report(spec:dict) -> list[str]:
    try:
        scene=compile_scene(spec)
        return quality(scene)
    except (VisualError,ValueError,TypeError) as exc:
        return [str(exc)]

def design_notes(spec: dict) -> list[dict]:
    """Conservative design-review hints; never used as export blockers or edits.

    These are deterministic observations, not AI aesthetic judgements. Only
    report checks supported by the actual editable specification.
    """
    notes: list[dict] = []
    width, height = spec.get("width", 1280), spec.get("height", 720)
    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
        return notes
    for idx, item in enumerate(spec.get("elements", [])):
        if not isinstance(item, dict) or item.get("hidden"):
            continue
        kind = item.get("type")
        if kind == "image" and not str(item.get("alt") or "").strip():
            notes.append({"code": "image-alt", "layer": idx + 1, "level": "advisory",
                          "message": "Add descriptive alternative text to this image for accessibility."})
        if kind not in {"text", "icon"} or item.get("group"):
            continue
        box = _xybox(item)
        if box is not None:
            x, y, w, h = box
            margin = min(24, width * .025, height * .035)
            if x < margin or y < margin or x + w > width - margin or y + h > height - margin:
                notes.append({"code": "safe-area", "layer": idx + 1, "level": "advisory",
                              "message": "Check the spacing around this element at the canvas edge."})
        if kind == "text":
            size = item.get("font_size", 25)
            if isinstance(size, (int, float)) and not isinstance(size, bool) and math.isfinite(size) and size < 16:
                notes.append({"code": "small-type", "layer": idx + 1, "level": "advisory",
                              "message": "Check readability at the final display or print size."})
        if len(notes) >= 8:
            break
    return notes


def _editable(item: dict) -> bool:
    return not item.get("hidden") and not item.get("locked") and item.get("type")!="image"

def _text_fit(item: dict) -> bool:
    try:
        _text_lines({"type":"text","text":item.get("text",""),"x":item["x"],"y":item["y"],
                     "w":item["w"],"h":item["h"],"size":item.get("font_size",25),
                     "bold":item.get("bold",False),"colour":item.get("colour","#172638")})
        return True
    except (VisualError,KeyError,ValueError,TypeError):
        return False

def _background(spec:dict,item:dict) -> str:
    theme=THEMES.get(spec.get("theme"),THEMES["editorial-light"])
    result=(spec.get("colours") or {}).get("background",theme["background"])
    cx=item["x"]+item["w"]/2
    cy=item["y"]+min(item["h"]/2,item.get("font_size",25)*.65)
    for part in spec["elements"]:
        if part is item:
            break
        if part.get("hidden") or part.get("type")!="rect":
            continue
        box=_xybox(part)
        if box and box[0]<=cx<=box[0]+box[2] and box[1]<=cy<=box[1]+box[3]:
            result=part.get("fill",result)
    return result

def _text_contrast(item:dict,background:str) -> tuple[float,float]:
    size=float(item.get("font_size",25))
    required=3.0 if (size>=24 and item.get("bold")) or size>=30 else 4.5
    try:return _contrast(item.get("colour","#172638"),background),required
    except (ValueError,TypeError):return 0.0,required

def _move_nearest(spec:dict,index:int) -> tuple[float,float] | None:
    item=spec["elements"][index]
    old=_xybox(item)
    if old is None:return None
    x,y,w,h=old
    width,height=spec["width"],spec["height"]
    if w>width-24 or h>height-24:return None
    occupied=[]
    for j,other in enumerate(spec["elements"]):
        if j==index or other.get("hidden") or other.get("allow_overlap"):
            continue
        if other.get("type") not in {"text","icon","image"}:
            continue
        if item.get("group") and item.get("group")==other.get("group"):
            continue
        box=_xybox(other)
        if box:occupied.append(box)
    candidates=[]
    xmax=max(0,int(width-w));ymax=max(0,int(height-h))
    for yy in range(12,ymax+1,18):
        for xx in range(12,xmax+1,18):
            box=(xx,yy,w,h)
            if all(not _intersects(box,other,GAP) for other in occupied):
                candidates.append((abs(xx-x)+abs(yy-y),xx,yy))
    if not candidates:return None
    _,nx,ny=min(candidates)
    return float(nx),float(ny)

def propose(spec:dict[str,Any]) -> dict[str,Any]:
    """Return a suggested copy plus an explicit diff; never mutate input."""
    if not isinstance(spec,dict) or spec.get("layout")!="canvas":
        raise VisualError("layout repair supports the editable canvas layout only")
    elements=spec.get("elements")
    if not isinstance(elements,list) or len(elements)>40:
        raise VisualError("canvas must contain no more than 40 elements")
    candidate=copy.deepcopy(spec)
    width,height=candidate.get("width",1280),candidate.get("height",720)
    if (isinstance(width,bool) or isinstance(height,bool) or not isinstance(width,(int,float))
            or not isinstance(height,(int,float)) or not 640<=width<=1920 or not 400<=height<=1080):
        raise VisualError("cannot repair a canvas with invalid dimensions")
    issues_before=_report(candidate)
    changes:list[dict]=[]
    for index,el in enumerate(candidate["elements"]):
        if not _editable(el) or el.get("group"):
            # Group geometry and locked objects are intentionally not altered;
            # moving a grouped child without its connectors would be destructive.
            continue
        rect=_xybox(el)
        if rect is None:continue
        x,y,w,h=rect
        if el.get("type") in {"text","icon","rect"}:
            for key,old,new in (
                ("x",el.get("x"),round(max(0,min(x,width-w)),2)),
                ("y",el.get("y"),round(max(0,min(y,height-h)),2)),
            ):
                if old!=new and len(changes)<MAX_CHANGES and w<=width and h<=height:
                    el[key]=new
                    _edit(changes,index,key,old,new,"Keep the object inside the canvas")
        if el.get("type")!="text":continue
        size=el.get("font_size",25)
        if not isinstance(size,(int,float)) or isinstance(size,bool) or not math.isfinite(size):
            continue
        # Alter typography only when it genuinely overflows. Never shorten copy.
        if not _text_fit(el):
            floor=max(13,math.ceil(float(size)*.70))
            for next_size in range(int(size)-1,floor-1,-1):
                el["font_size"]=next_size
                if _text_fit(el):
                    _edit(changes,index,"font_size",size,next_size,
                          "Fit exact wording within its existing text box")
                    break
            else:
                el["font_size"]=size
        try:
            bg=_background(candidate,el)
            ratio,required=_text_contrast(el,bg)
            if ratio<required:
                light="#FFFFFF";dark="#172638"
                new=max((light,dark),key=lambda z:_contrast(z,bg))
                if _contrast(new,bg)>=required:
                    old=el.get("colour")
                    if old!=new and len(changes)<MAX_CHANGES:
                        el["colour"]=new
                        el.pop("auto_colour",None)
                        _edit(changes,index,"colour",old,new,
                              "Improve text contrast on its current background")
        except (TypeError,ValueError,KeyError):
            pass
    # Move independent text/icon objects away from collisions. Never move
    # original raster imagery, user logos, locked elements, or grouped art.
    for idx,el in enumerate(candidate["elements"]):
        if not _editable(el) or el.get("group") or el.get("allow_overlap") or el.get("type") not in ("text","icon"):
            continue
        box=_xybox(el)
        if box is None:continue
        bad=False
        for j,other in enumerate(candidate["elements"]):
            if j==idx or other.get("hidden") or other.get("allow_overlap"):
                continue
            if other.get("type") not in ("text","icon","image"):
                continue
            other_box=_xybox(other)
            if not other_box or not _intersects(box,other_box):
                continue
            width_overlap=max(0,min(box[0]+box[2],other_box[0]+other_box[2])
                              -max(box[0],other_box[0]))
            height_overlap=max(0,min(box[1]+box[3],other_box[1]+other_box[3])
                               -max(box[1],other_box[1]))
            overlap=width_overlap*height_overlap
            if overlap>100 and overlap/min(box[2]*box[3],other_box[2]*other_box[3])>=.12:
                bad=True
                break
        if not bad:continue
        position=_move_nearest(candidate,idx)
        if not position:continue
        for key,new in zip(("x","y"),position):
            old=el.get(key)
            if old!=new and len(changes)<MAX_CHANGES:
                el[key]=new
                _edit(changes,idx,key,old,new,"Separate overlapping independent objects")
    remaining=_report(candidate)
    # If the proposed edits made the design worse, do not return a damaging
    # candidate. Operators still get the original problem report.
    if len(remaining)>len(issues_before):
        candidate=copy.deepcopy(spec)
        changes=[]
        remaining=issues_before
    return {
        "proposed_spec":candidate,
        "changes":changes,
        "issues_before":issues_before,
        "design_notes":design_notes(spec),
        "remaining_issues":remaining,
        "changed":bool(changes),
        "ready_to_apply":bool(changes) and not remaining,
        "requires_approval":True,
        "summary":f"{len(changes)} proposed field changes; {len(remaining)} issues remain. "
                  "Changes are not applied until the user approves.",
    }
