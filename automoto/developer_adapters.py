"""Developer Studio V8: opt-in, hash-pinned local toolchain and DAP adapter SDK.

External executables are *not sandboxed*. Registration never installs a binary;
execution is allowed only after project trust, exact binary re-verification and
a distinct per-invocation acknowledgement of execution and possible file writes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_languages as languages
from automoto import developer_studio as studio
from automoto import home, sandbox

router = APIRouter(prefix="/api/developer/studio/adapters", tags=["developer-adapters"])
SCHEMA_VERSION = 1
MAX_REGISTRY_BYTES = 64 * 1024
MAX_ADAPTERS = 24
MAX_ARGS = 12
MAX_BINARY_BYTES = 256 * 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
MAX_DAP_BYTES = 64 * 1024
MAX_DAP_HEADERS = 4096
MAX_DAP_FRAMES = 16
RUN_TIMEOUT = 7.0
DAP_TIMEOUT = 6.0
TYPES = ("compiler", "test", "formatter", "linter", "package", "debugger")
REGISTRY_LOCK = threading.RLock()
# A single executed tool at a time limits the damage of accidental repeat clicks
# and prevents the UI from encouraging parallel unsafe execution.
EXEC_LOCK = threading.Lock()


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)


class InspectIn(ProjectIn):
    executable: str = Field(min_length=1, max_length=2048)


class RegisterIn(InspectIn):
    id: str = Field(min_length=3, max_length=48, pattern=r"^[a-z][a-z0-9-]{2,47}$")
    label: str = Field(min_length=1, max_length=80)
    language: str = Field(min_length=1, max_length=40)
    category: Literal["compiler", "test", "formatter", "linter", "package", "debugger"]
    protocol: Literal["process", "dap"] = "process"
    args: list[str] = Field(default_factory=list, max_length=MAX_ARGS)
    expected_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]


class RegisteredIn(ProjectIn):
    id: str = Field(min_length=3, max_length=48, pattern=r"^[a-z][a-z0-9-]{2,47}$")
    confirmed: Literal[True]


class RunIn(RegisteredIn):
    accept_execution_and_write_risk: Literal[True]


def _trusted(root: Path) -> None:
    with studio.STATE_LOCK:
        if not studio._trusted(root, studio._load()):
            raise HTTPException(403, "Trust this exact local project before using external tools.")


def _registry_file() -> Path:
    directory = home.home() / "developer-studio"
    file = directory / "external-adapters.json"
    if directory.is_symlink() or file.is_symlink():
        raise HTTPException(403, "Adapter registry cannot be a symbolic link.")
    return file


def _load() -> dict:
    file = _registry_file()
    if not file.exists():
        return {"schema": SCHEMA_VERSION, "adapters": []}
    try:
        if file.stat().st_size > MAX_REGISTRY_BYTES:
            raise ValueError("oversized adapter registry")
        data = json.loads(file.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION
                or not isinstance(data.get("adapters"), list)
                or len(data["adapters"]) > MAX_ADAPTERS):
            raise ValueError("invalid adapter registry")
        if not all(isinstance(item, dict) for item in data["adapters"]):
            raise ValueError("invalid adapter entries")
        return data
    except (ValueError, OSError, UnicodeError) as exc:
        # Fail closed; preserve the original file for manual recovery.
        raise HTTPException(409, "Adapter registry is corrupt or inaccessible.") from exc


def _save(data: dict) -> None:
    file = _registry_file()
    directory = file.parent
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink() or file.is_symlink():
        raise HTTPException(403, "Adapter registry cannot be a symbolic link.")
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(raw) > MAX_REGISTRY_BYTES:
        raise HTTPException(413, "Adapter registry reached the storage limit.")
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".adapters-", dir=directory,
                                         delete=False) as out:
            tmp = Path(out.name)
            os.chmod(tmp, 0o600)
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, file)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def _disallowed_workspace_executable(path: Path, root: Path) -> bool:
    try:
        if path.is_relative_to(root):
            return True
        # Project-independent system tools only: do not run tools out of any
        # user-approved source root, including another project's tree.
        return any(path.is_relative_to(base.resolve())
                   for base in [sandbox.default_root(), *sandbox.extra_roots()])
    except (OSError, ValueError):
        return True


def _fingerprint(executable: str, root: Path) -> dict:
    if "\x00" in executable or not Path(executable).is_absolute():
        raise HTTPException(422, "Choose an absolute installed executable path.")
    try:
        target = Path(executable).resolve(strict=True)
        if _disallowed_workspace_executable(target, root):
            raise HTTPException(403, "Project and approved workspace executables are not allowed.")
        info = target.stat()
        if (not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BINARY_BYTES
                or not os.access(target, os.X_OK)):
            raise HTTPException(422, "Executable must be a runnable ordinary file under the size limit.")
        digest = hashlib.sha256()
        with target.open("rb") as source:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        after = target.stat()
        if (info.st_size != after.st_size or info.st_mtime_ns != after.st_mtime_ns
                or info.st_ino != after.st_ino):
            raise HTTPException(409, "Executable changed during fingerprinting.")
        return {"executable": str(target), "sha256": digest.hexdigest(),
                "size_bytes": info.st_size, "verification": "file bytes only; not a security audit"}
    except HTTPException:
        raise
    except (OSError, ValueError) as exc:
        raise HTTPException(422, "Executable cannot be verified.") from exc


def _validate_arguments(args: list[str]) -> None:
    if len(args) > MAX_ARGS:
        raise HTTPException(422, "Too many fixed command arguments.")
    for arg in args:
        if (not isinstance(arg, str) or len(arg) > 256
                or any(ord(ch) < 32 for ch in arg)):
            raise HTTPException(422, "Command arguments must be short, fixed text without controls.")
    # Arguments are intentionally static. No arbitrary caller-supplied command
    # overrides, template evaluation, file interpolation, shell or env expansion.


def _matching(root: Path, identifier: str) -> dict:
    with REGISTRY_LOCK:
        data = _load()
        matched = next((x for x in data["adapters"]
                        if x.get("id") == identifier
                        and x.get("project_identity") == studio._identity(root)), None)
    if matched is None:
        raise HTTPException(404, "No adapter registered for this exact local project.")
    return matched.copy()


def _environment(root: Path) -> dict:
    permitted = ("HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR", "TMP", "TEMP",
                 "LANG", "LC_ALL", "APPDATA", "LOCALAPPDATA")
    env = {name: os.environ[name] for name in permitted if name in os.environ}
    safe_path = []
    for item in os.environ.get("PATH", "").split(os.pathsep):
        if not item or not Path(item).is_absolute():
            continue
        try:
            resolved = Path(item).resolve(strict=True)
            if not _disallowed_workspace_executable(resolved, root):
                safe_path.append(str(resolved))
        except (OSError, ValueError):
            continue
    env["PATH"] = os.pathsep.join(safe_path)
    env["AUTOMOTO_TOOLCHAIN_SDK"] = "8"
    return env


def _start(root: Path, record: dict, *, dap: bool) -> subprocess.Popen:
    fingerprint = _fingerprint(record["executable"], root)
    if (fingerprint["sha256"] != record["sha256"]
            or fingerprint["executable"] != record["executable"]):
        raise HTTPException(409, "Executable bytes or location changed; re-register this adapter.")
    # The trusted root may be revoked while an operator is inspecting an adapter.
    _trusted(root)
    if studio._identity(root) != record["project_identity"]:
        raise HTTPException(409, "Project root identity changed; re-register this adapter.")
    command = [record["executable"], *record["args"]]
    kwargs = {
        "cwd": str(root), "env": _environment(root), "shell": False,
        "stdin": subprocess.PIPE if dap else subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL if dap else subprocess.STDOUT,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(command, **kwargs)
    except OSError as exc:
        raise HTTPException(502, "Unable to start the pinned external executable.") from exc


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=0.6)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        process.wait(timeout=0.5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _run_process(root: Path, record: dict) -> dict:
    started = time.monotonic()
    process = _start(root, record, dap=False)
    output = bytearray()
    overflow = threading.Event()
    timed_out = False

    def read_bounded():
        try:
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                remaining = MAX_OUTPUT_BYTES - len(output)
                output.extend(chunk[:max(0, remaining)])
                if len(chunk) > remaining:
                    overflow.set()
                    _terminate(process)
                    break
        except (OSError, ValueError):
            pass

    thread = threading.Thread(target=read_bounded, daemon=True)
    thread.start()
    try:
        try:
            process.wait(timeout=RUN_TIMEOUT)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate(process)
        thread.join(timeout=1.0)
    finally:
        _terminate(process)
        if process.stdout:
            process.stdout.close()
    result = {
        "adapter_id": record["id"], "category": record["category"],
        "status": "output_limit" if overflow.is_set()
                  else "timeout" if timed_out
                  else "completed" if process.returncode == 0 else "nonzero_exit",
        "exit_code": process.returncode, "elapsed_ms": int((time.monotonic() - started) * 1000),
        "output": output.decode("utf-8", errors="replace"),
        "output_truncated": overflow.is_set(), "timed_out": timed_out,
        "explicit_approval": True, "execution_mode": "trusted_local_subprocess",
        "platform_sandbox": False, "source_files_unchanged": "not_verified",
        "registry_modified": False,
    }
    return result


def _read_dap_frame(stream) -> dict:
    headers = 0
    length = None
    while True:
        line = stream.readline(MAX_DAP_HEADERS + 1)
        if not line:
            raise EOFError("DAP adapter disconnected.")
        headers += len(line)
        if headers > MAX_DAP_HEADERS:
            raise ValueError("DAP headers too large.")
        if line in (b"\r\n", b"\n"):
            break
        if line.lower().startswith(b"content-length:"):
            try:
                length = int(line.split(b":", 1)[1].strip())
            except ValueError as exc:
                raise ValueError("Invalid DAP frame length.") from exc
    if length is None or not (0 <= length <= MAX_DAP_BYTES):
        raise ValueError("Invalid or oversized DAP message.")
    raw = stream.read(length)
    if len(raw) != length:
        raise EOFError("Incomplete DAP response.")
    result = json.loads(raw.decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("Invalid DAP message object.")
    return result


def _dap_handshake(root: Path, record: dict) -> dict:
    started = time.monotonic()
    process = _start(root, record, dap=True)
    state: dict = {}
    request = {
        "seq": 1, "type": "request", "command": "initialize",
        "arguments": {"clientID": "automoto-developer-studio",
                      "clientName": "AutoMoto Developer Studio",
                      "adapterID": record["id"], "pathFormat": "path",
                      "linesStartAt1": True, "columnsStartAt1": True,
                      "supportsVariableType": False, "supportsRunInTerminalRequest": False},
    }

    def exchange():
        try:
            body = json.dumps(request, separators=(",", ":")).encode("utf-8")
            process.stdin.write(b"Content-Length: " + str(len(body)).encode()
                                + b"\r\n\r\n" + body)
            process.stdin.flush()
            for _ in range(MAX_DAP_FRAMES):
                message = _read_dap_frame(process.stdout)
                if (message.get("type") == "response" and
                        message.get("request_seq") == 1 and
                        message.get("command") == "initialize"):
                    if message.get("success") is not True:
                        raise ValueError("DAP initialise was rejected.")
                    capabilities = message.get("body", {})
                    if not isinstance(capabilities, dict):
                        capabilities = {}
                    allowed = ("supportsConfigurationDoneRequest", "supportsFunctionBreakpoints",
                               "supportsConditionalBreakpoints", "supportsHitConditionalBreakpoints",
                               "supportsEvaluateForHovers", "supportsSetVariable",
                               "supportsTerminateRequest", "supportsDisassembleRequest")
                    state["capabilities"] = {
                        key: capabilities.get(key) is True for key in allowed
                    }
                    return
            raise ValueError("DAP initialize response not received within frame limit.")
        except (OSError, ValueError, UnicodeError, EOFError, TypeError) as exc:
            state["error"] = type(exc).__name__

    thread = threading.Thread(target=exchange, daemon=True)
    thread.start()
    thread.join(timeout=DAP_TIMEOUT)
    timed_out = thread.is_alive()
    _terminate(process)
    thread.join(timeout=1.0)
    if process.stdout:
        process.stdout.close()
    if process.stdin:
        process.stdin.close()
    if timed_out:
        raise HTTPException(504, "Debug adapter initialization timed out; process terminated.")
    if "error" in state or "capabilities" not in state:
        raise HTTPException(502, "Invalid, rejected or malicious DAP initialize response.")
    return {
        "adapter_id": record["id"], "status": "initialized_only",
        "capabilities": state["capabilities"],
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "launch_sent": False, "attach_sent": False, "configuration_sent": False,
        "debuggee_started": "not_requested",
        "process_terminated": process.poll() is not None,
        "explicit_approval": True, "platform_sandbox": False,
        "source_files_unchanged": "not_verified",
    }


@router.get("/catalog")
def catalog(request: Request, project: str):
    studio._auth(request)
    root = studio._project(project)
    with REGISTRY_LOCK:
        stored = _load()["adapters"]
        registered = [
            {key: rec[key] for key in ("id", "label", "language", "category",
                                      "protocol", "executable", "sha256", "args")}
            for rec in stored if rec.get("project_identity") == studio._identity(root)
        ]
    return {"schema_version": SCHEMA_VERSION, "roles": list(TYPES),
            "registered": registered, "project_trusted": studio._trusted(root, studio._load()),
            "auto_install": False, "auto_execute": False, "platform_sandbox": False,
            "scope": "project-local adapter descriptors, external binaries installed separately"}


@router.post("/inspect")
def inspect_executable(request: Request, body: InspectIn):
    studio._auth(request)
    root = studio._project(body.project)
    _trusted(root)
    return _fingerprint(body.executable, root)


@router.post("/register")
def register(request: Request, body: RegisterIn):
    studio._auth(request)
    root = studio._project(body.project)
    _trusted(root)
    if body.language not in languages.IDS:
        raise HTTPException(422, "Unknown language registry identifier.")
    if (body.category == "debugger") != (body.protocol == "dap"):
        raise HTTPException(422, "Only debugger adapters may use DAP; debuggers require DAP.")
    _validate_arguments(body.args)
    verified = _fingerprint(body.executable, root)
    if verified["sha256"] != body.expected_sha256:
        raise HTTPException(409, "Executable checksum differs from the approved SHA-256.")
    record = {
        "id": body.id, "label": body.label, "language": body.language,
        "category": body.category, "protocol": body.protocol,
        "executable": verified["executable"], "sha256": verified["sha256"],
        "args": list(body.args), "project_identity": studio._identity(root),
    }
    with REGISTRY_LOCK:
        data = _load()
        if any(item.get("id") == body.id and
               item.get("project_identity") == record["project_identity"]
               for item in data["adapters"]):
            raise HTTPException(409, "Adapter ID is already registered for this project.")
        if len(data["adapters"]) >= MAX_ADAPTERS:
            raise HTTPException(429, "Private adapter registry limit reached.")
        data["adapters"].append(record)
        _save(data)
    return {"registered": True, "adapter": {
        key: record[key] for key in ("id", "label", "language", "category", "protocol",
                                    "executable", "sha256", "args")},
        "executable_started": False, "installed_binary": False,
        "project_files_modified": False}


@router.post("/unregister")
def unregister(request: Request, body: RegisteredIn):
    studio._auth(request)
    root = studio._project(body.project)
    _trusted(root)
    with REGISTRY_LOCK:
        data = _load()
        before = len(data["adapters"])
        data["adapters"] = [x for x in data["adapters"]
                            if not (x.get("id") == body.id and
                                    x.get("project_identity") == studio._identity(root))]
        if len(data["adapters"]) == before:
            raise HTTPException(404, "Adapter is not registered.")
        _save(data)
    return {"unregistered": True, "binary_uninstalled": False,
            "project_files_modified": False}


@router.post("/run")
def run(request: Request, body: RunIn):
    studio._auth(request)
    root = studio._project(body.project)
    _trusted(root)
    adapter = _matching(root, body.id)
    if adapter["protocol"] != "process":
        raise HTTPException(422, "Use DAP initialize for debugger adapters; launch is not supported.")
    if not EXEC_LOCK.acquire(blocking=False):
        raise HTTPException(429, "An external tool is already running.")
    try:
        return _run_process(root, adapter)
    finally:
        EXEC_LOCK.release()


@router.post("/dap/initialize")
def dap_initialize(request: Request, body: RunIn):
    studio._auth(request)
    root = studio._project(body.project)
    _trusted(root)
    adapter = _matching(root, body.id)
    if adapter["protocol"] != "dap":
        raise HTTPException(422, "Only registered DAP debugger adapters can initialize.")
    if not EXEC_LOCK.acquire(blocking=False):
        raise HTTPException(429, "An external tool is already running.")
    try:
        return _dap_handshake(root, adapter)
    finally:
        EXEC_LOCK.release()
