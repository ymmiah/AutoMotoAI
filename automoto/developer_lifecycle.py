"""Developer Studio V3 — safe file operations and private crash recovery.

Authenticated local-only routes, reusing V1 roots and V2 content preconditions.
No source execution, cloud persistence, automatic overwrites or irreversible delete.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import stat
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_editor as edit, developer_studio as studio, home

router = APIRouter(prefix="/api/developer/studio", tags=["developer-lifecycle"])
LOCK = threading.RLock()
MAX_SNAPSHOTS = 3
MAX_DIFF_LINES = 700
UUID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)


class FileOperation(ProjectIn):
    action: Literal["create", "rename", "trash"]
    path: str = Field(min_length=1, max_length=1024)
    destination: str | None = Field(default=None, max_length=1024)
    expected_sha256: str | None = Field(default=None, max_length=64)
    confirmed: Literal[True]


class WorkingCopy(ProjectIn):
    path: str = Field(min_length=1, max_length=1024)
    text: str = Field(max_length=edit.MAX_BYTES)
    encoding: edit.Enc
    newline: edit.Newline
    expected_sha256: str = Field(min_length=64, max_length=64)
    confirmed: Literal[True]


class SnapshotLookup(ProjectIn):
    path: str = Field(min_length=1, max_length=1024)
    snapshot_id: str = Field(min_length=32, max_length=32)


def _allowed(project: str) -> Path:
    root = studio._project(project)
    with studio.STATE_LOCK:
        if not studio._trusted(root, studio._load()):
            raise HTTPException(403, "Trust the exact project to manage files or recovery.")
    return root


def _source(root: Path, path: str, expected: str | None = None) -> tuple[Path, bytes]:
    file = studio._path(root, path)
    if file == root or not file.is_file():
        raise HTTPException(404, "Existing source file required.")
    data, _ = edit._raw(file)
    if expected is not None:
        if not edit.SHA.fullmatch(expected):
            raise HTTPException(422, "Invalid expected file checksum.")
        if hashlib.sha256(data).hexdigest() != expected:
            raise HTTPException(409, "Source changed since it was opened.")
    return file, data


def _destination(root: Path, path: str) -> Path:
    dest = studio._path(root, path)
    if dest == root or dest.exists() or dest.is_symlink():
        raise HTTPException(409, "Destination already exists.")
    parent = dest.parent
    if not parent.is_dir() or parent.is_symlink():
        raise HTTPException(404, "Destination parent directory must exist.")
    return dest


def _private_dir(root: Path, path: str, kind: str) -> Path:
    # Isolate per exact root identity and project-relative file.
    identity = json.dumps(studio._identity(root), sort_keys=True)
    key = hashlib.sha256((identity + "\x00" + path).encode("utf-8")).hexdigest()
    base = home.home() / "developer-studio" / kind
    directory = base / key
    for folder in (home.home() / "developer-studio", base, directory):
        if folder.is_symlink():
            raise HTTPException(403, "Recovery path cannot be a symbolic link.")
        folder.mkdir(mode=0o700, parents=False, exist_ok=True)
        if not folder.is_dir():
            raise HTTPException(403, "Recovery path is not a directory.")
        if os.name != "nt":
            os.chmod(folder, 0o700)
    return directory


def _atomic_private(folder: Path, name: str, data: bytes) -> None:
    if len(data) > edit.MAX_BYTES * 3:
        raise HTTPException(413, "Recovery record is too large.")
    target = folder / name
    if target.is_symlink():
        raise HTTPException(403, "Recovery record cannot be linked.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".stage-", delete=False) as stream:
            temporary = Path(stream.name)
            if os.name != "nt":
                os.chmod(temporary, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _snapshot_payload(root: Path, body: WorkingCopy, *, disk: bytes) -> dict:
    return {
        "project": studio._identity(root),
        "path": body.path,
        "expected_sha256": body.expected_sha256,
        "encoding": body.encoding,
        "newline": body.newline,
        "text": body.text,
        "disk_sha256": hashlib.sha256(disk).hexdigest(),
    }


def _store_snapshot(root: Path, body: WorkingCopy, disk: bytes) -> str:
    folder = _private_dir(root, body.path, "recovery")
    uid = uuid.uuid4().hex
    payload = _snapshot_payload(root, body, disk=disk)
    _atomic_private(folder, uid + ".json", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    items = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for stale in items[MAX_SNAPSHOTS:]:
        if not stale.is_symlink():
            stale.unlink(missing_ok=True)
    return uid


def _read_snapshot(root: Path, path: str, snapshot_id: str) -> dict:
    if not UUID_PATTERN.fullmatch(snapshot_id):
        raise HTTPException(422, "Invalid recovery identifier.")
    folder = _private_dir(root, path, "recovery")
    record = folder / (snapshot_id + ".json")
    if record.is_symlink():
        raise HTTPException(403, "Recovery record cannot be linked.")
    try:
        if record.stat().st_size > edit.MAX_BYTES * 3:
            raise ValueError("oversized")
        data = json.loads(record.read_text(encoding="utf-8"))
        if data.get("path") != path or data.get("project") != studio._identity(root):
            raise ValueError("wrong project identity")
        if not isinstance(data.get("text"), str) or len(data["text"].encode("utf-8")) > edit.MAX_BYTES * 2:
            raise ValueError("invalid text")
        return data
    except FileNotFoundError:
        raise HTTPException(404, "Recovery snapshot not found.") from None
    except (ValueError, OSError, UnicodeError, AttributeError):
        raise HTTPException(422, "Recovery record could not be verified.") from None


@router.post("/snapshot")
def snapshot(request: Request, body: WorkingCopy):
    studio._auth(request)
    root = _allowed(body.project)
    with LOCK:
        _, disk = _source(root, body.path, body.expected_sha256)
        edit._encode(body.text, body.encoding, body.newline)
        uid = _store_snapshot(root, body, disk)
    return {"snapshot_id": uid, "saved_locally": True, "source_modified": False}


@router.get("/snapshots")
def snapshots(request: Request, project: str, path: str):
    studio._auth(request)
    root = _allowed(project)
    _source(root, path)
    folder = _private_dir(root, path, "recovery")
    found = []
    for record in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True)[:MAX_SNAPSHOTS]:
        if not record.is_symlink() and UUID_PATTERN.fullmatch(record.stem):
            try:
                item = _read_snapshot(root, path, record.stem)
                found.append({"snapshot_id": record.stem, "base_sha256": item["expected_sha256"]})
            except HTTPException:
                continue
    return {"items": found, "local_only": True}


@router.get("/recovery")
def recovery(request: Request, project: str, path: str, snapshot_id: str):
    studio._auth(request)
    root = _allowed(project)
    # Recovery is a working-copy download, NOT an automatic disk overwrite.
    record = _read_snapshot(root, path, snapshot_id)
    return {"path": path, "text": record["text"], "encoding": record["encoding"],
            "newline": record["newline"], "base_sha256": record["expected_sha256"],
            "restored_to_disk": False, "source_modified": False}


@router.post("/discard-snapshot")
def discard_snapshot(request: Request, body: SnapshotLookup):
    studio._auth(request)
    root = _allowed(body.project)
    _read_snapshot(root, body.path, body.snapshot_id)
    (_private_dir(root, body.path, "recovery") / (body.snapshot_id + ".json")).unlink()
    return {"discarded": True}


@router.post("/diff")
def diff_preview(request: Request, body: WorkingCopy):
    studio._auth(request)
    root = _allowed(body.project)
    _, disk = _source(root, body.path, body.expected_sha256)
    source, encoding = edit._decode(disk, "auto" if body.encoding != "cp1252" else "cp1252")
    if encoding != body.encoding:
        raise HTTPException(409, "Encoding changed on disk.")
    edit._encode(body.text, body.encoding, body.newline)
    old = source.splitlines(keepends=True)
    new = body.text.splitlines(keepends=True)
    parts = list(difflib.unified_diff(old, new, fromfile="Saved source", tofile="Unsaved working copy", n=3))
    limited = parts[:MAX_DIFF_LINES]
    return {"diff": "".join(limited), "changed": bool(parts), "truncated": len(parts) > MAX_DIFF_LINES,
            "original_sha256": body.expected_sha256, "saved_to_disk": False}


@router.post("/operation")
def file_operation(request: Request, body: FileOperation):
    studio._auth(request)
    root = _allowed(body.project)
    with LOCK, edit.SAVE_LOCK:
        if body.action == "create":
            if not body.path or body.destination is not None or body.expected_sha256 is not None:
                raise HTTPException(422, "Create takes a new path only.")
            target = _destination(root, body.path)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            try:
                with os.fdopen(os.open(target, flags, 0o600), "wb") as stream:
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError:
                raise HTTPException(409, "File already exists.") from None
            except OSError:
                raise HTTPException(403, "Cannot safely create source file.") from None
            return {"action": "create", "path": body.path, "source_modified": True}

        if not body.expected_sha256:
            raise HTTPException(422, "Existing-source operations require an exact checksum.")
        file, original = _source(root, body.path, body.expected_sha256)
        if body.action == "rename":
            if not body.destination:
                raise HTTPException(422, "Specify a destination path.")
            dest = _destination(root, body.destination)
            # Atomic no-clobber link avoids platform-specific rename overwrite
            # behaviour; if unsupported, fail closed rather than copy unsafely.
            try:
                os.link(file, dest, follow_symlinks=False)
                try:
                    candidate, _ = edit._raw(dest)
                    latest, _ = edit._raw(file)
                    if candidate != original or latest != original:
                        raise HTTPException(409, "Source changed while renaming.")
                    file.unlink()
                except Exception:
                    dest.unlink(missing_ok=True)
                    raise
            except FileExistsError:
                raise HTTPException(409, "Destination already exists.") from None
            except OSError:
                raise HTTPException(403, "This filesystem cannot perform a safe no-overwrite rename.") from None
            return {"action": "rename", "path": body.destination, "old_path": body.path, "source_modified": True}

        # Soft-delete: preserve verified bytes privately BEFORE removing source.
        # Recovery is manually controlled. No permanent-delete API in V3.
        folder = _private_dir(root, body.path, "trash")
        uid = uuid.uuid4().hex
        _atomic_private(folder, uid + ".bin", original)
        verified = (folder / (uid + ".bin")).read_bytes()
        latest, _ = edit._raw(file)
        if verified != original or latest != original:
            (folder / (uid + ".bin")).unlink(missing_ok=True)
            raise HTTPException(409, "Source changed before archival. Delete cancelled.")
        file.unlink()
        return {"action": "trash", "archive_id": uid, "source_modified": True, "reversible": True}


@router.post("/restore-trash")
def restore_trash(request: Request, body: SnapshotLookup):
    studio._auth(request)
    root = _allowed(body.project)
    if not UUID_PATTERN.fullmatch(body.snapshot_id):
        raise HTTPException(422, "Invalid archive ID.")
    with LOCK, edit.SAVE_LOCK:
        folder = _private_dir(root, body.path, "trash")
        archived = folder / (body.snapshot_id + ".bin")
        if archived.is_symlink() or not archived.is_file():
            raise HTTPException(404, "Recovery archive unavailable.")
        if archived.stat().st_size > edit.MAX_BYTES:
            raise HTTPException(413, "Recovery archive is too large.")
        target = _destination(root, body.path)
        data = archived.read_bytes()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        try:
            with os.fdopen(os.open(target, flags, 0o600), "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            raise HTTPException(409, "Restore destination already exists.") from None
        except OSError:
            raise HTTPException(403, "Cannot restore archive.") from None
        if target.read_bytes() != data:
            raise HTTPException(409, "Restore integrity check failed.")
        archived.unlink()
        return {"restored": True, "path": body.path, "sha256": hashlib.sha256(data).hexdigest()}
