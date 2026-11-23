"""V54: reviewed, no-clobber creation of one NEW source file and guarded undo.

Preview is read-only and cannot create directories. Applying is only possible
through the human-facing, local-only endpoint or the V54 bounded-agent approval
bridge; both use the same single-use server-held preview token. Unix traversal
uses directory handles with O_NOFOLLOW where available, with O_EXCL on all
platforms. Undo checks file identity and content before removing anything.
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import json
import os
import secrets
import stat
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_index as index
from automoto import developer_lifecycle as lifecycle
from automoto import developer_safe_patch as patch
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/create", tags=["developer-safe-create"])
LOCK = threading.RLock()
PREVIEWS: "OrderedDict[str, dict]" = OrderedDict()
MAX_PREVIEWS = 24
TTL_SECONDS = 15 * 60
MAX_NEW_BYTES = 64 * 1024
MAX_NEW_LINES = 120
MAX_UNDO = 12
EXTENSIONS = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".html", ".css", ".scss", ".json", ".md", ".txt",
    ".go", ".rs", ".java", ".kt", ".swift", ".php",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".rb", ".sql", ".vue", ".svelte",
})


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    path: str = Field(min_length=1, max_length=1024)
    text: str = Field(min_length=1, max_length=MAX_NEW_BYTES)


class ActIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    path: str = Field(min_length=1, max_length=1024)
    token: str = Field(min_length=32, max_length=32)
    confirmed: Literal[True]


def _target(root: Path, path: str, *, absent: bool = True) -> Path:
    parts = path.split("/")
    if (len(parts) > 9 or any(
        not part or part.startswith(".") or
        index._excluded(part, i < len(parts) - 1)
        for i, part in enumerate(parts)
    )):
        raise HTTPException(403, "New files cannot target restricted, hidden or generated locations.")
    if Path(parts[-1]).suffix.lower() not in EXTENSIONS:
        raise HTTPException(403, "This source filename or extension is not allowed.")
    file = studio._path(root, path)
    if file == root or not file.parent.is_dir():
        raise HTTPException(404, "The destination parent folder must already exist.")
    if absent and (file.exists() or file.is_symlink()):
        raise HTTPException(409, "The source filename already exists. Creation never overwrites.")
    return file


def _parent_id(file: Path) -> tuple[int, int]:
    info = file.parent.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise HTTPException(403, "The destination parent is not a directory.")
    return (info.st_dev, info.st_ino)


def _prune() -> None:
    now = time.monotonic()
    for token, item in list(PREVIEWS.items()):
        if now - item["created"] > TTL_SECONDS:
            PREVIEWS.pop(token, None)
    while len(PREVIEWS) > MAX_PREVIEWS:
        PREVIEWS.popitem(last=False)


def _parent_fd(root: Path, path: str) -> int | None:
    """Open each Unix directory without following links. None on Windows."""
    if os.name == "nt" or not getattr(os, "O_NOFOLLOW", 0):
        return None
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(root, flags)
    try:
        for part in path.split("/")[:-1]:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_new(root: Path, path: str, data: bytes,
              parent_identity: tuple[int, int]) -> tuple[int, int]:
    """Exclusive creation, fsync and guarded cleanup of a partial write."""
    target = _target(root, path)
    fd_parent = _parent_fd(root, path)
    file_fd = None
    created_id = None
    created = False
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        if fd_parent is not None:
            parent = os.fstat(fd_parent)
            if (parent.st_dev, parent.st_ino) != parent_identity:
                raise HTTPException(409, "Destination directory changed since preview.")
            file_fd = os.open(target.name, flags, 0o600, dir_fd=fd_parent)
        else:
            if _parent_id(target) != parent_identity:
                raise HTTPException(409, "Destination directory changed since preview.")
            file_fd = os.open(target, flags, 0o600)
        created = True
        info = os.fstat(file_fd)
        created_id = (info.st_dev, info.st_ino)
        with os.fdopen(file_fd, "wb") as stream:
            file_fd = None
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if fd_parent is not None:
            try:
                os.fsync(fd_parent)
            except OSError:
                pass
        return created_id
    except (OSError, HTTPException) as exc:
        if created and created_id is not None:
            # This file was created by this transaction. Remove only the exact
            # inode, never a replacement by another writer.
            try:
                current = (os.stat(target.name, dir_fd=fd_parent, follow_symlinks=False)
                           if fd_parent is not None else target.lstat())
                if (current.st_dev, current.st_ino) == created_id:
                    if fd_parent is not None:
                        os.unlink(target.name, dir_fd=fd_parent)
                    else:
                        target.unlink()
            except OSError:
                pass
        if isinstance(exc, FileExistsError):
            raise HTTPException(409, "The filename already exists. Nothing was overwritten.") from None
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(403, "The source file could not be created securely.") from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if fd_parent is not None:
            os.close(fd_parent)

def _unchanged(root: Path, path: str, expected_sha: str, identity: tuple[int, int]) -> bool:
    """Compare a no-follow opened regular file with the exact recorded creation."""
    target = _target(root, path, absent=False)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        with os.fdopen(os.open(target, flags), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != identity:
                return False
            if info.st_size > MAX_NEW_BYTES:
                return False
            actual = hashlib.sha256(stream.read(MAX_NEW_BYTES + 1)).hexdigest()
            return actual == expected_sha
    except OSError:
        return False


def _delete_guarded(root: Path, path: str, digest: str, identity: tuple[int, int]) -> None:
    if not _unchanged(root, path, digest, identity):
        raise HTTPException(409, "File was changed or replaced after creation. Undo refused.")
    target = _target(root, path, absent=False)
    fd_parent = _parent_fd(root, path)
    try:
        if fd_parent is not None:
            info = os.stat(target.name, dir_fd=fd_parent, follow_symlinks=False)
            if (info.st_dev, info.st_ino) != identity:
                raise HTTPException(409, "File identity changed. Undo refused.")
            os.unlink(target.name, dir_fd=fd_parent)
        else:
            info = target.lstat()
            if (info.st_dev, info.st_ino) != identity or target.is_symlink():
                raise HTTPException(409, "File identity changed. Undo refused.")
            target.unlink()
    finally:
        if fd_parent is not None:
            os.close(fd_parent)


@router.post("/preview")
def preview(request: Request, body: PreviewIn):
    studio._auth(request)
    root = patch._trusted(body.project)
    target = _target(root, body.path)
    if "\x00" in body.text:
        raise HTTPException(415, "NUL bytes are not allowed in source.")
    data = body.text.encode("utf-8")
    if len(data) > MAX_NEW_BYTES or len(body.text.splitlines()) > MAX_NEW_LINES:
        raise HTTPException(413, "A new file must be 64 KiB or less and at most 120 lines.")
    if body.path.casefold().endswith(".py"):
        try:
            ast.parse(body.text, filename=body.path)
        except (SyntaxError, ValueError, RecursionError):
            raise HTTPException(422, "New file has invalid Python syntax.") from None
    before = ""  # a new file has no previous contents
    diff = "".join(difflib.unified_diff(
        before.splitlines(keepends=True), body.text.splitlines(keepends=True),
        fromfile="/dev/null", tofile="b/" + body.path,
    ))
    token = secrets.token_hex(16)
    item = {
        "created": time.monotonic(), "identity": studio._identity(root),
        "path": body.path, "parent_id": _parent_id(target),
        "sha256": hashlib.sha256(data).hexdigest(), "data": data,
    }
    with LOCK:
        _prune()
        PREVIEWS[token] = item
        _prune()
    return {
        "token": token, "path": body.path, "after_sha256": item["sha256"],
        "preview_diff": diff, "changed_lines": len(body.text.splitlines()),
        "syntax_checked": body.path.endswith(".py"), "file_exists": False,
        "prepared_by_server": True, "creation": True, "source_modified": False,
        "requires_confirmation": True, "expires_in_seconds": TTL_SECONDS,
    }


def _apply_checked(root: Path, path: str, token: str) -> dict:
    with LOCK:
        _prune()
        item = PREVIEWS.get(token)
        if not patch.TOKEN.fullmatch(token) or item is None:
            raise HTTPException(409, "Creation preview expired, invalid or already used.")
        if item["identity"] != studio._identity(root) or item["path"] != path:
            raise HTTPException(409, "Preview belongs to another project or file.")
        target = _target(root, path)
        if _parent_id(target) != tuple(item["parent_id"]):
            raise HTTPException(409, "Parent folder changed since preview.")
        created_id = _open_new(root, path, item["data"], tuple(item["parent_id"]))
        undo_id = secrets.token_hex(16)
        record = {
            "identity": item["identity"], "path": path,
            "sha256": item["sha256"], "inode": list(created_id),
            "parent_id": list(item["parent_id"]), "created_at": time.time(),
        }
        try:
            folder = lifecycle._private_dir(root, path, "create-undo")
            lifecycle._atomic_private(folder, undo_id + ".json",
                                      json.dumps(record).encode("utf-8"))
        except Exception:
            # A newly created file without an undo record is not acceptable.
            # Roll back only if the exact file and bytes remain unchanged.
            _delete_guarded(root, path, item["sha256"], created_id)
            raise
        PREVIEWS.pop(token, None)
        records = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True)
        for old in records[MAX_UNDO:]:
            if not old.is_symlink():
                old.unlink(missing_ok=True)
        return {
            "created": True, "path": path, "sha256": item["sha256"],
            "undo_id": undo_id, "source_modified": True,
            "executed": False, "shared": False,
        }


@router.post("/apply")
def apply(request: Request, body: ActIn):
    patch._require_ui(request)
    root = patch._trusted(body.project)
    return _apply_checked(root, body.path, body.token)


@router.post("/undo")
def undo(request: Request, body: ActIn):
    patch._require_ui(request)
    root = patch._trusted(body.project)
    if not patch.TOKEN.fullmatch(body.token):
        raise HTTPException(422, "Invalid undo identifier.")
    with LOCK:
        folder = lifecycle._private_dir(root, body.path, "create-undo")
        record = folder / (body.token + ".json")
        if record.is_symlink() or not record.is_file() or record.stat().st_size > 4096:
            raise HTTPException(404, "Creation undo record not found.")
        try:
            item = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            raise HTTPException(409, "Undo record cannot be verified.") from None
        if (item.get("identity") != studio._identity(root) or
            item.get("path") != body.path or
            not patch.editor.SHA.fullmatch(str(item.get("sha256", ""))) or
            not isinstance(item.get("inode"), list) or len(item["inode"]) != 2 or
            not isinstance(item.get("parent_id"), list) or len(item["parent_id"]) != 2):
            raise HTTPException(409, "Undo record does not match project identity.")
        target = _target(root, body.path, absent=False)
        if _parent_id(target) != tuple(item["parent_id"]):
            raise HTTPException(409, "Parent folder changed. Undo refused.")
        _delete_guarded(root, body.path, item["sha256"], tuple(item["inode"]))
        record.unlink(missing_ok=True)
        return {"undone": True, "path": body.path, "removed_new_file": True,
                "source_modified": True}
