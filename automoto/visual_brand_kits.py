"""Private, reusable Visual Studio brand kits (no uploads and no source mutation).

A kit is a small, validated palette/typography manifest referencing an *existing*
image in the user's uploads folder. Only a user action can place that image on
the canvas. Workspace isolation and image integrity are enforced on every load.
"""
from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from automoto import sandbox
from automoto.visual_foundation import VisualError, colour
from automoto.visual_studio import _auth, _quota_check, _root

router = APIRouter(prefix="/api/visual/studio/brand-kits", tags=["visual-studio"])
KIT_DIR = "artifacts/visual-studio/brand-kits"
PALETTE_KEYS = ("background", "ink", "muted", "accent", "card", "border", "tone0", "tone1", "tone2")
MAX_KITS = 30
MAX_KIT_BYTES = 12 * 1024


class BrandKitIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    colours: dict[str, str]
    heading_size: int = Field(..., ge=12, le=90)
    body_size: int = Field(..., ge=12, le=90)
    logo: str | None = Field(None, max_length=1000)


class PathIn(BaseModel):
    path: str = Field(..., min_length=1, max_length=1000)


def _folder() -> Path:
    return sandbox.resolve(KIT_DIR, base=_root(), allow_outside=False)


def _logo(relative: str | None) -> str | None:
    if not relative:
        return None
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise HTTPException(422, "brand logo must be an existing uploaded image")
    try:
        asset = sandbox.resolve(relative, base=_root(), allow_outside=False)
        asset.relative_to(sandbox.resolve("uploads", base=_root(), allow_outside=False))
    except (sandbox.SandboxError, ValueError):
        raise HTTPException(422, "brand logo must be inside your own uploads folder") from None
    if (asset.is_symlink() or not asset.is_file() or
            asset.stat().st_size > 8 * 1024 * 1024 or
            asset.suffix.lower() not in {".png", ".jpeg", ".jpg", ".webp", ".bmp"}):
        raise HTTPException(422, "brand logo must be an existing image under 8 MB")
    try:
        from PIL import Image
        with Image.open(asset) as im:
            if im.width < 1 or im.height < 1 or im.width * im.height > 16_000_000:
                raise ValueError("invalid image dimensions")
            im.verify()
    except (OSError, ValueError, SyntaxError):
        raise HTTPException(422, "brand logo is not a valid image") from None
    return asset.relative_to(_root()).as_posix()


def _contrast(a: str, b: str) -> float:
    def lum(value: str) -> float:
        values = [int(value[k:k+2], 16) / 255.0 for k in (1, 3, 5)]
        rgb = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
        return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    x, y = sorted((lum(a), lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def _clean(kit: BrandKitIn | dict[str, Any]) -> dict[str, Any]:
    if not isinstance(kit, BrandKitIn):
        kit = BrandKitIn.model_validate(kit)
    name = kit.name.strip()
    if not name:
        raise HTTPException(422, "brand kit name must not be blank")
    raw = kit.colours
    if set(raw) != set(PALETTE_KEYS):
        raise HTTPException(422, "brand kit must define the six main colours and three tones")
    try:
        colours = {k: colour(raw[k]) for k in PALETTE_KEYS}
    except VisualError as exc:
        raise HTTPException(422, str(exc)) from None
    if _contrast(colours["background"], colours["ink"]) < 4.5:
        raise HTTPException(422, "ink/background contrast must be at least 4.5:1")
    return {"schema": 1, "name": name, "colours": colours,
            "heading_size": kit.heading_size, "body_size": kit.body_size,
            "logo": _logo(kit.logo)}


def _target(relative: str) -> Path:
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise HTTPException(403, "invalid kit location")
    try:
        resolved = sandbox.resolve(relative, base=_root(), allow_outside=False)
        resolved.relative_to(_folder())
    except (sandbox.SandboxError, ValueError):
        raise HTTPException(403, "kit is outside your Visual Studio brand kit folder") from None
    if (resolved.parent != _folder() or resolved.is_symlink()
            or not resolved.name.endswith(".brand.json") or not resolved.is_file()):
        raise HTTPException(404, "brand kit not found")
    if resolved.stat().st_size > MAX_KIT_BYTES:
        raise HTTPException(413, "brand kit file exceeds its size limit")
    return resolved


@router.post("/validate")
def validate_kit(body: BrandKitIn, request: Request):
    """Validate the full kit without writing a brand or modifying a design."""
    _auth(request)
    return {"kit": _clean(body), "valid": True}


@router.post("/save")
def save_kit(body: BrandKitIn, request: Request):
    _auth(request)
    cleaned = _clean(body)
    folder = _folder()
    folder.mkdir(parents=True, exist_ok=True)
    if sum(1 for p in folder.glob("*.brand.json") if p.is_file() and not p.is_symlink()) >= MAX_KITS:
        raise HTTPException(413, "maximum of 30 saved brand kits reached")
    slug = re.sub(r"[^a-z0-9-]+", "-", cleaned["name"].lower()).strip("-")[:40] or "brand"
    path = folder / f"{slug}-{secrets.token_hex(5)}.brand.json"
    data = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_KIT_BYTES:
        raise HTTPException(413, "brand kit exceeds its size limit")
    _quota_check(len(data))
    try:
        with path.open("xb") as f:
            f.write(data)
    except OSError:
        path.unlink(missing_ok=True)
        raise HTTPException(500, "could not save brand kit") from None
    return {"path": path.relative_to(_root()).as_posix(), "kit": cleaned,
            "message": "private brand kit saved"}


@router.get("/list")
def list_kits(request: Request):
    _auth(request)
    folder = _folder()
    if not folder.is_dir():
        return {"kits": []}
    kits = []
    for path in sorted(folder.glob("*.brand.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:MAX_KITS]:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_KIT_BYTES:
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            kit = _clean(raw)
        except (OSError, ValueError, HTTPException, TypeError):
            continue
        kits.append({"path": path.relative_to(_root()).as_posix(), "name": kit["name"]})
    return {"kits": kits}


@router.get("/load")
def load_kit(request: Request, path: str):
    _auth(request)
    file = _target(path)
    try:
        kit = _clean(json.loads(file.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, HTTPException) as exc:
        raise HTTPException(422, f"saved brand kit is invalid: {str(exc)[:160]}") from None
    return {"kit": kit, "path": path}


@router.post("/delete")
def delete_kit(body: PathIn, request: Request):
    _auth(request)
    file = _target(body.path)
    try:
        file.unlink()
    except OSError:
        raise HTTPException(500, "could not delete brand kit") from None
    return {"deleted": True, "path": body.path}
