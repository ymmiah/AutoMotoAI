"""Developer Studio V18: guarded Go modules, workspace, service and profiling tools.

Local-only inspection is inert. Go build, test, vet and profiling require exact
workspace trust, SHA-pinned binaries and manifests, explicit execution consent,
offline toolchain settings and bounded runtime/output. Project code is NOT
isolated by the OS and may write files or access the network.
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

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_adapters as adapters
from automoto import developer_index as index
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/go", tags=["developer-go"])
VERSION = "1.0.0"
MAX_MANIFEST = 512 * 1024
MAX_MODULES = 12
MAX_SOURCES = 90
MAX_PACKAGES = 45
MAX_OUTPUT = 64 * 1024
MAX_PROFILE = 2 * 1024 * 1024
MAX_RUN_SECONDS = 110
RUN_LOCK = threading.Lock()
MODULE_RE = re.compile(r"(?m)^\s*module\s+(\S{1,200})\s*(?://.*)?$")
GO_RE = re.compile(r"(?m)^\s*go\s+(\d+\.\d+(?:\.\d+)?)\s*(?://.*)?$")
PACKAGE_RE = re.compile(r"(?m)^\s*package\s+([A-Za-z_]\w{0,100})\b")
FUNC_RE = re.compile(r"(?m)^\s*func\s+(?:\([^\n)]{1,140}\)\s*)?([A-Za-z_]\w{0,100})\s*\(")
TOOLS = ("go", "gopls")


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)


class RunIn(ProjectIn):
    task: Literal["version", "gopls_version", "build", "test", "vet", "profile"]
    tool: Literal["go", "gopls"]
    package: Optional[str] = Field(default=None, min_length=1, max_length=200)
    expected_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_execution_and_write_risk: Literal[True]


def _read(root: Path, relative: str, limit: int = MAX_MANIFEST) -> tuple[str, str, int]:
    """No-follow, ordinary-file, bounded content with a stable byte fingerprint."""
    if any(index._excluded(part, i < len(relative.split("/")) - 1)
           for i, part in enumerate(relative.split("/"))):
        raise HTTPException(403, "Private or generated project paths are not inspected.")
    file = studio._path(root, relative)
    if file == root:
        raise HTTPException(422, "Expected a regular project file.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(file, flags)
        with os.fdopen(fd, "rb") as stream:
            meta = os.fstat(stream.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_size > limit:
                raise HTTPException(413, "Go project file exceeds the inspection size limit.")
            raw = stream.read(limit + 1)
        if len(raw) > limit or b"\0" in raw:
            raise HTTPException(413, "Go file is oversized or binary.")
        value = raw.decode("utf-8-sig")
        return value, hashlib.sha256(raw).hexdigest(), len(raw)
    except (OSError, UnicodeError) as exc:
        raise HTTPException(403, "Cannot safely read the project file.") from exc


def _lines(text: str) -> list[str]:
    return [line.split("//", 1)[0].strip() for line in text.splitlines()[:4000]]


def _work_modules(text: str) -> tuple[list[str], list[str]]:
    uses, warnings = [], []
    active = False
    for line in _lines(text):
        if not line:
            continue
        if line == "use (":
            active = True
            continue
        if line == ")" and active:
            active = False
            continue
        if line.startswith("use "):
            value = line[4:].strip()
        elif active:
            value = line.strip()
        else:
            continue
        if not value or len(value) > 200 or value.startswith(("/", "\\", "-")):
            warnings.append("Invalid workspace use directive.")
            continue
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        if value in (".", "./"):
            value = "."
        if (not value or "\\" in value or ":" in value
                or any(part in ("..", "") for part in value.split("/"))):
            warnings.append("Workspace module reference escapes the approved project.")
            continue
        if value.startswith("./"):
            value = value[2:]
        if value not in uses:
            uses.append(value)
    if active:
        warnings.append("Unclosed go.work use group.")
    return uses[:MAX_MODULES], warnings + (["Too many workspace modules."] if len(uses) > MAX_MODULES else [])


def _fingerprints(root: Path) -> tuple[dict, str]:
    """Collect all manifest inputs before a subprocess; fail closed on scan gaps."""
    files: dict[str, dict] = {}
    module_paths = []
    incomplete = False
    for relative, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        if relative == "go.work" or relative == "go.work.sum" or relative.endswith(
                ("/go.mod", "/go.sum")) or relative in ("go.mod", "go.sum"):
            if len(files) >= 2 * MAX_MODULES + 6:
                incomplete = True
                continue
            value, digest, size = _read(root, relative)
            files[relative] = {"sha256": digest, "size": size}
            if relative == "go.mod" or relative.endswith("/go.mod"):
                name = relative[:-7] if relative != "go.mod" else "."
                match = MODULE_RE.search(value)
                module_paths.append({
                    "path": name, "module": match.group(1) if match else "",
                    "go": GO_RE.search(value).group(1) if GO_RE.search(value) else "",
                    "replace_directive": bool(re.search(r"(?m)^\s*replace\b|=>", value)),
                    "source_file": relative,
                })
    # A linked root go.work/go.mod must not silently look like an absent manifest.
    for name in ("go.mod", "go.work", "go.sum", "go.work.sum"):
        candidate = root / name
        if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
            raise HTTPException(403, "Linked Go manifest is not allowed.")
    work = files.get("go.work")
    uses: list[str] = []
    warnings: list[str] = []
    if work:
        value, _, _ = _read(root, "go.work")
        uses, warnings = _work_modules(value)
        if re.search(r"(?m)^\s*replace\b|=>", value):
            warnings.append("Go workspace replace directives require manual review.")
        if not uses:
            warnings.append("go.work contains no supported in-root modules.")
    declared = {m["path"] for m in module_paths}
    if work:
        for item in uses:
            if item not in declared:
                warnings.append("A workspace use module has no safely readable go.mod: " + item[:80])
        if any(path not in uses for path in declared):
            warnings.append("Go module discovery differs from go.work declarations.")
    elif "go.mod" not in files:
        warnings.append("No root go.mod or supported go.work found.")
    if any(m["replace_directive"] for m in module_paths):
        warnings.append("Go replace directives require manual inspection before tool execution.")
    if incomplete:
        warnings.append("Go manifest discovery exceeded bounded traversal.")
    if not module_paths or len(module_paths) > MAX_MODULES:
        warnings.append("Go module count is empty or exceeds the supported limit.")
    patterns = (["./" + x + "/..." if x != "." else "./..." for x in uses]
                if work else ["./..."] if "go.mod" in files else [])
    digest = hashlib.sha256(b"automoto-go18-manifests\0")
    for name, record in sorted(files.items()):
        digest.update(name.encode("utf-8") + b"\0" + record["sha256"].encode("ascii"))
    return {"manifests": files, "modules": sorted(module_paths, key=lambda m: m["path"]),
            "workspace": bool(work), "workspace_modules": uses,
            "patterns": patterns, "warnings": warnings,
            "safe_to_offer_runs": not warnings and bool(patterns)}, digest.hexdigest()


def _sources(root: Path) -> tuple[dict, str]:
    sources = []
    packages: dict[str, dict] = {}
    incomplete = False
    digest = hashlib.sha256(b"automoto-go18-sources\0")
    for relative, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        if not relative.endswith(".go"):
            continue
        if len(sources) >= MAX_SOURCES:
            incomplete = True
            continue
        record = index._source(root, relative)
        if not record:
            incomplete = True
            continue
        text, sha, _ = record
        match = PACKAGE_RE.search(text[:12000])
        parent = Path(relative).parent.as_posix()
        relative_dir = "." if parent == "." else "./" + parent
        entry = packages.setdefault(relative_dir, {
            "path": relative_dir, "package": match.group(1) if match else "",
            "files": 0, "tests": 0, "functions": [],
            "service_hints": [],
        })
        entry["files"] += 1
        if relative.endswith("_test.go"):
            entry["tests"] += 1
        for fn in FUNC_RE.findall(text[:20000])[:16]:
            if len(entry["functions"]) < 40 and fn not in entry["functions"]:
                entry["functions"].append(fn)
        for hint, token in (("http", '"net/http"'), ("grpc", '"google.golang.org/grpc"')):
            if token in text and hint not in entry["service_hints"]:
                entry["service_hints"].append(hint)
        sources.append({"path": relative, "sha256": sha,
                        "package": match.group(1) if match else "",
                        "test": relative.endswith("_test.go")})
        digest.update(relative.encode("utf-8") + b"\0" + sha.encode("ascii"))
    if len(packages) > MAX_PACKAGES:
        incomplete = True
    return {"files": sources, "packages": sorted(packages.values(), key=lambda x: x["path"])[:MAX_PACKAGES],
            "incomplete": incomplete}, digest.hexdigest()


def _tools(root: Path) -> list[dict]:
    results = []
    for name in TOOLS:
        candidate = shutil.which(name)
        if not candidate:
            results.append({"name": name, "status": "unavailable"})
            continue
        if Path(candidate).suffix.lower() in (".cmd", ".bat", ".ps1"):
            results.append({"name": name, "status": "shell_wrapper_blocked"})
            continue
        try:
            details = adapters._fingerprint(str(Path(candidate).absolute()), root)
            results.append({"name": name, "status": "installed_not_executed", **details})
        except HTTPException:
            results.append({"name": name, "status": "not_approved"})
    return results


def _inspect(root: Path) -> dict:
    manifest, sha = _fingerprints(root)
    source, source_sha = _sources(root)
    if source["incomplete"]:
        manifest["warnings"].append("Go source discovery was bounded or contained unreadable files.")
        manifest["safe_to_offer_runs"] = False
    return {"schema": VERSION, **manifest, "manifest_sha256": sha,
            "sources": source["files"], "packages": source["packages"],
            "source_sha256": source_sha, "scan_incomplete": source["incomplete"],
            "toolchains": _tools(root),
            "gopls": "Use existing separately consented Go LSP; no duplicate language server",
            "project_trusted": studio._trusted(root, studio._load()),
            "tool_executed": False, "dependency_downloads_performed": False,
            "deployment_started": False, "central_agent_studio": "developer",
            "agent_deployment_handoff_required": True}


def _command(body: RunIn, exe: str, summary: dict, output_dir: Path) -> list[str]:
    if body.task == "version" and body.tool == "go" and body.package is None:
        return [exe, "version"]
    if body.task == "gopls_version" and body.tool == "gopls" and body.package is None:
        return [exe, "version"]
    if body.tool != "go" or not summary["safe_to_offer_runs"]:
        raise HTTPException(409, "Go workspace is incomplete or contains unsafe/review-required directives.")
    if not summary["packages"] or summary["scan_incomplete"]:
        raise HTTPException(409, "Go source inventory is empty or incomplete.")
    patterns = summary["patterns"]
    if not patterns:
        raise HTTPException(409, "No in-root Go module build targets.")
    if body.task == "build" and body.package is None:
        return [exe, "build", "-mod=readonly", "-o", str(output_dir), *patterns]
    if body.task == "test" and body.package is None:
        return [exe, "test", "-mod=readonly", "-count=1", "-timeout=30s", *patterns]
    if body.task == "vet" and body.package is None:
        return [exe, "vet", "-mod=readonly", *patterns]
    if body.task == "profile":
        # A single concrete package, never a user-injected pattern or external import.
        found = next((x for x in summary["packages"]
                      if x["path"] == body.package and x["tests"] > 0), None)
        if found is None:
            raise HTTPException(422, "Select one discovered local Go package with tests for profiling.")
        return [exe, "test", "-mod=readonly", "-count=1", "-timeout=30s",
                "-run=Test", "-cpuprofile", str(output_dir / "cpu.pprof"), body.package]
    raise HTTPException(422, "Task, tool and package selection must match a fixed approved Go command.")


def _go_environment(root: Path, summary: dict) -> dict:
    env = adapters._environment(root)
    env.update({
        "GOTOOLCHAIN": "local", "GOENV": "off", "GOPROXY": "off",
        "GOSUMDB": "off", "GOVCS": "off", "CGO_ENABLED": "0",
        "GOWORK": str(root / "go.work") if summary["workspace"] else "off",
    })
    return env


def _execute(root: Path, tool: dict, args: list[str], env: dict, timeout: int) -> dict:
    """Process-group terminated, bounded local subprocess; NOT an OS sandbox."""
    current = adapters._fingerprint(tool["executable"], root)
    if (current["sha256"] != tool["sha256"] or
            current["executable"] != tool["executable"]):
        raise HTTPException(409, "Go executable changed since approval.")
    adapters._trusted(root)
    started = time.monotonic()
    kwargs = {"cwd": root, "env": env, "shell": False, "stdin": subprocess.DEVNULL,
              "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(args, **kwargs)
    except OSError as exc:
        raise HTTPException(502, "Approved Go program could not be started.") from exc
    output = bytearray()
    overflow = threading.Event()
    timed_out = False

    def bounded_read():
        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                available = MAX_OUTPUT - len(output)
                output.extend(chunk[:max(0, available)])
                if len(chunk) > available:
                    overflow.set()
                    adapters._terminate(proc)
                    break
        except (OSError, ValueError):
            pass

    thread = threading.Thread(target=bounded_read, daemon=True)
    thread.start()
    try:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            adapters._terminate(proc)
        thread.join(timeout=1)
    finally:
        adapters._terminate(proc)
        if proc.stdout:
            proc.stdout.close()
    return {
        "status": "output_limit" if overflow.is_set() else
                  "timeout" if timed_out else
                  "completed" if proc.returncode == 0 else "nonzero_exit",
        "exit_code": proc.returncode, "output": output.decode("utf-8", errors="replace"),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "timed_out": timed_out, "output_truncated": overflow.is_set(),
        "platform_sandbox": False, "explicit_approval": True,
    }


@router.get("/inspect")
def inspect(request: Request, project: str):
    studio._auth(request)
    return _inspect(studio._project(project))


@router.post("/run")
def run(request: Request, body: RunIn):
    studio._auth(request)
    root = studio._project(body.project)
    adapters._trusted(root)
    if not RUN_LOCK.acquire(blocking=False):
        raise HTTPException(429, "A Go tool task is already executing.")
    try:
        before = _inspect(root)
        if (before["manifest_sha256"] != body.expected_manifest_sha256
                or before["source_sha256"] != body.expected_source_sha256):
            raise HTTPException(409, "Go manifest or source inventory changed since approval.")
        candidate = next((t for t in before["toolchains"] if t["name"] == body.tool), None)
        if not candidate or candidate["status"] != "installed_not_executed":
            raise HTTPException(409, "Go/gopls binary is unavailable or not approved.")
        if (candidate["executable"] != body.expected_executable
                or candidate["sha256"] != body.expected_sha256):
            raise HTTPException(409, "Go/gopls executable changed since inspection.")
        with tempfile.TemporaryDirectory(prefix="automoto-go18-") as temp:
            directory = Path(temp)
            command = _command(body, candidate["executable"], before, directory)
            # Narrow TOCTOU window by rechecking manifests/sources and trust
            # before any subprocess; this is not a filesystem sandbox.
            after = _inspect(root)
            if (after["manifest_sha256"] != body.expected_manifest_sha256
                    or after["source_sha256"] != body.expected_source_sha256):
                raise HTTPException(409, "Go source/manifest changed during approval.")
            adapters._trusted(root)
            environment = _go_environment(root, before)
            result = _execute(root, candidate, command, environment, MAX_RUN_SECONDS)
            profile = directory / "cpu.pprof"
            result["profile"] = {"requested": body.task == "profile", "retained": False}
            if body.task == "profile" and result["status"] == "completed":
                try:
                    info = profile.stat()
                    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_PROFILE:
                        raise OSError("Go profile exceeds private size limit.")
                    result["profile"]["sha256"] = hashlib.sha256(profile.read_bytes()).hexdigest()
                    result["profile"]["size_bytes"] = info.st_size
                    # The same pinned Go binary is used for a bounded text
                    # summary; the raw profile is deleted with TemporaryDirectory.
                    report = _execute(root, candidate,
                                      [candidate["executable"], "tool", "pprof",
                                       "-top", "-nodecount=12", str(profile)],
                                      environment, 15)
                    result["profile"]["top"] = report["output"][:5000]
                    result["profile"]["summary_status"] = report["status"]
                except OSError:
                    result["profile"]["summary_status"] = "unavailable"
            result.update({
                "task": body.task, "tool": body.tool,
                "manifest_sha256": body.expected_manifest_sha256,
                "source_sha256": body.expected_source_sha256,
                "external_process_unsandboxed": True, "network_prevented_by_os": False,
                "source_files_unchanged": "not_verified",
                "package_installation_performed_by_app": False,
                "go_downloads_requested_by_app": False,
                "central_agent_studio": "developer", "agent_handoff_created": False,
                "agent_deployment_approved": False, "deployment_started": False,
                "commands_were_pinned": True,
            })
            return result
    finally:
        RUN_LOCK.release()
