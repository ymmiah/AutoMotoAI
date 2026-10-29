"""Safe archive handling: list, inspect, extract, create and repack.

Formats: .zip, .tar, .tar.gz/.tgz, .tar.bz2/.tbz2, .tar.xz/.txz, single-file .gz/.bz2/.xz,
plus read/extract-only .7z (py7zr or the 7-Zip CLI) and .rar (unar/lsar or 7-Zip) when available.

Archives from other people are untrusted. By default:
- member names are normalised and anything absolute, with ``..``, drive letters, NUL/control
  characters or Windows device names is refused (zip-slip);
- symlinks, hardlinks, devices and FIFOs are refused (``skip_links`` skips them instead);
- zip bombs are caught: total uncompressed size, file count, per-member compression ratio and
  nested-archive depth are limited, and bytes are counted while streaming so lying headers
  do not help;
- encrypted members need a password the user gave; nothing is ever brute-forced;
- extraction only goes into the sandbox / allowed roots, via a temporary folder that is moved
  into place only when everything succeeded. File modes are reduced to 0644/0755.
"""

from __future__ import annotations

import bz2
import fnmatch
import gzip
import io
import lzma
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import unicodedata
import zipfile
from zlib import error as zlib_error
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Iterator

from automoto import sandbox


class ArchiveError(ValueError):
    pass


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, "") or default))
    except ValueError:
        return default


def limits() -> dict[str, int]:
    return {
        "max_archive_bytes": _env_int("AUTOMOTO_ARCHIVE_MAX_BYTES", 1024 * 1024 * 1024),  # input size
        "max_total_bytes": _env_int("AUTOMOTO_ARCHIVE_MAX_UNPACKED", 2 * 1024 * 1024 * 1024),
        "max_files": _env_int("AUTOMOTO_ARCHIVE_MAX_FILES", 50000),
        "max_ratio": _env_int("AUTOMOTO_ARCHIVE_MAX_RATIO", 200),
        "max_depth": _env_int("AUTOMOTO_ARCHIVE_MAX_DEPTH", 3),
    }


RATIO_MIN_BYTES = 4 * 1024 * 1024  # ratio is only judged for members that expand to more than this

DEFAULT_EXCLUDES = [".git", ".svn", ".hg", "node_modules", ".DS_Store", "__MACOSX", "._*", "Thumbs.db", "desktop.ini",
                    "__pycache__", "*.pyc", ".idea", ".vscode", ".env", ".env.*", "*.swp", "*~"]

ARCHIVE_EXTS = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tbz", ".tar.xz", ".txz", ".gz", ".bz2", ".xz",
                ".7z", ".rar", ".jar", ".whl", ".nupkg", ".vsix", ".epub")
_WIN_DEVICES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_DRIVE = re.compile(r"^[A-Za-z]:")


def is_archive_name(name: str) -> bool:
    n = name.lower()
    return any(n.endswith(e) for e in ARCHIVE_EXTS)


# -- member model ---------------------------------------------------------------------------
@dataclass
class Member:
    name: str              # normalised, posix, no leading slash
    size: int              # uncompressed bytes (as declared)
    csize: int             # compressed bytes (0 if unknown)
    kind: str = "file"     # file | dir | symlink | hardlink | device | other
    encrypted: bool = False
    mtime: float = 0.0
    mode: int = 0o644
    raw: object = None     # backend object (ZipInfo / TarInfo / name)
    problem: str = ""      # why it is unsafe ('' = fine)
    link: str = ""

    def as_dict(self) -> dict:
        d = {"name": self.name, "size": self.size, "kind": self.kind}
        if self.csize:
            d["compressed"] = self.csize
        if self.encrypted:
            d["encrypted"] = True
        if self.problem:
            d["problem"] = self.problem
        if self.link:
            d["link"] = self.link
        return d


def safe_name(raw: str) -> tuple[str, str]:
    """Return (normalised name, problem). ``problem`` is '' when the name is safe."""
    if "\x00" in raw:
        return raw.replace("\x00", "?"), "NUL byte in name"
    name = raw.replace("\\", "/")
    if any(ord(c) < 32 for c in name):
        return name, "control character in name"
    if name.startswith("/") or _DRIVE.match(name) or name.startswith("//"):
        return name, "absolute path"
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return name, "path traversal (..)"
    for p in parts:
        stem = p.split(".")[0].lower().rstrip(" ")
        if stem in _WIN_DEVICES:
            return name, f"Windows device name ({p})"
        if p.endswith((" ", ".")) and p not in (".", ".."):
            return name, f"name ends with a space or dot ({p})"
    norm = "/".join(unicodedata.normalize("NFC", p) for p in parts)
    if not norm:
        return name, "empty name"
    return norm, ""


def _fix_zip_name(info: zipfile.ZipInfo) -> tuple[str, bool]:
    """Zip names without the UTF-8 flag are decoded as cp437; many tools actually wrote UTF-8."""
    if info.flag_bits & 0x800:
        return info.filename, False
    try:
        raw = info.filename.encode("cp437")
    except UnicodeEncodeError:
        return info.filename, False
    if raw.isascii():
        return info.filename, False
    try:
        return raw.decode("utf-8"), True
    except UnicodeDecodeError:
        return info.filename, False


# -- format detection -------------------------------------------------------------------------
def detect(p: Path) -> str:
    """zip | tar | gz | bz2 | xz | 7z | rar (by magic bytes, then by name)."""
    with p.open("rb") as fh:
        head = fh.read(512)
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return "zip"
    if head[:6] == b"7z\xbc\xaf\x27\x1c":
        return "7z"
    if head[:7] == b"Rar!\x1a\x07\x00" or head[:8] == b"Rar!\x1a\x07\x01\x00":
        return "rar"
    if len(head) >= 262 and head[257:262] == b"ustar":
        return "tar"
    comp = {b"\x1f\x8b": "gz", b"BZ": "bz2", b"\xfd7": "xz"}.get(head[:2])
    if comp:
        opener = {"gz": gzip.open, "bz2": bz2.open, "xz": lzma.open}[comp]
        try:
            with opener(p, "rb") as fh:
                inner = fh.read(512)
            if len(inner) >= 262 and inner[257:262] == b"ustar":
                return "tar"
            if comp == "gz" and inner[:1] and tarfile.is_tarfile(p):  # old-style (v7) tar
                return "tar"
        except (OSError, EOFError, lzma.LZMAError):
            pass
        return comp
    n = p.name.lower()
    if n.endswith(".tar"):
        return "tar"
    if zipfile.is_zipfile(p):  # self-extracting / prefixed zips
        return "zip"
    raise ArchiveError(f"{p.name}: not a recognised archive (zip, tar, tar.gz, tar.bz2, tar.xz, gz, bz2, xz, 7z, rar)")


def _seven_cli() -> str | None:
    for b in ("7zz", "7z", "7za"):
        if shutil.which(b):
            return shutil.which(b)
    if os.name == "nt":  # the 7-Zip installer doesn't add itself to PATH
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), "C:/Program Files"):
            exe = os.path.join(base, "7-Zip", "7z.exe") if base else ""
            if exe and os.path.isfile(exe):
                return exe
    return None


def capabilities() -> dict[str, str]:
    """What this machine can do with each format."""
    try:
        import py7zr  # noqa: F401
        seven = "read/extract (py7zr)"
    except ImportError:
        seven = "read/extract (7-Zip CLI)" if _seven_cli() else "unavailable - pip install py7zr or install 7-Zip"
    rar = ("read/extract (unar)" if shutil.which("unar") and shutil.which("lsar")
           else "read/extract (7-Zip CLI)" if _seven_cli() else "unavailable - install unar or 7-Zip")
    rw = "read/extract/create"
    return {"zip": rw, "tar": rw, "tar.gz": rw, "tar.bz2": rw, "tar.xz": rw, "gz": rw, "bz2": rw, "xz": rw,
            "7z": seven, "rar": rar}


# -- listing ------------------------------------------------------------------------------------
def _resolve_in(path: str | os.PathLike) -> Path:
    p = sandbox.resolve(path, allow_outside=True)
    if not p.is_file():
        raise ArchiveError(f"no such file: {path}")
    if p.stat().st_size > limits()["max_archive_bytes"]:
        raise ArchiveError(f"{p.name} is larger than the {limits()['max_archive_bytes'] // 2**20} MB archive limit")
    return p


def _zip_members(zf: zipfile.ZipFile) -> tuple[list[Member], int]:
    out, fixed = [], 0
    for info in zf.infolist():
        fname, was_fixed = _fix_zip_name(info)
        fixed += was_fixed
        name, prob = safe_name(fname)
        mode = (info.external_attr >> 16) & 0xFFFF
        kind = "dir" if info.is_dir() else "file"
        if stat.S_ISLNK(mode):
            kind, prob = "symlink", prob or "symbolic link"
        elif mode and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)) and stat.S_IFMT(mode):
            kind, prob = "other", prob or "special file"
        m = Member(name, info.file_size, info.compress_size, kind, bool(info.flag_bits & 0x1),
                   time.mktime(info.date_time + (0, 0, -1)) if info.date_time[0] >= 1980 else 0.0,
                   0o755 if mode & 0o111 else 0o644, info, prob)
        if info.compress_type == 99:
            m.encrypted = True  # WinZip AES
        out.append(m)
    return out, fixed


def _tar_members(tf: tarfile.TarFile) -> list[Member]:
    return [_tar_members_one(ti) for ti in tf]


def _tar_members_one(ti: tarfile.TarInfo) -> Member:
    name, prob = safe_name(ti.name)
    if ti.isdir():
        kind = "dir"
    elif ti.isreg():
        kind = "file"
    elif ti.issym():
        kind, prob = "symlink", prob or "symbolic link"
    elif ti.islnk():
        kind, prob = "hardlink", prob or "hard link"
    elif ti.ischr() or ti.isblk():
        kind, prob = "device", prob or "device file"
    else:
        kind, prob = "other", prob or "FIFO/special file"
    return Member(name, ti.size if ti.isreg() else 0, 0, kind, False, float(ti.mtime),
                  0o755 if ti.mode & 0o111 else 0o644, ti, prob, ti.linkname if ti.issym() or ti.islnk() else "")


def _single_name(p: Path) -> str:
    n = p.name
    for ext in (".gz", ".bz2", ".xz", ".gzip"):
        if n.lower().endswith(ext):
            return n[: -len(ext)] or "data"
    return n + ".out"


def _parse_7z_slt(text: str) -> list[dict]:
    items, cur = [], {}
    for line in text.splitlines():
        if not line.strip():
            if "Path" in cur:
                items.append(cur)
            cur = {}
            continue
        if " = " in line:
            k, v = line.split(" = ", 1)
            cur[k.strip()] = v
    if "Path" in cur:
        items.append(cur)
    return items


def _external_members(p: Path, fmt: str) -> list[Member]:
    out = []
    if fmt == "7z":
        try:
            import py7zr

            with py7zr.SevenZipFile(p, "r") as z:
                for f in z.list():
                    name, prob = safe_name(f.filename)
                    kind = "dir" if f.is_directory else "symlink" if getattr(f, "is_symlink", False) else "file"
                    if kind == "symlink":
                        prob = prob or "symbolic link"
                    out.append(Member(name, int(f.uncompressed or 0), int(f.compressed or 0), kind,
                                      bool(z.needs_password()), 0.0, 0o644, f.filename, prob))
            return out
        except ImportError:
            pass
        except Exception as exc:  # py7zr raises many types for broken/encrypted archives
            if "password" in str(exc).lower():
                raise ArchiveError(f"{p.name} is encrypted - give the password to list it") from None
            raise ArchiveError(f"{p.name}: cannot read 7z archive ({exc})") from None
    if fmt == "rar" and shutil.which("lsar"):
        import json

        r = subprocess.run(["lsar", "-j", str(p)], capture_output=True, text=True, timeout=120, env=sandbox.clean_env())
        try:
            data = json.loads(r.stdout or "{}")
        except json.JSONDecodeError:
            raise ArchiveError(f"{p.name}: lsar could not read it: {r.stderr.strip()[:200]}") from None
        for e in data.get("lsarContents", []):
            name, prob = safe_name(e.get("XADFileName", ""))
            kind = "dir" if e.get("XADIsDirectory") else "symlink" if e.get("XADLinkDestination") else "file"
            if kind == "symlink":
                prob = prob or "symbolic link"
            out.append(Member(name, int(e.get("XADFileSize", 0) or 0), int(e.get("XADCompressedSize", 0) or 0), kind,
                              bool(e.get("XADIsEncrypted")), 0.0, 0o644, e.get("XADFileName", ""), prob))
        return out
    cli = _seven_cli()
    if not cli:
        raise ArchiveError(f"{fmt} support is not installed: {capabilities()[fmt]}")
    r = subprocess.run([cli, "l", "-slt", "-p", str(p)],
                       capture_output=True, text=True, timeout=120, env=sandbox.clean_env(), stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip()
        if "password" in msg.lower() or "encrypted" in msg.lower():
            raise ArchiveError(f"{p.name} is encrypted (headers too) - give the password to list it")
        raise ArchiveError(f"{p.name}: 7-Zip could not read it: {msg[-300:]}")
    body = r.stdout.split("----------", 1)[-1]
    for e in _parse_7z_slt(body):
        name, prob = safe_name(e.get("Path", ""))
        attrs = e.get("Attributes", "")
        kind = "dir" if e.get("Folder") == "+" or attrs.startswith("D") else "file"
        if e.get("Symbolic Link") or " -l" in attrs or attrs.endswith("lrwxrwxrwx"):
            kind, prob = "symlink", prob or "symbolic link"
        out.append(Member(name, int(e.get("Size") or 0), int(e.get("Packed Size") or 0), kind,
                          e.get("Encrypted") == "+", 0.0, 0o644, e.get("Path", ""), prob))
    return out


def members(path: str | os.PathLike) -> tuple[str, list[Member], dict]:
    """(format, members, notes) for an archive. Never extracts anything."""
    return members_path(_resolve_in(path))


def members_path(p: Path) -> tuple[str, list[Member], dict]:
    fmt = detect(p)
    notes: dict = {}
    if fmt == "zip":
        try:
            with zipfile.ZipFile(p) as zf:
                ms, fixed = _zip_members(zf)
                if fixed:
                    notes["names_redecoded_utf8"] = fixed
                if zf.comment:
                    notes["comment"] = zf.comment[:200].decode("utf-8", "replace")
        except zipfile.BadZipFile as exc:
            raise ArchiveError(f"{p.name}: damaged zip ({exc})") from None
    elif fmt == "tar":
        try:
            with tarfile.open(p, "r:*") as tf:
                ms = _tar_members(tf)
        except (tarfile.TarError, EOFError, OSError, lzma.LZMAError) as exc:
            raise ArchiveError(f"{p.name}: damaged tar ({exc})") from None
    elif fmt in ("gz", "bz2", "xz"):
        size = -1
        if fmt == "gz":
            with p.open("rb") as fh:  # ISIZE trailer (mod 2^32) - a hint only, streaming is counted anyway
                fh.seek(-4, 2)
                size = int.from_bytes(fh.read(4), "little")
        ms = [Member(_single_name(p), max(size, 0), p.stat().st_size, "file")]
        notes["single_file"] = True
        if size < 0:
            notes["size_unknown"] = True
    else:
        ms = _external_members(p, fmt)
    return fmt, ms, notes


# -- inspection / bomb checks --------------------------------------------------------------------
def _nested_scan(p: Path, depth: int, lim: dict, report: dict) -> None:
    """Look inside zip members that are themselves zips (in memory, capped) to catch nested bombs."""
    if depth > lim["max_depth"]:
        report["problems"].append(f"archives nested deeper than {lim['max_depth']} levels")
        return
    try:
        zf = zipfile.ZipFile(p) if isinstance(p, Path) else zipfile.ZipFile(p)
    except zipfile.BadZipFile:
        return
    with zf:
        for info in zf.infolist()[:2000]:
            if info.is_dir() or not is_archive_name(info.filename) or not info.filename.lower().endswith((".zip", ".jar")):
                continue
            report["nested"].append({"name": info.filename, "depth": depth})
            if info.file_size > 64 * 1024 * 1024 or info.flag_bits & 0x1:
                continue
            try:
                inner = io.BytesIO(_read_capped(zf.open(info), 64 * 1024 * 1024))
            except (ArchiveError, zipfile.BadZipFile, RuntimeError, OSError):
                continue
            try:
                with zipfile.ZipFile(inner) as iz:
                    total = sum(i.file_size for i in iz.infolist())
                    report["nested_unpacked"] += total
                    if total > lim["max_total_bytes"]:
                        report["problems"].append(f"nested archive {info.filename} unpacks to {total:,} bytes")
                        continue
            except zipfile.BadZipFile:
                continue
            inner.seek(0)
            _nested_scan(inner, depth + 1, lim, report)  # type: ignore[arg-type]


def _read_capped(fh, cap: int) -> bytes:
    buf = bytearray()
    with fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            buf += chunk
            if len(buf) > cap:
                raise ArchiveError("member larger than allowed")
    return bytes(buf)


def inspect(path: str | os.PathLike, *, nested: bool = True) -> dict:
    """Safety report: format, counts, sizes, ratio, unsafe names, links, encryption, nested archives."""
    return inspect_path(_resolve_in(path), nested=nested)


def inspect_path(p: Path, *, nested: bool = True) -> dict:
    if p.stat().st_size > limits()["max_archive_bytes"]:
        raise ArchiveError(f"{p.name} is larger than the archive size limit")
    fmt, ms, notes = members_path(p)
    lim = limits()
    files = [m for m in ms if m.kind == "file"]
    total = sum(m.size for m in files)
    report: dict = {"format": fmt, "entries": len(ms), "files": len(files), "dirs": sum(m.kind == "dir" for m in ms),
                    "unpacked_bytes": total, "archive_bytes": p.stat().st_size, "problems": [], "warnings": [],
                    "nested": [], "nested_unpacked": 0, **notes}
    if len(ms) > lim["max_files"]:
        report["problems"].append(f"{len(ms):,} entries (limit {lim['max_files']:,})")
    if total > lim["max_total_bytes"]:
        report["problems"].append(f"unpacks to {total:,} bytes (limit {lim['max_total_bytes']:,})")
    for m in files:
        if m.csize and m.size > RATIO_MIN_BYTES and m.size / max(m.csize, 1) > lim["max_ratio"]:
            report["problems"].append(f"{m.name}: compression ratio {m.size // max(m.csize, 1)}:1 looks like a zip bomb")
            break
    if fmt == "zip" and p.stat().st_size and total / p.stat().st_size > lim["max_ratio"] and total > 64 * RATIO_MIN_BYTES:
        report["problems"].append(f"overall compression ratio {total // p.stat().st_size}:1 looks like a zip bomb")
    unsafe = [m for m in ms if m.problem]
    if unsafe:
        report["unsafe_members"] = [m.as_dict() for m in unsafe[:20]]
        kinds = sorted({m.problem for m in unsafe})
        (report["warnings"] if all(m.kind in ("symlink", "hardlink") and m.problem in ("symbolic link", "hard link")
                                   for m in unsafe) else report["problems"]).append(
            f"{len(unsafe)} unsafe member(s): {', '.join(kinds)}")
    seen: dict[str, str] = {}
    for m in ms:
        low = m.name.lower()
        if low in seen and seen[low] != m.name:
            report["warnings"].append(f"names differ only by case ({seen[low]} / {m.name}) - clash on Windows/macOS")
            break
        seen[low] = m.name
    dup = len(ms) - len({m.name for m in ms})
    if dup:
        report["warnings"].append(f"{dup} duplicate member name(s) - later ones would overwrite earlier ones")
    enc = [m for m in ms if m.encrypted]
    if enc:
        report["encrypted"] = len(enc)
        report["warnings"].append(f"{len(enc)} encrypted member(s) - a password is needed to extract them")
    if fmt == "zip" and nested:
        _nested_scan(p, 1, lim, report)
        if report["nested_unpacked"] and total + report["nested_unpacked"] > lim["max_total_bytes"]:
            report["problems"].append("nested archives together unpack beyond the size limit")
    if not report["nested"]:
        report.pop("nested")
        report.pop("nested_unpacked")
    tops = sorted({m.name.split("/")[0] for m in ms if m.name})
    report["top_level"] = tops[:20] + ([f"… {len(tops) - 20} more"] if len(tops) > 20 else [])
    report["safe"] = not report["problems"]
    return report


def tree(ms: list[Member], max_lines: int = 400) -> str:
    lines = []
    for m in sorted(ms, key=lambda m: m.name)[:max_lines]:
        depth = m.name.count("/")
        label = m.name.rsplit("/", 1)[-1] + ("/" if m.kind == "dir" else "")
        extra = "" if m.kind == "dir" else f"  {m.size:,} B"
        if m.kind in ("symlink", "hardlink"):
            extra = f"  -> {m.link} [{m.kind}]"
        if m.encrypted:
            extra += " [encrypted]"
        if m.problem and m.kind not in ("symlink", "hardlink"):
            extra += f" [UNSAFE: {m.problem}]"
        lines.append("  " * depth + label + extra)
    if len(ms) > max_lines:
        lines.append(f"… {len(ms) - max_lines} more entries")
    return "\n".join(lines)


def list_text(path: str | os.PathLike, max_lines: int = 400) -> str:
    fmt, ms, notes = members(path)
    total = sum(m.size for m in ms if m.kind == "file")
    head = f"{fmt} archive: {len(ms)} entries, {total:,} bytes unpacked"
    if notes.get("names_redecoded_utf8"):
        head += f" ({notes['names_redecoded_utf8']} names re-decoded as UTF-8)"
    return head + "\n" + tree(ms, max_lines)


# -- extraction ---------------------------------------------------------------------------------
class _Budget:
    def __init__(self, lim: dict):
        self.left = lim["max_total_bytes"]
        self.files = lim["max_files"]

    def take(self, n: int) -> None:
        self.left -= n
        if self.left < 0:
            raise ArchiveError("stopped: data unpacked beyond the size limit (zip bomb or lying headers)")


def _copy_stream(src, dst_path: Path, budget: _Budget, declared: int | None) -> int:
    written = 0
    with src, dst_path.open("wb") as out:
        while True:
            chunk = src.read(64 * 1024)
            if not chunk:
                break
            written += len(chunk)
            budget.take(len(chunk))
            if declared is not None and written > declared + 1024:
                raise ArchiveError(f"{dst_path.name}: more data than the header declares - refusing")
            out.write(chunk)
    return written


def _target(base: Path, name: str) -> Path:
    t = (base / name)
    # resolve the parent only (the file does not exist yet); both must stay under base
    parent = t.parent.resolve()
    if not (parent == base or base in parent.parents):
        raise ArchiveError(f"{name}: would escape the destination")
    return parent / t.name


def resolve_dest(dest: str | os.PathLike) -> Path:
    d = sandbox.resolve(dest, allow_outside=True)
    if d.exists() and not d.is_dir():
        raise ArchiveError(f"{dest} exists and is not a folder")
    return d


def extract(path: str | os.PathLike, dest: str | os.PathLike, *, password: str | None = None,
            members_only: list[str] | None = None, skip_links: bool = False, overwrite: bool = False,
            strip_top: bool = False, nested: bool = False) -> dict:
    """Extract safely into ``dest`` (inside the sandbox/allowed roots). Returns a summary dict."""
    return _extract(_resolve_in(path), resolve_dest(dest), password=password, members_only=members_only,
                    skip_links=skip_links, overwrite=overwrite, strip_top=strip_top, nested=nested)


def _open_members(p: Path, fmt: str, password: str | None):
    """Yield (member, readable stream or None) in archive order, opening the archive once."""
    if fmt == "zip":
        with zipfile.ZipFile(p) as zf:
            ms, _ = _zip_members(zf)
            for m in ms:
                if m.kind != "file":
                    yield m, None
                    continue
                try:
                    src = zf.open(m.raw, pwd=password.encode() if password and m.encrypted else None)
                except RuntimeError as exc:
                    raise ArchiveError(f"{m.name}: wrong password or unsupported encryption ({exc})") from None
                except NotImplementedError:
                    raise ArchiveError(f"{m.name}: compression/encryption method not supported "
                                       "(AES-encrypted zips need 7-Zip)") from None
                yield m, src
    elif fmt == "tar":
        with tarfile.open(p, "r:*") as tf:
            for ti in tf:
                m = _tar_members_one(ti)
                yield m, (tf.extractfile(ti) if m.kind == "file" else None)
    else:
        opener = {"gz": gzip.open, "bz2": bz2.open, "xz": lzma.open}[fmt]
        yield Member(_single_name(p), 0, 0, "file"), opener(p, "rb")


def _extract(p: Path, d: Path, *, password: str | None = None, members_only: list[str] | None = None,
             skip_links: bool = False, overwrite: bool = False, strip_top: bool = False, nested: bool = False,
             _depth: int = 1, _budget: _Budget | None = None) -> dict:
    lim = limits()
    report = inspect_path(p, nested=_depth == 1)
    hard = list(report["problems"])
    fmt, ms, _ = members_path(p)
    links = [m for m in ms if m.kind in ("symlink", "hardlink")]
    if links and not skip_links:
        hard.append(f"{len(links)} link member(s) ({', '.join(m.name for m in links[:3])}) - "
                    "refused; pass skip_links=true to extract everything else")
    if hard:
        raise ArchiveError("refusing to extract " + p.name + ": " + "; ".join(hard))
    if any(m.encrypted for m in ms) and not password:
        raise ArchiveError(f"{p.name} is password-protected ({sum(m.encrypted for m in ms)} encrypted member(s)). "
                           "Ask the user for the password and pass it as password=...; it is never guessed.")
    if d.exists() and any(d.iterdir()) and not overwrite:
        raise ArchiveError(f"{sandbox.rel(d)} is not empty - choose a new folder or pass overwrite=true")
    wanted = {safe_name(x)[0].rstrip("/") for x in members_only} if members_only else None
    tops = {m.name.split("/")[0] for m in ms if m.name}
    strip = strip_top and len(tops) == 1 and any("/" in m.name for m in ms)
    budget = _budget or _Budget(lim)
    d.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".automoto-extract-", dir=d.parent))
    count = skipped = 0
    try:
        base = tmp.resolve()
        if fmt in ("7z", "rar"):
            count = _extract_external(p, fmt, base, password, budget)
        else:
            for m, src in _open_members(p, fmt, password):
                try:
                    if m.kind in ("symlink", "hardlink"):
                        skipped += 1
                        continue
                    if m.problem:
                        raise ArchiveError(f"{m.name}: {m.problem}")
                    if wanted is not None and not any(m.name == w or m.name.startswith(w + "/") for w in wanted):
                        continue
                    name = m.name.split("/", 1)[1] if strip and "/" in m.name else ("" if strip else m.name)
                    if not name:
                        continue
                    budget.files -= 1
                    if budget.files < 0:
                        raise ArchiveError("stopped: too many files")
                    tgt = _target(base, name)
                    if m.kind == "dir":
                        tgt.mkdir(parents=True, exist_ok=True)
                        continue
                    tgt.parent.mkdir(parents=True, exist_ok=True)
                    if tgt.exists():
                        tgt.unlink()  # duplicate member: the last one wins (inspect reports it)
                    try:
                        _copy_stream(src, tgt, budget, m.size if fmt in ("zip", "tar") else None)
                        src = None
                    except RuntimeError as exc:
                        raise ArchiveError(f"{m.name}: wrong password ({exc})") from None
                    except (zipfile.BadZipFile, EOFError, lzma.LZMAError, zlib_error) as exc:
                        raise ArchiveError(f"{m.name}: damaged data ({exc})") from None
                    except OSError as exc:
                        if isinstance(exc, gzip.BadGzipFile) or "compressed" in str(exc).lower():
                            raise ArchiveError(f"{p.name}: damaged {fmt} data ({exc})") from None
                        raise
                    os.chmod(tgt, (m.mode & 0o755) | 0o644)
                    if m.mtime > 0:
                        try:
                            os.utime(tgt, (m.mtime, m.mtime))
                        except OSError:
                            pass
                    count += 1
                finally:
                    if src is not None:
                        src.close()
        nested_done = []
        if nested:
            for inner in sorted(base.rglob("*")):
                if inner.is_file() and is_archive_name(inner.name) and not inner.name.lower().endswith(
                        (".whl", ".jar", ".vsix", ".epub", ".nupkg")):
                    if _depth >= lim["max_depth"]:
                        raise ArchiveError(f"archives nested deeper than {lim['max_depth']} levels - refusing")
                    out_dir = inner.with_name(inner.name + ".d")
                    r = _extract(inner, out_dir, skip_links=skip_links, nested=True, _depth=_depth + 1, _budget=budget)
                    nested_done.append({"archive": inner.relative_to(base).as_posix(), "files": r["files"]})
        if d.exists():
            shutil.copytree(base, d, dirs_exist_ok=True)
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            tmp.rename(d)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    res: dict = {"dest": sandbox.rel(d), "format": fmt, "files": count}
    if skipped:
        res["skipped_links"] = skipped
    if _budget is None:
        res["bytes"] = lim["max_total_bytes"] - budget.left
    if strip:
        res["stripped_top_folder"] = next(iter(tops))
    if nested_done:
        res["nested"] = nested_done
    return res


def _extract_external(p: Path, fmt: str, base: Path, password: str | None, budget: _Budget) -> int:
    """7z/rar via py7zr or a CLI into an empty temp dir, then verify the result before it is moved."""
    stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=base.parent))
    try:
        done = False
        if fmt == "7z":
            try:
                import py7zr

                with py7zr.SevenZipFile(p, "r", password=password or None) as z:
                    z.extractall(path=stage)  # nosec B202 - empty staging dir, verified (links, sizes) before moving
                done = True
            except ImportError:
                pass
            except Exception as exc:
                raise ArchiveError(f"{p.name}: 7z extract failed ({exc})") from None
        if not done:
            if fmt == "rar" and shutil.which("unar"):
                cmd = ["unar", "-q", "-no-directory", "-o", str(stage)] + (["-p", password] if password else []) + [str(p)]
            else:
                cli = _seven_cli()
                if not cli:
                    raise ArchiveError(f"{fmt} extraction is not installed")
                cmd = [cli, "x", "-y", "-snl-", f"-o{stage}", f"-p{password or ''}", str(p)]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=sandbox.clean_env(),
                               stdin=subprocess.DEVNULL)
            if r.returncode != 0:
                msg = (r.stderr or r.stdout).strip()[-300:]
                raise ArchiveError(f"{p.name}: extract failed: {'wrong or missing password' if 'password' in msg.lower() else msg}")
        n = 0
        for f in stage.rglob("*"):
            if f.is_symlink():
                raise ArchiveError(f"{f.relative_to(stage)}: symbolic link in archive - refused")
            if f.is_file():
                n += 1
                budget.take(f.stat().st_size)
                budget.files -= 1
                if budget.files < 0:
                    raise ArchiveError("stopped: too many files")
                os.chmod(f, 0o644 | (f.stat().st_mode & 0o111 and 0o111))
        shutil.copytree(stage, base, dirs_exist_ok=True)
        return n
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def read_member(path: str | os.PathLike, member: str, *, max_bytes: int = 200000, password: str | None = None) -> bytes:
    """Bytes of one member without extracting anything to disk."""
    p = _resolve_in(path)
    fmt, ms, _ = members_path(p)
    want = safe_name(member)[0]
    m = next((x for x in ms if x.name == want), None)
    if not m:
        close = [x.name for x in ms if want.split("/")[-1] in x.name][:5]
        raise ArchiveError(f"no member {member!r}" + (f" (did you mean {', '.join(close)}?)" if close else ""))
    if m.kind != "file":
        raise ArchiveError(f"{member} is a {m.kind}, not a file")
    if m.encrypted and not password:
        raise ArchiveError(f"{member} is encrypted - a password is needed")
    cap = max(1, int(max_bytes))
    if fmt == "zip":
        with zipfile.ZipFile(p) as zf:
            try:
                with zf.open(m.raw, pwd=password.encode() if password else None) as fh:
                    return fh.read(cap)
            except RuntimeError as exc:
                raise ArchiveError(f"{member}: {exc}") from None
    if fmt == "tar":
        with tarfile.open(p, "r:*") as tf:
            fh = tf.extractfile(m.raw.name)  # type: ignore[union-attr]
            return fh.read(cap) if fh else b""
    if fmt in ("gz", "bz2", "xz"):
        with {"gz": gzip.open, "bz2": bz2.open, "xz": lzma.open}[fmt](p, "rb") as fh:
            return fh.read(cap)
    with tempfile.TemporaryDirectory() as td:
        _extract_external(p, fmt, Path(td), password, _Budget(limits()))
        f = Path(td) / m.name
        if f.is_file():
            return f.read_bytes()[:cap]
    raise ArchiveError(f"could not read {member}")


# -- creation -----------------------------------------------------------------------------------
def _excluded(rel: str, patterns: list[str]) -> bool:
    parts = rel.split("/")
    for pat in patterns:
        pat = pat.strip().rstrip("/")
        if not pat:
            continue
        if "/" in pat:
            if fnmatch.fnmatch(rel, pat) or rel.startswith(pat + "/"):
                return True
        elif any(fnmatch.fnmatch(part, pat) for part in parts):
            return True
    return False


def out_format(out: Path) -> str:
    n = out.name.lower()
    for ext, fmt in ((".tar.gz", "tar.gz"), (".tgz", "tar.gz"), (".tar.bz2", "tar.bz2"), (".tbz2", "tar.bz2"),
                     (".tar.xz", "tar.xz"), (".txz", "tar.xz"), (".tar", "tar"), (".zip", "zip"), (".gz", "gz"),
                     (".bz2", "bz2"), (".xz", "xz")):
        if n.endswith(ext):
            return fmt
    if n.endswith((".7z", ".rar")):
        raise ArchiveError(f"creating {n.rsplit('.', 1)[-1]} is not supported - write .zip or .tar.gz instead")
    raise ArchiveError(f"{out.name}: output must end in .zip, .tar, .tar.gz/.tgz, .tar.bz2, .tar.xz, .gz, .bz2 or .xz")


def collect(src: Path, exclude: list[str] | None = None, use_defaults: bool = True) -> tuple[list[Path], list[str]]:
    """Files under ``src`` (sorted), skipping excluded, sensitive and symlinked paths."""
    pats = (DEFAULT_EXCLUDES if use_defaults else []) + list(exclude or [])
    files, skipped = [], []
    if src.is_file():
        return [src], []
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        dp = Path(dirpath)
        keep = []
        for dn in sorted(dirnames):
            full = dp / dn
            rel = full.relative_to(src).as_posix()
            if full.is_symlink():
                skipped.append(rel + "/ (symlink)")
            elif _excluded(rel, pats):
                skipped.append(rel + "/")
            else:
                keep.append(dn)
        dirnames[:] = keep
        for fn in sorted(filenames):
            full = dp / fn
            rel = full.relative_to(src).as_posix()
            if full.is_symlink():
                skipped.append(rel + " (symlink)")
            elif _excluded(rel, pats):
                skipped.append(rel)
            elif sandbox.sensitive(full.resolve()):
                skipped.append(rel + " (sensitive)")
            elif full.is_file():
                files.append(full)
    return sorted(files, key=lambda f: f.relative_to(src).as_posix()), skipped


FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def create(sources: list[str | os.PathLike] | str, out: str | os.PathLike, *, root_name: str | None = None,
           exclude: list[str] | None = None, use_default_excludes: bool = True, deterministic: bool = True,
           overwrite: bool = True, level: int = 9) -> dict:
    """Pack files/folders into ``out``. ``root_name`` = top-level folder inside the archive
    (default: the source folder's name for one folder, none for files; '' = no top folder)."""
    if isinstance(sources, (str, os.PathLike)):
        sources = [sources]
    srcs = [sandbox.resolve(s, allow_outside=True) for s in sources]
    for s in srcs:
        if not s.exists():
            raise ArchiveError(f"no such file or folder: {sandbox.rel(s)}")
    return _create(srcs, sandbox.resolve(out, allow_outside=True), root_name=root_name, exclude=exclude,
                   use_default_excludes=use_default_excludes, deterministic=deterministic, overwrite=overwrite,
                   level=level)


def _create(srcs: list[Path], o: Path, *, root_name: str | None = None, exclude: list[str] | None = None,
            use_default_excludes: bool = True, deterministic: bool = True, overwrite: bool = True,
            level: int = 9) -> dict:
    fmt = out_format(o)
    if o.exists() and not overwrite:
        raise ArchiveError(f"{sandbox.rel(o)} exists")
    entries: list[tuple[Path, str]] = []
    skipped: list[str] = []
    for s in srcs:
        files, sk = collect(s, exclude, use_default_excludes)
        skipped += sk
        if s.is_dir():
            top = (s.name if root_name is None else root_name) if len(srcs) == 1 else s.name
            for f in files:
                rel = f.relative_to(s).as_posix()
                entries.append((f, f"{top}/{rel}" if top else rel))
        else:
            entries.append((s, (f"{root_name}/{s.name}" if root_name else s.name)))
    entries = [(f, a) for f, a in entries if f.resolve() != o.resolve()]
    if fmt in ("gz", "bz2", "xz"):
        if len(entries) != 1:
            raise ArchiveError(f".{fmt} holds one file - use .tar.{fmt} for folders")
    names = [a for _, a in entries]
    if len(set(names)) != len(names):
        raise ArchiveError("two inputs map to the same name inside the archive")
    for a in names:
        if safe_name(a)[1]:
            raise ArchiveError(f"{a}: {safe_name(a)[1]}")
    if deterministic:
        entries.sort(key=lambda e: e[1])
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "315532800") or 315532800)  # 1980-01-01
    o.parent.mkdir(parents=True, exist_ok=True)
    tmp = o.with_name(o.name + ".part")
    total = 0
    try:
        if fmt == "zip":
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=max(0, min(int(level), 9))) as zf:
                dirs_done: set[str] = set()
                for f, arc in entries:
                    # explicit directory entries help some installers (WordPress, older unzip tools)
                    parts = arc.split("/")[:-1]
                    for i in range(1, len(parts) + 1):
                        dn = "/".join(parts[:i]) + "/"
                        if dn not in dirs_done:
                            dirs_done.add(dn)
                            zi = zipfile.ZipInfo(dn, FIXED_TIME if deterministic else time.localtime()[:6])
                            zi.external_attr = (0o40755 << 16) | 0x10
                            zi.create_system = 3
                            zf.writestr(zi, b"")
                    mt = FIXED_TIME if deterministic else time.localtime(f.stat().st_mtime)[:6]
                    if mt[0] < 1980:
                        mt = FIXED_TIME
                    zi = zipfile.ZipInfo(arc, mt)
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    zi.create_system = 3
                    mode = 0o755 if f.stat().st_mode & 0o111 else 0o644
                    zi.external_attr = (stat.S_IFREG | mode) << 16
                    with f.open("rb") as src, zf.open(zi, "w") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
                    total += f.stat().st_size
        elif fmt.startswith("tar"):
            comp = {"tar": "", "tar.gz": "gz", "tar.bz2": "bz2", "tar.xz": "xz"}[fmt]
            raw = tmp.open("wb")
            try:
                gzf = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0 if deterministic else None,
                                    compresslevel=max(1, min(int(level), 9))) if comp == "gz" else None
                mode = "w" if comp in ("", "gz") else f"w:{comp}"
                tf = tarfile.open(fileobj=gzf or raw, mode=mode, format=tarfile.PAX_FORMAT) \
                    if comp in ("", "gz") else tarfile.open(tmp, mode, format=tarfile.PAX_FORMAT)
                with tf:
                    dirs_done = set()
                    for f, arc in entries:
                        parts = arc.split("/")[:-1]
                        for i in range(1, len(parts) + 1):
                            dn = "/".join(parts[:i])
                            if dn not in dirs_done:
                                dirs_done.add(dn)
                                ti = tarfile.TarInfo(dn)
                                ti.type, ti.mode = tarfile.DIRTYPE, 0o755
                                ti.mtime = epoch if deterministic else int(time.time())
                                tf.addfile(ti)
                        ti = tarfile.TarInfo(arc)
                        st = f.stat()
                        ti.size = st.st_size
                        ti.mode = 0o755 if st.st_mode & 0o111 else 0o644
                        ti.mtime = epoch if deterministic else int(st.st_mtime)
                        ti.uid = ti.gid = 0
                        ti.uname = ti.gname = ""
                        with f.open("rb") as src:
                            tf.addfile(ti, src)
                        total += st.st_size
                if gzf:
                    gzf.close()
            finally:
                raw.close()
        else:
            f = entries[0][0]
            if fmt == "gz":
                with f.open("rb") as src, tmp.open("wb") as raw, \
                        gzip.GzipFile(filename="" if deterministic else f.name, mode="wb", fileobj=raw,
                                      mtime=0 if deterministic else None) as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
            else:
                opener = bz2.open if fmt == "bz2" else lzma.open
                with f.open("rb") as src, opener(tmp, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
            total = f.stat().st_size
        os.replace(tmp, o)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    import hashlib

    h = hashlib.sha256()
    with o.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return {"out": sandbox.rel(o), "format": fmt, "files": len(entries), "bytes_in": total,
            "bytes_out": o.stat().st_size, "sha256": h.hexdigest(), "skipped": skipped[:50],
            "skipped_count": len(skipped), "top_level": sorted({a.split("/")[0] for a in names})[:10],
            "deterministic": deterministic}


def repack(path: str | os.PathLike, out: str | os.PathLike, *, root_name: str | None = None,
           exclude: list[str] | None = None, use_default_excludes: bool = True, deterministic: bool = True,
           password: str | None = None, skip_links: bool = False) -> dict:
    """Extract safely to a temp folder, clean it (excludes) and pack again (any supported output format).

    ``root_name`` None keeps the archive's own single top folder (if it has one); '' removes it;
    a string sets/renames it."""
    p = _resolve_in(path)
    o = sandbox.resolve(out, allow_outside=True)
    out_format(o)
    work = Path(tempfile.mkdtemp(prefix="automoto-repack-"))
    try:
        x = work / "x"
        _extract(p, x, password=password, skip_links=skip_links)
        kids = [k for k in x.iterdir() if k.name != "__MACOSX"]
        if len(kids) == 1 and kids[0].is_dir():
            src, top = kids[0], (kids[0].name if root_name is None else root_name)
        else:
            src, top = x, (root_name or "")
        res = _create([src], o, root_name=top, exclude=exclude, use_default_excludes=use_default_excludes,
                      deterministic=deterministic)
        if not res["files"]:
            o.unlink(missing_ok=True)
            raise ArchiveError("nothing left to pack after exclusions")
        res["source"] = sandbox.rel(p)
        return res
    finally:
        shutil.rmtree(work, ignore_errors=True)
