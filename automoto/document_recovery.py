"""v7 private recovery checkpoints for editable Document Assistant sources.

Explicit opt-in browser snapshots are write-once, bounded, checksum validated,
owner-scoped and never overwrite imported Office files or existing drafts.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import ConfigDict, ValidationError

from automoto.document_workspace import (
    DocumentSource, _atomic_file, _folder, _root
)
from automoto.visual_studio import _auth

router = APIRouter(prefix="/api/documents/recovery", tags=["document-recovery"])
MAX_CHECKPOINTS = 16
MAX_CHECKPOINT_BYTES = 750_000
ID_RE = re.compile(r"^[a-f0-9]{24}$")
FILE_RE = re.compile(r"^([a-f0-9]{24})\.recovery\.json$")


class CheckpointIn(DocumentSource):
    model_config = ConfigDict(extra="forbid")


def _folder_private(create: bool = False) -> Path:
    base = _folder()
    folder = base / "recovery"
    if base.is_symlink() or folder.is_symlink():
        raise HTTPException(403, "Recovery symlinks are not permitted")
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    if folder.exists() and (not folder.is_dir() or folder.is_symlink()):
        raise HTTPException(403, "Recovery location is not a private directory")
    if not folder.resolve().is_relative_to(_root()):
        raise HTTPException(403, "Recovery location escapes the current workspace")
    return folder


def _check_id(identifier: str) -> str:
    if not ID_RE.fullmatch(identifier):
        raise HTTPException(422, "Invalid recovery identifier")
    return identifier


def _file(identifier: str) -> Path:
    path = _folder_private() / (_check_id(identifier) + ".recovery.json")
    if path.is_symlink() or not path.resolve().is_relative_to(_root()):
        raise HTTPException(403, "Recovery file symlink is prohibited")
    if not path.is_file():
        raise HTTPException(404, "Recovery checkpoint not found")
    if path.stat().st_size > MAX_CHECKPOINT_BYTES:
        raise HTTPException(413, "Recovery checkpoint exceeds the permitted size")
    return path


def _canonical(data: dict[str, Any]) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _decode(path: Path) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("schema") != 1:
            raise ValueError("Unsupported snapshot schema")
        source = CheckpointIn.model_validate(record["source"])
        data = source.model_dump(exclude_none=True)
        if record.get("sha256") != hashlib.sha256(_canonical(data)).hexdigest():
            raise ValueError("Checkpoint content is corrupted")
        if not isinstance(record.get("created"), str) or len(record["created"]) > 40:
            raise ValueError("Invalid creation date")
        return {"created": record["created"], "sha256": record["sha256"], "source": data}
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, ValidationError):
        raise HTTPException(422, "Saved recovery checkpoint failed integrity validation") from None


def _recent_files() -> list[Path]:
    folder = _folder_private()
    if not folder.is_dir():
        return []
    candidates = [
        path for path in folder.iterdir() if FILE_RE.fullmatch(path.name)
        and path.is_file() and not path.is_symlink()
    ]
    return sorted(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name),
                  reverse=True)


@router.post("/save")
def save_checkpoint(body: CheckpointIn, request: Request):
    _auth(request)
    if not body.markdown.strip():
        raise HTTPException(422, "Cannot save an empty recovery checkpoint")
    data = body.model_dump(exclude_none=True)
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record = {"schema": 1, "created": created, "source": data,
              "sha256": hashlib.sha256(_canonical(data)).hexdigest()}
    raw = _canonical(record)
    if len(raw) > MAX_CHECKPOINT_BYTES:
        raise HTTPException(413, "Recovery checkpoint is too large")
    folder = _folder_private(create=True)
    identifier = secrets.token_hex(12)
    path = folder / (identifier + ".recovery.json")
    _atomic_file(path, raw)
    # Write-first pruning: a failing new save cannot destroy the last usable
    # snapshot. No broader document history or imported source is touched.
    old = _recent_files()[MAX_CHECKPOINTS:]
    for retired in old:
        retired.unlink(missing_ok=True)
    return {"id": identifier, "created": created, "sha256": record["sha256"],
            "message": "Saved a private recovery point; existing documents are unchanged"}


@router.get("/list")
def list_checkpoints(request: Request):
    _auth(request)
    items = []
    for path in _recent_files()[:MAX_CHECKPOINTS]:
        identifier = FILE_RE.fullmatch(path.name).group(1)
        try:
            record = _decode(path)
        except HTTPException:
            items.append({"id": identifier, "valid": False,
                          "name": "Damaged checkpoint", "created": "",
                          "bytes": path.stat().st_size})
            continue
        items.append({"id": identifier, "valid": True,
                      "name": record["source"]["name"],
                      "created": record["created"], "sha256": record["sha256"],
                      "bytes": path.stat().st_size})
    return {"checkpoints": items, "limit": MAX_CHECKPOINTS,
            "private": True, "note": "Recovery points do not automatically overwrite your drafts."}


@router.get("/load")
def load_checkpoint(id: str, request: Request):
    _auth(request)
    result = _decode(_file(id))
    return {"id": id, **result, "read_only": True, "applied": False,
            "message": "Restore this snapshot explicitly in the editor; it will not overwrite your original."}


@router.delete("/{id}")
def delete_checkpoint(id: str, request: Request):
    _auth(request)
    path = _file(id)
    path.unlink()
    return {"deleted": True, "id": id, "message": "Private recovery point deleted"}
