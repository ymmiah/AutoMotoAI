"""Shared, bounded design scene for editable PowerPoint, SVG, PNG and animated GIF.

No network, code evaluation, downloaded fonts or remote resources. Supplied images
are embedded or aspect-fitted without generative reconstruction; originals stay
unchanged. Coordinates are pixels in the requested canvas, not HTML/CSS.
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any

from automoto import sandbox

class VisualError(ValueError):
    """Invalid design or unavailable source asset."""

THEMES = {
    "editorial-light": {"background":"#F8F9F7", "ink":"#172638", "muted":"#526476",
                        "accent":"#246D83", "card":"#FFFFFF", "border":"#DCE5E9",
                        "tones":["#E8F3F1","#E7ECFB","#FFF0CF","#F5E9F5","#E6F3FC","#EDF5DE"]},
    "illustrated-workflow": {"background":"#FAFAF6", "ink":"#22252C", "muted":"#5A606B",
                        "accent":"#6350A4", "card":"#FFFFFF", "border":"#25252D",
                        "tones":["#E8DBFA","#D6E9FF","#FFF1AA","#DFEDB8","#FFE4DE","#DDF4EB"]},
    "premium-tech": {"background":"#0D1729", "ink":"#F8FAFC", "muted":"#C3D0E1",
                        "accent":"#56B2FA", "card":"#19283E", "border":"#34465E",
                        "tones":["#203D64","#234E51","#534267","#4A3E35","#294B66","#3F4D3A"]},
    "commercial": {"background":"#FBF7F0", "ink":"#2C2520", "muted":"#61594F",
                        "accent":"#A65B42", "card":"#FFFFFF", "border":"#E6D8CB",
                        "tones":["#F6E3D5","#EDE1D1","#E7E7D9","#F6D9D7","#E0E7EF","#F3E4B5"]},
}
ICONS = {"check","shield","idea","lightbulb","chart","growth","users","person",
         "clock","target","cloud","file","folder","image","sparkle","star","arrow",
         "globe","code","lock","settings"}

def colour(value: Any) -> str:
    if not isinstance(value,str) or not re.fullmatch(r"#[0-9a-fA-F]{6}",value):
        raise VisualError("colour must be a six-digit #RRGGBB value")
    return value.upper()

def number(value: Any, name: str, lo: float, hi: float) -> float:
    if isinstance(value,bool):
        raise VisualError(f"{name} must be a number")
    try: n=float(value)
    except (TypeError,ValueError):
        raise VisualError(f"{name} must be a number") from None
    if not math.isfinite(n) or not lo<=n<=hi:
        raise VisualError(f"{name} must be between {lo} and {hi}")
    return n

def bounded_text(value: Any, field: str, maximum: int=180) -> str:
    if not isinstance(value,str) or len(value)>maximum:
        raise VisualError(f"{field} must be text with at most {maximum} characters")
    # prevent accidental null/control chars in exported documents
    if any(ord(ch)<32 and ch not in "\n\t" for ch in value):
        raise VisualError(f"{field} contains unsupported control characters")
    return value

def source_image(path: str) -> tuple[Path,str]:
    from PIL import Image, ImageOps
    if not isinstance(path,str) or len(path)>1000:
        raise VisualError("image path must be a workspace filename")
    p=sandbox.resolve(path,allow_outside=True)
    if not p.is_file() or p.suffix.lower() not in {".png",".jpg",".jpeg",".webp",".bmp"}:
        raise VisualError("image must be a local PNG, JPEG, WebP or BMP file")
    if p.stat().st_size>24*1024*1024:
        raise VisualError("image exceeds the 24 MB limit")
    try:
        with Image.open(p) as im:
            if im.width*im.height>36_000_000 or getattr(im,"n_frames",1)>1:
                raise VisualError("image must be a single frame of at most 36 megapixels")
            im.verify()
    except (OSError,ValueError) as exc:
        if isinstance(exc,VisualError): raise
        raise VisualError(f"unable to read source image: {exc}") from None
    return p,hashlib.sha256(p.read_bytes()).hexdigest()

def _rect(x,y,w,h,fill,stroke=None,radius=18,stroke_width=2,role=""):
    return {"type":"rect","x":round(x,2),"y":round(y,2),"w":round(w,2),"h":round(h,2),
            "fill":colour(fill),"stroke":colour(stroke) if stroke else None,
            "radius":radius,"stroke_width":stroke_width,"role":role}

def _text(x,y,w,h,txt,size,ink,bold=False,role=""):
    return {"type":"text","x":round(x,2),"y":round(y,2),"w":round(w,2),"h":round(h,2),
            "text":bounded_text(txt,"text",1600),"size":size,"colour":colour(ink),
            "bold":bool(bold),"role":role}

def _icon(x,y,size,name,ink):
    if name not in ICONS: raise VisualError(f"unsupported icon: {name}")
    return {"type":"icon","x":round(x,2),"y":round(y,2),"w":size,"h":size,
            "name":name,"colour":colour(ink)}

def _line(x1,y1,x2,y2,ink,width=3):
    return {"type":"line","x1":round(x1,2),"y1":round(y1,2),
            "x2":round(x2,2),"y2":round(y2,2),"colour":colour(ink),"width":width}

def _image(x,y,w,h,path,alt,assets):
    p,digest=source_image(path)
    assets.append({"path":sandbox.rel(p),"sha256":digest,"protected":True})
    return {"type":"image","x":round(x,2),"y":round(y,2),"w":round(w,2),"h":round(h,2),
            "path":str(p),"alt":bounded_text(alt,"alt",250)}

def _box_valid(e,w,h):
    if e["type"]=="line":
        a=[e["x1"],e["x2"]]; b=[e["y1"],e["y2"]]
        return min(a)>=0 and max(a)<=w and min(b)>=0 and max(b)<=h
    return (e.get("x",0)>=0 and e.get("y",0)>=0 and
            e.get("w",0)>0 and e.get("h",0)>0 and
            e["x"]+e["w"]<=w+0.1 and e["y"]+e["h"]<=h+0.1)

def _scene(spec:dict[str,Any]) -> dict:
    if not isinstance(spec,dict): raise VisualError("design spec must be a JSON object")
    # Limit dimensions for predictable memory and processing across hosts.
    w=int(number(spec.get("width",1280),"width",640,1920))
    h=int(number(spec.get("height",720),"height",400,1080))
    if w*h>2_100_000: raise VisualError("canvas exceeds 2.1 megapixels")
    theme_name=str(spec.get("theme","illustrated-workflow"))
    if theme_name not in THEMES: raise VisualError("unknown theme: "+theme_name)
    t=dict(THEMES[theme_name])
    for k in ("background","ink","muted","accent","card","border"):
        if k in (spec.get("colours") or {}):
            t[k]=colour(spec["colours"][k])
    layout=str(spec.get("layout","workflow"))
    if layout not in {"workflow","cards","hero","canvas"}:
        raise VisualError("layout must be workflow, cards, hero or canvas")
    title=bounded_text(spec.get("title",""),"title",130)
    subtitle=bounded_text(spec.get("subtitle",""),"subtitle",250)
    footer=bounded_text(spec.get("footer",""),"footer",160)
    margin=max(28,round(w*.052))
    heading_size=max(30,round(h*.068))
    elements:list[dict]=[]
    assets:list[dict]=[]
    # Native layered artboards must not acquire an unexpected title strip
    # when reopened: every visible object should be an actual editable layer.
    plain = spec.get("artboard_only",False)
    if not isinstance(plain,bool) or (plain and layout!="canvas"):
        raise VisualError("artboard_only is supported only for canvas layouts")
    if not plain:
        elements.append(_rect(0,0,w,h,t["background"],radius=0,stroke_width=0,role="background"))
        elements.append(_rect(margin,margin*.68,max(48,round(w*.085)),max(5,round(h*.011)),
                              t["accent"],radius=4,stroke_width=0,role="accent"))
        logo=spec.get("brand_logo")
        reserve=min(round(w*.17),180) if logo else 0
        elements.append(_text(margin,margin*1.16,w-margin*2-reserve,heading_size*1.3,
                              title,heading_size,t["ink"],True,"heading"))
        if subtitle:
            elements.append(_text(margin,margin*1.16+heading_size*1.4,
                                  w-margin*2-reserve,round(h*.05),subtitle,max(17,round(h*.033)),
                                  t["muted"],False,"subtitle"))
        if logo:
            elements.append(_image(w-margin-reserve+14,margin*.81,reserve-16,
                                   max(34,round(h*.105)),str(logo),
                                   str(spec.get("brand_logo_alt") or "Original supplied brand logo"),assets))
    content_top=max(round(h*.30) if subtitle else round(h*.27),135)
    content_bottom=h-max(50,round(h*.095))
    content_h=content_bottom-content_top
    content_w=w-margin*2
    if content_h<150: raise VisualError("canvas leaves insufficient space for content")
    items=spec.get("nodes") if layout=="workflow" else spec.get("cards")
    if layout in {"workflow","cards"}:
        if not isinstance(items,list) or not 2<=len(items)<=6:
            raise VisualError(f"{layout} requires 2 to 6 node/card objects")
        if any(not isinstance(item,dict) for item in items):
            raise VisualError("all workflow nodes or cards must be objects")
        n=len(items)
        columns=(3 if n>=5 else 2 if n==4 else n)
        rows=math.ceil(n/columns)
        gap=max(16,round(w*.023))
        cell_w=(content_w-gap*(columns-1))/columns
        cell_h=(content_h-gap*(rows-1))/rows
        if cell_h<120 or cell_w<125:
            raise VisualError("too many cards for this canvas; choose larger dimensions")
        ids=[]
        centres={}
        for index,item in enumerate(items):
            name=str(item.get("id",f"node-{index+1}"))
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,45}",name) or name in ids:
                raise VisualError("node IDs must be unique short ASCII identifiers")
            ids.append(name)
            label=bounded_text(item.get("title",item.get("label","")),"node title",75)
            details=bounded_text(item.get("text",item.get("description","")),"node detail",160)
            icon=str(item.get("icon","file" if index==0 else "check" if index==n-1 else "settings"))
            if icon not in ICONS: raise VisualError(f"unsupported icon: {icon}")
            tone=item.get("tone",t["tones"][index%len(t["tones"])])
            tone=colour(tone)
            row=index//columns
            col=index%columns
            # Snake workflow reading order: across a row, down, then back.
            # This avoids a diagonal connector crossing unrelated cards.
            if layout=="workflow" and row%2:
                col=columns-1-col
            x=margin+col*(cell_w+gap);y=content_top+row*(cell_h+gap)
            elements.append(_rect(x,y,cell_w,cell_h,t["card"],t["border"],radius=22,stroke_width=2,role="card"))
            icon_size=min(52,max(30,round(cell_h*.27)))
            elements.append(_rect(x+16,y+14,icon_size+13,icon_size+13,tone,
                                  radius=16,stroke_width=0,role="icon-background"))
            elements.append(_icon(x+22,y+20,icon_size,icon,t["ink"]))
            # Use width-bounded headings and descriptions; measure during rendering.
            heading_offset=max(icon_size+36,min(96,round(cell_h*.36)))
            heading_y=y+heading_offset
            text_size=max(17,min(23,round(cell_w*.057)))
            heading_h=max(36,min(58,round(cell_h*.25)))
            elements.append(_text(x+19,heading_y,cell_w-38,heading_h,
                                  label,text_size,t["ink"],True,"card-heading"))
            if details:
                detail_y=heading_y+heading_h+4
                detail_h=cell_h-heading_offset-heading_h-13
                detail_size=max(15,min(19,round(cell_w*.043)))
                elements.append(_text(x+19,detail_y,cell_w-38,detail_h,
                                      details,detail_size,t["muted"],False,"card-detail"))
            centres[name]=(x+cell_w/2,y+cell_h/2)
        if layout=="workflow":
            links=spec.get("links",[])
            if links is None: links=[]
            if not isinstance(links,list) or len(links)>12:
                raise VisualError("links must contain no more than twelve connections")
            if not links:
                links=[{"from":ids[j],"to":ids[j+1]} for j in range(n-1)]
            # Draw connectors on top of the cards but keep endpoints between boundaries.
            for link in links:
                if not isinstance(link,dict): raise VisualError("link must be an object")
                a,b=link.get("from"),link.get("to")
                if a not in centres or b not in centres or a==b:
                    raise VisualError("link endpoints must name two different existing nodes")
                ax,ay=centres[a];bx,by=centres[b]
                if abs(ay-by)<2:
                    sign=1 if bx>ax else -1
                    off=cell_w*.50+3
                    x1,y1=ax+sign*off,ay
                    x2,y2=bx-sign*off,by
                else:
                    sign=1 if by>ay else -1
                    off=cell_h*.50+3
                    x1,y1=ax,ay+sign*off
                    x2,y2=bx,by-sign*off
                # connections in a single row may go in gaps; the visual marker
                # is used by GIF animation to show live flow.
                elements.append(_line(x1,y1,x2,y2,t["accent"],3))
            # Connectors belong under cards, never above content or labels.
            connectors=[element for element in elements if element["type"]=="line"]
            elements=[element for element in elements if element["type"]!="line"]
            first_card=next((i for i,element in enumerate(elements)
                             if element.get("role")=="card"),len(elements))
            elements[first_card:first_card]=connectors
    elif layout=="hero":
        path=spec.get("image")
        if not path: raise VisualError("hero requires a source image path")
        side=str(spec.get("image_side","right"))
        if side not in {"left","right"}: raise VisualError("image_side must be left or right")
        image_w=content_w*.48
        image_h=content_h
        ix=margin if side=="left" else w-margin-image_w
        tx=w-margin-image_w+20 if side=="left" else margin
        elements.append(_rect(ix,content_top,image_w,image_h,t["card"],t["border"],radius=20))
        elements.append(_image(ix+10,content_top+10,image_w-20,image_h-20,
                               str(path),str(spec.get("alt") or "Original source image"),assets))
        body=bounded_text(spec.get("text",""),"hero text",440)
        elements.append(_text(tx,content_top+30,content_w-image_w-42,content_h*.75,
                              body,max(20,round(h*.044)),t["ink"],True,"hero-text"))
    else:
        user=spec.get("elements")
        if not isinstance(user,list) or not 0<=len(user)<=40:
            raise VisualError("canvas requires 0 to 40 elements")
        hidden_groups={item.get("group") for item in user
                       if isinstance(item,dict) and item.get("hidden") is True and item.get("group")}
        for element in user:
            if not isinstance(element,dict): raise VisualError("canvas elements must be objects")
            for flag in ("hidden","locked"):
                if flag in element and not isinstance(element[flag],bool):
                    raise VisualError(f"{flag} must be true or false")
            if element.get("hidden",False):
                continue  # Keep source draft unchanged; omit this layer in every export.
            kind=element.get("type")
            if kind=="line" and any(element.get(key) in hidden_groups
                                    for key in ("from_group","to_group")):
                continue
            if kind=="line":
                e=_line(number(element.get("x1"),"x1",0,w),number(element.get("y1"),"y1",0,h),
                        number(element.get("x2"),"x2",0,w),number(element.get("y2"),"y2",0,h),
                        element.get("colour",t["accent"]),
                        number(element.get("stroke_width",3),"stroke_width",1,12))
            else:
                x=number(element.get("x"),"x",0,w)
                y=number(element.get("y"),"y",0,h)
                ew=number(element.get("w"),"w",1,w)
                eh=number(element.get("h"),"h",1,h)
                if kind=="text":
                    e=_text(x,y,ew,eh,bounded_text(element.get("text",""),"text",1600),
                            number(element.get("font_size",25),"font_size",12,90),
                            element.get("colour",t["ink"]),bool(element.get("bold")),"user-text")
                elif kind=="rect":
                    e=_rect(x,y,ew,eh,element.get("fill",t["card"]),
                            element.get("stroke",t["border"]),radius=number(element.get("radius",14),"radius",0,100))
                elif kind=="icon":
                    e=_icon(x,y,min(ew,eh),str(element.get("name","sparkle")),
                            element.get("colour",t["accent"]))
                elif kind=="image":
                    e=_image(x,y,ew,eh,str(element.get("path","")),
                             str(element.get("alt","Original source image")),assets)
                else:
                    raise VisualError("canvas type must be text, rect, icon, image or line")
            # Preserve semantic grouping in the compiled scene so visual
            # inspection can distinguish deliberate card contents from
            # accidentally overlapping independent objects.
            if "group" in element:
                group=element["group"]
                if not isinstance(group,str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,50}",group):
                    raise VisualError("canvas group must be a short ASCII identifier")
                e["group"]=group
            if "allow_overlap" in element:
                if not isinstance(element["allow_overlap"],bool):
                    raise VisualError("allow_overlap must be true or false")
                e["allow_overlap"]=element["allow_overlap"]
            if kind=="line":
                for anchor in ("from_group","to_group"):
                    if anchor in element:
                        value=element[anchor]
                        if not isinstance(value,str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,50}",value):
                            raise VisualError(f"{anchor} must name a short ASCII group")
                        e[anchor]=value
            elements.append(e)
    if footer:
        elements.append(_text(margin,h-max(39,round(h*.057)),content_w,
                              max(16,round(h*.037)),footer,max(13,round(h*.023)),t["muted"],False,"footer"))
    for e in elements:
        if not _box_valid(e,w,h):
            raise VisualError(f"{e['type']} lies outside the design canvas")
    return {"width":w,"height":h,"theme":theme_name,"tokens":t,"elements":elements,
            "assets":assets,"layout":layout,"title":title,"notes":bounded_text(spec.get("notes",""),"notes",4000)}

def compile_scene(spec: dict[str,Any]) -> dict:
    """The single validated representation shared by every exporter."""
    return _scene(spec)
