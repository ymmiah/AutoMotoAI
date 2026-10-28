"""Agent tools for archives (group ``archive``) and binary downloads."""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

from automoto import archives, netguard, sandbox
from automoto.tools import I, S, Tool, ToolContext, ToolFailed, _obj

B = {"type": "boolean"}
ARR = {"type": "array", "items": {"type": "string"}}


def _list(v: Any) -> list[str] | None:
    if v is None or v == "":
        return None
    if isinstance(v, str):
        v = v.strip()
        if v.startswith("["):
            try:
                return [str(x) for x in json.loads(v)]
            except json.JSONDecodeError:
                pass
        return [x.strip() for x in v.split(",") if x.strip()]
    return [str(x) for x in v]


def _wrap(fn):
    def inner(ctx: ToolContext, **kw: Any) -> str:
        try:
            return fn(ctx, **kw)
        except archives.ArchiveError as exc:
            raise ToolFailed(str(exc)) from None
    return inner


def _fmt(d: dict) -> str:
    return json.dumps(d, indent=1, ensure_ascii=False, default=str)


@_wrap
def archive_list(ctx: ToolContext, path: str, max_lines: int = 300) -> str:
    return archives.list_text(path, max(20, min(int(max_lines or 300), 2000)))


@_wrap
def archive_inspect(ctx: ToolContext, path: str) -> str:
    rep = archives.inspect(path)
    verdict = "SAFE to extract" if rep["safe"] else "UNSAFE - extraction will be refused"
    return f"{verdict}\n{_fmt(rep)}"


@_wrap
def archive_read(ctx: ToolContext, path: str, member: str, max_chars: int = 20000, password: str = "") -> str:
    cap = max(200, min(int(max_chars or 20000), 60000))
    data = archives.read_member(path, member, max_bytes=cap * 4, password=password or None)
    if b"\x00" in data[:4096]:
        return f"{member}: binary, {len(data)} bytes read (extract it to work on it)"
    text = data.decode("utf-8", errors="replace")
    return text[:cap] + (f"\n[… truncated at {cap} chars]" if len(text) > cap else "")


@_wrap
def archive_extract(ctx: ToolContext, path: str, dest: str, members: Any = None, skip_links: bool = False,
                    overwrite: bool = False, strip_top: bool = False, nested: bool = False, password: str = "") -> str:
    r = archives.extract(path, dest, password=password or None, members_only=_list(members),
                         skip_links=bool(skip_links), overwrite=bool(overwrite), strip_top=bool(strip_top),
                         nested=bool(nested))
    return f"extracted {r['files']} file(s) to {r['dest']}\n{_fmt(r)}\nEdit the files there, then archive_create to repack."


@_wrap
def archive_create(ctx: ToolContext, sources: Any, out: str, root_name: str | None = None, exclude: Any = None,
                   default_excludes: bool = True, deterministic: bool = True) -> str:
    srcs = _list(sources) or []
    if not srcs:
        raise ToolFailed("sources: give one or more files/folders")
    r = archives.create(srcs, out, root_name=root_name, exclude=_list(exclude),
                        use_default_excludes=default_excludes is not False, deterministic=deterministic is not False)
    return f"wrote {r['out']} ({r['files']} files, {r['bytes_out']:,} bytes)\n{_fmt(r)}"


@_wrap
def archive_repack(ctx: ToolContext, path: str, out: str, root_name: str | None = None, exclude: Any = None,
                   default_excludes: bool = True, deterministic: bool = True, password: str = "") -> str:
    r = archives.repack(path, out, root_name=root_name, exclude=_list(exclude),
                        use_default_excludes=default_excludes is not False, deterministic=deterministic is not False,
                        password=password or None)
    return f"repacked {r['source']} -> {r['out']} ({r['files']} files)\n{_fmt(r)}"


MAX_DOWNLOAD_MB = 100


def download_file(ctx: ToolContext, url: str, path: str = "", max_mb: int = 50) -> str:
    """Download a URL (through the SSRF guard) into a file in the workspace."""
    cap = max(1, min(int(max_mb or 50), MAX_DOWNLOAD_MB)) * 1024 * 1024
    name = path or (urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1] or "download.bin")
    try:
        out = sandbox.resolve(name if path else f"downloads/{name}", allow_outside=True)
    except sandbox.SandboxError as exc:
        raise ToolFailed(str(exc)) from None
    if out.is_dir():
        raise ToolFailed(f"{sandbox.rel(out)} is a folder - give a file path")
    r = None
    for attempt in range(3):  # a throttled CDN connection is retried on a fresh one
        try:
            r = netguard.request(url, timeout=60, total_timeout=600, min_rate=32 * 1024, max_bytes=cap + 1,
                                 headers={"Accept": "*/*"})
            break
        except netguard.SlowResponse as exc:
            if attempt == 2:
                raise ToolFailed(f"download failed after 3 tries: {exc}") from None
        except netguard.BlockedURL as exc:
            raise ToolFailed(f"blocked: {exc}") from None
        except OSError as exc:
            raise ToolFailed(f"download failed: {exc}") from None
    if r.status >= 400:
        raise ToolFailed(f"HTTP {r.status} for {r.url}")
    if len(r.body) > cap:
        raise ToolFailed(f"larger than {cap // 2**20} MB - pass max_mb (up to {MAX_DOWNLOAD_MB}) if that is expected")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.body)
    import hashlib

    note = ""
    if archives.is_archive_name(out.name):
        try:
            rep = archives.inspect(out)
            note = f"\narchive check: {'safe' if rep['safe'] else 'UNSAFE: ' + '; '.join(rep['problems'])} " \
                   f"({rep['files']} files, {rep['unpacked_bytes']:,} bytes unpacked)"
        except archives.ArchiveError as exc:
            note = f"\narchive check: {exc}"
    return (f"saved {sandbox.rel(out)} ({len(r.body):,} bytes, {r.content_type or 'unknown type'}) from {r.url}\n"
            f"sha256 {hashlib.sha256(r.body).hexdigest()}{note}")


_PW = {**S, "description": "only if the user gave you the password; never guess"}
_ROOT = {**S, "description": "top-level folder inside the archive: omit = keep/derive, '' = none, or a new name"}

TOOLS: list[Tool] = [
    Tool("archive_list", "List the contents of a .zip/.tar/.tar.gz/.tgz/.tar.bz2/.tar.xz/.gz/.7z/.rar archive as a tree "
         "(no extraction).", _obj({"path": S, "max_lines": I}, ["path"]), "safe", archive_list, "archive"),
    Tool("archive_inspect", "Safety report for an archive before extracting: zip-slip/absolute names, symlinks, zip bomb "
         "ratios and sizes, file count, nested archives, encryption, filename encoding.",
         _obj({"path": S}, ["path"]), "safe", archive_inspect, "archive"),
    Tool("archive_read", "Read one text member of an archive without extracting (e.g. readme.txt, the main .php file).",
         _obj({"path": S, "member": S, "max_chars": I, "password": _PW}, ["path", "member"]), "safe", archive_read, "archive"),
    Tool("archive_extract", "Extract an archive safely into a NEW folder in the workspace (unsafe names, links and bombs "
         "are refused; nothing is written unless everything is fine). strip_top=true drops a single top folder; "
         "members=[...] extracts only those paths; nested=true also unpacks archives inside (depth-limited).",
         _obj({"path": S, "dest": S, "members": ARR, "skip_links": B, "overwrite": B, "strip_top": B, "nested": B,
               "password": _PW}, ["path", "dest"]), "risky", archive_extract, "archive"),
    Tool("archive_create", "Pack files/folders into .zip/.tar/.tar.gz/.tgz/.tar.bz2/.tar.xz (or one file into .gz/.bz2/.xz). "
         "Excludes .git, node_modules, .DS_Store, __MACOSX, .env, __pycache__, editor folders by default; symlinks are "
         "skipped. deterministic=true (default) gives byte-identical output (sorted, fixed timestamps).",
         _obj({"sources": ARR, "out": S, "root_name": _ROOT, "exclude": {**ARR, "description": "glob patterns, e.g. ['tests', '*.map']"},
               "default_excludes": B, "deterministic": B}, ["sources", "out"]), "risky", archive_create, "archive"),
    Tool("archive_repack", "Clean and re-pack an archive in one step (extract safely to a temp folder, drop excluded/dev "
         "files, pack again - can also change format or rename the top folder).",
         _obj({"path": S, "out": S, "root_name": _ROOT, "exclude": ARR, "default_excludes": B, "deterministic": B,
               "password": _PW}, ["path", "out"]), "risky", archive_repack, "archive"),
    Tool("download_file", "Download a file (zip, csv, pdf, image…) from a public http(s) URL into the workspace "
         "(default downloads/<name>). Private/internal addresses are blocked. Archives are safety-checked.",
         _obj({"url": S, "path": S, "max_mb": I}, ["url"]), "risky", download_file, "archive"),
]
