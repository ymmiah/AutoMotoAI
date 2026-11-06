"""Visual Studio multi-page documents: isolated drafts and real PDF/PPTX exports.

This does not create separate image-editing processes or upload user artwork.
Every page passes the same authoritative renderer and workspace asset checks as
the existing single-canvas editor.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from automoto import sandbox
from automoto.visual_foundation import VisualError
from automoto.visual_renderer import render
from automoto.visual_studio import (
    DIR, _auth, _compiled, _design_dir, _filename, _quota_check, _root,
)

MAX_PAGES = 20
MAX_DOCUMENT_BYTES = 512 * 1024

router = APIRouter(prefix="/api/visual/studio/document", tags=["visual-studio"])


class PageIn(BaseModel):
    name: str = Field("Page", min_length=1, max_length=80)
    spec: dict[str, Any]


class DocumentIn(BaseModel):
    name: str = Field("Untitled document", max_length=100)
    pages: list[PageIn] = Field(..., min_length=1, max_length=MAX_PAGES)


class DocumentExportIn(DocumentIn):
    format: Literal["pdf", "pptx"] = "pptx"
    output_mode: Literal["flat", "layered"] = "flat"


def _pages(pages: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate every saved/exported page, with a limit on the *entire* payload."""
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES:
        raise HTTPException(422, "document requires 1 to 20 pages")
    raw = []
    for item in pages:
        if isinstance(item, PageIn):
            raw.append({"name": item.name, "spec": item.spec})
        elif isinstance(item, dict):
            name, spec = item.get("name"), item.get("spec")
            if not isinstance(name, str) or not 1 <= len(name) <= 80 or not isinstance(spec, dict):
                raise HTTPException(422, "each document page requires a name and an editable canvas")
            raw.append({"name": name, "spec": spec})
        else:
            raise HTTPException(422, "each document page must be an object")
    try:
        data = json.dumps(raw, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        raise HTTPException(422, "document pages must be valid JSON") from None
    if len(data) > MAX_DOCUMENT_BYTES - 8192:
        raise HTTPException(413, "document exceeds the 512 KB size limit")
    scenes = []
    for i, page in enumerate(raw):
        if page["spec"].get("layout") != "canvas":
            raise HTTPException(422, f"page {i + 1}: only editable canvas layouts are supported")
        try:
            scenes.append(_compiled(page["spec"]))
        except HTTPException as exc:
            raise HTTPException(exc.status_code, f"page {i + 1}: {exc.detail}") from None
    return raw, scenes


def _write(name: str, pages: list[dict[str, Any]]) -> str:
    payload = json.dumps({"schema": 2, "name": name, "pages": pages},
                         separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, "document exceeds the 512 KB size limit")
    _quota_check(len(payload))
    folder = _design_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = sandbox.resolve(f"{DIR}/{_filename(name, 'design.json')}", base=_root(), allow_outside=False)
    try:
        with target.open("xb") as stream:
            stream.write(payload)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target.relative_to(_root()).as_posix()


@router.post("/save")
def save_document(body: DocumentIn, request: Request):
    _auth(request)
    pages, _ = _pages(body.pages)
    try:
        path = _write(body.name, pages)
    except OSError as exc:
        raise HTTPException(500, "could not save the multi-page draft") from exc
    return {"path": path, "page_count": len(pages), "message": "editable multi-page draft saved"}


@router.post("/export")
def export_document(body: DocumentExportIn, request: Request):
    _auth(request)
    pages, scenes = _pages(body.pages)
    # Validate before touching disk, and preserve photo hashes with the
    # renderer's existing provenance check.
    _quota_check()
    target = sandbox.resolve(f"{DIR}/{_filename(body.name, body.format)}", base=_root(),
                             allow_outside=False)
    manifest = target.with_name(target.name + ".visual.json")
    draft = None
    try:
        render(scenes[0], target, scenes=scenes)
        assets = sorted({a["path"]: a for scene in scenes for a in scene["assets"]}.values(),
                        key=lambda item: item["path"])
        metadata = {
            "schema_version": 2, "format": body.format, "scene_count": len(scenes),
            "page_names": [page["name"] for page in pages],
            "original_assets": assets, "output_mode": body.output_mode,
            "output_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "quality": {"structural_check": "passed", "visual_manual_review": "required"},
        }
        if body.output_mode == "layered":
            draft = _write(body.name, pages)
            metadata["editable_project"] = draft
        else:
            metadata["editable_project"] = None
        blob = json.dumps(metadata, indent=2, ensure_ascii=False).encode("utf-8")
        _quota_check(len(blob))
        with manifest.open("xb") as stream:
            stream.write(blob)
        # Check the accumulated output size, not just the manifest.
        _quota_check()
    except (VisualError, ValueError, OSError, HTTPException) as exc:
        target.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)
        if draft:
            (_root() / draft).unlink(missing_ok=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(422, f"document export failed: {str(exc)[:700]}") from None
    return {
        "path": target.relative_to(_root()).as_posix(),
        "manifest": manifest.relative_to(_root()).as_posix(),
        "draft": draft, "page_count": len(scenes), "format": body.format,
        "output_mode": body.output_mode,
        "message": f"Exported {len(scenes)} validated pages as {body.format.upper()}.",
    }
