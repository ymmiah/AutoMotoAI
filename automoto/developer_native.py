"""Developer Studio V20: C/C++ CMake, compiler, CTest and native diagnostics.

Read-only analysis never runs user code. Every external build/test/sanitiser
command requires local project trust, explicit per-run consent, exact source
and CMake manifest snapshots and SHA-pinned installed tools. CMake executes
untrusted project configuration and tests; this is NOT an OS/network sandbox.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_adapters as adapters
from automoto import developer_index as index
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/native", tags=["developer-native"])
VERSION = "1.0.0"
MANIFEST_LIMIT = 512 * 1024
MAX_SOURCES = 100
MAX_COMMANDS = 100
MAX_OUTPUT = 96 * 1024
TIMEOUT = 110
LOCK = threading.Lock()
MANIFEST_NAMES = {"CMakeLists.txt", "CMakePresets.json", "CMakeUserPresets.json",
                  ".clangd", "compile_commands.json"}
SOURCE_SUFFIXES = (".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hh", ".hxx")
TOOLS = ("cmake", "ctest", "gcc", "g++", "clang", "clang++", "cl", "clangd")
DEBUGGERS = ("lldb-dap", "codelldb")
INCLUDE = re.compile(r'(?m)^[ \t]*#[ \t]*include[ \t]*[<"]([^>"\n]{1,160})[>"]')
DECL = re.compile(r"(?m)^\s*(?:extern\s+\"C\"\s+)?(?:[A-Za-z_][\w:*<>~&\s]{0,90}\s+)"
                  r"([A-Za-z_]\w{0,90})\s*\([^;\n]{0,220}\)\s*(?:\{|$)")
ERROR = re.compile(r'(?m)^([^\n:]{1,260}\.(?:c|cc|cpp|cxx|h|hpp)):(\d{1,8}):'
                   r'(\d{1,8}):\s*(fatal error|error|warning|note):\s*(.{1,450})')
SANITIZER = re.compile(r'(?i)(AddressSanitizer|UndefinedBehaviorSanitizer|'
                       r'runtime error:|heap-buffer-overflow|stack-buffer-overflow|'
                       r'use-after-free|double-free|undefined-behavior)')


class RootIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)


class RunIn(RootIn):
    task: Literal["cmake_version", "ctest_version", "compiler_version",
                  "clangd_version", "build", "test", "sanitize"]
    tool: Literal["cmake", "ctest", "gcc", "g++", "clang", "clang++", "cl", "clangd"]
    expected_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_toolchain_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_build_test_and_network_risk: Literal[True]


def _read(root: Path, name: str, limit: int = MANIFEST_LIMIT) -> tuple[str, str, int]:
    parts = name.replace("\\", "/").split("/")
    if any(index._excluded(part, i < len(parts) - 1) for i, part in enumerate(parts)):
        raise HTTPException(403, "Restricted native project path.")
    file = studio._path(root, name)
    if file == root:
        raise HTTPException(403, "Expected regular project file.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(file, flags)
        with os.fdopen(fd, "rb") as src:
            info = os.fstat(src.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise HTTPException(413, "Native project file exceeds inspection size limit.")
            raw = src.read(limit + 1)
        if len(raw) > limit or b"\0" in raw:
            raise HTTPException(413, "Native project file is binary or oversized.")
        return raw.decode("utf-8-sig"), hashlib.sha256(raw).hexdigest(), len(raw)
    except (OSError, UnicodeError) as exc:
        raise HTTPException(403, "Cannot read native project file safely.") from exc


def _compiled_db(root: Path) -> dict:
    if not (root / "compile_commands.json").exists():
        return {"present": False, "entries": [], "truncated": False}
    text, sha, _ = _read(root, "compile_commands.json")
    try:
        parsed = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise HTTPException(422, "compile_commands.json contains invalid JSON.") from exc
    if not isinstance(parsed, list):
        raise HTTPException(422, "compile_commands.json must be an array.")
    if len(parsed) > MAX_COMMANDS:
        raise HTTPException(413, "Compilation database exceeds the supported limit.")
    entries = []
    for item in parsed:
        if not isinstance(item, dict):
            raise HTTPException(422, "Invalid compile command object.")
        file, directory = item.get("file"), item.get("directory")
        if not isinstance(file, str) or not isinstance(directory, str):
            raise HTTPException(422, "Compile command paths must be strings.")
        try:
            cwd = Path(directory).resolve(strict=True)
            target = (Path(file) if Path(file).is_absolute() else cwd / file).resolve(strict=True)
            if (not cwd.is_relative_to(root) or not target.is_relative_to(root)
                    or not target.is_file() or target.is_symlink()):
                raise HTTPException(403, "Compile command references an external or linked source.")
            relative = target.relative_to(root).as_posix()
            if any(index._excluded(p) for p in relative.split("/")):
                raise HTTPException(403, "Compile command references a restricted path.")
        except (OSError, ValueError) as exc:
            raise HTTPException(403, "Compile command source is outside the workspace.") from exc
        # Never reveal or execute command/arguments; they may embed tokens.
        entries.append({"file": relative, "language": "C++" if
                        target.suffix.lower() in (".cpp", ".cc", ".cxx") else "C"})
    return {"present": True, "sha256": sha, "entries": entries, "truncated": False,
            "commands_executed": False, "flags_redacted": True}


def _manifests(root: Path) -> tuple[dict, str]:
    files = {}
    warnings = []
    truncated = False
    for relative, warning in index._walk(root):
        if warning:
            truncated = True
            continue
        if relative.rsplit("/", 1)[-1] not in MANIFEST_NAMES:
            continue
        if len(files) >= 50:
            truncated = True
            continue
        value, sha, size = _read(root, relative)
        files[relative] = {"sha256": sha, "size": size}
        if relative.endswith("CMakeLists.txt"):
            if re.search(r"(?im)^\s*(?:include|execute_process|file\s*\(\s*DOWNLOAD|"
                         r"ExternalProject_Add|FetchContent_Declare)\b", value):
                warnings.append("CMake script can execute or fetch external code: " + relative)
    for name in ("CMakeLists.txt", "CMakePresets.json", "CMakeUserPresets.json",
                 ".clangd", "compile_commands.json"):
        file = root / name
        if file.is_symlink() or getattr(file, "is_junction", lambda: False)():
            raise HTTPException(403, "Linked native project configuration is forbidden.")
    if "CMakeLists.txt" not in files:
        warnings.append("Root CMakeLists.txt is missing.")
    if "CMakeUserPresets.json" in files:
        warnings.append("User CMake presets need separate human review.")
    if truncated:
        warnings.append("CMake scan was incomplete or exceeded limits.")
    db = _compiled_db(root)
    digest = hashlib.sha256(b"automoto-native-v20-manifests\0")
    for file, meta in sorted(files.items()):
        digest.update(file.encode("utf-8") + b"\0" + meta["sha256"].encode("ascii"))
    return {"manifests": files, "compile_commands": db,
            "warnings": warnings, "scan_truncated": truncated,
            "safe_to_offer_runs": not warnings}, digest.hexdigest()


def _sources(root: Path) -> tuple[dict, str]:
    files, symbols, incomplete = [], [], False
    fingerprint = hashlib.sha256(b"automoto-native-v20-sources\0")
    for relative, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        if not relative.lower().endswith(SOURCE_SUFFIXES):
            continue
        if len(files) >= MAX_SOURCES:
            incomplete = True
            continue
        record = index._source(root, relative)
        if not record:
            incomplete = True
            continue
        src, sha, size = record
        functions = DECL.findall(src[:30000])[:12]
        includes = INCLUDE.findall(src[:30000])[:15]
        language = "C++" if relative.lower().endswith((".cpp", ".cc", ".cxx",
                                                       ".hpp", ".hh", ".hxx")) else "C"
        files.append({"path": relative, "sha256": sha, "bytes": size,
                      "language": language, "functions": functions,
                      "includes": includes})
        symbols.extend({"path": relative, "name": f} for f in functions[:8])
        fingerprint.update(relative.encode("utf-8") + b"\0" + sha.encode("ascii"))
    return {"files": files, "symbols": symbols[:80], "incomplete": incomplete}, fingerprint.hexdigest()


def _tools(root: Path) -> tuple[list[dict], list[dict], str]:
    tools = []
    debugger = []
    digest = hashlib.sha256(b"automoto-native-v20-tools\0")
    for name in (*TOOLS, *DEBUGGERS):
        candidate = shutil.which(name)
        if not candidate:
            entry = {"name": name, "status": "unavailable"}
        elif Path(candidate).suffix.lower() in (".cmd", ".bat", ".ps1"):
            entry = {"name": name, "status": "shell_wrapper_blocked"}
        else:
            try:
                entry = {"name": name, "status": "installed_not_executed",
                         **adapters._fingerprint(str(Path(candidate).absolute()), root),
                         "invocation": str(Path(candidate).absolute())}
            except HTTPException:
                entry = {"name": name, "status": "not_approved"}
        (debugger if name in DEBUGGERS else tools).append(entry)
        digest.update(name.encode("ascii") + b"\0" +
                      entry["status"].encode("ascii") + b"\0" +
                      entry.get("sha256", "").encode("ascii") + b"\0" +
                      entry.get("invocation", "").encode("utf-8"))
    return tools, debugger, digest.hexdigest()


def _inspect(root: Path) -> dict:
    manifest, m_sha = _manifests(root)
    source, s_sha = _sources(root)
    if source["incomplete"] or not source["files"]:
        manifest["warnings"].append("Native source inventory is incomplete or empty.")
        manifest["safe_to_offer_runs"] = False
    tools, debugger, t_sha = _tools(root)
    return {"schema": VERSION, **manifest, "manifest_sha256": m_sha,
            "source_sha256": s_sha, "toolchain_sha256": t_sha,
            "files": source["files"], "symbols": source["symbols"],
            "source_scan_incomplete": source["incomplete"],
            "toolchains": tools, "debug_adapters": debugger,
            "clangd": "Use existing separately approved C/C++ LSP; no server started.",
            "dap": "Use existing separately approved native debugger adapter; no attach started.",
            "project_trusted": studio._trusted(root, studio._load()),
            "project_code_executed": False,
            "download_or_install_performed": False, "deployment_started": False,
            "central_agent_studio": "developer",
            "agent_deployment_handoff_required": True}


def _command(body: RunIn, tool: dict) -> list[str]:
    if body.task == "cmake_version" and body.tool == "cmake":
        return [tool["executable"], "--version"]
    if body.task == "ctest_version" and body.tool == "ctest":
        return [tool["executable"], "--version"]
    if body.task == "clangd_version" and body.tool == "clangd":
        return [tool["executable"], "--version"]
    if body.task == "compiler_version" and body.tool in ("gcc", "g++", "clang", "clang++", "cl"):
        return [tool["executable"], "/?" if body.tool == "cl" else "--version"]
    if body.tool != "cmake":
        raise HTTPException(422, "Build/test/sanitiser requires the approved CMake tool.")
    if body.task not in ("build", "test", "sanitize"):
        raise HTTPException(422, "Unsupported native task.")
    return []


def _sanitizer_compilers(summary: dict) -> tuple[dict, dict] | None:
    lookup = {x["name"]: x for x in summary["toolchains"]
              if x["status"] == "installed_not_executed"}
    for c, cpp in (("clang", "clang++"), ("gcc", "g++")):
        if c in lookup and cpp in lookup and os.name != "nt":
            try:
                for driver in (lookup[c], lookup[cpp]):
                    if Path(driver["invocation"]).resolve(strict=True) != Path(driver["executable"]):
                        raise HTTPException(409, "Native compiler invocation no longer matches the verified binary.")
            except (OSError, ValueError) as exc:
                raise HTTPException(409, "Native compiler invocation path is unavailable.") from exc
            return lookup[c], lookup[cpp]
    return None


def _environment(root: Path) -> dict:
    env = adapters._environment(root)
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = "2"
    env["CTEST_PARALLEL_LEVEL"] = "1"
    env["ASAN_OPTIONS"] = "detect_leaks=0:halt_on_error=1"
    env["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    if os.name == "nt":
        # MSVC requires Visual Studio SDK paths. Only admit existing absolute
        # directories outside every approved workspace; never raw strings.
        for key in ("LIB", "LIBPATH", "INCLUDE"):
            allowed = []
            for token in os.environ.get(key, "").split(os.pathsep)[:40]:
                if not token or len(token) > 600:
                    continue
                try:
                    p = Path(token).resolve(strict=True)
                    if p.is_dir() and not adapters._disallowed_workspace_executable(p, root):
                        allowed.append(str(p))
                except (OSError, ValueError):
                    pass
            if allowed:
                env[key] = os.pathsep.join(allowed)
    return env


def _execute(root: Path, command: list[str], env: dict, timeout: int = TIMEOUT) -> dict:
    options = {"cwd": root, "shell": False, "env": env, "stdin": subprocess.DEVNULL,
               "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        options["start_new_session"] = True
    start = time.monotonic()
    try:
        proc = subprocess.Popen(command, **options)
    except OSError as exc:
        raise HTTPException(502, "Approved native tool could not start.") from exc
    output, overflow, timed_out = bytearray(), threading.Event(), False

    def drain():
        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                left = MAX_OUTPUT - len(output)
                output.extend(chunk[:max(left, 0)])
                if len(chunk) > left:
                    overflow.set()
                    adapters._terminate(proc)
                    break
        except (OSError, ValueError):
            pass

    worker = threading.Thread(target=drain, daemon=True)
    worker.start()
    try:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            adapters._terminate(proc)
        worker.join(timeout=1)
    finally:
        adapters._terminate(proc)
        if proc.stdout:
            proc.stdout.close()
    return {"status": "output_limit" if overflow.is_set() else
                      "timeout" if timed_out else
                      "completed" if proc.returncode == 0 else "nonzero_exit",
            "exit_code": proc.returncode,
            "output": output.decode("utf-8", errors="replace"),
            "elapsed_ms": int((time.monotonic() - start) * 1000),
            "timed_out": timed_out, "output_truncated": overflow.is_set()}


def _diagnostics(root: Path, message: str) -> list[dict]:
    issues = []
    for match in ERROR.finditer(message[:MAX_OUTPUT]):
        if len(issues) >= 30:
            break
        path, line, col, severity, text = match.groups()
        relative = None
        try:
            file = (Path(path) if Path(path).is_absolute() else root / path).resolve()
            if file.is_relative_to(root) and file.is_file():
                relative = file.relative_to(root).as_posix()
        except (OSError, ValueError):
            pass
        issues.append({"path": relative, "line": int(line), "column": int(col),
                       "severity": severity, "message": text[:300]})
    return issues


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
        raise HTTPException(429, "A native project task is already running.")
    try:
        before = _inspect(root)
        if (before["manifest_sha256"] != body.expected_manifest_sha256
                or before["source_sha256"] != body.expected_source_sha256
                or before["toolchain_sha256"] != body.expected_toolchain_sha256):
            raise HTTPException(409, "Native project manifests, source or tools changed since approval.")
        binary = next((x for x in before["toolchains"] if x["name"] == body.tool), None)
        if (not binary or binary["status"] != "installed_not_executed"
                or binary["executable"] != body.expected_executable
                or binary["sha256"] != body.expected_sha256):
            raise HTTPException(409, "Native executable differs from the approved fingerprint.")
        command = _command(body, binary)
        if body.task in ("build", "test", "sanitize"):
            if not before["safe_to_offer_runs"]:
                raise HTTPException(409, "CMake workspace requires manual review before execution.")
            ctest = next((x for x in before["toolchains"]
                          if x["name"] == "ctest" and x["status"] == "installed_not_executed"), None)
            if body.task != "build" and not ctest:
                raise HTTPException(409, "A verified installed CTest tool is required.")
        else:
            ctest = None
        compilers = _sanitizer_compilers(before) if body.task == "sanitize" else None
        if body.task == "sanitize" and compilers is None:
            raise HTTPException(409, "Address/undefined sanitisers require local Clang or GCC on a supported POSIX host.")
        after = _inspect(root)
        if (after["manifest_sha256"] != body.expected_manifest_sha256
                or after["source_sha256"] != body.expected_source_sha256
                or after["toolchain_sha256"] != body.expected_toolchain_sha256):
            raise HTTPException(409, "Native inputs changed while preparing the approved task.")
        adapters._trusted(root)
        env = _environment(root)
        steps = []
        with tempfile.TemporaryDirectory(prefix="automoto-native20-") as temporary:
            folder = Path(temporary) / "build"
            if command:
                steps.append(("version", command))
            else:
                configure = [binary["executable"], "-S", str(root), "-B", str(folder),
                             "-DCMAKE_BUILD_TYPE=Debug", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"]
                if compilers:
                    c, cpp = compilers
                    configure += ["-DCMAKE_C_COMPILER=" + c["invocation"],
                                  "-DCMAKE_CXX_COMPILER=" + cpp["invocation"]]
                    flags = "-fsanitize=address,undefined -fno-omit-frame-pointer -g"
                    configure += ["-DCMAKE_C_FLAGS=" + flags, "-DCMAKE_CXX_FLAGS=" + flags,
                                  "-DCMAKE_EXE_LINKER_FLAGS=-fsanitize=address,undefined"]
                steps.append(("configure", configure))
                steps.append(("build", [binary["executable"], "--build", str(folder),
                                        "--config", "Debug", "--parallel", "2"]))
                if ctest:
                    steps.append(("test", [ctest["executable"], "--test-dir", str(folder),
                                            "-C", "Debug", "--output-on-failure",
                                            "--timeout", "20"]))
            elapsed = 0
            stage_results = []
            for step, argv in steps:
                # CTest and compiler tool identities are pinned in the full
                # toolchain snapshot. Recheck immediately before each stage.
                newest = _inspect(root)
                if (newest["manifest_sha256"] != body.expected_manifest_sha256
                        or newest["source_sha256"] != body.expected_source_sha256
                        or newest["toolchain_sha256"] != body.expected_toolchain_sha256):
                    raise HTTPException(409, "Native workspace/tools changed between execution stages.")
                adapters._trusted(root)
                result = _execute(root, argv, env)
                elapsed += result["elapsed_ms"]
                stage_results.append({"stage": step, **result})
                if result["status"] != "completed" or elapsed > TIMEOUT * 1000:
                    break
        combined = "\n".join("## " + x["stage"] + "\n" + x["output"]
                             for x in stage_results)
        failed = next((x for x in stage_results if x["status"] != "completed"), None)
        return {"task": body.task, "tool": body.tool,
                "status": failed["status"] if failed else "completed",
                "stages": [{"stage": x["stage"], "status": x["status"],
                            "exit_code": x["exit_code"]} for x in stage_results],
                "output": combined[:MAX_OUTPUT],
                "elapsed_ms": elapsed,
                "diagnostics": _diagnostics(root, combined),
                "sanitizer_detected": bool(SANITIZER.search(combined)),
                "sanitizer_evidence": [line[:300] for line in combined.splitlines()
                                       if SANITIZER.search(line)][:12],
                "manifest_sha256": body.expected_manifest_sha256,
                "source_sha256": body.expected_source_sha256,
                "temporary_build_deleted": True, "source_files_unchanged": "not_verified",
                "external_process_unsandboxed": True, "network_prevented_by_os": False,
                "package_installation_performed_by_app": False,
                "central_agent_studio": "developer",
                "agent_handoff_created": False, "agent_deployment_approved": False,
                "deployment_started": False}
    finally:
        LOCK.release()
