"""Developer Studio V17: evidence-first Python and emerging toolchain workflows.

Inspection never executes project code or installs packages. External programs
require project trust, explicit confirmation, exact manifest and executable
hashes and are not OS/network sandboxed. Only a copied .venv Python interpreter
can execute project tests; symlinked virtualenv interpreters are not supported.
"""
from __future__ import annotations

import ast
import hashlib
import os
import re
import shutil
import stat
import subprocess
import threading
import time
from pathlib import Path
from typing import Literal, Optional

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 supported by AutoMoto
    import tomli as tomllib

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_adapters as adapters
from automoto import developer_index as index
from automoto import developer_javascript as javascript
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/python", tags=["developer-python"])
SCHEMA = "1.0.0"
RUN_LOCK = threading.Lock()
MAX_MANIFEST = 96 * 1024
MAX_PYTHON_FILES = 80
MAX_DIAGNOSTICS = 60
MAX_OUTPUT = 64 * 1024
MAX_SECONDS = 20
MANIFESTS = ("pyproject.toml", "uv.lock", "requirements.txt",
             "requirements-dev.txt", "poetry.lock", "pdm.lock",
             "Pipfile.lock", ".python-version", "pytest.ini")
TOOLS = ("python", "uv", "ruff", "ty")
FRAMEWORKS = {
    "Django": "django", "Flask": "flask", "FastAPI": "fastapi",
    "Starlette": "starlette", "Litestar": "litestar", "SQLAlchemy": "sqlalchemy",
    "Pydantic": "pydantic", "Pytest": "pytest",
}
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,160}")
TEST = re.compile(r"(?:^|/)(?:test_[^/]+|[^/]+_test)\.py$", re.I)


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)


class SyntaxIn(ProjectIn):
    path: str = Field(min_length=1, max_length=1024)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class RunIn(ProjectIn):
    task: Literal["version", "pytest", "ty_check", "ruff_check"]
    tool: Literal["python", "venv_python", "uv", "ruff", "ty"]
    expected_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_execution_and_write_risk: Literal[True]


def _manifest(root: Path) -> tuple[dict, str]:
    fingerprint = hashlib.sha256(b"python-v17-manifests\0")
    files = {}
    pyproject = {}
    for name in MANIFESTS:
        path = root / name
        if not path.exists() and not path.is_symlink():
            continue
        record = index._source(root, name)
        if not record or record[2] > MAX_MANIFEST:
            raise HTTPException(403, "Python manifest is unreadable, linked or oversized.")
        files[name] = {"sha256": record[1], "size": record[2]}
        fingerprint.update(name.encode("utf-8") + b"\0" + record[1].encode("ascii"))
        if name == "pyproject.toml":
            try:
                pyproject = tomllib.loads(record[0])
            except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
                raise HTTPException(422, "pyproject.toml is malformed.") from exc
            if not isinstance(pyproject, dict):
                raise HTTPException(422, "pyproject.toml must contain a TOML table.")
    project = pyproject.get("project", {})
    build = pyproject.get("build-system", {})
    if not isinstance(project, dict) or not isinstance(build, dict):
        raise HTTPException(422, "Python project/build tables must be objects.")
    dependencies = []
    for entry in project.get("dependencies", []):
        if isinstance(entry, str) and len(dependencies) < 250:
            dependencies.append(entry[:200])
    groups = pyproject.get("dependency-groups", {})
    if isinstance(groups, dict):
        for group in list(groups.values())[:20]:
            if isinstance(group, list):
                dependencies.extend(item[:200] for item in group[:80] if isinstance(item, str))
    optional = project.get("optional-dependencies", {})
    if isinstance(optional, dict):
        for group in list(optional.values())[:20]:
            if isinstance(group, list):
                dependencies.extend(item[:200] for item in group[:80] if isinstance(item, str))
    if "requirements.txt" in files:
        source = index._source(root, "requirements.txt")
        if source:
            dependencies.extend(line.strip()[:200] for line in source[0].splitlines()[:200]
                                if line.strip() and not line.lstrip().startswith("#"))
    declared = set()
    for entry in dependencies[:800]:
        match = NAME.match(entry.strip())
        if match:
            declared.add(match.group().lower().replace("_", "-").replace(".", "-"))
    frameworks = [{"name": label, "package": key, "evidence": "declared, not installed"}
                  for label, key in FRAMEWORKS.items() if key in declared]
    build_requires = build.get("requires", [])
    if not isinstance(build_requires, list):
        build_requires = []
    venv = _venv_info(root)
    fingerprint.update(b"virtualenv\0" + venv["status"].encode("ascii") + b"\0" +
                       venv.get("config_sha256", "").encode("ascii"))
    summary = {
        "name": str(project.get("name", ""))[:160],
        "requires_python": str(project.get("requires-python", ""))[:100],
        "build_backend": str(build.get("build-backend", ""))[:120],
        "build_requires": [x[:150] for x in build_requires[:30] if isinstance(x, str)],
        "dependency_count": min(len(dependencies), 800),
        "frameworks": frameworks, "manifests": files,
        "managers_detected": [x for x, name in (("uv", "uv.lock"),
                                                 ("poetry", "poetry.lock"),
                                                 ("pdm", "pdm.lock"),
                                                 ("pip", "requirements.txt"))
                              if name in files],
        "uv_lock_present": "uv.lock" in files,
        "declared_tools": [x for x in ("uv", "ruff", "ty", "pytest", "mypy", "pyright")
                           if x in pyproject.get("tool", {})]
                           if isinstance(pyproject.get("tool", {}), dict) else [],
    }
    return summary, fingerprint.hexdigest()


def _venv_info(root: Path) -> dict:
    """Read metadata without following a symlink or running the interpreter."""
    folder = root / ".venv"
    config = folder / "pyvenv.cfg"
    if folder.is_symlink() or getattr(folder, "is_junction", lambda: False)():
        return {"status": "linked_environment_blocked"}
    if not folder.is_dir() or config.is_symlink():
        return {"status": "not_found"}
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        fd = os.open(config, flags)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return {"status": "invalid"}
            raw = stream.read(8193)
        if len(raw) > 8192:
            return {"status": "oversized_configuration"}
        text = raw.decode("utf-8", errors="replace")
    except OSError:
        return {"status": "unreadable_configuration"}
    values = dict((key.strip(), value.strip()) for line in text.splitlines()
                  if "=" in line and len(line) < 512
                  for key, value in (line.split("=", 1),))
    return {"status": "detected_not_executed",
            "config_sha256": hashlib.sha256(raw).hexdigest(),
            "version_declared": values.get("version", "").strip()[:60],
            "include_system_site_packages": values.get("include-system-site-packages", "").strip()[:20]}


def _venv_binary(root: Path) -> Optional[dict]:
    venv = _venv_info(root)
    if (venv["status"] != "detected_not_executed" or
            venv.get("include_system_site_packages", "").lower() != "false"):
        return None
    folder = root / ".venv"
    candidates = ((folder / "Scripts" / "python.exe",) if os.name == "nt"
                  else (folder / "bin" / "python",))
    for binary in candidates:
        if any(part.is_symlink() or getattr(part, "is_junction", lambda: False)()
               for part in (folder, binary.parent, binary)):
            continue
        try:
            data = binary.stat()
            if not stat.S_ISREG(data.st_mode) or data.st_size > 256 * 1024 * 1024:
                continue
            if not os.access(binary, os.X_OK):
                continue
            digest = hashlib.sha256()
            with binary.open("rb") as stream:
                while True:
                    buf = stream.read(1024 * 1024)
                    if not buf:
                        break
                    digest.update(buf)
            new = binary.stat()
            if (data.st_size, data.st_mtime_ns, data.st_ino) != (
                    new.st_size, new.st_mtime_ns, new.st_ino):
                continue
            return {"name": "venv_python", "status": "installed_not_executed",
                    "executable": str(binary), "sha256": digest.hexdigest(),
                    "venv_copy_required": True, "not_os_sandboxed": True}
        except OSError:
            continue
    return None


def _tools(root: Path) -> list[dict]:
    results = []
    for name in TOOLS:
        candidate = shutil.which("python3" if name == "python" and os.name != "nt" else name)
        if not candidate and name == "python":
            candidate = shutil.which("python")
        if not candidate:
            results.append({"name": name, "status": "unavailable"})
            continue
        if Path(candidate).suffix.lower() in (".cmd", ".bat", ".ps1"):
            results.append({"name": name, "status": "shell_wrapper_blocked"})
            continue
        try:
            checked = adapters._fingerprint(str(Path(candidate).absolute()), root)
            results.append({"name": name, "status": "installed_not_executed", **checked})
        except HTTPException:
            results.append({"name": name, "status": "not_approved"})
    venv = _venv_binary(root)
    results.append(venv or {"name": "venv_python", "status": "not_available_or_linked"})
    return results


def _sources(root: Path) -> tuple[list[str], list[str], bool]:
    sources, tests = [], []
    incomplete = False
    for relative, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        if relative.endswith(".py"):
            record = index._source(root, relative)
            if record:
                if len(sources) < MAX_PYTHON_FILES:
                    sources.append(relative)
                    if TEST.search(relative):
                        tests.append(relative)
                else:
                    incomplete = True
    return sources, tests, incomplete


def _inspect(root: Path) -> dict:
    summary, digest = _manifest(root)
    sources, tests, truncated = _sources(root)
    return {"schema": SCHEMA, **summary, "manifest_sha256": digest,
            "python_files": sources, "test_files": tests, "scan_truncated": truncated,
            "virtual_environment": _venv_info(root), "toolchains": _tools(root),
            "python_lsp": "existing consent-bound pyright LSP; ty is an optional checker",
            "project_trusted": studio._trusted(root, studio._load()),
            "tool_executed": False, "installation_performed": False,
            "deployment_started": False, "central_agent_studio": "developer",
            "agent_deployment_handoff_required": True}


def _source(root: Path, path: str) -> tuple[str, str]:
    if (path.startswith("-") or any(ord(c) < 32 for c in path)
            or not path.endswith(".py")):
        raise HTTPException(422, "Choose a valid project-relative Python file.")
    record = index._source(root, path)
    if not record:
        raise HTTPException(403, "Python file is unsafe, linked, missing or oversized.")
    return record[0], record[1]


@router.get("/inspect")
def inspect(request: Request, project: str):
    studio._auth(request)
    return _inspect(studio._project(project))


@router.post("/syntax")
def syntax(request: Request, body: SyntaxIn):
    studio._auth(request)
    root = studio._project(body.project)
    source, digest = _source(root, body.path)
    if digest != body.expected_sha256:
        raise HTTPException(409, "Source changed; refresh its checksum.")
    try:
        tree = ast.parse(source, filename=body.path)
    except SyntaxError as exc:
        return {"path": body.path, "source_sha256": digest, "valid": False,
                "diagnostics": [{"line": exc.lineno, "column": exc.offset,
                                 "message": str(exc.msg)[:300]}], "executed": False}
    return {"path": body.path, "source_sha256": digest, "valid": True,
            "functions": sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                             for n in ast.walk(tree)),
            "classes": sum(isinstance(n, ast.ClassDef) for n in ast.walk(tree)),
            "diagnostics": [], "executed": False}


def _command(body: RunIn, executable: str) -> list[str]:
    if body.task == "version":
        if body.tool not in ("python", "venv_python", "uv", "ty", "ruff"):
            raise HTTPException(422, "Invalid version tool.")
        return [executable, "-V"] if body.tool in ("python", "venv_python") else (
            [executable, "version"] if body.tool == "ty" else [executable, "--version"])
    if body.task == "pytest" and body.tool == "venv_python":
        return [executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                "--disable-warnings"]
    if body.task == "ty_check" and body.tool == "ty":
        return [executable, "check", "--no-progress"]
    if body.task == "ruff_check" and body.tool == "ruff":
        return [executable, "check", "--no-cache", "--no-fix", "."]
    raise HTTPException(422, "Tests require a verified copied .venv Python; choose the right tool for checks.")


def _run_venv(root: Path, tool: dict, command: list[str]) -> dict:
    """Run a copy-only venv interpreter; never treat this as an OS sandbox."""
    if _venv_binary(root) != tool:
        raise HTTPException(409, "Project virtual environment changed before execution.")
    env = adapters._environment(root)
    env["VIRTUAL_ENV"] = str(root / ".venv")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PIP_NO_INDEX"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    started = time.monotonic()
    proc = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=(os.name != "nt"))
    output = bytearray()
    overflow = threading.Event()
    timeout = False

    def read():
        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                left = MAX_OUTPUT - len(output)
                output.extend(chunk[:max(0, left)])
                if len(chunk) > left:
                    overflow.set()
                    adapters._terminate(proc)
                    break
        except (OSError, ValueError):
            pass

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        try:
            proc.wait(timeout=MAX_SECONDS)
        except subprocess.TimeoutExpired:
            timeout = True
            adapters._terminate(proc)
        reader.join(timeout=1)
    finally:
        adapters._terminate(proc)
        if proc.stdout:
            proc.stdout.close()
    return {"status": "output_limit" if overflow.is_set() else
                      "timeout" if timeout else
                      "completed" if proc.returncode == 0 else "nonzero_exit",
            "output": output.decode("utf-8", errors="replace"),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "exit_code": proc.returncode,
            "timed_out": timeout, "output_truncated": overflow.is_set(),
            "platform_sandbox": False, "explicit_approval": True}


@router.post("/run")
def run(request: Request, body: RunIn):
    studio._auth(request)
    root = studio._project(body.project)
    adapters._trusted(root)
    if not RUN_LOCK.acquire(blocking=False):
        raise HTTPException(429, "A Python tool task is already running.")
    try:
        first = _inspect(root)
        if first["manifest_sha256"] != body.expected_manifest_sha256:
            raise HTTPException(409, "Python manifests changed since inspection.")
        choice = next((t for t in first["toolchains"] if t["name"] == body.tool), None)
        if not choice or choice["status"] != "installed_not_executed":
            raise HTTPException(409, "Tool unavailable or not approved.")
        if (choice["executable"] != body.expected_executable or
                choice["sha256"] != body.expected_sha256):
            raise HTTPException(409, "Tool identity differs from approved fingerprint.")
        command = _command(body, choice["executable"])
        if _manifest(root)[1] != body.expected_manifest_sha256:
            raise HTTPException(409, "Python manifest changed during task preparation.")
        adapters._trusted(root)
        if body.tool == "venv_python":
            current = _venv_binary(root)
            if current != choice:
                raise HTTPException(409, "Virtualenv interpreter changed after approval.")
            result = _run_venv(root, choice, command)
        else:
            current = adapters._fingerprint(choice["executable"], root)
            if (current["sha256"] != body.expected_sha256 or
                    current["executable"] != body.expected_executable):
                raise HTTPException(409, "System executable changed after approval.")
            record = {"id": "py17-" + body.task, "category": "test",
                      "executable": choice["executable"], "sha256": choice["sha256"],
                      "args": command[1:], "project_identity": studio._identity(root)}
            result = javascript._run_task(root, record)
        result.update({"task": body.task, "tool": body.tool,
                       "manifest_sha256": body.expected_manifest_sha256,
                       "external_process_unsandboxed": True,
                       "network_prevented_by_os": False,
                       "source_files_unchanged": "not_verified",
                       "package_installation_performed_by_app": False,
                       "central_agent_studio": "developer",
                       "agent_handoff_created": False,
                       "agent_deployment_approved": False,
                       "deployment_started": False})
        return result
    finally:
        RUN_LOCK.release()
