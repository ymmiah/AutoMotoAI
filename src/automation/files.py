"""Filesystem operations with path-traversal protection."""
from __future__ import annotations

import logging
import os
import shutil
import string
import sys
from pathlib import Path

from src.core.exceptions import FileOperationError, PathSecurityError

logger = logging.getLogger(__name__)


def _resolve(path: str | Path) -> Path:
    """Resolve and return an absolute path; raises PathSecurityError for null bytes."""
    raw = str(path)
    if "\x00" in raw:
        raise PathSecurityError("Null byte detected in path")
    return Path(raw).expanduser().resolve()


def list_directory(path: str | Path) -> list[dict]:
    """Return directory contents as a list of entry dicts, sorted dirs-first."""
    p = _resolve(path)
    if not p.is_dir():
        raise FileOperationError(f"'{p}' is not a directory.")
    entries: list[dict] = []
    try:
        for entry in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            try:
                stat = entry.stat()
                entries.append({
                    "name": entry.name,
                    "path": str(entry),
                    "is_dir": entry.is_dir(),
                    "size": stat.st_size if entry.is_file() else 0,
                    "mtime": stat.st_mtime,
                    "ext": entry.suffix.lower(),
                })
            except PermissionError:
                entries.append({
                    "name": entry.name,
                    "path": str(entry),
                    "is_dir": False,
                    "size": 0,
                    "mtime": 0,
                    "ext": "",
                    "inaccessible": True,
                })
    except PermissionError as exc:
        raise FileOperationError(f"Cannot list '{p}': {exc}") from exc
    return entries


def create_file(path: str | Path, content: str = "") -> Path:
    p = _resolve(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        logger.info("Created file: %s", p)
        return p
    except OSError as exc:
        raise FileOperationError(f"Cannot create '{p}': {exc}") from exc


def create_directory(path: str | Path) -> Path:
    p = _resolve(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
        logger.info("Created directory: %s", p)
        return p
    except OSError as exc:
        raise FileOperationError(f"Cannot create directory '{p}': {exc}") from exc


def delete_path(path: str | Path) -> None:
    p = _resolve(path)
    try:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        logger.info("Deleted: %s", p)
    except OSError as exc:
        raise FileOperationError(f"Cannot delete '{p}': {exc}") from exc


def rename_path(src: str | Path, dst_name: str) -> Path:
    s = _resolve(src)
    d = _resolve(s.parent / dst_name)
    try:
        s.rename(d)
        logger.info("Renamed '%s' -> '%s'", s, d)
        return d
    except OSError as exc:
        raise FileOperationError(f"Cannot rename '{s}': {exc}") from exc


def get_drives() -> list[str]:
    """Return available drive roots: letters on Windows, '/' on Unix."""
    if sys.platform == "win32":
        return [
            f"{letter}:\\"
            for letter in string.ascii_uppercase
            if os.path.exists(f"{letter}:\\")
        ]
    return ["/"]


def get_home() -> Path:
    return Path.home()
