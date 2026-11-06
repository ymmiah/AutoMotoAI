"""Predictable, reversible Visual Studio design inspection and bounded repairs.

Repairs return a new canvas specification and a per-field change log. Nothing
is persisted until the user explicitly saves/exports. Original user assets,
exact text strings, locked layers and intentionally allowed overlaps stay intact.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from automoto.visual_foundation import VisualError, compile_scene
from automoto.visual_renderer import _contrast, _text_lines, quality

MAX_REPAIRS = 70
MIN_TEXT = 12


def _report(spec: dict[str, Any]) -> list[dict[str, str]]:
    try:
        scene = compile_scene(spec)
        errors = quality(scene)
    except (ValueError, OSError, TypeError) as exc:
        return [{"code": "invalid", "message": str(exc)[:450]}]
    issues = []
    for message in errors:
        if message.startswith("text overflows") or "text does not fit" in message:
            code = "text-fit"
        elif message.startswith("low contrast"):
            code = "contrast"
        elif message.startswith("unintended overlap"):
            code = "collision"
        elif "shaping" in message:
            code = "font-support"
        else:
            code = "quality"
        issues.append({"code": code, "message": message[:450]})
    return issues[:40]


def inspect(spec: dict[str, Any]) -> dict[str, Any]:
    """Read-only structured quality report; no I/O, edits or exports."""
    problems = _report(spec)
    return {"passed": not problems, "issue_count": len(problems),
            "issues": problems, "repairable": any(x["code"] in
            {"text-fit", "contrast", "collision", "invalid"} for x in problems)}


def _unlocked(el: dict[str, Any]) -> bool:
    return not el.get("locked", False) and not el.get("hidden", False)


def _group_locked(elements: list[dict[str, Any]], el: dict[str, Any]) -> bool:
    group = el.get("group")
    return bool(group) and any(other.get("group") == group and other.get("locked")
                               for other in elements)


def _positions(el: dict[str, Any]) -> tuple[float, float, float, float] | None:
    if el.get("type") not in {"text", "image", "icon", "rect"}:
        return None
    try:
        return tuple(float(el[k]) for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):
        return None


def _collision(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a.get("allow_overlap") or b.get("allow_overlap"):
        return False
    if a.get("group") and a.get("group") == b.get("group"):
        return False
    av, bv = _positions(a), _positions(b)
    if not av or not bv:
        return False
    ax, ay, aw, ah = av
    bx, by, bw, bh = bv
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return False
    area = ix * iy
    return area > 100 and area / min(aw * ah, bw * bh) >= .12


def _visible_content(elements: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    return [(i, e) for i, e in enumerate(elements) if
            e.get("type") in {"text", "icon", "image"} and not e.get("hidden", False) and
            (e.get("type") != "text" or bool(e.get("text", "").strip()))]


def _record(changes: list[dict[str, Any]], i: int, field: str,
            old: Any, new: Any, why: str) -> None:
    if old != new and len(changes) < MAX_REPAIRS:
        changes.append({"element": i, "field": field, "before": old,
                        "after": new, "reason": why})


def _move_to_canvas(spec: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    w, h = spec["width"], spec["height"]
    for i, e in enumerate(spec["elements"]):
        if not _unlocked(e) or _group_locked(spec["elements"], e):
            continue
        p = _positions(e)
        if p:
            x, y, ew, eh = p
            if ew > w or eh > h or ew <= 0 or eh <= 0:
                continue   # Never crop or distort supplied images to fit.
            for field, old, upper in (("x", x, w-ew), ("y", y, h-eh)):
                new = round(max(0, min(old, upper)), 2)
                if new != old:
                    e[field] = new
                    _record(changes, i, field, old, new, "Keep object inside the canvas")
        elif e.get("type") == "line" and not e.get("from_group") and not e.get("to_group"):
            for field, maximum in (("x1",w),("x2",w),("y1",h),("y2",h)):
                try: old=float(e[field])
                except (TypeError, ValueError, KeyError): continue
                new=round(max(0,min(old,maximum)),2)
                if old != new:
                    e[field] = new
                    _record(changes,i,field,old,new,"Keep connector inside the canvas")


def _fix_fit(spec: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    for i, e in enumerate(spec["elements"]):
        if e.get("type") != "text" or not _unlocked(e) or _group_locked(spec["elements"],e):
            continue
        p=_positions(e)
        if not p: continue
        original=e.get("font_size",25)
        try:
            start=int(float(original))
        except (ValueError,TypeError): continue
        if not MIN_TEXT<=start<=90: continue
        test={"type":"text","w":p[2],"h":p[3],"text":e.get("text",""),
              "size":start,"bold":e.get("bold",False)}
        try:
            _text_lines(test)
            continue
        except VisualError:
            pass
        for font in range(start-1,MIN_TEXT-1,-1):
            test["size"]=font
            try:
                _text_lines(test)
                e["font_size"]=font
                _record(changes,i,"font_size",original,font,
                        "Fit exact wording without truncation")
                break
            except VisualError:
                continue


def _fix_contrast(spec: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    background = {
        "editorial-light":"#F8F9F7", "illustrated-workflow":"#FAFAF6",
        "premium-tech":"#0D1729", "commercial":"#FBF7F0",
    }.get(spec.get("theme"),"#FFFFFF")
    background = (spec.get("colours") or {}).get("background",background)
    for i,e in enumerate(spec["elements"]):
        if e.get("type")!="text" or not _unlocked(e) or _group_locked(spec["elements"],e):
            continue
        p=_positions(e)
        if not p or not e.get("text","").strip():continue
        x,y,w,h=p
        bg=background
        # A text layer receives its background from the most recent rectangle
        # painted at its first-line centre, not from decorative shapes drawn later.
        for prev in spec["elements"][:i]:
            q=_positions(prev)
            if (prev.get("type")=="rect" and not prev.get("hidden") and q and
                q[0]<=x+w/2<=q[0]+q[2] and q[1]<=y+min(h/2,e.get("font_size",25)*.65)<=q[1]+q[3]):
                bg=prev.get("fill",bg)
        old=e.get("colour", "#22252C")
        try:
            font=float(e.get("font_size",25))
            threshold=3.0 if (font>=24 and e.get("bold")) or font>=30 else 4.5
            if _contrast(old,bg)>=threshold:continue
            dark,light="#172638","#FFFFFF"
            choice=max((dark,light),key=lambda candidate:_contrast(candidate,bg))
            if _contrast(choice,bg)<threshold:continue
        except (ValueError,TypeError):continue
        e["colour"]=choice
        e.pop("auto_colour",None)
        _record(changes,i,"colour",old,choice,"Repair unreadable text contrast")


def _fix_collision(spec:dict[str, Any],changes:list[dict[str,Any]]) -> None:
    elements=spec["elements"]
    indices=_visible_content(elements)
    if len(indices)<2:return
    width,height=spec["width"],spec["height"]
    for i,e in indices:
        if e.get("type") not in {"text","icon"} or not _unlocked(e):
            continue
        if e.get("group") or _group_locked(elements,e):
            continue   # Do not split a designed group or alter protected photographs.
        p=_positions(e)
        if not p:continue
        x,y,w,h=p
        if w>width or h>height:continue
        blockers=[other for j,other in indices if j!=i]
        if not any(_collision(e,other) for other in blockers):continue
        # Search deterministic nearby positions. Prioritise no movement or a
        # short move. Keep text above the same horizontal baseline if possible.
        candidates=[]
        for yy in range(16, max(17,int(height-h)+1),20):
            for xx in range(16,max(17,int(width-w)+1),20):
                candidates.append((abs(xx-x)+abs(yy-y),xx,yy))
        candidates.sort()
        for _,xx,yy in candidates:
            proposed={**e,"x":xx,"y":yy}
            if not any(_collision(proposed,other) for other in blockers):
                e["x"],e["y"]=xx,yy
                _record(changes,i,"x",x,xx,"Move text/icon away from independent artwork")
                _record(changes,i,"y",y,yy,"Move text/icon away from independent artwork")
                break


def repair(spec: dict[str, Any]) -> dict[str,Any]:
    """Return reversible recommended adjustments. No file I/O or side effects."""
    if not isinstance(spec,dict) or spec.get("layout")!="canvas":
        raise VisualError("Visual Repair currently supports individual editable canvases")
    if not isinstance(spec.get("elements"),list) or len(spec["elements"])>40:
        raise VisualError("invalid canvas element list")
    if any(not isinstance(item,dict) for item in spec["elements"]):
        raise VisualError("every editable canvas element must be an object")
    width,height=spec.get("width",1280),spec.get("height",720)
    if any(isinstance(value,bool) or not isinstance(value,(float,int)) or
           not 1<=value<=1920 for value in (width,height)):
        raise VisualError("canvas width/height must be positive bounded numbers")
    if width*height>2_100_000:
        raise VisualError("canvas exceeds the 2.1 megapixel limit")
    if spec.get("colours") is not None and not isinstance(spec["colours"],dict):
        raise VisualError("design colours must be an object")
    current=deepcopy(spec)
    current.setdefault("width",1280)
    current.setdefault("height",720)
    before=inspect(current)
    edits=[]
    _move_to_canvas(current,edits)
    _fix_fit(current,edits)
    _fix_collision(current,edits)
    # Contrast is assessed after placement so a moved label uses the new
    # underlying colour rather than the one at its original position.
    _fix_contrast(current,edits)
    after=inspect(current)
    return {
        "spec":current,"changes":edits,"changed":bool(edits),
        "before":before,"after":after,
        "message":("Suggestions generated. Inspect each change before accepting."
                   if edits else "No safe deterministic repair found; manual editing may be necessary.")
    }
