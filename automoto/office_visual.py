"""Editable visual building blocks for PowerPoint.

All icons are native DrawingML/PowerPoint shapes: no web calls, icon fonts or
rasterisation. Photos and logos are inserted from their original files by the
existing picture helper; this module never redraws or changes a supplied face.
"""

from __future__ import annotations

import math
import re

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from automoto.office import OfficeError

ICONS = frozenset({
    "check", "shield", "idea", "lightbulb", "chart", "growth", "users",
    "person", "clock", "target", "cloud", "file", "folder", "image",
    "sparkle", "star", "arrow", "globe", "code", "lock", "settings",
})

def _rgb(value: str) -> RGBColor:
    if not isinstance(value, str) or not re.fullmatch(r"#?[0-9a-fA-F]{6}", value):
        raise OfficeError("visual colour must be a six-digit hex code")
    return RGBColor.from_string(value.lstrip("#"))


def _shape(slide, kind, x, y, w, h, fill=None, line=None, rotation=None, line_width=1.2):
    s = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill:
        s.fill.solid()
        s.fill.fore_color.rgb = _rgb(fill)
    else:
        s.fill.background()
    if line:
        s.line.color.rgb = _rgb(line)
        s.line.width = Pt(line_width)
    else:
        s.line.fill.background()
    if rotation is not None:
        s.rotation = rotation
    return s


def _segment(slide, x1, y1, x2, y2, color, thickness=2.2):
    s = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1),
                                   Inches(x2), Inches(y2))
    s.line.color.rgb = _rgb(color)
    s.line.width = Pt(thickness)
    return s


def _textbox(slide, text, x, y, w, h, size=18, color="#19283D", bold=False,
             align=PP_ALIGN.LEFT, font="Aptos", valign=MSO_ANCHOR.MIDDLE):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.015)
    tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = valign
    tf.text = str(text)
    for p in tf.paragraphs:
        p.alignment = align
        for r in p.runs:
            r.font.name = font
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.color.rgb = _rgb(color)
    return tb


def _palette(theme):
    bg = str(theme.get("background") or "#F7F9FC")
    rgb = [int(bg.lstrip("#")[i:i+2], 16) for i in (0, 2, 4)]
    dark = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2] < 112
    return {
        "accent": "#" + str(theme.get("accent") or "2E75B6").lstrip("#"),
        "primary": "#" + str(theme.get("primary") or "1F3864").lstrip("#"),
        "ink": "#" + str(theme.get("text") or ("F8FAFC" if dark else "24344B")).lstrip("#"),
        "secondary": "#CBD5E1" if dark else "#56677D",
        "card": "#1E293B" if dark else "#FFFFFF",
        "border": "#42536B" if dark else "#E1E8F0",
        "bg": bg if bg.startswith("#") else "#" + bg,
        "dark": dark,
        "font": str(theme.get("font") or "Aptos"),
        "head_font": str(theme.get("heading_font") or theme.get("font") or "Aptos Display"),
    }


def add_icon(slide, name: str, x: float, y: float, size: float, colour="#2E75B6"):
    """A small icon composed of editable PowerPoint vector shapes."""
    name = str(name or "sparkle").lower().replace("-", "_")
    if name not in ICONS:
        raise OfficeError("Unknown icon " + repr(name) + ". Use: " + ", ".join(sorted(ICONS)))
    if name == "lightbulb":
        name = "idea"
    if name == "growth":
        name = "chart"
    if name == "person":
        name = "users"
    if name == "star":
        name = "sparkle"
    pad = size * 0.12
    x, y, size = x + pad, y + pad, size - 2 * pad
    def shp(t, a, b, c, d, **kw):
        return _shape(slide, t, x + a*size, y + b*size, c*size, d*size, **kw)
    def line(a, b, c, d, width=2):
        return _segment(slide, x+a*size, y+b*size, x+c*size, y+d*size, colour, width)
    if name == "check":
        line(.05, .54, .40, .85, 2.8)
        line(.40, .85, .96, .13, 2.8)
    elif name == "shield":
        shp(MSO_SHAPE.PENTAGON, .12, .04, .76, .88, line=colour, line_width=2.4, rotation=180)
        line(.3, .48, .45, .64)
        line(.45, .64, .72, .36)
    elif name == "idea":
        shp(MSO_SHAPE.OVAL, .25, .05, .50, .52, line=colour, line_width=2)
        shp(MSO_SHAPE.RECTANGLE, .40, .59, .20, .19, fill=colour)
        line(.38, .84, .62, .84)
    elif name == "chart":
        for ix, height in ((.08, .28), (.38, .55), (.68, .82)):
            shp(MSO_SHAPE.ROUNDED_RECTANGLE, ix, .91-height, .22, height, fill=colour)
    elif name == "users":
        for xx in (.07, .58):
            shp(MSO_SHAPE.OVAL, xx+.12, .12, .20, .20, fill=colour)
            shp(MSO_SHAPE.ROUNDED_RECTANGLE, xx, .47, .45, .32, fill=colour)
    elif name == "clock":
        shp(MSO_SHAPE.OVAL, .08, .08, .84, .84, line=colour, line_width=2.2)
        line(.5, .5, .5, .25)
        line(.5, .5, .72, .59)
    elif name == "target":
        for d in (.88, .52, .17):
            shp(MSO_SHAPE.OVAL, .5-d/2, .5-d/2, d, d, line=colour, line_width=2)
    elif name == "cloud":
        shp(MSO_SHAPE.ROUNDED_RECTANGLE, .12, .48, .75, .28, fill=colour)
        shp(MSO_SHAPE.OVAL, .21, .31, .40, .40, fill=colour)
        shp(MSO_SHAPE.OVAL, .43, .22, .39, .45, fill=colour)
    elif name in ("file", "image", "folder"):
        shp(MSO_SHAPE.ROUNDED_RECTANGLE, .10, .11, .80, .76, line=colour, line_width=2)
        if name == "file":
            for yy in (.38, .56, .72):
                line(.27, yy, .73, yy, 1.6)
        elif name == "image":
            shp(MSO_SHAPE.OVAL, .62, .27, .13, .13, fill=colour)
            line(.19, .70, .44, .43)
            line(.44, .43, .61, .61)
            line(.61, .61, .72, .50)
        else:
            shp(MSO_SHAPE.RECTANGLE, .18, .18, .35, .11, fill=colour)
    elif name == "sparkle":
        shp(MSO_SHAPE.STAR_4_POINT, .18, .08, .68, .68, fill=colour)
        shp(MSO_SHAPE.STAR_4_POINT, .03, .73, .22, .22, fill=colour)
    elif name == "arrow":
        shp(MSO_SHAPE.RIGHT_ARROW, .08, .29, .83, .46, fill=colour)
    elif name == "globe":
        shp(MSO_SHAPE.OVAL, .08, .08, .84, .84, line=colour, line_width=2)
        line(.11, .50, .89, .50, 1.5)
        line(.50, .10, .50, .90, 1.5)
    elif name == "code":
        line(.38, .19, .12, .50, 2.8)
        line(.12, .50, .38, .81, 2.8)
        line(.62, .19, .88, .50, 2.8)
        line(.88, .50, .62, .81, 2.8)
    elif name == "lock":
        shp(MSO_SHAPE.OVAL, .27, .05, .46, .55, line=colour, line_width=2)
        shp(MSO_SHAPE.ROUNDED_RECTANGLE, .18, .42, .64, .48, fill=colour)
    elif name == "settings":
        shp(MSO_SHAPE.GEAR_6, .08, .08, .84, .84, line=colour, line_width=2)
        shp(MSO_SHAPE.OVAL, .36, .36, .28, .28, fill=colour)
    return name


def title_decoration(slide, spec, theme, width=13.333, height=7.5):
    """Right-side editorial motif that never obscures the source title or subtitle."""
    p = _palette(theme)
    accent = p["accent"]
    _shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, width-1.15, .60, .13, 5.25, fill=accent)
    _shape(slide, MSO_SHAPE.OVAL, width-3.30, 1.88, 2.0, 2.0, line=accent, line_width=3)
    _shape(slide, MSO_SHAPE.OVAL, width-2.77, 2.41, .94, .94, fill=accent)
    _shape(slide, MSO_SHAPE.OVAL, width-3.54, 4.20, .32, .32, fill=accent)


def heading_icon(slide, spec, theme, width=13.333):
    """Small, deliberately placed editable vector icon beside a content slide heading."""
    p = _palette(theme)
    add_icon(slide, spec.get("icon") or "sparkle", width-1.48, .54, .58, p["accent"])


def render_cards(slide, spec, theme, width=13.333, height=7.5):
    cards = spec.get("cards")
    if not isinstance(cards, list) or not 1 <= len(cards) <= 6:
        raise OfficeError("cards slide needs 1-6 cards with title, text and optional icon")
    p = _palette(theme)
    count = len(cards)
    cols = 2 if count == 4 else (3 if count > 2 else count)
    rows = math.ceil(count / cols)
    left, gap = .66, .20
    top, region_h = 1.82, height - 2.40
    w = (width - 2*left - (cols-1)*gap) / cols
    h = (region_h - (rows-1)*gap) / rows
    for idx, card in enumerate(cards):
        if not isinstance(card, dict):
            raise OfficeError("each card must be an object")
        col, row = idx % cols, idx // cols
        x, y = left+col*(w+gap), top+row*(h+gap)
        _shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, fill=p["card"], line=p["border"])
        _shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x+.15, y+.18, .60, .60,
               line=p["accent"])
        add_icon(slide, card.get("icon") or ("target", "idea", "chart", "users", "shield", "check")[idx],
                 x+.20, y+.23, .50, p["accent"])
        _textbox(slide, str(card.get("title") or ""), x+.17, y+.92, w-.34, .42,
                 18 if cols == 3 else 20, p["ink"], True, font=p["head_font"])
        _textbox(slide, str(card.get("text") or ""), x+.17, y+1.40, w-.34,
                 max(.25, h-1.54), 13 if rows > 1 else 16, p["secondary"],
                 font=p["font"], valign=MSO_ANCHOR.TOP)
    return count


def render_metrics(slide, spec, theme, width=13.333, height=7.5):
    metrics = spec.get("metrics")
    if not isinstance(metrics, list) or not 1 <= len(metrics) <= 4:
        raise OfficeError("metrics slide needs 1-4 metrics with value and label")
    p = _palette(theme)
    gap, left = .20, .66
    w = (width-2*left-gap*(len(metrics)-1))/len(metrics)
    for i, metric in enumerate(metrics):
        if not isinstance(metric, dict):
            raise OfficeError("each metric must be an object")
        x, y = left+i*(w+gap), 2.08
        _shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, 3.10, fill=p["card"], line=p["border"])
        _shape(slide, MSO_SHAPE.RECTANGLE, x+.22, y+.24, .49, .05, fill=p["accent"])
        _textbox(slide, str(metric.get("value") or "—"), x+.23, y+.62, w-.46, 1.06,
                 35 if len(metrics)>2 else 43, p["accent"], True, font=p["head_font"])
        _textbox(slide, str(metric.get("label") or ""), x+.23, y+1.84, w-.46, .85,
                 17 if len(metrics)>2 else 19, p["ink"], font=p["font"], valign=MSO_ANCHOR.TOP)
    return len(metrics)


def render_steps(slide, spec, theme, width=13.333, height=7.5):
    steps = spec.get("steps")
    if not isinstance(steps, list) or not 2 <= len(steps) <= 5:
        raise OfficeError("steps slide needs 2-5 step objects")
    p = _palette(theme)
    n = len(steps)
    left, gap = .75, .12
    w = (width-1.5-gap*(n-1))/n
    cy = 2.75
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise OfficeError("each step must be an object")
        x = left + i*(w+gap)
        if i < n-1:
            _segment(slide, x+.60, cy+.37, x+w+gap+.06, cy+.37, p["border"], 2)
        _shape(slide, MSO_SHAPE.OVAL, x+.04, cy, .74, .74, fill=p["accent"])
        _textbox(slide, i+1, x+.13, cy+.11, .56, .48, 21, "#FFFFFF", True,
                 align=PP_ALIGN.CENTER, font=p["head_font"])
        _textbox(slide, str(step.get("title") or ""), x, 3.78, w, .61,
                 17 if n>3 else 19, p["ink"], True, font=p["head_font"])
        _textbox(slide, str(step.get("text") or ""), x, 4.55, w, 1.20,
                 13 if n>3 else 15, p["secondary"], font=p["font"], valign=MSO_ANCHOR.TOP)
    return n


def render_image_text(slide, spec, theme, add_image, width=13.333, height=7.5):
    """Place original image bytes in a bounded area without cropping, colour edits or face changes."""
    image = spec.get("image") or spec.get("right_image")
    if not isinstance(image, str) or not image:
        raise OfficeError("image_text slide needs an existing image path")
    p = _palette(theme)
    right = str(spec.get("image_side") or "right").lower() != "left"
    left = .72
    image_x = 7.25 if right else left
    text_x = left if right else 7.20
    picture_y, picture_w, picture_h = 1.84, 5.28, 4.88
    _shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, image_x, picture_y, picture_w, picture_h,
           fill=p["card"], line=p["border"])
    add_image(slide, image, image_x+.12, picture_y+.14, picture_w-.24, picture_h-.28,
              spec.get("alt") or "User-supplied image retained without cropping")
    if spec.get("icon"):
        add_icon(slide, spec["icon"], text_x, 2.00, .65, p["accent"])
    _textbox(slide, str(spec.get("text") or spec.get("body") or ""), text_x, 2.91,
             5.27, 2.55, 23 if len(str(spec.get("text") or "")) < 100 else 18,
             p["ink"], font=p["font"], valign=MSO_ANCHOR.TOP)
    if spec.get("caption"):
        _textbox(slide, str(spec["caption"]), image_x+.22, 6.23, picture_w-.44, .30,
                 11, p["secondary"], font=p["font"], align=PP_ALIGN.CENTER)
    return image


def render_canvas(slide, spec, theme, add_image, width=13.333, height=7.5):
    """Place individually editable text/shape/icon objects at explicit positions in inches.

    A layout contract makes coordinates testable and prevents clipped content; all
    source images are inserted with aspect-fit and their originals are untouched.
    """
    items = spec.get("elements")
    if not isinstance(items, list) or not 1 <= len(items) <= 30:
        raise OfficeError("canvas slide needs 1-30 positioned elements")
    p = _palette(theme)
    for element in items:
        if not isinstance(element, dict):
            raise OfficeError("canvas elements must be objects")
        t = str(element.get("type") or "")
        if t not in ("text", "image", "icon", "rectangle"):
            raise OfficeError("canvas element type must be text, image, icon or rectangle")
        try:
            x, y, w, h = [float(element[key]) for key in ("x", "y", "w", "h")]
        except (KeyError, TypeError, ValueError):
            raise OfficeError("each canvas element needs numeric x, y, w and h in inches") from None
        if (not all(math.isfinite(v) for v in (x,y,w,h)) or x < .20 or y < 1.60 or
                w < .10 or h < .10 or x+w > width-.20 or y+h > height-.62):
            raise OfficeError("canvas element must fit inside the slide content area (in inches)")
        if t == "text":
            txt = str(element.get("text") or "")
            if len(txt) > 2500:
                raise OfficeError("canvas text is too long")
            sz = float(element.get("font_size") or 21)
            if not 12 <= sz <= 80:
                raise OfficeError("canvas text size must be 12-80 pt")
            _textbox(slide, txt, x, y, w, h, sz, str(element.get("colour") or p["ink"]),
                     bool(element.get("bold", False)), font=p["font"],
                     valign=MSO_ANCHOR.TOP)
        elif t == "image":
            name = str(element.get("path") or "")
            if not name:
                raise OfficeError("image canvas element needs a source path")
            add_image(slide, name, x, y, w, h,
                      element.get("alt") or "Unmodified source image")
        elif t == "icon":
            add_icon(slide, element.get("name") or "sparkle", x, y, min(w, h),
                     str(element.get("colour") or p["accent"]))
        else:
            _shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h,
                   fill=str(element.get("fill") or p["card"]),
                   line=str(element.get("line") or p["border"]))
    return len(items)
