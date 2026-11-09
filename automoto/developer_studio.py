"""Developer Studio V1: authenticated, local-only, non-mutating project explorer.

Project files are never edited or executed. Trust decisions only record the
operator's explicit consent for later development stages; V1 remains read-only.
Hosted mode is intentionally excluded by the existing default-deny route gate.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import threading
from pathlib import Path, PurePosixPath
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import home, sandbox

router = APIRouter(prefix="/api/developer/studio", tags=["developer-studio"])
MAX_ITEMS = 200
MAX_PREVIEW = 128 * 1024
MAX_STATE = 32 * 1024
STATE_LOCK = threading.RLock()
EXCLUDED = frozenset({
    ".git", ".svn", ".hg", ".ssh", ".gnupg", ".aws", ".azure", ".kube",
    ".docker", ".venv", "venv", "node_modules", "__pycache__", ".next",
    ".nuxt", ".cache", "dist", "build", ".idea", ".vscode-test"
})


class OpenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(..., min_length=1, max_length=1024)


class TrustIn(OpenIn):
    trusted: bool
    confirmed: Literal[True]


def _auth(request: Request) -> None:
    from automoto import server
    server._authorise(request, local_only=True)


def _forbidden(name: str) -> bool:
    low = name.casefold()
    if low in EXCLUDED:
        return True
    if low.startswith(".env") and low not in {".env.example", ".env.sample", ".env.template", ".env.dist"}:
        return True
    return False


def _project(path: str) -> Path:
    if "\x00" in path:
        raise HTTPException(422, "Invalid project path.")
    try:
        root = sandbox.check_root(path)
        allowed = [sandbox.default_root(), *sandbox.extra_roots()]
        for base in allowed:
            try:
                parts = root.relative_to(base).parts
            except ValueError:
                continue
            if any(_forbidden(part) for part in parts):
                raise HTTPException(403, "Restricted project folder.")
            break
        if _forbidden(root.name):
            raise HTTPException(403, "Restricted project folder.")
        return root
    except (sandbox.SandboxError, OSError, ValueError) as exc:
        raise HTTPException(403, "Project must be inside your approved AutoMoto folders.") from exc


def _state_path() -> Path:
    folder = home.home() / "developer-studio"
    if folder.is_symlink():
        raise HTTPException(403, "Developer Studio settings folder cannot be a symlink.")
    return folder / "workspaces.json"


def _load() -> dict:
    path = _state_path()
    if path.is_symlink():
        raise HTTPException(403, "Developer Studio state cannot be a symlink.")
    try:
        if not path.is_file():
            return {"trusted": [], "recent": []}
        if path.stat().st_size > MAX_STATE:
            raise ValueError("oversized state")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("trusted"), list) or not isinstance(data.get("recent"), list):
            raise ValueError("invalid state")
        return data
    except (OSError, ValueError, UnicodeError):
        # Corrupt state never conveys trust or a stored project selection.
        return {"trusted": [], "recent": []}


def _save(data: dict) -> None:
    path = _state_path()
    if path.is_symlink():
        raise HTTPException(403, "Developer Studio state cannot be a symlink.")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(payload) > MAX_STATE:
        raise HTTPException(413, "Too many workspace records.")
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".workspaces-", delete=False) as out:
            tmp = Path(out.name)
            os.chmod(tmp, 0o600)
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def _identity(root: Path) -> dict:
    info = root.stat()
    return {"path": str(root), "device": info.st_dev, "inode": info.st_ino}


def _trusted(root: Path, state: dict) -> bool:
    record = _identity(root)
    return record in state["trusted"]


def _status(root: Path, state: dict) -> dict:
    return {
        "project": str(root),
        "name": root.name,
        "trusted": _trusted(root, state),
        "read_only": True,
        "can_edit": False,
        "can_execute": False,
    }


def _path(root: Path, relative: str) -> Path:
    if not relative or relative == ".":
        return root
    if "\\" in relative or "\x00" in relative or len(relative) > 1024:
        raise HTTPException(422, "Invalid project-relative path.")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in ("", ".", "..") or _forbidden(part) for part in relative.split("/")):
        raise HTTPException(403, "Unsafe project-relative path.")
    candidate = root
    for part in pure.parts:
        candidate = candidate / part
        if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
            raise HTTPException(403, "Symbolic links and junctions are not browsable.")
    try:
        resolved = sandbox.resolve(str(candidate), base=root, allow_outside=False)
    except sandbox.SandboxError as exc:
        raise HTTPException(403, "Path escapes the project or is restricted.") from exc
    return resolved


@router.get("/roots")
def roots(request: Request):
    _auth(request)
    with STATE_LOCK:
        state = _load()
    folders = [sandbox.default_root(), *sandbox.extra_roots()]
    available = []
    for folder in folders:
        try:
            root = _project(str(folder))
        except HTTPException:
            continue
        if str(root) not in {item["project"] for item in available}:
            available.append(_status(root, state))
    recent = []
    for value in state["recent"][:20]:
        if not isinstance(value, str):
            continue
        try:
            recent.append(_status(_project(value), state))
        except HTTPException:
            continue
    return {"roots": available, "recent": recent, "local_only": True, "read_only": True}


@router.post("/open")
def open_project(body: OpenIn, request: Request):
    _auth(request)
    root = _project(body.project)
    with STATE_LOCK:
        state = _load()
        state["recent"] = [str(root)] + [v for v in state["recent"] if isinstance(v, str) and v != str(root)][:19]
        _save(state)
        result = _status(root, state)
    return result


@router.post("/trust")
def trust_project(body: TrustIn, request: Request):
    _auth(request)
    root = _project(body.project)
    with STATE_LOCK:
        state = _load()
        record = _identity(root)
        state["trusted"] = [r for r in state["trusted"] if isinstance(r, dict) and r.get("path") != str(root)][:63]
        if body.trusted:
            state["trusted"].insert(0, record)
        _save(state)
        result = _status(root, state)
    return result


@router.get("/tree")
def tree(request: Request, project: str, directory: str = "."):
    _auth(request)
    root = _project(project)
    folder = _path(root, directory)
    if not folder.is_dir():
        raise HTTPException(404, "Project directory not found.")
    entries = []
    truncated = False
    try:
        with os.scandir(folder) as iterator:
            for item in iterator:
                if _forbidden(item.name) or item.is_symlink():
                    continue
                child = Path(item.path)
                if getattr(child, "is_junction", lambda: False)():
                    continue
                try:
                    allowed = sandbox.resolve(str(child), base=root, allow_outside=False)
                    if allowed != child.resolve():
                        continue
                    is_dir = item.is_dir(follow_symlinks=False)
                    if not is_dir and not item.is_file(follow_symlinks=False):
                        continue
                    size = None if is_dir else item.stat(follow_symlinks=False).st_size
                except (sandbox.SandboxError, OSError):
                    continue
                entries.append({"name": item.name, "path": child.relative_to(root).as_posix(),
                                "directory": is_dir, "size": size})
                if len(entries) > MAX_ITEMS:
                    entries.pop()
                    truncated = True
                    break
    except OSError:
        raise HTTPException(403, "Directory cannot be read.") from None
    entries.sort(key=lambda e: (not e["directory"], e["name"].casefold()))
    return {"directory": "." if folder == root else folder.relative_to(root).as_posix(),
            "items": entries, "truncated": truncated, "read_only": True}


@router.get("/preview")
def preview(request: Request, project: str, path: str):
    _auth(request)
    root = _project(project)
    file = _path(root, path)
    if file == root:
        raise HTTPException(422, "Choose a source file.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(file, flags)
        with os.fdopen(fd, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise HTTPException(422, "Only ordinary files can be previewed.")
            if metadata.st_size > MAX_PREVIEW:
                raise HTTPException(413, "Source preview limited to 128 KiB.")
            raw = stream.read(MAX_PREVIEW + 1)
    except OSError:
        raise HTTPException(403, "Source file cannot be opened.") from None
    if len(raw) > MAX_PREVIEW or b"\x00" in raw:
        raise HTTPException(415, "Large or binary files are not supported in V1.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(415, "V1 previews UTF-8 source only. Encoding support is planned for V2.") from None
    return {"path": path, "text": text, "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw), "read_only": True, "trusted": _trusted(root, _load())}
