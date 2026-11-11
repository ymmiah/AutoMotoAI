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
from typing import Literal, Mapping, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_adapters as adapters
from automoto import developer_index as index
from automoto import developer_rust as rust
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
# CMake's Visual Studio generator names. The major version comes from vswhere;
# the string CMake accepts is not taken from installer text.
_VS_GENERATORS = {
    15: "Visual Studio 15 2017",
    16: "Visual Studio 16 2019",
    17: "Visual Studio 17 2022",
    18: "Visual Studio 18 2026",
}
_VS_PLATFORMS = {"x64", "Win32", "ARM64", "ARM"}
_VS_TOOL_X64 = "Microsoft.VisualStudio.Component.VC.Tools.x86.x64"
_VS_TOOL_ARM64 = "Microsoft.VisualStudio.Component.VC.Tools.ARM64"
_VS_WORKLOAD = "Microsoft.VisualStudio.Workload.VCTools"
_VERSION_TEXT = re.compile(r"[0-9]+(?:\.[0-9]+){1,3}")
_COMPILER_MISSING = (
    "This Windows C/C++ build needs a C and C++ compiler. AutoMoto did not "
    "find Visual Studio C++ tools, Ninja with a compiler, or MinGW. Install "
    "Visual Studio Build Tools with the Desktop development with C++ "
    "workload, or install Ninja or MinGW with a C/C++ compiler, then try again."
)
_CMAKE_TOO_OLD = (
    "This Windows C/C++ build found Visual Studio, but the approved CMake "
    "cannot generate projects for that version. Install a newer CMake, or "
    "install Ninja or MinGW with a C/C++ compiler, then try again."
)


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


def _path_has_tool(env: Mapping[str, str], root: Path, names: tuple[str, ...]) -> bool:
    """True when the scrubbed PATH contains one of these tool names."""
    folders = [item for item in (env.get("PATH") or "").split(os.pathsep) if item][:40]
    suffixes = [""]
    for ext in (rust._env_lookup(env, "PATHEXT") or "").split(os.pathsep):
        if ext.startswith(".") and ext not in suffixes and len(ext) <= 8:
            suffixes.append(ext)
    for folder in folders:
        base = Path(folder)
        for name in names:
            candidates = [base / name]
            for ext in suffixes:
                if ext:
                    candidates.append(base / (name + ext))
            for candidate in candidates:
                try:
                    if not candidate.is_file():
                        continue
                    resolved = candidate.resolve(strict=True)
                except (OSError, ValueError):
                    continue
                if not adapters._disallowed_workspace_executable(resolved, root):
                    return True
    return False


def _cmake_platform(env: Mapping[str, str], source: Mapping[str, str]) -> str:
    arch = (rust._env_lookup(env, "PROCESSOR_ARCHITECTURE")
            or rust._env_lookup(source, "PROCESSOR_ARCHITECTURE")
            or "AMD64")
    kind = rust._lib_arch({"PROCESSOR_ARCHITECTURE": arch})
    return {"x64": "x64", "arm64": "ARM64", "x86": "Win32"}.get(kind, "x64")


def _program_dirs(env: Mapping[str, str], source: Mapping[str, str], root: Path) -> list:
    found = []
    for key in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432"):
        for mapping in (env, source):
            folder = rust._approved_directory(rust._env_lookup(mapping, key), root)
            if folder is not None and folder not in found:
                found.append(folder)
    return found


def _locate_vswhere(env: Mapping[str, str], source: Mapping[str, str], root: Path) -> Optional[Path]:
    """vswhere.exe from the scrubbed PATH or a Program Files installer directory."""
    candidates = []
    for folder in (env.get("PATH") or "").split(os.pathsep)[:40]:
        if folder:
            candidates.append(Path(folder) / "vswhere.exe")
    for base in _program_dirs(env, source, root):
        candidates.append(base / "Microsoft Visual Studio" / "Installer" / "vswhere.exe")
    seen = set()
    for candidate in candidates:
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            resolved = candidate.resolve(strict=True)
        except (OSError, ValueError):
            continue
        marker = os.path.normcase(str(resolved))
        if marker in seen:
            continue
        seen.add(marker)
        if (resolved.name.casefold() != "vswhere.exe"
                or resolved.suffix.casefold() in {".cmd", ".bat", ".ps1"}
                or adapters._disallowed_workspace_executable(resolved, root)):
            continue
        return resolved
    return None


def _decode_tool_output(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", "replace")
    return raw.decode("utf-8-sig", "replace")


def _run_vswhere(executable: Path, env: dict, component: str) -> str:
    command = [str(executable), "-products", "*", "-prerelease", "-requires", component,
               "-format", "json", "-utf8", "-sort"]
    try:
        completed = subprocess.run(
            command, shell=False, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    output = _decode_tool_output(completed.stdout[:262144])
    if completed.returncode != 0 and not output.strip():
        return ""
    return output


def _parse_vswhere(text: str) -> list:
    stripped = (text or "").strip()
    if not stripped:
        return []
    try:
        parsed = json.loads(stripped)
    except (ValueError, RecursionError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    found = []
    for item in parsed[:8]:
        if not isinstance(item, dict):
            continue
        version = item.get("installationVersion")
        if not isinstance(version, str) or not _VERSION_TEXT.fullmatch(version):
            continue
        generator = _VS_GENERATORS.get(int(version.split(".", 1)[0]))
        path = item.get("installationPath")
        if generator is None or (path is not None and not isinstance(path, str)):
            continue
        found.append({"major": int(version.split(".", 1)[0]), "generator": generator,
                      "installationPath": path or ""})
    found.sort(key=lambda item: item["major"], reverse=True)
    return found


def _accept_vs_install(path: str, root: Path) -> Optional[Path]:
    """A Visual Studio root outside the workspace that actually contains C++ tools."""
    approved = rust._approved_directory(path, root)
    if approved is None:
        return None
    if "microsoft visual studio" not in [part.casefold() for part in approved.parts]:
        return None
    tools = approved / "VC" / "Tools" / "MSVC"
    auxiliary = approved / "VC" / "Auxiliary" / "Build"
    try:
        if (tools.is_dir() and not tools.is_symlink()) or (
                auxiliary.is_dir() and not auxiliary.is_symlink()):
            return approved
    except OSError:
        return None
    return None


def _component_order(platform: str) -> tuple:
    if platform == "ARM64":
        return (_VS_TOOL_ARM64, _VS_TOOL_X64, _VS_WORKLOAD)
    return (_VS_TOOL_X64, _VS_WORKLOAD)


def _query_vswhere(env: dict, source: Mapping[str, str], root: Path, platform: str) -> list:
    executable = _locate_vswhere(env, source, root)
    if executable is None or platform not in _VS_PLATFORMS:
        return []
    accepted = []
    seen = set()
    for component in _component_order(platform):
        chosen = "x64" if platform == "ARM64" and component != _VS_TOOL_ARM64 else platform
        for item in _parse_vswhere(_run_vswhere(executable, env, component)):
            item["platform"] = chosen
            if _accept_vs_install(item.get("installationPath") or "", root) is None:
                continue
            marker = (item["generator"], chosen, os.path.normcase(item.get("installationPath") or ""))
            if marker in seen:
                continue
            seen.add(marker)
            accepted.append(item)
    return accepted


def _parse_cmake_generators(text: str) -> set:
    names = set()
    started = False
    blanks = 0
    for line in (text or "").splitlines():
        if not started:
            if "generators are available on this platform" in line.casefold():
                started = True
            continue
        if not line.strip():
            blanks += 1
            if blanks >= 2:
                break
            continue
        blanks = 0
        match = re.match(r"^\s*\*?\s*(.+?)\s+=\s+\S", line)
        if match:
            names.add(match.group(1).strip())
    return names


def _supported_generators(cmake: Optional[str], env: dict, root: Path) -> Optional[set]:
    """Generator names this CMake binary reports. None means the list is unknown."""
    if not cmake:
        return None
    try:
        tool = Path(cmake).resolve(strict=True)
    except (OSError, ValueError):
        return None
    if adapters._disallowed_workspace_executable(tool, root):
        return None
    try:
        completed = subprocess.run(
            [str(tool), "--help"], shell=False, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    names = _parse_cmake_generators(_decode_tool_output(completed.stdout[:262144]))
    return names or None


def _compiler_pair(env: Mapping[str, str], root: Path) -> bool:
    gcc = _path_has_tool(env, root, ("gcc", "gcc.exe"))
    gxx = _path_has_tool(env, root, ("g++", "g++.exe"))
    clang = _path_has_tool(env, root, ("clang", "clang.exe"))
    clangxx = _path_has_tool(env, root, ("clang++", "clang++.exe"))
    return (gcc and gxx) or (clang and clangxx)


def _ninja_usable(env: Mapping[str, str], root: Path) -> bool:
    return _path_has_tool(env, root, ("ninja", "ninja.exe")) and _compiler_pair(env, root)


def _mingw_usable(env: Mapping[str, str], root: Path) -> bool:
    return (_path_has_tool(env, root, ("mingw32-make", "mingw32-make.exe"))
            and _path_has_tool(env, root, ("gcc", "gcc.exe"))
            and _path_has_tool(env, root, ("g++", "g++.exe")))


def _generator_allowed(name: str, supported: Optional[set]) -> bool:
    return supported is None or name in supported


def _windows_cmake_plan(env: dict, source: Mapping[str, str], root: Path,
                        cmake: Optional[str]) -> tuple:
    """CMake -G/-A args, or a plain diagnostic when no Windows C/C++ compiler exists.

    NMake, CMake's default on Windows, only works when cl.exe is already on PATH
    (a Developer Command Prompt). A normal Windows session has Visual Studio
    installed but does not put cl.exe on PATH, so configure must name a generator
    vswhere can back. Ninja and MinGW are used only when those tools are present.
    """
    if _path_has_tool(env, root, ("cl", "cl.exe")):
        return [], None
    platform = _cmake_platform(env, source)
    instances = _query_vswhere(env, source, root, platform)
    supported = _supported_generators(cmake, env, root)
    saw_vs = False
    for item in instances:
        item_platform = item.get("platform") or platform
        if item_platform not in _VS_PLATFORMS:
            continue
        if _accept_vs_install(item.get("installationPath") or "", root) is None:
            continue
        if not _generator_allowed(item["generator"], supported):
            saw_vs = True
            continue
        return ["-G", item["generator"], "-A", item_platform], None
    if _generator_allowed("Ninja", supported) and _ninja_usable(env, root):
        return ["-G", "Ninja"], None
    if _generator_allowed("MinGW Makefiles", supported) and _mingw_usable(env, root):
        return ["-G", "MinGW Makefiles"], None
    # A real Visual Studio tree was found, but this CMake has no generator for it.
    if saw_vs:
        return [], _CMAKE_TOO_OLD
    return [], _COMPILER_MISSING


def _environment(root: Path, *, windows: Optional[bool] = None,
                 cmake_executable: Optional[str] = None) -> tuple:
    env = adapters._environment(root)
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = "2"
    env["CTEST_PARALLEL_LEVEL"] = "1"
    env["ASAN_OPTIONS"] = "detect_leaks=0:halt_on_error=1"
    env["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return env, [], None
    # The shared V8 environment drops arbitrary inherited values. CMake,
    # vswhere and MSBuild still need the same non-secret Windows toolchain
    # locators V19 restores for rustc (ProgramFiles, VS/SDK tokens, PATHEXT,
    # LIB/INCLUDE). Secret values stay out of this dictionary.
    rust._copy_windows_locators(env, os.environ, root)
    arguments, problem = _windows_cmake_plan(env, os.environ, root, cmake_executable)
    return env, arguments, problem


def _build_steps(cmake: str, ctest: Optional[str], root: Path, folder: Path,
                 generator_args: list, compilers) -> list:
    """Configure, build and optionally test. VS generators need --config and -C Debug."""
    configure = [cmake, "-S", str(root), "-B", str(folder)]
    configure.extend(generator_args)
    configure.extend(["-DCMAKE_BUILD_TYPE=Debug", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"])
    if compilers:
        c_compiler, cpp_compiler = compilers
        configure += ["-DCMAKE_C_COMPILER=" + c_compiler["invocation"],
                      "-DCMAKE_CXX_COMPILER=" + cpp_compiler["invocation"]]
        flags = "-fsanitize=address,undefined -fno-omit-frame-pointer -g"
        configure += ["-DCMAKE_C_FLAGS=" + flags, "-DCMAKE_CXX_FLAGS=" + flags,
                      "-DCMAKE_EXE_LINKER_FLAGS=-fsanitize=address,undefined"]
    steps = [("configure", configure),
             ("build", [cmake, "--build", str(folder), "--config", "Debug",
                        "--parallel", "2"])]
    if ctest:
        steps.append(("test", [ctest, "--test-dir", str(folder), "-C", "Debug",
                               "--output-on-failure", "--timeout", "20"]))
    return steps


def _compiler_problem_result(body: RunIn, message: str) -> dict:
    return {"task": body.task, "tool": body.tool, "status": "nonzero_exit",
            "stages": [{"stage": "configure", "status": "nonzero_exit", "exit_code": 1}],
            "output": message, "elapsed_ms": 0, "diagnostics": [],
            "sanitizer_detected": False, "sanitizer_evidence": [],
            "manifest_sha256": body.expected_manifest_sha256,
            "source_sha256": body.expected_source_sha256,
            "temporary_build_deleted": True, "source_files_unchanged": "not_verified",
            "external_process_unsandboxed": True, "network_prevented_by_os": False,
            "package_installation_performed_by_app": False,
            "central_agent_studio": "developer",
            "agent_handoff_created": False, "agent_deployment_approved": False,
            "deployment_started": False}


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
        env, generator_args, compiler_problem = _environment(
            root, cmake_executable=binary["executable"] if body.tool == "cmake" else None)
        # Version probes do not need a compiler. Configure/build/test do: return
        # the plain diagnostic instead of CMake's missing-compiler log.
        if compiler_problem and not command:
            return _compiler_problem_result(body, compiler_problem)
        steps = []
        with tempfile.TemporaryDirectory(prefix="automoto-native20-") as temporary:
            folder = Path(temporary) / "build"
            if command:
                steps.append(("version", command))
            else:
                steps.extend(_build_steps(
                    binary["executable"], ctest["executable"] if ctest else None,
                    root, folder, generator_args, compilers))
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
