"""Visual Studio tools for the gaps the older image tools do not cover.

``visual_create`` / ``visual_check`` / ``image_compose`` stay as they are.
These tools add layout repair (proposal only), brand kits, multi-page export,
GIF/PNG/PPTX/PDF export through the studio, and local AI review.

A later visual module auto-registers as ``automoto/<name>_studio_tools.py``.
"""

from __future__ import annotations

import json

from automoto.studio_registry import INT, OBJ, S, StudioSpec, call_studio, obj, studio_request
from automoto.tools import Tool, ToolContext

# The same bounded canvas the studio's own export test publishes.
PROMO_SPEC = {
    "width": 800, "height": 500, "theme": "illustrated-workflow",
    "layout": "canvas", "title": "Visual Studio test", "subtitle": "Real editable scene",
    "elements": [
        {"type": "line", "x1": 290, "y1": 350, "x2": 510, "y2": 350, "colour": "#25252D", "stroke_width": 3},
        {"type": "rect", "x": 80, "y": 270, "w": 210, "h": 160, "fill": "#FFFFFF", "stroke": "#25252D"},
        {"type": "text", "x": 98, "y": 314, "w": 165, "h": 70, "text": "Receive", "font_size": 28,
         "colour": "#22252C", "bold": True},
        {"type": "rect", "x": 510, "y": 270, "w": 210, "h": 160, "fill": "#FFFFFF", "stroke": "#25252D"},
        {"type": "text", "x": 529, "y": 314, "w": 165, "h": 70, "text": "Verify", "font_size": 28,
         "colour": "#22252C", "bold": True},
    ],
}


def visual_export(ctx: ToolContext, spec: dict, name: str = "Design", format: str = "png",
                  animation: dict | None = None, output_mode: str = "flat") -> str:
    from automoto import visual_studio

    body = visual_studio.ExportIn.model_validate({
        "spec": spec, "name": name, "format": format or "png",
        "animation": animation, "output_mode": output_mode or "flat",
    })
    return call_studio(visual_studio.export, body, studio_request("POST"))


def visual_repair(ctx: ToolContext, spec: dict, name: str = "Design") -> str:
    """Proposal only. The studio does not save or export."""
    from automoto import visual_studio

    body = visual_studio.DesignIn.model_validate({"spec": spec, "name": name})
    raw = call_studio(visual_studio.propose_repair, body, studio_request("POST"))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    for key in ("preview", "original_preview"):
        if isinstance(data.get(key), str) and len(data[key]) > 120:
            data[key] = "[preview omitted; nothing was saved]"
    data.setdefault("applied", False)
    return json.dumps(data)[:20000]


def visual_brand_save(ctx: ToolContext, name: str, colours: dict, heading_size: int = 32,
                      body_size: int = 16, logo: str = "") -> str:
    from automoto import visual_brand_kits

    body = visual_brand_kits.BrandKitIn.model_validate({
        "name": name, "colours": colours, "heading_size": heading_size, "body_size": body_size,
        "logo": logo or None,
    })
    return call_studio(visual_brand_kits.save_kit, body, studio_request("POST"))


def visual_pages_export(ctx: ToolContext, name: str, pages: list, format: str = "pptx",
                        output_mode: str = "flat") -> str:
    from automoto import visual_documents

    body = visual_documents.DocumentExportIn.model_validate({
        "name": name, "pages": pages, "format": format or "pptx", "output_mode": output_mode or "flat",
    })
    return call_studio(visual_documents.export_document, body, studio_request("POST"))


def visual_ai_review(ctx: ToolContext, spec: dict, name: str = "Design") -> str:
    """Local vision model. Returns notes. Does not change the design."""
    from automoto import visual_studio

    body = visual_studio.DesignIn.model_validate({"spec": spec, "name": name})
    return call_studio(visual_studio.ai_review, body, studio_request("POST"))


STUDIO = StudioSpec(
    id="visual",
    name="Visual Studio",
    hosted_ok=True,
    approval="risky",
    local_only=("visual_ai_review",),
    words=r"\b(visual studio|brand colours|brand colors|promo|layout repair|animated gif|gif)\b",
    exts=(".gif",),
    skills=("visual-studio",),
    fuzzy=("promo", "brand", "gif"),
    how="Use visual_export for a new PNG, JPG, SVG, PDF, PPTX or animated GIF (animation.effect flow, "
        "pulse or reveal). visual_repair returns a proposal and does not apply it; stop there unless the "
        "user approves a later export of proposed_spec. visual_brand_save stores a palette. "
        "visual_pages_export builds a multi-page PDF or PPTX. visual_ai_review is local-only and does not "
        "edit the design. For a single infographic the existing visual_create tool still works. "
        "Name the file when you finish.",
    labels={
        "visual_export": "Exporting the design",
        "visual_repair": "Proposing layout fixes",
        "visual_brand_save": "Saving the brand kit",
        "visual_pages_export": "Exporting the multi-page design",
        "visual_ai_review": "Reviewing the design",
    },
    tools=(
        Tool("visual_export", "Export a Visual Studio canvas to png, jpg, svg, pdf, pptx or gif. "
             "GIF needs an animation object. Writes a new file and does not modify source images.",
             obj({"spec": OBJ, "name": S, "format": S, "animation": OBJ, "output_mode": S}, ["spec"]),
             "risky", visual_export),
        Tool("visual_repair", "Propose layout fixes for a canvas. Returns the diff and does not save, "
             "export or apply it. Leave proposed_spec unused until the user approves.",
             obj({"spec": OBJ, "name": S}, ["spec"]), "safe", visual_repair),
        Tool("visual_brand_save", "Save a private brand-colour kit. It does not paint the canvas by itself.",
             obj({"name": S, "colours": OBJ, "heading_size": INT, "body_size": INT, "logo": S},
                 ["name", "colours"]), "risky", visual_brand_save),
        Tool("visual_pages_export", "Export 1 to 20 canvas pages as a new PPTX or PDF.",
             obj({"name": S, "pages": {"type": "array"}, "format": S, "output_mode": S}, ["name", "pages"]),
             "risky", visual_pages_export),
        Tool("visual_ai_review", "Ask the local offline vision model about a canvas. Returns notes only. "
             "Not available on a hosted server. Does not change the design.",
             obj({"spec": OBJ, "name": S}, ["spec"]), "risky", visual_ai_review),
    ),
)
