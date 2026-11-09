"""Developer Studio V4: bounded, authenticated, read-only project search.

Search never executes, mutates, indexes remotely or follows linked directories.
Replace preview is a proposed *working copy*, never a disk write; the V2
trusted save endpoint remains the sole way to commit any edit.
"""
from __future__ import annotations

import difflib
from itertools import islice
import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_editor as editor, developer_studio as studio

router = APIRouter(prefix="/api/developer/studio", tags=["developer-navigation"])
MAX_QUERY = 160
MAX_REPLACEMENT = 1024
MAX_HITS = 100
MAX_FILES = 300
MAX_SCAN_BYTES = 8 * 1024 * 1024
MAX_REPLACEMENTS = 200


class SearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    directory: str = Field(default=".", max_length=1024)
    query: str = Field(min_length=1, max_length=MAX_QUERY)
    case_sensitive: bool = False
    scope: Literal["content", "filename"] = "content"


class ReplacePreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    path: str = Field(min_length=1, max_length=1024)
    query: str = Field(min_length=1, max_length=MAX_QUERY)
    replacement: str = Field(max_length=MAX_REPLACEMENT)
    case_sensitive: bool = False
    expected_sha256: str = Field(min_length=64, max_length=64)
    encoding: editor.Enc


def _pattern(query: str, case_sensitive: bool) -> re.Pattern[str]:
    if not query or not query.strip() or "\x00" in query:
        raise HTTPException(422, "Enter a non-empty literal search term.")
    return re.compile(re.escape(query), 0 if case_sensitive else re.IGNORECASE)


def _walk(root: Path, folder: Path):
    """Breadth-first, bounded traversal of approved existing directories."""
    pending = [folder]
    dirs = 0
    while pending and dirs < MAX_FILES:
        current = pending.pop(0)
        dirs += 1
        try:
            with os.scandir(current) as iterator:
                entries = list(islice(iterator, MAX_FILES + 1))
                overflow = len(entries) > MAX_FILES
                entries = sorted(entries[:MAX_FILES], key=lambda p: p.name.casefold())
        except OSError:
            continue
        for entry in entries:
            if studio._forbidden(entry.name) or entry.is_symlink():
                continue
            candidate = Path(entry.path)
            if getattr(candidate, "is_junction", lambda: False)():
                continue
            try:
                rel = candidate.relative_to(root).as_posix()
                verified = studio._path(root, rel)
                if verified != candidate:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if len(pending) < MAX_FILES:
                        pending.append(candidate)
                    else:
                        yield None, None  # queue limit; the result is incomplete
                elif entry.is_file(follow_symlinks=False):
                    yield rel, candidate
            except (HTTPException, OSError, ValueError):
                continue
        if overflow:
            yield None, None  # bounded scan of a very large directory


@router.post("/search")
def search(request: Request, body: SearchIn):
    studio._auth(request)
    root = studio._project(body.project)
    folder = studio._path(root, body.directory)
    if not folder.is_dir():
        raise HTTPException(404, "Search folder does not exist.")
    pattern = _pattern(body.query, body.case_sensitive)
    hits, scanned, total_bytes, capped = [], 0, 0, False
    for rel, candidate in _walk(root, folder):
        if rel is None:
            capped = True
            continue
        if scanned >= MAX_FILES or len(hits) >= MAX_HITS or total_bytes >= MAX_SCAN_BYTES:
            capped = True
            break
        scanned += 1
        if body.scope == "filename":
            if pattern.search(candidate.name):
                hits.append({"path": rel, "line": 0, "column": 0,
                             "preview": candidate.name, "sha256": None})
            continue
        try:
            raw, _ = editor._raw(candidate)
            total_bytes += len(raw)
            # Auto-detect UTF-8 and BOM-backed UTF-16; ignore undecodable or binary.
            decoded, _ = editor._decode(raw, "auto")
        except (HTTPException, UnicodeError, OSError):
            continue
        digest = hashlib.sha256(raw).hexdigest()
        for line_no, line in enumerate(decoded.splitlines(), start=1):
            for match in pattern.finditer(line):
                hits.append({"path": rel, "line": line_no, "column": match.start() + 1,
                             "preview": line[max(0, match.start() - 50):match.end() + 90][:180],
                             "sha256": digest})
                if len(hits) >= MAX_HITS:
                    capped = True
                    break
            if len(hits) >= MAX_HITS:
                break
    return {"items": hits, "scanned_files": scanned, "scanned_bytes": total_bytes,
            "truncated": capped, "scope": body.scope, "local_only": True,
            "source_modified": False}


@router.post("/replace-preview")
def replace_preview(request: Request, body: ReplacePreviewIn):
    studio._auth(request)
    root = studio._project(body.project)
    with studio.STATE_LOCK:
        if not studio._trusted(root, studio._load()):
            raise HTTPException(403, "Trust this exact project before proposing source changes.")
    if not editor.SHA.fullmatch(body.expected_sha256):
        raise HTTPException(422, "Invalid checksum.")
    target = studio._path(root, body.path)
    if target == root or not target.is_file():
        raise HTTPException(404, "Existing regular source file required.")
    raw, _ = editor._raw(target)
    if hashlib.sha256(raw).hexdigest() != body.expected_sha256:
        raise HTTPException(409, "Source changed on disk. Reopen before replacing.")
    old, encoding = editor._decode(raw, "auto" if body.encoding != "cp1252" else "cp1252")
    if encoding != body.encoding:
        raise HTTPException(409, "Encoding changed. Reopen source.")
    needle = _pattern(body.query, body.case_sensitive)
    count = sum(1 for _ in needle.finditer(old))
    if count > MAX_REPLACEMENTS:
        raise HTTPException(413, "Replacement limit exceeded; narrow your search.")
    replacement, actual = needle.subn(lambda _: body.replacement, old)
    newline = editor._newlines(old)
    if newline == "mixed":
        raise HTTPException(422, "Choose a line-ending style in the editor before replacing.")
    editor._encode(replacement, body.encoding, newline)
    diff = list(difflib.unified_diff(old.splitlines(keepends=True), replacement.splitlines(keepends=True),
                                     fromfile="Saved file", tofile="Proposed changes", n=3))
    return {"path": body.path, "text": replacement, "count": actual,
            "diff": "".join(diff[:350]), "diff_truncated": len(diff) > 350,
            "base_sha256": body.expected_sha256, "encoding": encoding,
            "newline": newline, "source_modified": False, "requires_review": True}
