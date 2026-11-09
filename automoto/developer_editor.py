"""Developer Studio V2 — bounded, conflict-safe source editing (local only).

Never execute source. Every save requires a trusted root, an explicit confirmation
flag, byte-for-byte SHA-256 precondition and atomic replacement in the same folder.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
import threading
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio", tags=["developer-editor"])
MAX_BYTES = 128 * 1024
SAVE_LOCK = threading.RLock()
SHA = re.compile(r"^[a-f0-9]{64}$")
Enc = Literal["utf-8", "utf-8-sig", "utf-16-le", "utf-16-be", "cp1252"]
Newline = Literal["lf", "crlf", "cr", "mixed", "none"]


class SaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(..., min_length=1, max_length=1024)
    path: str = Field(..., min_length=1, max_length=1024)
    text: str = Field(..., max_length=MAX_BYTES)
    encoding: Enc
    newline: Newline
    expected_sha256: str = Field(..., min_length=64, max_length=64)
    confirmed: Literal[True]


def _file(project: str, path: str) -> tuple[Path, Path]:
    root = studio._project(project)
    target = studio._path(root, path)
    if target == root or not target.is_file():
        raise HTTPException(404, "Choose an existing regular source file.")
    return root, target


def _raw(file: Path) -> tuple[bytes, os.stat_result]:
    if file.is_symlink() or getattr(file, "is_junction", lambda: False)():
        raise HTTPException(403, "Linked source files cannot be opened.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        with os.fdopen(os.open(file, flags), "rb") as stream:
            info = os.fstat(stream.fileno())
            on_path = file.lstat()
            if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (on_path.st_dev, on_path.st_ino):
                raise HTTPException(409, "Source changed while opening it.")
            if info.st_size > MAX_BYTES:
                raise HTTPException(413, "V2 limits source files to 128 KiB.")
            data = stream.read(MAX_BYTES + 1)
    except OSError:
        raise HTTPException(403, "Source file cannot be read.") from None
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "V2 limits source files to 128 KiB.")
    return data, info


def _decode(data: bytes, requested: str) -> tuple[str, str]:
    if data.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    elif data.startswith(b"\xff\xfe"):
        encoding = "utf-16-le"
    elif data.startswith(b"\xfe\xff"):
        encoding = "utf-16-be"
    else:
        encoding = "utf-8" if requested == "auto" else requested
        if encoding not in {"utf-8", "cp1252"}:
            raise HTTPException(422, "This source has no Unicode BOM. Try UTF-8 or Windows-1252.")
    if requested not in {"auto", encoding}:
        raise HTTPException(422, "Detected encoding does not match requested encoding.")
    if b"\x00" in data and not encoding.startswith("utf-16"):
        raise HTTPException(415, "Binary files cannot be edited as source.")
    payload = data[2:] if encoding.startswith("utf-16") else data
    try:
        text = payload.decode("utf-16-le" if encoding == "utf-16-le" else
                              "utf-16-be" if encoding == "utf-16-be" else encoding)
    except UnicodeError:
        raise HTTPException(415, "File is not valid for the requested encoding.") from None
    if "\x00" in text:
        raise HTTPException(415, "Binary or NUL-containing source files are not editable.")
    return text, encoding


def _newlines(text: str) -> Newline:
    crlf = text.count("\r\n")
    only_lf = text.count("\n") - crlf
    only_cr = text.count("\r") - crlf
    styles = sum(bool(v) for v in (crlf, only_lf, only_cr))
    if styles > 1:
        return "mixed"
    return ("crlf" if crlf else "lf" if only_lf else "cr" if only_cr else "none")


def _encode(text: str, encoding: Enc, newline: Newline) -> bytes:
    if "\x00" in text:
        raise HTTPException(422, "Source cannot contain NUL.")
    if newline == "mixed":
        raise HTTPException(422, "Select LF, CRLF or CR explicitly for mixed-line-ending files.")
    normal = text.replace("\r\n", "\n").replace("\r", "\n")
    if newline == "crlf":
        normal = normal.replace("\n", "\r\n")
    elif newline == "cr":
        normal = normal.replace("\n", "\r")
    elif newline == "none" and "\n" in normal:
        raise HTTPException(422, "Choose a line ending for newly added lines.")
    try:
        if encoding == "utf-16-le":
            result = b"\xff\xfe" + normal.encode("utf-16-le")
        elif encoding == "utf-16-be":
            result = b"\xfe\xff" + normal.encode("utf-16-be")
        else:
            result = normal.encode(encoding)
    except UnicodeError:
        raise HTTPException(422, "Characters cannot be represented in the selected encoding.") from None
    if len(result) > MAX_BYTES:
        raise HTTPException(413, "Edited source would exceed 128 KiB.")
    return result


@router.get("/file")
def open_file(request: Request, project: str, path: str, encoding: str = "auto"):
    studio._auth(request)
    if encoding not in {"auto", "utf-8", "utf-8-sig", "utf-16-le", "utf-16-be", "cp1252"}:
        raise HTTPException(422, "Unknown encoding.")
    root, file = _file(project, path)
    data, _ = _raw(file)
    text, detected = _decode(data, encoding)
    with studio.STATE_LOCK:
        trusted = studio._trusted(root, studio._load())
    return {"path": file.relative_to(root).as_posix(), "text": text, "size": len(data),
            "encoding": detected, "newline": _newlines(text),
            "sha256": hashlib.sha256(data).hexdigest(), "trusted": trusted,
            "can_edit": trusted, "source_modified": False}


@router.post("/save-file")
def save_file(request: Request, body: SaveIn):
    studio._auth(request)
    if not SHA.fullmatch(body.expected_sha256):
        raise HTTPException(422, "Invalid source checksum.")
    root, file = _file(body.project, body.path)
    with SAVE_LOCK, studio.STATE_LOCK:
        if not studio._trusted(root, studio._load()):
            raise HTTPException(403, "Trust this exact project before saving source files.")
        old, info = _raw(file)
        sha = hashlib.sha256(old).hexdigest()
        if sha != body.expected_sha256:
            raise HTTPException(409, "Source changed on disk. Reload and review before trying again.")
        _, actual_encoding = _decode(old, "auto" if body.encoding != "cp1252" else "cp1252")
        if actual_encoding != body.encoding:
            raise HTTPException(409, "Source encoding changed. Reload before saving.")
        if not (stat.S_IMODE(info.st_mode) & stat.S_IWUSR):
            raise HTTPException(403, "Read-only source file cannot be replaced.")
        fresh = _encode(body.text, body.encoding, body.newline)
        if old == fresh:
            return {"changed": False, "sha256": sha, "size": len(old),
                    "encoding": body.encoding, "newline": _newlines(body.text)}
        tmp: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=file.parent, prefix=".automoto-edit-", delete=False) as stream:
                tmp = Path(stream.name)
                stream.write(fresh)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(tmp, stat.S_IMODE(info.st_mode))
            # Verify the same original inode and bytes immediately before replacing it.
            latest, current = _raw(file)
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino) or latest != old:
                raise HTTPException(409, "Source changed during save. No overwrite was performed.")
            os.replace(tmp, file)  # atomic within the source directory
            if os.name != "nt":
                try:
                    fd = os.open(file.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                except OSError:
                    pass  # replacement was atomic; not all filesystems support directory fsync
        except OSError:
            raise HTTPException(403, "File could not be saved safely.") from None
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
        return {"changed": True, "sha256": hashlib.sha256(fresh).hexdigest(), "size": len(fresh),
                "encoding": body.encoding, "newline": _newlines(body.text)}
