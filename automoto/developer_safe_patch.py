"""V51: preview, apply and undo one checked source patch at a time.

Local-only, existing regular files and one unambiguous literal replacement.
Preview reads only; Apply and Undo are UI actions requiring explicit consent.
The actual disk write is delegated to Developer Studio's existing atomic,
checksum-checked editor. Undo records are kept in its private recovery folder.
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import json
import re
import secrets
import threading
import time
from collections import OrderedDict
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_editor as editor
from automoto import developer_index as index
from automoto import developer_lifecycle as lifecycle
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/patch", tags=["developer-safe-patch"])
MAX_FRAGMENT = 8000
MAX_CHANGED_LINES = 80
MAX_DIFF_LINES = 180
PREVIEW_SECONDS = 15 * 60
MAX_PREVIEWS = 30
UNDO_RECORDS = 12
TOKEN = re.compile(r"^[0-9a-f]{32}$")
LOCK = threading.RLock()
PREVIEWS: "OrderedDict[str, dict]" = OrderedDict()


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    path: str = Field(min_length=1, max_length=1024)
    expected_sha256: str = Field(min_length=64, max_length=64)
    old_fragment: str = Field(min_length=1, max_length=MAX_FRAGMENT)
    new_fragment: str = Field(max_length=MAX_FRAGMENT)


class ActIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    path: str = Field(min_length=1, max_length=1024)
    token: str = Field(min_length=32, max_length=32)
    confirmed: Literal[True]


def _trusted(project: str):
    root = studio._project(project)
    with studio.STATE_LOCK:
        if not studio._trusted(root, studio._load()):
            raise HTTPException(403, "Trust this exact project before editing.")
    return root


def _file(root, path: str):
    parts = path.split("/")
    if any(index._excluded(part, i < len(parts) - 1) for i, part in enumerate(parts)):
        raise HTTPException(403, "Protected source files cannot be patched.")
    target = studio._path(root, path)
    if target == root or not target.is_file():
        raise HTTPException(404, "Choose an existing ordinary source file.")
    return target


def _source(root, path):
    target = _file(root, path)
    raw, _ = editor._raw(target)
    text, encoding = editor._decode(raw, "auto")
    newline = editor._newlines(text)
    if newline == "mixed":
        raise HTTPException(422, "Mixed line endings must be resolved in the editor first.")
    return raw, text, encoding, newline


def _require_ui(request: Request):
    studio._auth(request)
    if getattr(request.state, "automoto_agent_call", False):
        raise HTTPException(403, "Only the human-facing patch review can apply or undo a patch.")


def _prune():
    now = time.monotonic()
    for key, item in list(PREVIEWS.items()):
        if now - item["created"] > PREVIEW_SECONDS:
            PREVIEWS.pop(key, None)
    while len(PREVIEWS) > MAX_PREVIEWS:
        PREVIEWS.popitem(last=False)


def _folder(root, path):
    return lifecycle._private_dir(root, path, "patch-undo")


def _undo_record(root, path, token):
    if not TOKEN.fullmatch(token):
        raise HTTPException(422, "Invalid undo identifier.")
    file = _folder(root, path) / (token + ".json")
    if file.is_symlink() or not file.is_file() or file.stat().st_size > 400_000:
        raise HTTPException(404, "Undo record not found.")
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeError):
        raise HTTPException(422, "Undo record could not be verified.") from None
    if (data.get("identity") != studio._identity(root) or
        data.get("path") != path or
        not isinstance(data.get("previous_text"), str) or
        not editor.SHA.fullmatch(str(data.get("before_sha256", ""))) or
        not editor.SHA.fullmatch(str(data.get("after_sha256", "")))):
        raise HTTPException(409, "Undo record does not match this project and file.")
    try:
        recovered = editor._encode(data["previous_text"], data["encoding"], data["newline"])
    except (KeyError, ValueError, TypeError, HTTPException):
        raise HTTPException(409, "Undo record encoding or content could not be verified.") from None
    if hashlib.sha256(recovered).hexdigest() != data["before_sha256"]:
        raise HTTPException(409, "Undo record failed its source integrity check.")
    return file, data


@router.post("/preview")
def preview(request: Request, body: PreviewIn):
    studio._auth(request)
    root = _trusted(body.project)
    if not editor.SHA.fullmatch(body.expected_sha256):
        raise HTTPException(422, "Invalid expected file digest.")
    raw, original, encoding, newline = _source(root, body.path)
    original_hash = hashlib.sha256(raw).hexdigest()
    if original_hash != body.expected_sha256:
        raise HTTPException(409, "Stale source. Reopen the file before building a patch.")
    count = original.count(body.old_fragment)
    if count != 1:
        raise HTTPException(409, "The patch must match exactly one place in the original file.")
    proposed = original.replace(body.old_fragment, body.new_fragment, 1)
    if proposed == original:
        raise HTTPException(422, "No source changes were proposed.")
    diff = list(difflib.unified_diff(
        original.splitlines(keepends=True), proposed.splitlines(keepends=True),
        fromfile="before/" + body.path, tofile="after/" + body.path, n=3))
    changed = sum(1 for line in diff if (line.startswith("+") and not line.startswith("+++")) or
                  (line.startswith("-") and not line.startswith("---")))
    if changed > MAX_CHANGED_LINES or len(diff) > MAX_DIFF_LINES:
        raise HTTPException(413, "Patch is too large. Propose a smaller change.")
    encoded = editor._encode(proposed, encoding, newline)
    if len(encoded) > editor.MAX_BYTES:
        raise HTTPException(413, "Patched file is too large.")
    if body.path.casefold().endswith(".py"):
        try:
            ast.parse(proposed, filename=body.path)
        except (SyntaxError, ValueError, RecursionError):
            raise HTTPException(422, "Patch does not produce valid Python syntax.") from None
    item = {
        "created": time.monotonic(), "identity": studio._identity(root),
        "project": str(root), "path": body.path, "original_sha256": original_hash,
        "after_sha256": hashlib.sha256(encoded).hexdigest(),
        "old_text": original, "new_text": proposed, "encoding": encoding,
        "newline": newline,
    }
    token = secrets.token_hex(16)
    with LOCK:
        _prune()
        PREVIEWS[token] = item
        _prune()
    return {
        "token": token, "path": body.path,
        "original_sha256": original_hash, "after_sha256": item["after_sha256"],
        "diff": "".join(diff), "changed_lines": changed, "syntax_checked": body.path.casefold().endswith(".py"),
        "source_modified": False, "requires_confirmation": True,
        "expires_in_seconds": PREVIEW_SECONDS, "local_only": True,
    }


def _apply_checked(root, path: str, token: str, request: Request):
    """Private atomic V51 transaction; caller must enforce explicit consent.

    The API route enforces UI-only authorisation. V53's bounded-agent bridge
    calls this function only after the independent per-tool approval succeeds.
    """
    _file(root, path)
    if not TOKEN.fullmatch(token):
        raise HTTPException(422, "Invalid patch identifier.")
    with LOCK:
        _prune()
        item = PREVIEWS.get(token)
        if not item:
            raise HTTPException(409, "Patch preview expired or was already used.")
        if item["identity"] != studio._identity(root) or item["path"] != path:
            raise HTTPException(409, "The preview belongs to another project or file.")
        raw, original, _, _ = _source(root, path)
        if hashlib.sha256(raw).hexdigest() != item["original_sha256"]:
            raise HTTPException(409, "Source changed since preview. Reopen and review.")
        undo_id = secrets.token_hex(16)
        record = {
            "identity": item["identity"], "path": path,
            "previous_text": original, "before_sha256": item["original_sha256"],
            "after_sha256": item["after_sha256"], "encoding": item["encoding"],
            "newline": item["newline"], "created_at": time.time(),
        }
        folder = _folder(root, path)
        lifecycle._atomic_private(folder, undo_id + ".json",
                                  json.dumps(record, ensure_ascii=False).encode("utf-8"))
        model = editor.SaveIn.model_validate({
            "project": str(root), "path": path, "text": item["new_text"],
            "encoding": item["encoding"], "newline": item["newline"],
            "expected_sha256": item["original_sha256"], "confirmed": True,
        })
        try:
            result = editor.save_file(request, model)
        except Exception:
            (folder / (undo_id + ".json")).unlink(missing_ok=True)
            raise
        PREVIEWS.pop(token, None)
        records = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True)
        for old in records[UNDO_RECORDS:]:
            if not old.is_symlink():
                old.unlink(missing_ok=True)
        return {
            "applied": result["changed"], "path": path,
            "sha256": result["sha256"], "undo_id": undo_id,
            "source_modified": result["changed"], "shared": False, "executed": False,
        }


@router.post("/apply")
def apply(request: Request, body: ActIn):
    _require_ui(request)
    root = _trusted(body.project)
    return _apply_checked(root, body.path, body.token, request)

@router.post("/undo")
def undo(request: Request, body: ActIn):
    _require_ui(request)
    root = _trusted(body.project)
    _file(root, body.path)
    with LOCK:
        file, item = _undo_record(root, body.path, body.token)
        model = editor.SaveIn.model_validate({
            "project": str(root), "path": body.path,
            "text": item["previous_text"], "encoding": item["encoding"],
            "newline": item["newline"], "expected_sha256": item["after_sha256"],
            "confirmed": True,
        })
        result = editor.save_file(request, model)
        file.unlink(missing_ok=True)
        return {"undone": result["changed"], "path": body.path,
                "sha256": result["sha256"], "source_modified": result["changed"]}
