"""Authenticated Visual Studio editor API.

The browser edits a validated canvas specification. The same renderer is used for
previews and exports, so what users see is the actual produced output. Previews
never write files; saved drafts and exports live in each user's own workspace.
"""
from __future__ import annotations

import base64
import io
import json
import re
import secrets
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from PIL import Image

from automoto import sandbox, tenancy
from automoto.visual_foundation import THEMES, VisualError, compile_scene
from automoto.visual_renderer import raster, quality, repair_text_fitting, sequence_stages
from automoto.visual_art_tools import visual_create
from automoto.tools import ToolContext, ToolFailed

router = APIRouter(prefix="/api/visual/studio", tags=["visual-studio"])
FORMATS = {"png", "jpg", "svg", "pdf", "pptx", "gif"}
MAX_SPEC_BYTES = 48 * 1024
DIR = "artifacts/visual-studio"


class DesignIn(BaseModel):
    spec: dict[str, Any]
    name: str = Field("Untitled design", max_length=100)


class ExportIn(DesignIn):
    format: str = Field("png", max_length=8)
    animation: dict[str, Any] | None = None


class PreviewIn(DesignIn):
    frame: float | None = Field(None, ge=0, lt=1)
    animation: dict[str, Any] | None = None


def _auth(request: Request) -> None:
    # Imported lazily to avoid a server -> visual_studio -> server import cycle.
    from automoto import server
    server._authorise(request)


def _root() -> Path:
    return sandbox.default_root().resolve()


def _design_dir() -> Path:
    path = sandbox.resolve(DIR, base=_root(), allow_outside=False)
    return path


def _validate(spec: dict[str, Any]) -> dict[str, Any]:
    # Bounded JSON before model processing, image decoding, or rendering.
    try:
        encoded = json.dumps(spec, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, f"invalid design JSON: {exc}") from None
    if len(encoded.encode("utf-8")) > MAX_SPEC_BYTES:
        raise HTTPException(413, "design exceeds the 48 KB specification limit")
    if "slides" in spec:
        raise HTTPException(422, "the interactive editor handles one canvas; export multi-slide decks through the agent")

    # Uploaded media must belong to the authenticated user's workspace only,
    # not the extra folders granted for a separate task or the host's filesystem.
    paths = []
    if spec.get("brand_logo"):
        paths.append(spec["brand_logo"])
    if spec.get("layout") == "hero" and spec.get("image"):
        paths.append(spec["image"])
    for el in spec.get("elements", []) if isinstance(spec.get("elements"), list) else []:
        if isinstance(el, dict) and el.get("type") == "image":
            paths.append(el.get("path"))
    for p in paths:
        if not isinstance(p, str) or not p or Path(p).is_absolute():
            raise HTTPException(422, "image sources must be relative files inside your workspace")
        try:
            resolved = sandbox.resolve(p, base=_root(), allow_outside=False)
        except sandbox.SandboxError:
            raise HTTPException(422, "image source is outside your workspace") from None
        if not resolved.is_file():
            raise HTTPException(422, "referenced source image does not exist")
    return spec


def _compiled(spec: dict[str, Any]) -> dict[str, Any]:
    try:
        scene = compile_scene(_validate(spec))
        repair_text_fitting(scene)
        warnings = quality(scene)
    except (VisualError, ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)[:1000]) from None
    if warnings:
        raise HTTPException(422, "visual quality check failed: " + "; ".join(warnings[:5])[:1300])
    return scene


def _name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower().strip()).strip("-")
    return (slug[:44].strip("-") or "design")


def _filename(name: str, suffix: str) -> str:
    return f"{_name(name)}-{secrets.token_hex(6)}.{suffix}"


def _limit() -> int | None:
    if not tenancy.multiuser():
        return None
    from automoto import accounts
    return int(float(accounts.get_setting("storage_mb")) * 1024 * 1024)


def _quota_check(additional: int = 0) -> None:
    limit = _limit()
    if limit is None:
        return
    from automoto import server
    if server._dir_size(_root()) + additional > limit:
        raise HTTPException(413, "workspace storage limit reached; remove files before exporting")


def _write_design(name: str, spec: dict[str, Any]) -> str:
    folder = _design_dir()
    folder.mkdir(parents=True, exist_ok=True)
    filename = _filename(name, "design.json")
    target = sandbox.resolve(f"{DIR}/{filename}", base=_root(), allow_outside=False)
    payload = json.dumps({"schema": 1, "name": name, "spec": spec},
                         ensure_ascii=False, indent=2).encode("utf-8")
    _quota_check(len(payload))
    with target.open("xb") as f:
        f.write(payload)
    return target.relative_to(_root()).as_posix()


@router.get("/presets")
def presets(request: Request):
    _auth(request)
    return {"themes": list(THEMES), "layouts": ["workflow", "cards", "hero", "canvas"],
            "formats": sorted(FORMATS), "animation_effects": ["flow", "pulse", "float", "reveal", "sequence"],
            "size_limits": {"width": [640, 1920], "height": [400, 1080], "gif_pixels": 1_000_000}}


@router.post("/preview")
def preview(body: PreviewIn, request: Request):
    _auth(request)
    scene = _compiled(body.spec)
    try:
        if body.frame is not None:
            config=body.animation or body.spec.get("animation") or {}
            if not isinstance(config,dict) or config.get("effect")!="sequence":
                raise VisualError("timeline frame preview requires a sequence animation")
            sequence_stages(scene,config)
            im = raster(scene,progress=body.frame,effect="sequence",animation=config)
        else:
            im = raster(scene)
        data = io.BytesIO()
        im.save(data, format="PNG", optimize=True)
    except (VisualError, OSError, ValueError) as exc:
        raise HTTPException(422, str(exc)[:1000]) from None
    if data.tell() > 4 * 1024 * 1024:
        raise HTTPException(413, "rendered preview exceeds 4 MB")
    return {"image": "data:image/png;base64," + base64.b64encode(data.getvalue()).decode("ascii"),
            "width": scene["width"], "height": scene["height"],
            "adjustments": scene.get("text_repairs", []), "frame": body.frame,
            "quality": "passed structural checks; manual visual review required"}


@router.post("/save")
def save(body: DesignIn, request: Request):
    _auth(request)
    _compiled(body.spec)
    _quota_check()
    try:
        file = _write_design(body.name, body.spec)
    except OSError as exc:
        raise HTTPException(500, f"could not save design: {exc}") from None
    return {"path": file, "message": "editable design draft saved"}


@router.get("/list")
def list_designs(request: Request):
    _auth(request)
    folder = _design_dir()
    if not folder.is_dir():
        return {"designs": []}
    found = []
    for p in sorted(folder.glob("*.design.json"), key=lambda q: q.stat().st_mtime, reverse=True)[:40]:
        if p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_SPEC_BYTES + 8192:
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            title = str(raw.get("name", "Untitled design"))[:100]
        except (OSError, ValueError, AttributeError):
            continue
        found.append({"path": p.relative_to(_root()).as_posix(), "name": title,
                      "modified": int(p.stat().st_mtime)})
    return {"designs": found}


@router.get("/load")
def load(request: Request, path: str):
    _auth(request)
    try:
        p = sandbox.resolve(path, base=_root(), allow_outside=False)
        p.relative_to(_design_dir())
    except (ValueError, sandbox.SandboxError):
        raise HTTPException(403, "design is outside your Visual Studio directory") from None
    if p.is_symlink() or not p.is_file() or not p.name.endswith(".design.json"):
        raise HTTPException(404, "design not found")
    if p.stat().st_size > MAX_SPEC_BYTES + 8192:
        raise HTTPException(413, "saved design is too large")
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        if obj.get("schema") != 1 or not isinstance(obj.get("spec"), dict):
            raise ValueError("unsupported design schema")
        _compiled(obj["spec"])
    except (ValueError, OSError) as exc:
        raise HTTPException(422, f"saved design is invalid: {exc}") from None
    return {"name": str(obj.get("name", "Untitled design"))[:100], "spec": obj["spec"]}


@router.post("/export")
def export(body: ExportIn, request: Request):
    _auth(request)
    fmt = body.format.lower()
    if fmt not in FORMATS:
        raise HTTPException(422, "unsupported export format")
    _compiled(body.spec)
    _quota_check()
    filename = _filename(body.name, fmt)
    target = sandbox.resolve(f"{DIR}/{filename}", base=_root(), allow_outside=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        message = visual_create(ToolContext(), str(target), body.spec, body.animation)
    except (ToolFailed, VisualError, OSError, ValueError) as exc:
        raise HTTPException(422, str(exc)[:1200]) from None
    sidecar = target.with_name(target.name + ".visual.json")
    # The draft is a separate editable file; leave the generated binary intact
    # if storing the draft fails, and report the problem.
    try:
        _quota_check(len(json.dumps(body.spec).encode("utf-8")))
        draft = _write_design(body.name, body.spec)
    except (HTTPException, OSError) as exc:
        target.unlink(missing_ok=True)
        sidecar.unlink(missing_ok=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(500, f"could not persist editable design: {exc}") from None
    return {"path": target.relative_to(_root()).as_posix(),
            "manifest": sidecar.relative_to(_root()).as_posix(),
            "draft": draft, "format": fmt,
            "message": message}
