"""V32: inert Fortran, COBOL, Ada, Pascal, Assembly and Visual Basic evidence.

Compilers are not sandboxed. Only a copied, canonical, SHA-checked fixture may
be compiled following trusted-project, exact toolchain and per-run consent.
No produced executable is run, published, or installed.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import threading
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_adapters as adapters
from automoto import developer_index as index
from automoto import developer_jvm as jvm
from automoto import developer_native as native
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/legacy", tags=["developer-legacy"])
LOCK = threading.Lock()
VERSION = "1.0.0"
MAX_FILES = 150
MAX_SOURCE = 192 * 1024
MAX_MANIFEST = 256 * 1024
MAX_TOTAL = 8 * 1024 * 1024
TOOLS = ("gfortran", "cobc", "gnatmake", "fpc", "nasm", "vbnc")
SUFFIXES = {
    ".f90": "fortran", ".f95": "fortran", ".f03": "fortran",
    ".f08": "fortran", ".f": "fortran", ".for": "fortran",
    ".cob": "cobol", ".cbl": "cobol", ".cpy": "cobol",
    ".adb": "ada", ".ads": "ada",
    ".pas": "pascal", ".pp": "pascal", ".dpr": "pascal", ".dpk": "pascal",
    ".asm": "assembly", ".s": "assembly",
    ".vb": "visual_basic", ".vbs": "vbscript",
}
MANIFESTS = frozenset({"fpm.toml", "alire.toml", "alire.lock", "Makefile", "makefile",
                       "CMakeLists.txt", "packages.config"})
FIXTURES = {
    "fortran_compile": ("gfortran", "test/v32_fixture.f90", "fortran"),
    "cobol_compile": ("cobc", "test/v32_fixture.cob", "cobol"),
    "ada_compile": ("gnatmake", "test/v32_fixture.adb", "ada"),
    "pascal_compile": ("fpc", "test/v32_fixture.pas", "pascal"),
    "assembly_compile": ("nasm", "test/v32_fixture.asm", "assembly"),
}
SYMBOLS = {
    "fortran": re.compile(r"(?im)^\s*(?:program|module|subroutine|function)\s+([a-z]\w{0,60})"),
    "cobol": re.compile(r"(?im)^\s*(?:PROGRAM-ID\.|SECTION\.)\s*([a-z0-9_-]{1,60})"),
    "ada": re.compile(r"(?im)^\s*(?:procedure|function|package(?:\s+body)?)\s+([a-z]\w{0,60})"),
    "pascal": re.compile(r"(?im)^\s*(?:program|unit|procedure|function)\s+([a-z]\w{0,60})"),
    "assembly": re.compile(r"(?im)^\s*(?:global|section)\s+([.\w]{1,60})"),
    "visual_basic": re.compile(r"(?im)^\s*(?:public|private|friend)?\s*(?:sub|function|class|module)\s+([a-z]\w{0,60})"),
    "vbscript": re.compile(r"(?im)^\s*(?:sub|function|class)\s+([a-z]\w{0,60})"),
}
RISKS = (
    ("external command or process", re.compile(r"(?i)\b(?:system|execute_command_line|CALL\s+SYSTEM|Shell|CreateObject|WScript\.Shell|spawn|exec)\b")),
    ("file or dynamic module access", re.compile(r"(?i)\b(?:open|loadlibrary|dllimport|CreateFile|fopen|pragma\s+link)\b")),
    ("network or remote operation", re.compile(r"(?i)\b(?:socket|httpclient|XMLHTTP|WinHttp|curl|wget)\b")),
)


class CompileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    task: Literal["fortran_compile", "cobol_compile", "ada_compile",
                  "pascal_compile", "assembly_compile"]
    tool: Literal["gfortran", "cobc", "gnatmake", "fpc", "nasm"]
    expected_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_toolchain_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_compiler_and_network_risk: Literal[True]


def _kind(name: str) -> tuple[str | None, bool]:
    leaf = name.rsplit("/", 1)[-1]
    manifest = leaf in MANIFESTS or leaf.endswith((".gpr", ".lpi", ".lpr", ".vbproj"))
    language = SUFFIXES.get(Path(leaf).suffix.lower())
    if language and Path(leaf).suffix == ".s":
        # Assembly dialect/architecture is ambiguous; retain explicit uncertainty.
        language = "assembly"
    return language, manifest


def _inventory(root: Path) -> tuple[list[dict], dict, str, bool]:
    files, manifests, total, incomplete = [], {}, 0, False
    digest = hashlib.sha256(b"automoto-v32-legacy-inventory\0")
    for name, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        language, manifest = _kind(name)
        if not language and not manifest:
            continue
        if len(files) + len(manifests) >= MAX_FILES:
            incomplete = True
            break
        content, sha, size = jvm._read(root, name, MAX_MANIFEST if manifest else MAX_SOURCE)
        total += size
        if total > MAX_TOTAL:
            incomplete = True
            break
        digest.update(name.encode() + b"\0" + sha.encode() + b"\0")
        if manifest:
            manifests[name] = {"path": name, "sha256": sha, "bytes": size,
                               "evaluated": False, "dependencies_resolved": False}
        else:
            files.append({
                "path": name, "language": language, "sha256": sha, "bytes": size,
                "symbols": SYMBOLS[language].findall(content[:60000])[:30],
                "risk_signals": [
                    {"kind": label, "line": content[:m.start()].count("\n") + 1}
                    for label, pattern in RISKS
                    if (m := pattern.search(content[:60000]))
                ],
                "canonical_fixture": any(name == f[1] and language == f[2]
                                         for f in FIXTURES.values()),
                "executed": False,
                "dialect_verified": False,
            })
    # Known project control files may be omitted by the walker when symlinked.
    for name in [*MANIFESTS, *(f[1] for f in FIXTURES.values())]:
        target = root / name
        if target.is_symlink() or getattr(target, "is_junction", lambda: False)():
            raise HTTPException(403, "Linked V32 manifest or fixture forbidden.")
    for pattern in ("*.gpr", "*.lpi", "*.lpr", "*.vbproj"):
        for target in root.glob(pattern):
            if target.is_symlink() or getattr(target, "is_junction", lambda: False)():
                raise HTTPException(403, "Linked V32 project file forbidden.")
    return files, manifests, digest.hexdigest(), incomplete


def _tools(root: Path) -> tuple[list[dict], str]:
    entries = []
    digest = hashlib.sha256(b"automoto-v32-legacy-toolchains\0")
    for name in TOOLS:
        binary = shutil.which(name)
        if not binary:
            item = {"name": name, "status": "unavailable"}
        elif Path(binary).suffix.lower() in (".cmd", ".bat", ".ps1"):
            item = {"name": name, "status": "shell_wrapper_blocked"}
        else:
            try:
                item = {"name": name, "status": "installed_not_executed",
                        **adapters._fingerprint(str(Path(binary).absolute()), root)}
            except HTTPException:
                item = {"name": name, "status": "untrusted_executable"}
        digest.update((name + "\0" + item["status"] + "\0" +
                       item.get("executable", "") + "\0" +
                       item.get("sha256", "")).encode())
        entries.append(item)
    return entries, digest.hexdigest()


def _inspect(root: Path) -> dict:
    files, manifests, inventory_sha, incomplete = _inventory(root)
    tools, tool_sha = _tools(root)
    return {
        "schema": VERSION, "files": files, "manifests": manifests,
        "language_counts": {lang: sum(f["language"] == lang for f in files)
                            for lang in ("fortran", "cobol", "ada", "pascal",
                                         "assembly", "visual_basic", "vbscript")},
        "toolchains": tools,
        "inventory_sha256": inventory_sha,
        "toolchain_sha256": tool_sha,
        "scan_incomplete": incomplete,
        "warnings": ["Bounded scan incomplete: compilation denied."] if incomplete else [],
        "project_trusted": studio._trusted(root, studio._load()),
        "source_executed": False, "manifest_evaluated": False,
        "dependencies_resolved": False, "packages_installed": False,
        "network_started": False, "deployment_started": False,
        "central_agent_studio": "developer",
        "agent_deployment_handoff_required": True,
        "limitations": ("Syntax/dialect and architecture are not verified. .s may be GNU assembly; "
                        ".asm may be MASM, NASM or other dialect. .vb may be VB.NET, "
                        "while .vbs is VBScript. No automatic VB compilation, "
                        "COBOL copybooks, Ada Alire/GPR, Pascal Delphi, Fortran fpm "
                        "or make/CMake evaluation. Fixed compilers are not sandboxed."),
    }


def _command(task: str, tool: str, executable: str, snapshot: dict) -> list[str]:
    expected, fixture, language = FIXTURES[task]
    if tool != expected or not any(
        f["path"] == fixture and f["language"] == language and f["canonical_fixture"]
        for f in snapshot["files"]
    ):
        raise HTTPException(409, "Unapproved V32 tool or missing fixture.")
    args = {
        "fortran_compile": ["-c", fixture, "-o", "v32.o"],
        "cobol_compile": ["-c", fixture, "-o", "v32.o"],
        "ada_compile": ["-c", fixture],
        "pascal_compile": ["-Cn", fixture],
        "assembly_compile": ["-f", "elf64", fixture, "-o", "v32.o"],
    }
    return [executable, *args[task]]


def _stage(root: Path, snapshot: dict, task: str, destination: Path) -> None:
    _, path, lang = FIXTURES[task]
    match = next((f for f in snapshot["files"] if f["path"] == path and
                  f["language"] == lang and f["canonical_fixture"]), None)
    if match is None:
        raise HTTPException(409, "V32 fixture missing.")
    target = studio._path(root, path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(target, flags)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != match["bytes"]:
                raise HTTPException(409, "V32 fixture changed.")
            data = handle.read(MAX_SOURCE + 1)
    except OSError as exc:
        raise HTTPException(403, "Cannot safely open fixture.") from exc
    if len(data) > MAX_SOURCE or hashlib.sha256(data).hexdigest() != match["sha256"]:
        raise HTTPException(409, "V32 fixture checksum changed.")
    dest = destination / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def _compile(root: Path, body: CompileIn) -> dict:
    adapters._trusted(root)
    before = _inspect(root)
    if before["scan_incomplete"]:
        raise HTTPException(409, "Incomplete inventory cannot compile.")
    if (before["inventory_sha256"] != body.expected_inventory_sha256 or
            before["toolchain_sha256"] != body.expected_toolchain_sha256):
        raise HTTPException(409, "V32 source or toolchain drift.")
    tool = next((x for x in before["toolchains"] if x["name"] == body.tool and
                 x["status"] == "installed_not_executed"), None)
    if (not tool or tool.get("executable") != body.expected_executable or
            tool.get("sha256") != body.expected_sha256):
        raise HTTPException(409, "V32 compiler fingerprint changed.")
    command = _command(body.task, body.tool, body.expected_executable, before)
    with tempfile.TemporaryDirectory(prefix="automoto-legacy32-") as directory:
        folder = Path(directory)
        staged = folder / "fixture"
        staged.mkdir(mode=0o700)
        _stage(root, before, body.task, staged)
        home = folder / "home"
        home.mkdir(mode=0o700)
        env = adapters._environment(root)
        env.update({"HOME": str(home), "TMPDIR": str(folder),
                    "XDG_CACHE_HOME": str(home / "cache"),
                    "XDG_CONFIG_HOME": str(home / "config"), "CI": "true"})
        after = _inspect(root)
        if (before["inventory_sha256"] != after["inventory_sha256"] or
                before["toolchain_sha256"] != after["toolchain_sha256"]):
            raise HTTPException(409, "V32 inventory changed while staging.")
        adapters._trusted(root)
        result = native._execute(staged, command, env, timeout=90)
        artifacts = [
            {"name": p.relative_to(staged).as_posix(),
             "bytes": p.stat().st_size,
             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in staged.rglob("*")
            if p.is_file() and p.relative_to(staged).as_posix() != FIXTURES[body.task][1]
            and p.stat().st_size <= 8 * 1024 * 1024
        ][:16]
    return {
        "task": body.task, "tool": body.tool,
        "status": result["status"], "exit_code": result["exit_code"],
        "output": result["output"][:native.MAX_OUTPUT],
        "compiler_sha256": tool["sha256"],
        "inventory_sha256": before["inventory_sha256"],
        "generated_artifacts": artifacts,
        "artifacts_deleted_after_compile": True,
        "source_executed_by_studio": False,
        "compiler_invoked": True,
        "unsandboxed_compiler": True,
        "network_isolation": False,
        "original_workspace_integrity_verified": False,
        "deployment_started": False,
        "agent_handoff_created": False,
    }


@router.get("/inspect")
def inspect(request: Request, project: str):
    studio._auth(request)
    return _inspect(studio._project(project))


@router.post("/compile")
def compile_fixture(request: Request, body: CompileIn):
    studio._auth(request)
    if not LOCK.acquire(blocking=False):
        raise HTTPException(429, "Another V32 compile is in progress.")
    try:
        return _compile(studio._project(body.project), body)
    finally:
        LOCK.release()
