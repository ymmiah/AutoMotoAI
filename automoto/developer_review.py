"""Developer Studio review checkpoints: Keep or Undo what one agent task changed.

Before a coding task starts, the Studio records a bounded copy of the trusted
project's ordinary source files. After the task, it lists what changed (with a
text diff) so the user can keep the result or undo it. Undo restores changed
and deleted files from the copy and removes files the task created. Nothing is
executed. Excluded folders (``.git``, ``node_modules``, secrets ...) and
symbolic links are never copied or touched, and undo refuses to delete new
files when the copy was incomplete.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import secrets
import shutil
import stat
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Optional

from automoto import developer_studio as studio
from automoto import home

router = APIRouter(prefix="/api/developer/studio/review", tags=["developer-review"])
MAX_FILES = 3000
MAX_FILE = 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_DIFF_FILE = 128 * 1024
MAX_DIFF_LINES = 400
MAX_CHANGES = 200
KEEP_CHECKPOINTS = 6
_ID_CHARS = set("0123456789abcdef")


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)


class CheckpointIn(StartIn):
    checkpoint: str = Field(min_length=16, max_length=64)


class UndoIn(CheckpointIn):
    confirmed: Literal[True]
    paths: Optional[list[str]] = Field(default=None, max_length=MAX_CHANGES)


def _base() -> Path:
    folder = home.home() / "developer-studio" / "checkpoints"
    if folder.is_symlink():
        raise HTTPException(403, "Checkpoint folder cannot be a symlink.")
    return folder


def _folder(checkpoint: str) -> Path:
    if not set(checkpoint) <= _ID_CHARS:
        raise HTTPException(422, "Invalid checkpoint.")
    folder = _base() / checkpoint
    if folder.is_symlink() or not (folder / "manifest.json").is_file():
        raise HTTPException(404, "Checkpoint not found. It may already be kept or undone.")
    return folder


def _walk(root: Path):
    """Yield (relative posix path, Path) for ordinary files, skipping excluded names and links."""
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            with os.scandir(folder) as it:
                items = sorted(it, key=lambda e: e.name)
        except OSError:
            continue
        for item in items:
            if studio._forbidden(item.name) or item.is_symlink():
                continue
            path = Path(item.path)
            if getattr(path, "is_junction", lambda: False)():
                continue
            try:
                if item.is_dir(follow_symlinks=False):
                    stack.append(path)
                elif item.is_file(follow_symlinks=False):
                    yield path.relative_to(root).as_posix(), path
            except OSError:
                continue


def _digest(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _state(root: Path) -> dict:
    files, total, complete = {}, 0, True
    for rel, path in _walk(root):
        if len(files) >= MAX_FILES:
            complete = False
            break
        try:
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE or total + info.st_size > MAX_TOTAL:
                complete = False
                continue
            digest, size = _digest(path)
        except OSError:
            complete = False
            continue
        total += size
        files[rel] = {"sha256": digest, "size": size}
    return {"files": files, "complete": complete}


def _manifest(folder: Path) -> dict:
    return json.loads((folder / "manifest.json").read_text(encoding="utf-8"))


def _prune() -> None:
    base = _base()
    if not base.is_dir():
        return
    folders = sorted((p for p in base.iterdir() if p.is_dir() and not p.is_symlink()),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    for old in folders[KEEP_CHECKPOINTS:]:
        shutil.rmtree(old, ignore_errors=True)


def _trusted_root(project: str) -> Path:
    root = studio._project(project)
    if not studio._trusted(root, studio._load()):
        raise HTTPException(403, "Trust this project first.")
    return root


def _text(data: bytes) -> Optional[list[str]]:
    if len(data) > MAX_DIFF_FILE or b"\x00" in data:
        return None
    try:
        return data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None


def _changes(root: Path, folder: Path, manifest: dict) -> list[dict]:
    before = manifest["files"]
    now = _state(root)["files"]
    out = []
    for rel in sorted(set(before) | set(now)):
        if rel in before and rel in now and before[rel]["sha256"] == now[rel]["sha256"]:
            continue
        if rel not in now and not (root / rel).exists() and rel not in before:
            continue
        kind = "added" if rel not in before else "deleted" if rel not in now else "modified"
        if kind == "deleted" and (root / rel).exists():
            continue  # file grew past the copy limits; it was not deleted
        old = (folder / "files" / rel).read_bytes() if kind != "added" else b""
        try:
            new = (root / rel).read_bytes() if kind != "deleted" else b""
        except OSError:
            new = b""
        a, b = _text(old), _text(new)
        entry = {"path": rel, "change": kind, "added": 0, "removed": 0, "diff": None, "binary": a is None or b is None}
        if a is not None and b is not None:
            lines = list(difflib.unified_diff(a, b, "before/" + rel, "after/" + rel, lineterm="", n=3))
            entry["added"] = sum(1 for x in lines if x.startswith("+") and not x.startswith("+++"))
            entry["removed"] = sum(1 for x in lines if x.startswith("-") and not x.startswith("---"))
            entry["diff"] = "\n".join(lines[:MAX_DIFF_LINES])
            entry["diff_truncated"] = len(lines) > MAX_DIFF_LINES
        out.append(entry)
        if len(out) >= MAX_CHANGES:
            break
    return out


@router.post("/start")
def start(body: StartIn, request: Request):
    studio._auth(request)
    root = _trusted_root(body.project)
    checkpoint = secrets.token_hex(12)
    folder = _base() / checkpoint
    (folder / "files").mkdir(parents=True, exist_ok=False)
    os.chmod(folder, 0o700)
    state = _state(root)
    for rel in list(state["files"]):
        target = folder / "files" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(root / rel, target, follow_symlinks=False)
        except OSError:
            state["files"].pop(rel)
            state["complete"] = False
    manifest = {"project": str(root), "identity": studio._identity(root), "created": time.time(), **state}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _prune()
    return {"checkpoint": checkpoint, "files": len(state["files"]), "complete": state["complete"]}


@router.get("/changes")
def changes(request: Request, project: str, checkpoint: str):
    studio._auth(request)
    root = studio._project(project)
    folder = _folder(checkpoint)
    manifest = _manifest(folder)
    if manifest.get("identity") != studio._identity(root):
        raise HTTPException(409, "This checkpoint belongs to a different project.")
    items = _changes(root, folder, manifest)
    return {"checkpoint": checkpoint, "complete": manifest["complete"], "changes": items,
            "added": sum(i["added"] for i in items), "removed": sum(i["removed"] for i in items)}


@router.post("/keep")
def keep(body: CheckpointIn, request: Request):
    studio._auth(request)
    studio._project(body.project)
    folder = _folder(body.checkpoint)
    shutil.rmtree(folder, ignore_errors=True)
    return {"kept": True}


@router.post("/undo")
def undo(body: UndoIn, request: Request):
    studio._auth(request)
    root = _trusted_root(body.project)
    folder = _folder(body.checkpoint)
    manifest = _manifest(folder)
    if manifest.get("identity") != studio._identity(root):
        raise HTTPException(409, "This checkpoint belongs to a different project.")
    items = _changes(root, folder, manifest)
    wanted = set(body.paths) if body.paths is not None else None
    restored, removed, skipped = [], [], []
    for item in items:
        rel = item["path"]
        if wanted is not None and rel not in wanted:
            continue
        target = studio._path(root, rel) if item["change"] != "deleted" else None
        if item["change"] == "added":
            if not manifest["complete"]:
                skipped.append({"path": rel, "reason": "The checkpoint was incomplete, so new files are left in place."})
                continue
            target.unlink(missing_ok=True)
            removed.append(rel)
            continue
        if target is None:
            parent = studio._path(root, str(Path(rel).parent.as_posix())) if "/" in rel else root
            parent.mkdir(parents=True, exist_ok=True)
            target = parent / Path(rel).name
            if target.is_symlink():
                skipped.append({"path": rel, "reason": "A link now sits at this path."})
                continue
        shutil.copyfile(folder / "files" / rel, target, follow_symlinks=False)
        restored.append(rel)
    if wanted is None:
        shutil.rmtree(folder, ignore_errors=True)
    return {"restored": restored, "removed": removed, "skipped": skipped}


# Tools & languages page: path-based availability only. Nothing is executed.
TOOLCHAINS = {
    "typescript": ["tsc", "node"], "javascript": ["node"], "python": ["python3", "python"],
    "php": ["php"], "sql": ["sqlite3"], "go": ["go"], "rust": ["cargo", "rustc"],
    "native": ["gcc", "clang", "cc", "cl"], "jvm": ["java", "javac"], "dotnet": ["dotnet"],
    "android": ["adb", "gradle"], "swift": ["swift", "xcodebuild"], "ios": ["xcodebuild"],
    "mobile": ["flutter", "npx"], "shell": ["bash", "pwsh", "sh"], "scripting": ["ruby", "lua", "perl"],
    "science": ["Rscript", "julia"], "functional": ["scala", "dotnet", "clojure"],
    "beam": ["erl", "elixir", "gleam"], "logic": ["ghc", "ocaml", "swipl", "sbcl"],
    "legacy": ["gfortran", "cobc", "gnat", "fpc", "nasm"], "wasm": ["wasm-tools", "wat2wasm"],
    "latex": ["tectonic", "latexmk"], "typst": ["typst", "quarto"],
}


@router.get("/toolchains")
def toolchains(request: Request):
    studio._auth(request)
    out = {}
    for key, names in TOOLCHAINS.items():
        found = next((n for n in names if shutil.which(n)), None)
        out[key] = {"installed": bool(found), "tool": found, "checked": names}
    return {"toolchains": out, "verification": "executable located on PATH; not run"}
