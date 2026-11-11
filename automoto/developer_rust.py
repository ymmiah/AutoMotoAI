"""V19 Rust Engineering: bounded Cargo workspace inspection and explicit local tools.

Read-only inspection never invokes Cargo, rustc, rust-analyzer or a debugger.
All compiler/test commands require trusted local roots, SHA-pinned binaries and
manifests, explicit risk consent and an isolated temporary Cargo build output.
Rust programs/build scripts are NOT OS/network sandboxed.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Literal, Mapping, Optional

try:
    import tomllib
except ModuleNotFoundError:  # Supported AutoMoto Python 3.10
    import tomli as tomllib

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_adapters as adapters
from automoto import developer_index as index
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/rust", tags=["developer-rust"])
SCHEMA = "1.0.0"
MANIFEST_LIMIT = 512 * 1024
MAX_MEMBERS = 20
MAX_SOURCES = 100
MAX_OUTPUT = 96 * 1024
MAX_SECONDS = 110
LOCK = threading.Lock()
TOOL_NAMES = ("cargo", "rustc", "rust-analyzer")
DEBUG_NAMES = ("lldb-dap", "codelldb")
SYMBOL = re.compile(r"(?m)^\s*(?:pub(?:\([^)]{0,60}\))?\s+)?"
                    r"(?:async\s+|unsafe\s+|const\s+)*"
                    r"(fn|struct|enum|trait|mod|type|impl)\s+([A-Za-z_]\w{0,90})")
DIAGNOSTIC = re.compile(r"^(.{1,300}\.rs):(\d{1,8}):(\d{1,7}):\s*"
                        r"(error|warning)(?:\[([A-Z]\d{4})\])?:\s*(.{1,500})$")
PATH_TOKEN = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_./-]{0,180}$")
# Tasks that invoke the native linker (or a build script that does).
_LINKER_TASKS = frozenset({"check", "build", "test", "clippy"})
# Names rustc and the cc crate read while locating vswhere and the MSVC tools.
# Values are installation paths or short toolchain tokens, never secrets.
_WINDOWS_DIR_VARS = (
    "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "SystemRoot",
    "VSINSTALLDIR", "VCINSTALLDIR", "VCToolsInstallDir", "VCToolsRedistDir",
    "WindowsSdkDir", "WindowsSdkBinPath", "WindowsSdkVerBinPath",
    "UniversalCRTSdkDir",
)
_WINDOWS_TOKEN_VARS = {
    "SystemDrive": re.compile(r"^[A-Za-z]:$"),
    "PROCESSOR_ARCHITECTURE": re.compile(r"^(?:x86|AMD64|ARM64|IA64)$", re.I),
    "PROCESSOR_ARCHITEW6432": re.compile(r"^(?:x86|AMD64|ARM64)$", re.I),
    "PATHEXT": re.compile(r"^(?:\.[A-Za-z0-9]{1,8};?){1,20}$"),
    "VCToolsVersion": re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}$"),
    "WindowsSDKVersion": re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}\\?$"),
    "WindowsSDKLibVersion": re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}\\?$"),
    "UCRTVersion": re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}\\?$"),
    "VisualStudioVersion": re.compile(r"^[0-9]{2}\.[0-9]$"),
    "VSCMD_ARG_HOST_ARCH": re.compile(r"^(?:x86|x64|arm|arm64)$", re.I),
    "VSCMD_ARG_TGT_ARCH": re.compile(r"^(?:x86|x64|arm|arm64)$", re.I),
    "VSCMD_ARG_VCVARS_SPECTRE": re.compile(r"^spectre$"),
    "VSCMD_VER": re.compile(r"^[0-9]+(?:\.[0-9]+){1,4}$"),
}
_WINDOWS_PATH_LIST_VARS = ("LIB", "LIBPATH", "INCLUDE", "EXTERNAL_INCLUDE")
_VS_YEARS = ("2026", "18", "2022", "2019", "2017")
_VS_EDITIONS = ("Enterprise", "Professional", "Community", "BuildTools", "Preview")
_MSVC_MISSING = (
    "This Windows Rust build needs Microsoft's linker (link.exe from the "
    "Visual Studio C++ build tools). AutoMoto did not find that linker. "
    "Install Visual Studio Build Tools with the Desktop development with C++ "
    "workload, then try again."
)
_GNU_LINK_DIAGNOSTIC = (
    "This Windows Rust build needs Microsoft's linker (link.exe from the "
    "Visual Studio C++ build tools). AutoMoto found a different program named "
    "link from Unix tools, often Git for Windows. That program cannot link "
    "Rust code. Install Visual Studio Build Tools with the Desktop development "
    "with C++ workload, then try again."
)


class WorkspaceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)


class RunIn(WorkspaceIn):
    task: Literal["cargo_version", "rustc_version", "analyzer_version",
                  "check", "build", "test", "clippy", "fmt_check"]
    tool: Literal["cargo", "rustc", "rust-analyzer"]
    expected_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_execution_and_write_risk: Literal[True]


def _read(root: Path, relative: str, size: int = MANIFEST_LIMIT) -> tuple[str, str]:
    """Read a bounded regular UTF-8 file, never following a linked path."""
    file = studio._path(root, relative)
    if file == root or any(index._excluded(part, i < len(relative.split("/")) - 1)
                           for i, part in enumerate(relative.split("/"))):
        raise HTTPException(403, "Cargo manifest path is restricted.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(file, flags)
        with os.fdopen(fd, "rb") as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > size:
                raise HTTPException(413, "Cargo manifest exceeds safe inspection bounds.")
            raw = source.read(size + 1)
        if len(raw) > size or b"\0" in raw:
            raise HTTPException(413, "Cargo manifest is too large or binary.")
        return raw.decode("utf-8-sig"), hashlib.sha256(raw).hexdigest()
    except (OSError, UnicodeError) as exc:
        raise HTTPException(403, "Cargo file cannot be safely read.") from exc


def _toml(root: Path, name: str) -> tuple[dict, str]:
    raw, sha = _read(root, name)
    try:
        data = tomllib.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise HTTPException(422, "Cargo manifest TOML is malformed or ambiguous.") from exc
    if not isinstance(data, dict):
        raise HTTPException(422, "Expected Cargo TOML object.")
    return data, sha


def _member_path(value: object) -> str:
    if not isinstance(value, str) or not PATH_TOKEN.fullmatch(value):
        raise HTTPException(422, "Cargo workspace members must be explicit local directories.")
    relative = value[2:] if value.startswith("./") else value
    if relative in (".", ""):
        return "."
    parts = relative.split("/")
    if any(part in ("", ".", "..") or part.startswith(".") for part in parts):
        raise HTTPException(422, "Cargo workspace member is not a safe in-root directory.")
    return relative


def _manifest(root: Path) -> tuple[dict, str]:
    root_file = root / "Cargo.toml"
    if root_file.is_symlink() or getattr(root_file, "is_junction", lambda: False)():
        raise HTTPException(403, "Linked root Cargo.toml is forbidden.")
    if not root_file.is_file():
        raise HTTPException(422, "Choose a local project containing Cargo.toml.")
    main, sha = _toml(root, "Cargo.toml")
    members = []
    workspace = main.get("workspace")
    if workspace is not None:
        if not isinstance(workspace, dict):
            raise HTTPException(422, "Cargo workspace must be a TOML table.")
        selected = workspace.get("members", [])
        if not isinstance(selected, list) or len(selected) > MAX_MEMBERS:
            raise HTTPException(422, "Cargo workspace members exceed the supported limit.")
        members = [_member_path(item) for item in selected]
        if len(set(members)) != len(members):
            raise HTTPException(422, "Duplicate workspace members are unsupported.")
    if main.get("package") is not None and "." not in members:
        members.insert(0, ".")
    if not members:
        raise HTTPException(422, "No supported explicit Cargo workspace members found.")
    manifests = {}
    crates = []
    parsed_manifests = []
    warnings = []
    for member in members:
        file = "Cargo.toml" if member == "." else member + "/Cargo.toml"
        if member != ".":
            # Refuse linked ancestors before reading manifests.
            studio._path(root, member)
        manifest, digest = (main, sha) if member == "." else _toml(root, file)
        parsed_manifests.append((member, manifest))
        meta = manifest.get("package")
        if not isinstance(meta, dict):
            raise HTTPException(422, "Workspace member lacks a Cargo package table.")
        name, version = meta.get("name"), meta.get("version")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", name):
            raise HTTPException(422, "Invalid or missing Cargo package name.")
        if not isinstance(version, str) or len(version) > 80:
            raise HTTPException(422, "Invalid or missing Cargo package version.")
        script = root / member / "build.rs"
        if meta.get("build") not in (None, False) or script.exists() or script.is_symlink():
            warnings.append("Build script in " + member + " requires independent review.")
        for kind in ("lib", "bin", "example", "test", "bench"):
            block = manifest.get(kind)
            targets = block if isinstance(block, list) else [block] if isinstance(block, dict) else []
            for item in targets:
                if not isinstance(item, dict):
                    continue
                custom = item.get("path")
                if custom is not None:
                    # Any custom target path may bypass the bounded source
                    # inventory, including paths with no literal "..".
                    warnings.append("Custom Cargo target path in " + member +
                                    " requires review before execution.")
        if manifest.get("patch") or manifest.get("replace"):
            warnings.append("Cargo patch/replace directives in " + member + " require review.")
        manifests[file] = {"sha256": digest, "name": name, "version": version}
        crates.append({"path": member, "name": name, "version": version,
                       "edition": str(meta.get("edition", "2015"))[:20],
                       "manifest": file,
                       "has_tests": (root / member / "tests").is_dir()})
    config = root / ".cargo" / "config.toml"
    if config.exists() or config.is_symlink():
        warnings.append("Project-local Cargo config requires manual review.")
    for toolchain_name in ("rust-toolchain.toml", "rust-toolchain"):
        toolchain = root / toolchain_name
        if toolchain.exists() or toolchain.is_symlink():
            warnings.append("Project toolchain override requires manual review.")
    lock = root / "Cargo.lock"
    if lock.is_symlink() or getattr(lock, "is_junction", lambda: False)():
        raise HTTPException(403, "Linked Cargo.lock is forbidden.")
    if lock.exists():
        _, digest = _read(root, "Cargo.lock")
        manifests["Cargo.lock"] = {"sha256": digest}
    else:
        warnings.append("Cargo.lock missing; frozen builds cannot be verified.")
    # Cargo may compile dependencies declared through a local path, not just
    # listed workspace crates. Require every such path to resolve to one
    # of the inspected and approved in-root crates.
    approved = {(root if member == "." else root / member).resolve()
                for member in members}
    for member, manifest in parsed_manifests:
        dependency_maps = [(member, manifest.get(kind)) for kind in
                           ("dependencies", "dev-dependencies", "build-dependencies")]
        target_tables = manifest.get("target", {})
        if isinstance(target_tables, dict):
            for table in list(target_tables.values())[:50]:
                if isinstance(table, dict):
                    dependency_maps.extend((member, table.get(kind)) for kind in
                                           ("dependencies", "dev-dependencies", "build-dependencies"))
        workspace_table = manifest.get("workspace", {})
        if isinstance(workspace_table, dict):
            dependency_maps.append((".", workspace_table.get("dependencies")))
        for base, deps in dependency_maps:
            if deps is None:
                continue
            if not isinstance(deps, dict):
                warnings.append("Cargo dependencies must be a table in " + member + ".")
                continue
            for dep, spec in list(deps.items())[:200]:
                if not isinstance(spec, dict) or "path" not in spec:
                    continue
                path = spec["path"]
                if (not isinstance(path, str) or not re.fullmatch(r"[A-Za-z0-9_./-]{1,180}", path)
                        or path.startswith(("/", "\\", "-"))
                        or "\\" in path):
                    warnings.append("Unsafe local Cargo dependency path in " + member + ".")
                    continue
                try:
                    resolved = (root / base / path).resolve(strict=True)
                    if resolved not in approved or not resolved.is_dir():
                        warnings.append("Cargo dependency path outside approved crates: " +
                                        str(dep)[:70])
                except (OSError, ValueError):
                    warnings.append("Missing or unsafe Cargo dependency path in " + member + ".")
    # The Cargo CLI could expand additional workspace globs if present; only
    # explicit members and exact crate manifests are admitted here.
    if workspace and (workspace.get("exclude") or workspace.get("default-members")):
        warnings.append("Workspace excludes/default-members need manual review.")
    if len(crates) != len(members):
        warnings.append("Incomplete Cargo workspace.")
    digest = hashlib.sha256(b"automoto-rust-v19-manifests\0")
    for path, data in sorted(manifests.items()):
        digest.update(path.encode() + b"\0" + data["sha256"].encode("ascii"))
    return {"crates": crates, "workspace": workspace is not None,
            "manifests": manifests, "warnings": warnings,
            "safe_to_offer_runs": not warnings}, digest.hexdigest()


def _source_inventory(root: Path) -> tuple[dict, str]:
    items, symbols = [], []
    truncated = False
    digest = hashlib.sha256(b"automoto-rust-v19-sources\0")
    for relative, warning in index._walk(root):
        if warning:
            truncated = True
            continue
        if not relative.endswith(".rs"):
            continue
        if len(items) >= MAX_SOURCES:
            truncated = True
            continue
        record = index._source(root, relative)
        if not record:
            truncated = True
            continue
        raw, sha, _ = record
        entries = [{"kind": kind, "name": name} for kind, name
                   in SYMBOL.findall(raw[:30000])[:18]]
        items.append({"path": relative, "sha256": sha,
                      "test": relative.endswith("_test.rs") or
                              "/tests/" in "/" + relative,
                      "symbols": entries})
        digest.update(relative.encode() + b"\0" + sha.encode("ascii"))
        if len(symbols) < 80:
            symbols.extend({"path": relative, **item} for item in entries[:10])
    return {"files": items, "symbols": symbols[:80], "incomplete": truncated}, digest.hexdigest()


def _tools(root: Path) -> tuple[list[dict], list[dict]]:
    values = []
    debug = []
    for name in (*TOOL_NAMES, *DEBUG_NAMES):
        resolved = shutil.which(name)
        if not resolved:
            item = {"name": name, "status": "unavailable"}
        elif Path(resolved).suffix.lower() in (".bat", ".cmd", ".ps1"):
            item = {"name": name, "status": "shell_wrapper_blocked"}
        else:
            try:
                checked = adapters._fingerprint(str(Path(resolved).absolute()), root)
                rustup_shim = (Path(resolved).name.lower() in
                               ("cargo", "cargo.exe", "rustc", "rustc.exe",
                                "rust-analyzer", "rust-analyzer.exe")
                               and Path(checked["executable"]).name.lower()
                               in ("rustup", "rustup.exe"))
                item = {"name": name, "status": "installed_not_executed",
                        **checked, "rustup_shim": rustup_shim}
            except HTTPException:
                item = {"name": name, "status": "not_approved"}
        (debug if name in DEBUG_NAMES else values).append(item)
    return values, debug


def _inspect(root: Path) -> dict:
    cargo, manifest_sha = _manifest(root)
    sources, source_sha = _source_inventory(root)
    if sources["incomplete"] or not sources["files"]:
        cargo["warnings"].append("Rust source scan is incomplete or empty.")
        cargo["safe_to_offer_runs"] = False
    tools, debug = _tools(root)
    return {"schema": SCHEMA, **cargo,
            "manifest_sha256": manifest_sha,
            "source_sha256": source_sha,
            "files": sources["files"], "symbols": sources["symbols"],
            "scan_incomplete": sources["incomplete"],
            "toolchains": tools, "debug_adapters": debug,
            "rust_analyzer_lsp": "Existing V6 consent-bound Rust LSP; not started by inspection.",
            "debugger": "Existing V8 approved DAP workflow; V19 never launches or attaches a debugger.",
            "project_trusted": studio._trusted(root, studio._load()),
            "tool_executed": False, "download_requested": False,
            "deployment_started": False,
            "central_agent_studio": "developer",
            "agent_deployment_handoff_required": True}


def _command(body: RunIn, exe: str, summary: dict) -> list[str]:
    version_tasks = {"cargo_version": "cargo", "rustc_version": "rustc",
                     "analyzer_version": "rust-analyzer"}
    if body.task in version_tasks:
        if body.tool != version_tasks[body.task]:
            raise HTTPException(422, "Version check requires its matching tool.")
        return [exe, "--version"]
    if body.tool != "cargo" or not summary["safe_to_offer_runs"]:
        raise HTTPException(409, "Workspace or tool requires manual review before execution.")
    if body.task == "check":
        return [exe, "check", "--workspace", "--all-targets", "--frozen",
                "--message-format=short"]
    if body.task == "build":
        return [exe, "build", "--workspace", "--frozen"]
    if body.task == "test":
        return [exe, "test", "--workspace", "--frozen"]
    if body.task == "clippy":
        return [exe, "clippy", "--workspace", "--all-targets", "--frozen", "--", "-D", "warnings"]
    if body.task == "fmt_check":
        return [exe, "fmt", "--all", "--", "--check"]
    raise HTTPException(422, "Unsupported fixed Rust task.")


def _env_lookup(source: Mapping[str, str], name: str) -> Optional[str]:
    """Windows environment names are case-insensitive. Tests pass a plain dict."""
    if name in source:
        return source[name]
    folded = name.casefold()
    for key, value in source.items():
        if key.casefold() == folded and isinstance(value, str):
            return value
    return None


def _env_has(env: Mapping[str, str], name: str) -> bool:
    folded = name.casefold()
    return any(key.casefold() == folded for key in env)


def _version_key(name: str) -> tuple:
    parts = []
    for piece in name.split("."):
        if not piece.isdigit():
            return ()
        parts.append(int(piece))
    return tuple(parts)


def _approved_directory(value: Optional[str], root: Path) -> Optional[Path]:
    """Absolute existing directory outside the project and other approved roots."""
    if not value or len(value) > 300 or "\x00" in value or "\n" in value:
        return None
    folder = Path(value)
    if not folder.is_absolute():
        return None
    try:
        resolved = folder.resolve(strict=True)
    except (OSError, ValueError):
        return None
    if not resolved.is_dir() or adapters._disallowed_workspace_executable(resolved, root):
        return None
    return resolved


def _approved_directories(value: Optional[str], root: Path, limit: int = 30) -> list:
    if not value:
        return []
    approved = []
    for item in value.split(os.pathsep)[:limit]:
        folder = _approved_directory(item, root)
        if folder is not None and folder not in approved:
            approved.append(folder)
    return approved


def _link_executable(directory: Path) -> Optional[Path]:
    direct = directory / "link.exe"
    if direct.is_file():
        return direct
    try:
        for child in directory.iterdir():
            if child.is_file() and child.name.casefold() == "link.exe":
                return child
    except OSError:
        return None
    return None


def _read_signature(path: Path) -> bytes:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size <= 6 * 1024 * 1024:
            return handle.read(6 * 1024 * 1024 + 1)
        head = handle.read(2 * 1024 * 1024)
        handle.seek(max(0, size - 2 * 1024 * 1024))
        return head + handle.read(2 * 1024 * 1024)


def _signature_kind(blob: bytes) -> str:
    incremental = "Incremental Linker".encode("utf-16le")
    if b"Incremental Linker" in blob or incremental in blob:
        return "msvc"
    if (b"coreutils" in blob or b"extra operand" in blob
            or b"gnu.org/software/coreutils" in blob):
        return "gnu"
    return "unknown"


def _msvc_tool_layout(path: Path) -> bool:
    parts = [part.casefold() for part in path.parts]
    return (path.name.casefold() == "link.exe" and "vc" in parts
            and "tools" in parts and "msvc" in parts and "bin" in parts)


def _unix_tools_directory(directory: Path) -> bool:
    parts = [part.casefold() for part in directory.parts]
    if len(parts) >= 2 and parts[-1] == "bin" and parts[-2] == "usr":
        return True
    return len(parts) >= 2 and parts[-1] == "bin" and parts[-2] in {
        "mingw64", "mingw32", "cygwin64", "cygwin", "msys64", "msys32"}


def _classify_link_file(path: Path, root: Path) -> str:
    try:
        if not path.is_file():
            return "absent"
        resolved = path.resolve(strict=True)
        if (not resolved.is_file()
                or adapters._disallowed_workspace_executable(resolved, root)):
            return "absent"
        blob = _read_signature(resolved)
    except (OSError, ValueError):
        return "absent"
    kind = _signature_kind(blob)
    if kind != "unknown":
        return kind
    try:
        size = resolved.stat().st_size
    except OSError:
        return "unknown"
    if _msvc_tool_layout(resolved) and blob.startswith(b"MZ") and size >= 200_000:
        return "msvc"
    if _unix_tools_directory(resolved.parent):
        return "gnu"
    return "unknown"


def _classify_directory(directory: Path, root: Path) -> str:
    allowed = _approved_directory(str(directory), root)
    if allowed is None:
        return "blocked"
    executable = _link_executable(allowed)
    if executable is None:
        return "absent"
    return _classify_link_file(executable, root)


def _lib_arch(source: Mapping[str, str]) -> str:
    arch = (_env_lookup(source, "PROCESSOR_ARCHITECTURE") or "AMD64").casefold()
    if arch in {"arm64", "aarch64"}:
        return "arm64"
    if arch in {"x86", "i386"}:
        return "x86"
    return "x64"


def _host_targets(source: Mapping[str, str]) -> list:
    arch = _lib_arch(source)
    if arch == "arm64":
        return [("HostARM64", "arm64"), ("Hostx64", "arm64"), ("Hostx64", "x64")]
    if arch == "x86":
        return [("Hostx86", "x86"), ("Hostx64", "x86")]
    return [("Hostx64", "x64"), ("HostX64", "x64"), ("Hostx86", "x64")]


def _pinned_toolset(source: Mapping[str, str]) -> str:
    value = (_env_lookup(source, "VCToolsVersion") or "").strip()
    if _WINDOWS_TOKEN_VARS["VCToolsVersion"].fullmatch(value):
        return value
    return ""


def _link_in_toolset(toolset: Path, source: Mapping[str, str], root: Path) -> Optional[Path]:
    pinned = _pinned_toolset(source)
    if pinned and toolset.name != pinned:
        return None
    if not toolset.is_dir() or toolset.is_symlink():
        return None
    for host, target in _host_targets(source):
        candidate = toolset / "bin" / host / target / "link.exe"
        if _classify_link_file(candidate, root) == "msvc":
            try:
                return candidate.resolve(strict=True)
            except (OSError, ValueError):
                continue
    return None


def _toolsets(instance: Path, source: Mapping[str, str]) -> list:
    tools = instance / "VC" / "Tools" / "MSVC"
    if not tools.is_dir() or tools.is_symlink():
        return []
    pinned = _pinned_toolset(source)
    found = []
    try:
        children = list(tools.iterdir())
    except OSError:
        return []
    for child in children[:12]:
        if not child.is_dir() or child.is_symlink() or not _version_key(child.name):
            continue
        if pinned and child.name != pinned:
            continue
        found.append(child)
    found.sort(key=lambda item: _version_key(item.name), reverse=True)
    return found


def _vs_instances(source: Mapping[str, str], root: Path) -> list:
    instances = []
    install = _approved_directory(_env_lookup(source, "VSINSTALLDIR"), root)
    if install is not None:
        instances.append(install)
    vc_install = _approved_directory(_env_lookup(source, "VCINSTALLDIR"), root)
    if vc_install is not None and vc_install.name.casefold() == "vc":
        instances.append(vc_install.parent)
    for key in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        base = _approved_directory(_env_lookup(source, key), root)
        if base is None:
            continue
        visual_studio = base / "Microsoft Visual Studio"
        for year in _VS_YEARS:
            for edition in _VS_EDITIONS:
                instance = visual_studio / year / edition
                if instance.is_dir() and not instance.is_symlink() and instance not in instances:
                    instances.append(instance)
    return instances


def _find_msvc_link(source: Mapping[str, str], root: Path) -> Optional[Path]:
    tools = _approved_directory(_env_lookup(source, "VCToolsInstallDir"), root)
    if tools is not None:
        found = _link_in_toolset(tools, source, root)
        if found is not None:
            return found
    best = None
    best_version = ()
    for instance in _vs_instances(source, root):
        for toolset in _toolsets(instance, source):
            found = _link_in_toolset(toolset, source, root)
            version = _version_key(toolset.name)
            if found is not None and version >= best_version:
                best, best_version = found, version
    return best


def _kits_roots(source: Mapping[str, str], root: Path) -> list:
    roots = []
    sdk = _approved_directory(_env_lookup(source, "WindowsSdkDir"), root)
    if sdk is not None:
        roots.append(sdk)
    for key in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432"):
        base = _approved_directory(_env_lookup(source, key), root)
        if base is None:
            continue
        kits = base / "Windows Kits" / "10"
        if kits.is_dir() and not kits.is_symlink() and kits not in roots:
            roots.append(kits)
    return roots


def _sdk_version(kits: Path, arch: str) -> Optional[Path]:
    lib_root = kits / "Lib"
    if not lib_root.is_dir() or lib_root.is_symlink():
        return None
    found = []
    try:
        children = list(lib_root.iterdir())
    except OSError:
        return None
    for child in children[:40]:
        if not child.is_dir() or child.is_symlink() or not _version_key(child.name):
            continue
        if (child / "um" / arch / "kernel32.lib").is_file():
            found.append(child)
    if not found:
        return None
    return max(found, key=lambda item: _version_key(item.name))


def _fill_sdk_paths(env: dict, source: Mapping[str, str], root: Path,
                    link_exe: Path) -> None:
    """Supply LIB and INCLUDE when a developer prompt has not already set them.

    Microsoft's linker still needs kernel32.lib. A LIB that only names the
    compiler directory is not enough, so this waits until the Windows SDK
    library folder is present too.
    """
    if len(link_exe.parents) < 4:
        return
    toolset = link_exe.parents[3]
    arch = _lib_arch(source)
    spectre = _env_lookup(source, "VSCMD_ARG_VCVARS_SPECTRE") == "spectre"
    msvc_lib = toolset / "lib" / "spectre" / arch if spectre else toolset / "lib" / arch
    libs = []
    approved_msvc = _approved_directory(str(msvc_lib), root)
    if approved_msvc is not None:
        libs.append(approved_msvc)
    includes = []
    approved_include = _approved_directory(str(toolset / "include"), root)
    if approved_include is not None:
        includes.append(approved_include)
    sdk_libs = 0
    for kits in _kits_roots(source, root):
        version = _sdk_version(kits, arch)
        if version is None:
            continue
        for folder in (version / "um" / arch, version / "ucrt" / arch):
            approved = _approved_directory(str(folder), root)
            if approved is not None:
                libs.append(approved)
                sdk_libs += 1
        include_root = kits / "Include" / version.name
        for name in ("ucrt", "um", "shared"):
            approved = _approved_directory(str(include_root / name), root)
            if approved is not None:
                includes.append(approved)
        break
    if not _env_has(env, "LIB") and approved_msvc is not None and sdk_libs:
        env["LIB"] = os.pathsep.join(str(folder) for folder in libs)
    if not _env_has(env, "INCLUDE") and includes:
        env["INCLUDE"] = os.pathsep.join(str(folder) for folder in includes)


def _copy_windows_locators(env: dict, source: Mapping[str, str], root: Path) -> None:
    for name in _WINDOWS_DIR_VARS:
        if _env_has(env, name):
            continue
        folder = _approved_directory(_env_lookup(source, name), root)
        if folder is not None:
            env[name] = str(folder)
    comspec = _env_lookup(source, "ComSpec")
    if comspec and not _env_has(env, "ComSpec"):
        command = Path(comspec)
        try:
            resolved = command.resolve(strict=True) if command.is_absolute() else None
        except (OSError, ValueError):
            resolved = None
        if (resolved is not None and resolved.is_file()
                and resolved.name.casefold() == "cmd.exe"
                and not adapters._disallowed_workspace_executable(resolved, root)):
            env["ComSpec"] = str(resolved)
    for name, pattern in _WINDOWS_TOKEN_VARS.items():
        if _env_has(env, name):
            continue
        value = _env_lookup(source, name)
        if value and pattern.fullmatch(value.strip()):
            env[name] = value.strip()
    for name in _WINDOWS_PATH_LIST_VARS:
        if _env_has(env, name):
            continue
        approved = _approved_directories(_env_lookup(source, name), root)
        if approved:
            env[name] = os.pathsep.join(str(folder) for folder in approved)


def _prepare_windows_toolchain(env: dict, source: Mapping[str, str],
                               root: Path) -> Optional[str]:
    """Make rustc's MSVC link.exe win, without admitting secret environment values.

    rustc finds the linker itself when ProgramFiles(x86) is present (vswhere)
    or a developer prompt has set VCINSTALLDIR. The scrubbed V8 environment
    dropped those locator variables. cargo then executed bare link.exe, and
    Git for Windows' usr\\bin (GNU coreutils link) was the first match.
    """
    _copy_windows_locators(env, source, root)
    discovered = _find_msvc_link(source, root)
    ordered = []
    gnu_found = False
    msvc_dirs = []
    neutral = []
    gnu_dirs = []
    for item in (env.get("PATH") or "").split(os.pathsep)[:40]:
        if not item:
            continue
        kind = _classify_directory(Path(item), root)
        if kind == "blocked":
            continue
        try:
            folder = str(Path(item).resolve(strict=True))
        except (OSError, ValueError):
            continue
        if kind == "msvc":
            msvc_dirs.append(folder)
        elif kind == "gnu":
            gnu_found = True
            gnu_dirs.append(folder)
        elif folder not in neutral:
            neutral.append(folder)
    if discovered is not None:
        msvc_dirs.insert(0, str(discovered.parent))
    seen = set()
    # MSVC directories stay in front of Git/MSYS usr\\bin. GNU link can remain
    # later on PATH so a windows-gnu toolchain still finds gcc beside it.
    for folder in msvc_dirs + neutral + gnu_dirs:
        key = os.path.normcase(folder)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(folder)
    env["PATH"] = os.pathsep.join(ordered)
    if msvc_dirs:
        if discovered is not None:
            _fill_sdk_paths(env, source, root, discovered)
        return None
    # Keep Unix-tool directories on PATH. A windows-gnu toolchain needs them,
    # and deleting them would hide gcc. The caller substitutes a plain
    # diagnostic if this MSVC toolchain still ends up executing GNU link.
    if gnu_found:
        return _GNU_LINK_DIAGNOSTIC
    return _MSVC_MISSING


def _gnu_link_output(output: str) -> bool:
    """GNU coreutils link, not Microsoft's linker, produced this failure."""
    lowered = output.casefold()
    return "extra operand" in lowered and "link --help" in lowered


def _linker_failure_is_not_msvc(output: str) -> bool:
    """True when the failure is GNU link or a missing link.exe, not an LNK error."""
    lowered = output.casefold()
    if "lnk1" in lowered:
        return False
    if _gnu_link_output(output):
        return True
    if "link.exe" not in lowered:
        return False
    return ("not found" in lowered or "os error 2" in lowered
            or "cannot find the file" in lowered
            or "the system cannot find the file" in lowered)


def _environment(root: Path, temp: Path, *, windows: Optional[bool] = None) -> tuple:
    env = adapters._environment(root)
    env.update({
        "CARGO_HOME": str(temp / "cargo-home"),
        "CARGO_TARGET_DIR": str(temp / "target"),
        "CARGO_NET_OFFLINE": "true",
        "CARGO_INCREMENTAL": "0",
        "CARGO_TERM_COLOR": "never",
        "RUSTUP_AUTO_INSTALL": "0",
        "RUST_BACKTRACE": "0",
    })
    (temp / "cargo-home").mkdir(mode=0o700, exist_ok=True)
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return env, None
    # V8's scrubbed environment still omits arbitrary inherited values.
    # Only Windows toolchain locators and absolute library directories
    # outside every approved project root are added back.
    return env, _prepare_windows_toolchain(env, os.environ, root)


def _execute(root: Path, tool: dict, command: list[str], env: dict) -> dict:
    checked = adapters._fingerprint(tool["executable"], root)
    if (checked["executable"] != tool["executable"] or
            checked["sha256"] != tool["sha256"]):
        raise HTTPException(409, "Installed Rust tool changed before execution.")
    adapters._trusted(root)
    kwargs = {"cwd": root, "env": env, "shell": False,
              "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE,
              "stderr": subprocess.STDOUT}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    started = time.monotonic()
    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError as exc:
        raise HTTPException(502, "Approved Rust tool could not start.") from exc
    output = bytearray()
    overflow = threading.Event()
    timed_out = False

    def read_bounded():
        try:
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                remainder = MAX_OUTPUT - len(output)
                output.extend(chunk[:max(0, remainder)])
                if len(chunk) > remainder:
                    overflow.set()
                    adapters._terminate(process)
                    break
        except (OSError, ValueError):
            pass

    worker = threading.Thread(target=read_bounded, daemon=True)
    worker.start()
    try:
        try:
            process.wait(timeout=MAX_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
            adapters._terminate(process)
        worker.join(timeout=1)
    finally:
        adapters._terminate(process)
        if process.stdout:
            process.stdout.close()
    return {"status": "output_limit" if overflow.is_set() else
                      "timeout" if timed_out else
                      "completed" if process.returncode == 0 else "nonzero_exit",
            "exit_code": process.returncode, "output": output.decode("utf-8", "replace"),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "timed_out": timed_out, "output_truncated": overflow.is_set(),
            "explicit_approval": True, "platform_sandbox": False}


def _diagnostics(root: Path, output: str) -> list[dict]:
    found = []
    for raw in output.splitlines()[:1000]:
        if len(found) >= 30:
            break
        match = DIAGNOSTIC.match(raw.strip())
        if not match:
            continue
        path, line, col, severity, code, message = match.groups()
        safe = None
        if not Path(path).is_absolute():
            try:
                candidate = studio._path(root, path.replace("\\", "/"))
                if candidate.is_file():
                    safe = path.replace("\\", "/")
            except (HTTPException, OSError, ValueError):
                pass
        found.append({"path": safe, "line": int(line), "column": int(col),
                      "severity": severity, "code": code,
                      "message": message[:300]})
    return found


@router.get("/inspect")
def inspect(request: Request, project: str):
    studio._auth(request)
    return _inspect(studio._project(project))


@router.post("/run")
def run(request: Request, body: RunIn):
    studio._auth(request)
    root = studio._project(body.project)
    adapters._trusted(root)
    if not LOCK.acquire(blocking=False):
        raise HTTPException(429, "A Rust project tool is already running.")
    try:
        before = _inspect(root)
        if (before["manifest_sha256"] != body.expected_manifest_sha256
                or before["source_sha256"] != body.expected_source_sha256):
            raise HTTPException(409, "Rust manifests or source files changed since approval.")
        tool = next((x for x in before["toolchains"] if x["name"] == body.tool), None)
        if not tool or tool["status"] != "installed_not_executed":
            raise HTTPException(409, "Selected Rust executable is unavailable or unapproved.")
        if (tool["executable"] != body.expected_executable or
                tool["sha256"] != body.expected_sha256):
            raise HTTPException(409, "Rust executable identity changed since approval.")
        command = _command(body, tool["executable"], before)
        if tool.get("rustup_shim"):
            # Linux rustup symlinks resolve to rustup itself. Calling that
            # realpath as "cargo" instead runs the rustup CLI; invoke only
            # the already-installed stable toolchain explicitly, offline.
            # The rustup binary itself is SHA-pinned like other executables.
            command = [tool["executable"], "run", "stable", body.tool, *command[1:]]
        after = _inspect(root)
        if (after["manifest_sha256"] != body.expected_manifest_sha256
                or after["source_sha256"] != body.expected_source_sha256):
            raise HTTPException(409, "Rust workspace changed during execution preparation.")
        with tempfile.TemporaryDirectory(prefix="automoto-rust19-") as workdir:
            env, linker_problem = _environment(root, Path(workdir))
            result = _execute(root, tool, command, env)
        if (os.name == "nt" and body.task in _LINKER_TASKS
                and result["status"] != "completed"
                and _linker_failure_is_not_msvc(result["output"])):
            if _gnu_link_output(result["output"]):
                result["output"] = _GNU_LINK_DIAGNOSTIC
            else:
                result["output"] = linker_problem or _MSVC_MISSING
        result.update({"task": body.task, "tool": body.tool,
                       "manifest_sha256": body.expected_manifest_sha256,
                       "source_sha256": body.expected_source_sha256,
                       "diagnostics": _diagnostics(root, result["output"]),
                       "temporary_build_artifacts_deleted": True,
                       "project_file_changes": "not_verified",
                       "external_process_unsandboxed": True,
                       "network_prevented_by_os": False,
                       "package_installation_performed_by_app": False,
                       "agent_handoff_created": False,
                       "agent_deployment_approved": False,
                       "central_agent_studio": "developer",
                       "deployment_started": False})
        return result
    finally:
        LOCK.release()
