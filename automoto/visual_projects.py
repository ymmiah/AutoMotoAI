"""Shared editable image projects for every AutoMoto image workflow.

A flat PNG/JPEG/WebP never has recoverable vector/model layers. Imported artwork
therefore starts as one protected image layer. Native scenes retain their
individually editable text, icons, cards and shapes. No fictional segmentation.
"""
from __future__ import annotations

import json
import math
import secrets
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from automoto import sandbox
from automoto.visual_foundation import VisualError, compile_scene

MODES = frozenset({"flat", "layered"})
SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
PROJECT_DIR = "artifacts/visual-studio"

def mode(value: str) -> str:
    if value not in MODES:
        raise VisualError("output_mode must be 'flat' or 'layered'")
    return value

def _relative_image(path: str | Path, workspace: Path | None = None) -> str:
    """Never create a Studio draft that would read outside its owner's workspace."""
    root = (workspace or sandbox.default_root()).resolve()
    original = Path(path)
    candidate = original.resolve() if original.is_absolute() else (root / original).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        raise VisualError("editable layers require the image to be inside your own workspace") from None
    if not candidate.is_file() or candidate.suffix.lower() not in SUFFIXES:
        raise VisualError("editable image needs an existing PNG, JPEG, WebP or BMP file")
    if candidate.stat().st_size > 24 * 1024 * 1024:
        raise VisualError("editable source image exceeds 24 MB")
    with Image.open(candidate) as image:
        if image.width * image.height > 36_000_000:
            raise VisualError("editable source image exceeds 36 megapixels")
        if getattr(image, "n_frames", 1) != 1:
            raise VisualError("animated input requires a separately extracted static frame")
        image.verify()
    return relative.as_posix()

def image_project(path: str | Path, workspace: Path | None = None) -> dict[str, Any]:
    """Wrap original raster pixels in one editable canvas layer (no AI redrawing)."""
    root = (workspace or sandbox.default_root()).resolve()
    rel = _relative_image(path, root)
    with Image.open(root / rel) as opened:
        oriented = ImageOps.exif_transpose(opened)
        ow, oh = oriented.size
    cap = min(1.0, 1920 / ow, 1080 / oh, math.sqrt(2_100_000 / (ow * oh)))
    minimum = max(640 / ow, 400 / oh)
    # For typical photographs, keep the original aspect ratio (including
    # square and portrait images). If a very long/narrow image cannot meet
    # both canvas minima without exceeding its maxima, letterbox via the
    # existing aspect-fit image renderer; never stretch its pixels.
    scale = max(cap, minimum) if minimum <= cap else cap
    w = max(640, min(1920, round(ow * scale)))
    h = max(400, min(1080, round(oh * scale)))
    return {
        "schema":1,"width":w,"height":h,"layout":"canvas","theme":"editorial-light",
        "artboard_only":True,"title":"","subtitle":"",
        "elements":[{
            "type":"image","x":0,"y":0,"w":w,"h":h,"path":rel,
            "alt":"Original artwork (single raster layer)", "group":"original-artwork"
        }]
    }

def scene_project(scene: dict[str,Any], workspace: Path | None = None) -> dict[str,Any]:
    """Convert a deterministic rendered scene to individual native editor layers."""
    root = (workspace or sandbox.default_root()).resolve()
    elements=[]
    for e in scene["elements"]:
        kind=e["type"]
        el={"type":kind}
        if kind in ("rect","text","icon","image"):
            for key in ("x","y","w","h"):
                el[key]=e[key]
            if kind=="rect":
                for key in ("fill","stroke","radius"):
                    if e.get(key) is not None:el[key]=e[key]
            elif kind=="text":
                el.update(text=e["text"],font_size=e["size"],colour=e["colour"],bold=e.get("bold",False))
            elif kind=="icon":
                el.update(name=e["name"],colour=e["colour"])
            else:
                el.update(path=_relative_image(e["path"],root),alt=e.get("alt","Original image"))
        elif kind=="line":
            el.update({key:e[key] for key in ("x1","x2","y1","y2","colour","width") if key in e})
            el["stroke_width"]=el.pop("width",3)
        else:
            raise VisualError("unsupported scene layer")
        # Background and other drawing primitives remain separate editables.
        for key in ("group","allow_overlap","hidden","locked"):
            if key in e:el[key]=e[key]
        elements.append(el)
    if len(elements)>40:
        raise VisualError("this design has more than 40 layers; simplify it before opening the editor")
    draft={
        "schema":1, "width":scene["width"],"height":scene["height"],"layout":"canvas",
        "theme":scene["theme"],"artboard_only":True,"title":"","subtitle":"",
        "elements":elements
    }
    compile_scene(draft)  # guarantee it opens as a real editable canvas
    return draft

def save_project(spec:dict[str,Any], name:str="Artwork",workspace:Path|None=None) -> str:
    """Create one Studio draft only on explicit layered output or import."""
    root=(workspace or sandbox.default_root()).resolve()
    # Validate every user-controlled asset before writing.
    from automoto.visual_foundation import compile_scene
    compile_scene(spec)
    for item in spec.get("elements", []):
        if item.get("type")=="image":
            _relative_image(item["path"],root)
    slug="".join(c if c.isalnum() and c.isascii() else "-" for c in name.lower()).strip("-")[:40] or "image"
    folder=(root/PROJECT_DIR).resolve()
    if not folder.is_relative_to(root):
        raise VisualError("unsafe project destination")
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/(slug+"-"+secrets.token_hex(6)+".design.json")
    data=json.dumps({"schema":1,"name":name[:100],"spec":spec},indent=2,ensure_ascii=False).encode("utf-8")
    if len(data)>56*1024:
        raise VisualError("editable design project exceeds maximum size")
    try:
        with path.open("xb") as f:f.write(data)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path.relative_to(root).as_posix()
