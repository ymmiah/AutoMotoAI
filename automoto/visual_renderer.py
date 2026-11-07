"""Render a compiled AutoMoto scene to actual SVG, PNG, PDF, editable PPTX or animated GIF."""
from __future__ import annotations

import base64
import io
import math
import os
import re
from html import escape
from pathlib import Path
from typing import Any

from automoto.visual_foundation import VisualError, compile_scene, colour

def _hexrgb(s):
    return tuple(int(s[x:x+2],16) for x in (1,3,5))

def _font(size, bold=False):
    from PIL import ImageFont
    names=(["DejaVuSans-Bold.ttf","LiberationSans-Bold.ttf","Arial Bold.ttf"]
           if bold else ["DejaVuSans.ttf","LiberationSans-Regular.ttf","Arial.ttf"])
    for name in names:
        try: return ImageFont.truetype(name,max(8,round(float(size))))
        except OSError: pass
    # Missing Unicode fonts must not result in fake glyphs or invented text.
    return ImageFont.load_default()

def _wrap(text, font, width, draw):
    """Wrap by measured glyph widths while keeping the source text exactly unchanged."""
    result=[]
    for original in text.split("\n"):
        line=""
        if not original:
            result.append("");continue
        for word in original.split():
            candidate=word if not line else line+" "+word
            if draw.textbbox((0,0),candidate,font=font)[2] <= width:
                line=candidate
            else:
                if line: result.append(line)
                if draw.textbbox((0,0),word,font=font)[2] > width:
                    raise VisualError("text does not fit its box; shorten the text or widen the box")
                line=word
        if line: result.append(line)
    return result

def _text_lines(e):
    from PIL import Image,ImageDraw
    im=Image.new("RGB",(2,2))
    d=ImageDraw.Draw(im)
    f=_font(e["size"],e.get("bold",False))
    lines=_wrap(e["text"],f,e["w"],d)
    line_h=max(float(e["size"])*1.26, 13)
    if len(lines)*line_h > e["h"]+2:
        raise VisualError(f"text overflows its box ({e.get('role') or 'text'}): "
                          "shorten the wording or increase the canvas size")
    return lines,f,line_h

def _luminance(hex_colour):
    channels=[component/255 for component in _hexrgb(hex_colour)]
    adjusted=[channel/12.92 if channel<=0.04045 else ((channel+0.055)/1.055)**2.4
              for channel in channels]
    return sum(a*b for a,b in zip(adjusted,(0.2126,0.7152,0.0722)))

def _contrast(a,b):
    la,lb=_luminance(a),_luminance(b)
    hi,lo=max(la,lb),min(la,lb)
    return (hi+0.05)/(lo+0.05)

def repair_text_fitting(scene):
    """Targeted text-size repair; never truncate, replace or paraphrase wording."""
    lower_bounds={"heading":24,"subtitle":15,"card-heading":15,"card-detail":13,
                  "hero-text":17,"footer":12}
    fixes=[]
    for e in scene["elements"]:
        if e["type"]!="text" or not e.get("text","").strip():
            continue
        role=e.get("role","")
        if role not in lower_bounds:
            continue  # manually positioned text should not change size unexpectedly
        original=float(e["size"])
        floor=max(lower_bounds[role],round(original*.68))
        while e["size"]>floor:
            try:
                _text_lines(e)
                break
            except VisualError:
                e["size"]=round(float(e["size"])-1,2)
        if e["size"]!=original:
            fixes.append({"role":role,"old_size":original,"new_size":e["size"]})
    scene["text_repairs"]=fixes
    return fixes

def quality(scene):
    from PIL import features
    findings=[]
    rectangles=[]
    for e in scene["elements"]:
        if e["type"]=="rect":
            rectangles.append(e)
        if e["type"]=="text":
            try:_text_lines(e)
            except VisualError as exc:findings.append(str(exc))
            if re.search(r"[\u0590-\u08FF]",e["text"]) and not features.check("raqm"):
                findings.append("complex-script shaping support is unavailable for raster export")
            if not e["text"].strip():
                continue
            px=e["x"]+e["w"]/2
            py=e["y"]+min(e["h"]/2,e["size"]*.65)
            bg=scene["tokens"]["background"]
            for rect in rectangles:
                if rect["x"]<=px<=rect["x"]+rect["w"] and rect["y"]<=py<=rect["y"]+rect["h"]:
                    bg=rect["fill"]
            # WCAG AA: 4.5:1 normal text, 3:1 larger/bold display text.
            target=3.0 if (e["size"]>=24 and e.get("bold")) or e["size"]>=30 else 4.5
            ratio=_contrast(e["colour"],bg)
            if ratio<target:
                findings.append(f"low contrast ({ratio:.1f}:1) in {e.get('role') or 'text'}; "
                                f"requires at least {target:.1f}:1")
    if scene.get("layout")=="canvas":
        # Text, icons and unmodified photos should not accidentally cover
        # unrelated objects. Cards intentionally layer their own grouped
        # content on card backgrounds; those are deliberately excluded.
        items=[e for e in scene["elements"] if e["type"] in ("text","icon","image")
               and e.get("role") not in {"heading","subtitle","footer"}
               and (e["type"]!="text" or e.get("text","").strip())]
        for i,a in enumerate(items):
            for b in items[i+1:]:
                if a.get("allow_overlap") or b.get("allow_overlap"):
                    continue
                if a.get("group") and a.get("group")==b.get("group"):
                    continue
                ix=max(0,min(a["x"]+a["w"],b["x"]+b["w"])-max(a["x"],b["x"]))
                iy=max(0,min(a["y"]+a["h"],b["y"]+b["h"])-max(a["y"],b["y"]))
                if ix*iy>100 and ix*iy/min(a["w"]*a["h"],b["w"]*b["h"])>=.12:
                    findings.append("unintended overlap between independent "
                                    f"{a['type']} and {b['type']} elements; "
                                    "reposition them, group them, or explicitly allow_overlap")
                    if len(findings)>=10:
                        return findings
    return findings

def _icon_png(draw,e,scale=1):
    x=int(e["x"]*scale);y=int(e["y"]*scale)
    side=max(10,int(e["w"]*scale));c=e["colour"]
    # Icons are drawn in native vector primitives rather than dependent fonts.
    def xy(a,b):return (int(x+side*a),int(y+side*b))
    def line(points,width=.08):
        draw.line([xy(*pt) for pt in points],fill=c,width=max(2,int(side*width)),joint="curve")
    def circle(a,b,d,fill=None,width=2):
        draw.ellipse((*xy(a,b),*xy(a+d,b+d)),fill=fill,outline=c,width=max(2,int(width*scale)))
    def rect(a,b,wa,hb,fill=None,r=.08):
        draw.rounded_rectangle((*xy(a,b),*xy(a+wa,b+hb)),radius=max(2,int(side*r)),fill=fill,outline=c,width=max(2,int(side*.055)))
    name=e["name"]
    if name in {"check"}:line([(.12,.52),(.42,.82),(.89,.16)],.1)
    elif name in {"shield"}:
        line([(.5,.08),(.86,.23),(.78,.68),(.50,.93),(.22,.68),(.14,.23),(.5,.08)],.08)
        line([(.31,.51),(.45,.65),(.68,.39)],.075)
    elif name in {"chart","growth"}:
        for xx,top in ((.1,.51),(.38,.31),(.66,.12)):rect(xx,top,.20,.83-top,fill=c)
    elif name in {"file","folder","image"}:
        rect(.19,.09,.63,.82)
        if name=="image":circle(.57,.23,.12,c);line([(.26,.70),(.44,.45),(.57,.61),(.73,.43)],.055)
        elif name=="folder":rect(.22,.19,.32,.15,fill=c)
        else:
            for yy in (.38,.54,.68):line([(.29,yy),(.70,yy)],.055)
    elif name in {"users","person"}:
        circle(.36,.13,.28,fill=c)
        rect(.21,.48,.58,.38,fill=c)
    elif name=="clock":
        circle(.10,.1,.8)
        line([(.50,.50),(.50,.25)],.07);line([(.50,.50),(.70,.60)],.07)
    elif name=="target":
        for a,d in ((.1,.8),(.26,.48),(.42,.16)):circle(a,a,d)
    elif name=="cloud":
        circle(.17,.38,.35,fill=c);circle(.41,.21,.38,fill=c);rect(.16,.56,.70,.20,fill=c)
    elif name in {"lock"}:
        circle(.28,.12,.44);rect(.20,.49,.60,.38,fill=c)
    elif name in {"code"}:
        line([(.40,.20),(.17,.50),(.40,.80)],.08)
        line([(.60,.20),(.83,.50),(.60,.80)],.08)
    elif name=="globe":
        circle(.10,.10,.80);line([(.10,.50),(.90,.50)],.045)
        line([(.50,.10),(.50,.90)],.045)
    elif name=="arrow":
        line([(.16,.50),(.86,.50),(.59,.25)],.09)
        line([(.86,.50),(.59,.76)],.09)
    elif name in {"idea","lightbulb"}:
        circle(.26,.10,.50);rect(.40,.65,.20,.18,fill=c)
    elif name in {"sparkle","star"}:
        line([(.5,.07),(.5,.91)],.1);line([(.11,.49),(.89,.49)],.1)
    else:
        circle(.12,.12,.76);circle(.38,.38,.24,fill=c)

def _image_data(e):
    from PIL import Image,ImageOps
    p=Path(e["path"])
    with Image.open(p) as im:
        im.load()
        original=ImageOps.exif_transpose(im).convert("RGBA")
    return original

def _draw_element(im,draw,e,scale=1):
    from PIL import Image,ImageDraw,ImageOps
    t=e["type"]
    if t=="rect":
        box=(round(e["x"]*scale),round(e["y"]*scale),
             round((e["x"]+e["w"])*scale),round((e["y"]+e["h"])*scale))
        draw.rounded_rectangle(box,radius=max(0,round(e["radius"]*scale)),
                               fill=e["fill"],outline=e.get("stroke"),
                               width=max(1,round(e.get("stroke_width",1)*scale)) if e.get("stroke") else 1)
    elif t=="line":
        points=[(round(e["x1"]*scale),round(e["y1"]*scale)),
                (round(e["x2"]*scale),round(e["y2"]*scale))]
        draw.line(points,fill=e["colour"],width=max(1,round(e["width"]*scale)))
    elif t=="text":
        lines,font,line_h=_text_lines(e)
        if scale!=1: font=_font(e["size"]*scale,e.get("bold",False))
        for index,line in enumerate(lines):
            draw.text((round(e["x"]*scale),round((e["y"]+index*line_h)*scale)),
                      line,font=font,fill=e["colour"])
    elif t=="icon":
        _icon_png(draw,e,scale)
    elif t=="image":
        image=_image_data(e)
        box_w=max(1,round(e["w"]*scale));box_h=max(1,round(e["h"]*scale))
        image=ImageOps.contain(image,(box_w,box_h),Image.Resampling.LANCZOS)
        px=round(e["x"]*scale+(box_w-image.width)/2)
        py=round(e["y"]*scale+(box_h-image.height)/2)
        im.paste(image,(px,py),image)

def sequence_stages(scene:dict,config:dict) -> dict[str,float]:
    """Validate a compact, group-based reveal timeline. No code or expressions."""
    if not isinstance(config,dict):
        raise VisualError("animation must be a JSON object")
    stages=config.get("stages")
    if not isinstance(stages,list) or not 1<=len(stages)<=12:
        raise VisualError("sequence animation requires 1 to 12 stages")
    groups={e["group"] for e in scene["elements"] if e.get("group")}
    seen={}
    for step in stages:
        if not isinstance(step,dict) or set(step)!={"group","start"}:
            raise VisualError("each animation stage must contain only group and start")
        key=step["group"]
        if not isinstance(key,str) or key not in groups or key in seen:
            raise VisualError("animation stage names must be unique visible design groups")
        value=step["start"]
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or not 0<=value<1:
            raise VisualError("animation stage start must be a number from 0 to below 1")
        seen[key]=float(value)
    return seen


def raster(scene,scale=1.0,progress=None,effect="flow",animation=None):
    from PIL import Image,ImageDraw
    w,h=scene["width"],scene["height"]
    im=Image.new("RGB",(round(w*scale),round(h*scale)),scene["tokens"]["background"])
    draw=ImageDraw.Draw(im)
    elements=scene["elements"]
    if progress is not None and effect=="keyframes":
        from automoto.visual_motion import motion_raster
        return motion_raster(scene, progress, animation or {}, scale)
    if progress is not None and effect=="sequence":
        starts=sequence_stages(scene,animation or {})
        visible={group for group,start in starts.items() if progress>=start}
        for e in elements:
            group=e.get("group")
            if group in starts and group not in visible:
                continue
            # A connection becomes visible only when both endpoint stages have appeared.
            if e["type"]=="line" and any(e.get(k) in starts and e.get(k) not in visible
                                         for k in ("from_group","to_group")):
                continue
            _draw_element(im,draw,e,scale)
    elif progress is not None and effect=="reveal":
        revealable=[i for i,e in enumerate(elements) if e.get("role")=="card"]
        # Card/icon/text groups remain logically tied by paint order and spatial
        # containment; reveal per column rather than producing static duplicates.
        visible=math.ceil(progress*len(revealable))
        display_cards=revealable[:visible]
        card_rects=[elements[i] for i in display_cards]
        for e in elements:
            if e.get("role")=="background":_draw_element(im,draw,e,scale);continue
            if e.get("role")=="card" and e not in card_rects:continue
            if e.get("role") in {"heading","subtitle","accent","footer"}:
                _draw_element(im,draw,e,scale);continue
            if e["type"]=="line":continue
            cx=e.get("x",0)+e.get("w",0)/2
            cy=e.get("y",0)+e.get("h",0)/2
            if any(c["x"]<=cx<=c["x"]+c["w"] and c["y"]<=cy<=c["y"]+c["h"] for c in card_rects):
                _draw_element(im,draw,e,scale)
    else:
        for e in elements:_draw_element(im,draw,e,scale)
    if progress is not None:
        if effect in {"flow","pulse","float"}:
            accent=scene["tokens"]["accent"]
            edges=[e for e in elements if e["type"]=="line"]
            nodes=[e for e in elements if e.get("role")=="icon-background"]
            if edges and effect=="flow":
                for index,e in enumerate(edges):
                    step=(progress+index/max(1,len(edges)))%1
                    cx=e["x1"]+(e["x2"]-e["x1"])*step
                    cy=e["y1"]+(e["y2"]-e["y1"])*step
                    radius=max(5,round(9*scale))
                    draw.ellipse((round(cx*scale)-radius,round(cy*scale)-radius,
                                  round(cx*scale)+radius,round(cy*scale)+radius),
                                 fill=accent,outline=scene["tokens"]["ink"],width=max(1,round(2*scale)))
            elif nodes:
                index=min(len(nodes)-1,int(progress*len(nodes)))
                n=nodes[index]
                cx=(n["x"]+n["w"]/2)*scale
                cy=(n["y"]+n["h"]/2)*scale
                rad=(n["w"]*.54 + 7*math.sin(progress*math.pi*2))*scale
                draw.ellipse((round(cx-rad),round(cy-rad),round(cx+rad),round(cy+rad)),
                             outline=accent,width=max(2,round(4*scale)))
            else:
                # Hero and freeform scenes also need real moving frames, not a
                # sequence of identical stills.
                bar=max(18,int(scene["width"]*.14*scale))
                bx=int(scene["width"]*.052*scale)+round(progress*bar)
                by=int(scene["height"]*.965*scale)
                draw.rounded_rectangle((bx,by,bx+round(30*scale),by+round(7*scale)),
                                       radius=max(2,round(3*scale)),fill=accent)
    return im

def _svg_icon(e):
    x,y,s=e["x"],e["y"],e["w"]
    name=e["name"];c=e["colour"]
    shape={
      "check":"<path d='M 12 52 L 41 82 L 90 15' />",
      "shield":"<path d='M50 8 L86 24 L79 70 L50 94 L21 70 L14 24 Z'/><path d='M30 50 L45 65 L70 37'/>",
      "file":"<rect x='18' y='9' width='64' height='82' rx='9'/><path d='M30 39 H70 M30 55 H70 M30 70 H70'/>",
      "chart":"<path d='M10 88 H90'/><path d='M19 86 V55 H35 V86 M43 86 V35 H59 V86 M67 86 V15 H83 V86'/>",
      "users":"<circle cx='50' cy='30' r='16'/><path d='M20 83 V64 Q20 48 50 48 Q80 48 80 64 V83 Z'/>",
      "clock":"<circle cx='50' cy='50' r='40'/><path d='M50 21 V50 L72 61'/>",
      "target":"<circle cx='50' cy='50' r='40'/><circle cx='50' cy='50' r='25'/><circle cx='50' cy='50' r='9'/>",
      "image":"<rect x='12' y='13' width='76' height='74' rx='7'/><circle cx='64' cy='34' r='9'/><path d='M20 75 L42 49 L58 65 L73 51'/>",
      "code":"<path d='M38 20 L15 50 L38 80 M62 20 L85 50 L62 80'/>",
      "arrow":"<path d='M12 50 H89 L60 24 M89 50 L60 76'/>",
      "lock":"<rect x='19' y='45' width='62' height='42' rx='7'/><path d='M31 45 V29 A19 19 0 0 1 69 29 V45'/>",
      "globe":"<circle cx='50' cy='50' r='40'/><path d='M10 50 H90 M50 10 V90 M29 20 Q50 50 29 80 M71 20 Q50 50 71 80'/>",
      "sparkle":"<path d='M50 5 L56 42 L95 50 L56 57 L50 95 L43 57 L5 50 L43 42 Z'/>",
      "idea":"<circle cx='50' cy='39' r='27'/><path d='M37 71 H63 M40 82 H60'/>",
    }.get(name,"<circle cx='50' cy='50' r='35'/><circle cx='50' cy='50' r='13'/>")
    return (f'<g transform="translate({x:g},{y:g}) scale({s/100:g})" stroke="{c}" '
            f'stroke-width="7" stroke-linecap="round" stroke-linejoin="round" fill="none">{shape}</g>')

def svg_string(scene):
    """Generate script-free SVG; source raster images are embedded as data, never linked."""
    w,h=scene["width"],scene["height"]
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">']
    for e in scene["elements"]:
        t=e["type"]
        if t=="rect":
            stroke=e["stroke"] or "none"
            parts.append(f'<rect x="{e["x"]}" y="{e["y"]}" width="{e["w"]}" height="{e["h"]}" '
                         f'rx="{e["radius"]}" fill="{e["fill"]}" stroke="{stroke}" '
                         f'stroke-width="{e.get("stroke_width",0)}"/>')
        elif t=="line":
            parts.append(f'<line x1="{e["x1"]}" y1="{e["y1"]}" x2="{e["x2"]}" y2="{e["y2"]}" '
                         f'stroke="{e["colour"]}" stroke-width="{e["width"]}" stroke-linecap="round"/>')
        elif t=="icon":
            parts.append(_svg_icon(e))
        elif t=="text":
            lines,_,line_h=_text_lines(e)
            parts.append(f'<text fill="{e["colour"]}" font-family="DejaVu Sans, Arial, sans-serif" '
                         f'font-weight="{700 if e.get("bold") else 400}" font-size="{e["size"]}">')
            for k,line in enumerate(lines):
                yy=e["y"]+e["size"]*.96+k*line_h
                parts.append(f'<tspan x="{e["x"]}" y="{yy:g}">{escape(line)}</tspan>')
            parts.append("</text>")
        elif t=="image":
            p=Path(e["path"])
            fmt={".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",
                 ".webp":"image/webp",".bmp":"image/bmp"}[p.suffix.lower()]
            data=base64.b64encode(p.read_bytes()).decode("ascii")
            parts.append(f'<image x="{e["x"]}" y="{e["y"]}" width="{e["w"]}" height="{e["h"]}" '
                         f'preserveAspectRatio="xMidYMid meet" xlink:href="data:{fmt};base64,{data}"/>')
    parts.append("</svg>")
    return "\n".join(parts)

def _pptx_scenes(scenes:list[dict],path:Path):
    """Native PowerPoint geometry and text, not a flattened PNG slideshow."""
    import pptx
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.enum.text import MSO_AUTO_SIZE, MSO_ANCHOR
    from pptx.util import Inches,Pt
    from PIL import Image
    from automoto.office_visual import add_icon
    if not 1<=len(scenes)<=40:
        raise VisualError("PPTX must contain 1 to 40 slides")
    prs=pptx.Presentation()
    prs.slide_width=Inches(13.333);prs.slide_height=Inches(7.5)
    for scene in scenes:
        sw=prs.slide_width;sh=prs.slide_height
        sx=sw/scene["width"];sy=sh/scene["height"]
        slide=prs.slides.add_slide(prs.slide_layouts[6])
        for e in scene["elements"]:
            t=e["type"]
            X=lambda v: round(float(v)*sx)
            Y=lambda v: round(float(v)*sy)
            if t=="rect":
                kind=MSO_SHAPE.RECTANGLE if e["radius"]<=0 else MSO_SHAPE.ROUNDED_RECTANGLE
                s=slide.shapes.add_shape(kind,X(e["x"]),Y(e["y"]),X(e["w"]),Y(e["h"]))
                s.fill.solid();s.fill.fore_color.rgb=RGBColor(*_hexrgb(e["fill"]))
                if e["stroke"]:
                    s.line.color.rgb=RGBColor(*_hexrgb(e["stroke"]))
                    s.line.width=Pt(e["stroke_width"]*sx/12700)
                else:s.line.fill.background()
            elif t=="line":
                s=slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,X(e["x1"]),Y(e["y1"]),
                                             X(e["x2"]),Y(e["y2"]))
                s.line.color.rgb=RGBColor(*_hexrgb(e["colour"]))
                s.line.width=Pt(max(1,e["width"]*72*7.5/scene["height"]))
            elif t=="icon":
                size=min(e["w"]*13.333/scene["width"],e["h"]*7.5/scene["height"])
                add_icon(slide,e["name"],e["x"]*13.333/scene["width"],e["y"]*7.5/scene["height"],
                         size,e["colour"])
            elif t=="text":
                lines,_,_= _text_lines(e)
                s=slide.shapes.add_textbox(X(e["x"]),Y(e["y"]),X(e["w"]),Y(e["h"]))
                tf=s.text_frame;tf.word_wrap=True
                tf.margin_left=tf.margin_right=tf.margin_top=tf.margin_bottom=0
                tf.vertical_anchor=MSO_ANCHOR.TOP
                tf.auto_size=MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
                tf.text="\n".join(lines)
                for paragraph in tf.paragraphs:
                    for run in paragraph.runs:
                        run.font.name="Aptos"
                        run.font.size=Pt(e["size"]*7.5*72/scene["height"])
                        run.font.bold=e.get("bold",False)
                        run.font.color.rgb=RGBColor(*_hexrgb(e["colour"]))
            elif t=="image":
                from PIL import ImageOps
                p=Path(e["path"])
                with Image.open(p) as opened:
                    iw,ih=opened.size
                    # Existing JPEG/PNG bytes stay original unless PowerPoint
                    # cannot accept the source or EXIF orientation requires a
                    # corrected display copy. Never write back to the source.
                    orient=opened.getexif().get(274,1)
                    convert=p.suffix.lower() in {".webp",".bmp"} or orient not in {1,None}
                    if convert:
                        copy=ImageOps.exif_transpose(opened).convert("RGBA")
                        iw,ih=copy.size
                        temporary=io.BytesIO()
                        copy.save(temporary,format="PNG")
                        temporary.seek(0)
                        source=temporary
                    else:
                        source=str(p)
                fit=min(X(e["w"])/iw,Y(e["h"])/ih)
                pic=slide.shapes.add_picture(source,
                     X(e["x"])+round((X(e["w"])-iw*fit)/2),
                     Y(e["y"])+round((Y(e["h"])-ih*fit)/2),
                     round(iw*fit),round(ih*fit))
                pic._element.nvPicPr.cNvPr.set("descr",e["alt"])
        if scene.get("notes"):
            slide.notes_slide.notes_text_frame.text=scene["notes"]
    prs.core_properties.title=scenes[0]["title"][:250]
    prs.save(str(path))

def render(scene:dict,path:Path,*,animation:dict|None=None,scenes:list[dict]|None=None):
    """Write a file, validate output and keep the source assets unchanged."""
    from PIL import Image
    ext=path.suffix.lower()
    if path.exists():raise VisualError("output already exists; choose a new filename")
    if ext not in {".png",".jpg",".jpeg",".gif",".svg",".pptx",".pdf"}:
        raise VisualError("output must be PNG, JPEG, GIF, SVG, PPTX or PDF")
    if ext not in {".pptx", ".pdf"} and scenes is not None and len(scenes)>1:
        raise VisualError("multiple scenes require PowerPoint or PDF")
    findings=[]
    selected=scenes or [scene]
    for item in selected:
        repair_text_fitting(item)
        findings+=quality(item)
    if findings:raise VisualError("visual quality check failed: "+"; ".join(findings[:5]))
    source_hashes={e["path"]:__import__("hashlib").sha256(Path(e["path"]).read_bytes()).hexdigest()
                   for s in selected for e in s["elements"] if e["type"]=="image"}
    path.parent.mkdir(parents=True,exist_ok=True)
    try:
        if ext==".svg":
            path.write_text(svg_string(scene),encoding="utf-8")
        elif ext==".pptx":
            _pptx_scenes(selected,path)
        elif ext==".gif":
            if scene["width"]*scene["height"]>1_000_000:
                raise VisualError("GIF canvas exceeds 1 megapixel; reduce the dimensions")
            config=animation or {}
            if not isinstance(config,dict):raise VisualError("animation must be an object")
            frames=int(config.get("frames",20))
            duration=int(config.get("duration_ms",110))
            loops=int(config.get("loop",0))
            effect=str(config.get("effect","flow"))
            if not 8<=frames<=48 or not 50<=duration<=500 or not 0<=loops<=20:
                raise VisualError("GIF needs 8-48 frames, 50-500ms and loop 0-20")
            if effect not in {"flow","pulse","float","reveal","sequence","keyframes"}:
                raise VisualError("GIF effect must be flow, pulse, float, reveal, sequence or keyframes")
            if effect=="sequence":
                sequence_stages(scene,config)
            if effect=="keyframes":
                from automoto.visual_motion import validate_keyframes
                validate_keyframes(scene,config)
            images=[]
            for index in range(frames):
                images.append(raster(scene,progress=index/(frames-1) if effect=="keyframes" else index/frames,
                                     effect=effect,animation=config))
            # Single palette avoids visible colour flicker between GIF frames.
            palette=images[-1].quantize(colors=192)
            paletted=[im.quantize(palette=palette,dither=Image.Dither.NONE) for im in images]
            paletted[0].save(str(path),format="GIF",save_all=True,append_images=paletted[1:],
                             duration=duration,loop=loops,disposal=2,optimize=False)
            with Image.open(path) as check:
                if getattr(check,"n_frames",1)<2:
                    raise VisualError("GIF output is static: the animation was not rendered")
        elif ext==".pdf":
            # Each compiled canvas is a real page. PDF is deliberately
            # flattened; choose PPTX for native editable shape/text slides.
            pages=[raster(item) for item in selected]
            pages[0].save(str(path),format="PDF",save_all=True,
                          append_images=pages[1:],resolution=96)
        else:
            fmt="JPEG" if ext in {".jpeg",".jpg"} else "PNG"
            raster(scene).save(str(path),format=fmt,quality=93)
        if not path.exists() or path.stat().st_size==0:raise VisualError("export is empty")
        for name,digest in source_hashes.items():
            if __import__("hashlib").sha256(Path(name).read_bytes()).hexdigest()!=digest:
                raise VisualError("original asset unexpectedly changed during export")
    except Exception:
        if path.exists():path.unlink()
        raise
    return path
