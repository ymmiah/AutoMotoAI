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
from typing import Literal, Optional

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
    warnings = []
    for member in members:
        file = "Cargo.toml" if member == "." else member + "/Cargo.toml"
        if member != ".":
            # Refuse linked ancestors before reading manifests.
            studio._path(root, member)
        manifest, digest = (main, sha) if member == "." else _toml(root, file)
        meta = manifest.get("package")
        if not isinstance(meta, dict):
            raise HTTPException(422, "Workspace member lacks a Cargo package table.")
        name, version = meta.get("name"), meta.get("version")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", name):
            raise HTTPException(422, "Invalid or missing Cargo package name.")
        if not isinstance(version, str) or len(version) > 80:
            raise HTTPException(422, "Invalid or missing Cargo package version.")
        if meta.get("build") not in (None, False) or (root / member / "build.rs").exists():
            warnings.append("Build script in " + member + " requires independent review.")
        for kind in ("lib", "bin", "example", "test", "bench"):
            block = manifest.get(kind)
            targets = block if isinstance(block, list) else [block] if isinstance(block, dict) else []
            for item in targets:
                if not isinstance(item, dict):
                    continue
                custom = item.get("path")
                if custom is not None:
                    if not isinstance(custom, str) or not PATH_TOKEN.fullmatch(custom) or (
                        ".." in custom.split("/") or custom.startswith("/")):
                        warnings.append("Unsafe custom Cargo target path in " + member + ".")
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
    toolchain = root / "rust-toolchain.toml"
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
                item = {"name": name, "status": "installed_not_executed",
                        **adapters._fingerprint(str(Path(resolved).absolute()), root)}
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


def _environment(root: Path, temp: Path) -> dict:
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
    return env


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
        after = _inspect(root)
        if (after["manifest_sha256"] != body.expected_manifest_sha256
                or after["source_sha256"] != body.expected_source_sha256):
            raise HTTPException(409, "Rust workspace changed during execution preparation.")
        with tempfile.TemporaryDirectory(prefix="automoto-rust19-") as workdir:
            env = _environment(root, Path(workdir))
            result = _execute(root, tool, command, env)
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
