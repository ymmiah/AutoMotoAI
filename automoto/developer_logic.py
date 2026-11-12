"""Developer Studio V31: inert Haskell, OCaml, Lisp, Scheme and Prolog adapters.

Inspection reads bounded source and manifests only. A separate, SHA-pinned,
trusted, user-approved fixed fixture action may launch an external interpreter.
Those processes are NOT sandboxed and may access the host or network.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import threading
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_adapters as adapters
from automoto import developer_index as index
from automoto import developer_jvm as jvm
from automoto import developer_native as native
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/logic", tags=["developer-logic"])
VERSION = "1.0.0"
LOCK = threading.Lock()
MAX_FILES = 140
MAX_SOURCE = 192 * 1024
MAX_MANIFEST = 512 * 1024
MAX_TOTAL = 8 * 1024 * 1024
TIMEOUT = 90

EXTENSIONS = {
    ".hs": "haskell", ".lhs": "haskell",
    ".ml": "ocaml", ".mli": "ocaml",
    ".lisp": "lisp", ".lsp": "lisp", ".cl": "lisp",
    ".scm": "scheme", ".ss": "scheme",
    ".pl": "prolog",
}
MANIFESTS = frozenset({
    "cabal.project", "cabal.project.freeze", "stack.yaml", "stack.yaml.lock",
    "package.yaml", "dune-project", "dune", "dune-workspace",
    "opam", "project.opam", "project.asd", "pack.pl",
})
TOOLS = ("runghc", "ghc", "cabal", "stack", "ocaml", "dune", "opam",
         "sbcl", "clisp", "guile", "swipl")
FIXTURES = {
    "haskell_test": ("runghc", "test/v31_fixture.hs", "haskell"),
    "ocaml_test": ("ocaml", "test/v31_fixture.ml", "ocaml"),
    "lisp_test": ("sbcl", "test/v31_fixture.lisp", "lisp"),
    "scheme_test": ("guile", "test/v31_fixture.scm", "scheme"),
    "prolog_test": ("swipl", "test/v31_fixture.pl", "prolog"),
}
MARKERS = {
    "haskell_test": "V31_HASKELL_PASS 42",
    "ocaml_test": "V31_OCAML_PASS 42",
    "lisp_test": "V31_LISP_PASS 42",
    "scheme_test": "V31_SCHEME_PASS 42",
    "prolog_test": "V31_PROLOG_PASS 42",
}
DECLARATIONS = {
    "haskell": re.compile(r"(?m)^\s*(?:module|data|newtype|class)\s+([A-Z][\w.']{0,69})|^\s*([a-z_]\w{0,69})\s*::"),
    "ocaml": re.compile(r"(?m)^\s*(?:let(?:\s+rec)?|module|type|val)\s+([A-Za-z_]\w{0,69})"),
    "lisp": re.compile(r"(?im)^\s*\((?:defun|defmacro|defpackage|defclass)\s+([A-Za-z0-9_\-:*+!?]{1,70})"),
    "scheme": re.compile(r"(?im)^\s*\(define(?:-syntax)?\s+\(?([A-Za-z0-9_\-!?+*/<>=]{1,70})"),
    "prolog": re.compile(r"(?m)^\s*([a-z][A-Za-z0-9_]{0,69})\s*(?:\(|:-)"),
}
RISKS = (
    ("external process or file access", re.compile(
        r"(?i)\b(?:System\.Process|readProcess|createProcess|Unix\.system|Sys\.command|run-program|run-shell-command|system|open-input-file|open-output-file|open_file)\b")),
    ("dynamic loading or code evaluation", re.compile(
        r"(?i)\b(?:TemplateHaskell|runQ|Dynlink|load|eval|consult|use_module|ensure_loaded|load_files)\b")),
    ("possible network or dependency operation", re.compile(
        r"(?i)\b(?:Network\.HTTP|Network\.Socket|Cohttp|http-client|socket|pack_install|cabal\s+install|opam\s+install)\b")),
)


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    task: Literal["haskell_test", "ocaml_test", "lisp_test", "scheme_test", "prolog_test"]
    tool: Literal["runghc", "ocaml", "sbcl", "guile", "swipl"]
    expected_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_toolchain_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_execution_and_network_risk: Literal[True]


def _kind(path: str, contents: str | None = None) -> tuple[str | None, bool]:
    leaf = path.rsplit("/", 1)[-1]
    manifest = path in MANIFESTS or leaf.endswith((".cabal", ".opam", ".asd"))
    language = EXTENSIONS.get(Path(leaf).suffix.lower())
    if manifest:
        language = None
    # Perl also uses .pl; do not assert Prolog without a Prolog-specific signal.
    if language == "prolog" and contents is not None:
        if not re.search(r"(?m)^\s*(?::-|[a-z][A-Za-z0-9_]*\s*(?:\([^)]*\))?\s*:-)", contents):
            language = None
    return language, manifest


def _inventory(root: Path) -> tuple[list[dict], dict, str, bool]:
    files, manifests, total, incomplete = [], {}, 0, False
    digest = hashlib.sha256(b"automoto-v31-logic-inventory\0")
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
        contents, sha, size = jvm._read(root, name, MAX_MANIFEST if manifest else MAX_SOURCE)
        total += size
        if total > MAX_TOTAL:
            incomplete = True
            break
        if not manifest:
            language, _ = _kind(name, contents)
            if language is None:
                # Ambiguous Perl/Prolog files remain unknown and are never executed.
                continue
        digest.update(name.encode("utf-8") + b"\0" + sha.encode("ascii") + b"\0")
        if manifest:
            manifests[name] = {
                "path": name, "sha256": sha, "bytes": size,
                "evaluated": False, "dependencies_resolved": False,
            }
        else:
            declarations = DECLARATIONS[language].findall(contents[:60000])[:24]
            symbols = [("".join(found) if isinstance(found, tuple) else found)
                       for found in declarations]
            signals = [
                {"kind": label, "line": contents[:match.start()].count("\n") + 1}
                for label, pattern in RISKS
                if (match := pattern.search(contents[:60000]))
            ]
            files.append({
                "path": name, "language": language, "sha256": sha,
                "bytes": size, "symbols": symbols, "risk_signals": signals,
                "canonical_fixture": any(name == fixture[1] and language == fixture[2]
                                         for fixture in FIXTURES.values()),
                "executed": False,
            })
    # Index walkers can omit links: explicitly reject any canonical control file
    # that might otherwise disappear from the hashed inventory.
    for name in [*MANIFESTS, *(fixture[1] for fixture in FIXTURES.values())]:
        target = root / name
        if target.is_symlink() or getattr(target, "is_junction", lambda: False)():
            raise HTTPException(403, "Linked V31 manifest or fixture is forbidden.")
    for pattern in ("*.cabal", "*.opam", "*.asd"):
        for target in root.glob(pattern):
            if target.is_symlink() or getattr(target, "is_junction", lambda: False)():
                raise HTTPException(403, "Linked V31 project declaration is forbidden.")
    return files, manifests, digest.hexdigest(), incomplete


def _tools(root: Path) -> tuple[list[dict], str]:
    entries = []
    digest = hashlib.sha256(b"automoto-v31-logic-toolchains\0")
    for name in TOOLS:
        binary = shutil.which(name)
        if not binary:
            item = {"name": name, "status": "unavailable"}
        elif Path(binary).suffix.lower() in (".cmd", ".bat", ".ps1"):
            item = {"name": name, "status": "shell_wrapper_blocked"}
        else:
            try:
                item = {
                    "name": name, "status": "installed_not_executed",
                    **adapters._fingerprint(str(Path(binary).absolute()), root),
                }
            except HTTPException:
                item = {"name": name, "status": "untrusted_executable"}
        digest.update((name + "\0" + item["status"] + "\0" +
                       item.get("executable", "") + "\0" +
                       item.get("sha256", "")).encode("utf-8"))
        entries.append(item)
    return entries, digest.hexdigest()


def _inspect(root: Path) -> dict:
    files, manifests, inventory_sha, incomplete = _inventory(root)
    tools, tool_sha = _tools(root)
    return {
        "schema": VERSION,
        "files": files,
        "manifests": manifests,
        "language_counts": {
            lang: sum(file["language"] == lang for file in files)
            for lang in ("haskell", "ocaml", "lisp", "scheme", "prolog")
        },
        "toolchains": tools,
        "inventory_sha256": inventory_sha,
        "toolchain_sha256": tool_sha,
        "scan_incomplete": incomplete,
        "warnings": (["Bounded V31 scan incomplete; all actions denied."]
                     if incomplete else []),
        "project_trusted": studio._trusted(root, studio._load()),
        "source_executed": False,
        "manifest_evaluated": False,
        "dependencies_resolved": False,
        "packages_installed": False,
        "network_started": False,
        "deployment_started": False,
        "os_network_isolation": False,
        "central_agent_studio": "developer",
        "agent_deployment_handoff_required": True,
        "limitations": ("Source declarations are heuristic; .pl may be Perl. "
                        "Cabal/Stack, Dune/Opam, ASDF, Scheme libraries and "
                        "Prolog directives are not evaluated during inspection. "
                        "Approved fixed fixtures are unsandboxed processes."),
        "platform": sys.platform,
    }


def _stage_fixture(root: Path, snapshot: dict, task: str, destination: Path) -> None:
    _, path, language = FIXTURES[task]
    matching = next((f for f in snapshot["files"]
                     if f["path"] == path and f["language"] == language
                     and f["canonical_fixture"]), None)
    if not matching:
        raise HTTPException(409, "Canonical V31 fixture is absent or ambiguous.")
    source = studio._path(root, path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(source, flags)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_size != matching["bytes"]
                    or info.st_size > MAX_SOURCE):
                raise HTTPException(409, "V31 fixture changed size or type.")
            data = stream.read(info.st_size + 1)
    except OSError as exc:
        raise HTTPException(403, "Cannot safely read V31 fixture.") from exc
    if hashlib.sha256(data).hexdigest() != matching["sha256"]:
        raise HTTPException(409, "V31 fixture changed after consent.")
    target = destination / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _command(task: str, tool: str, exe: str, snapshot: dict) -> list[str]:
    expected_tool, fixture, lang = FIXTURES[task]
    if tool != expected_tool:
        raise HTTPException(422, "Tool does not match the fixed V31 task.")
    if not any(f["path"] == fixture and f["language"] == lang and
               f["canonical_fixture"] for f in snapshot["files"]):
        raise HTTPException(409, "Expected SHA-inventoried V31 fixture is missing.")
    args = {
        "haskell_test": [fixture],
        "ocaml_test": ["-noinit", fixture],
        "lisp_test": ["--noinform", "--no-sysinit", "--no-userinit", "--script", fixture],
        "scheme_test": ["--no-auto-compile", "-s", fixture],
        "prolog_test": ["-q", "-f", "none", "-s", fixture, "-g", "main", "-t", "halt"],
    }
    return [exe, *args[task]]


def _run(root: Path, body: RunIn) -> dict:
    adapters._trusted(root)
    before = _inspect(root)
    if before["scan_incomplete"]:
        raise HTTPException(409, "Incomplete V31 inventory cannot execute.")
    if (body.expected_inventory_sha256 != before["inventory_sha256"] or
            body.expected_toolchain_sha256 != before["toolchain_sha256"]):
        raise HTTPException(409, "Approved V31 source/toolchain inventory changed.")
    chosen = next((entry for entry in before["toolchains"]
                   if entry["name"] == body.tool and
                   entry["status"] == "installed_not_executed"), None)
    if (not chosen or chosen.get("executable") != body.expected_executable or
            chosen.get("sha256") != body.expected_sha256):
        raise HTTPException(409, "V31 executable fingerprint has changed.")
    command = _command(body.task, body.tool, body.expected_executable, before)
    with tempfile.TemporaryDirectory(prefix="automoto-logic31-") as directory:
        folder = Path(directory)
        stage = folder / "fixture"
        stage.mkdir(mode=0o700)
        _stage_fixture(root, before, body.task, stage)
        home = folder / "home"
        home.mkdir(mode=0o700)
        env = adapters._environment(root)
        env.update({
            "HOME": str(home), "TMPDIR": str(folder),
            "XDG_CACHE_HOME": str(home / "cache"),
            "XDG_CONFIG_HOME": str(home / "config"),
            "CABAL_DIR": str(home / "cabal"),
            "OPAMROOT": str(home / "opam"),
            "GUILE_AUTO_COMPILE": "0",
            "CI": "true",
        })
        after = _inspect(root)
        if (after["inventory_sha256"] != before["inventory_sha256"] or
                after["toolchain_sha256"] != before["toolchain_sha256"]):
            raise HTTPException(409, "V31 source/toolchain changed while staging.")
        adapters._trusted(root)
        started = time.monotonic()
        output = native._execute(stage, command, env, timeout=TIMEOUT)
    matched = MARKERS[body.task] in output["output"]
    status = output["status"]
    if status == "completed" and not matched:
        status = "validation_failed"
    return {
        "task": body.task, "tool": body.tool,
        "status": status, "exit_code": output["exit_code"],
        "output": output["output"][:native.MAX_OUTPUT],
        "fixture_marker_matched": matched,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "inventory_sha256": before["inventory_sha256"],
        "tool_sha256": chosen["sha256"],
        "temporary_copy_deleted": True,
        "original_sources_modified_by_studio": False,
        "original_workspace_integrity_verified": False,
        "external_code_unsandboxed": True,
        "os_network_isolation": False,
        "package_installer_called_by_studio": False,
        "runtime_network_activity_not_proven_absent": True,
        "deployment_started": False,
        "central_agent_studio": "developer",
        "agent_handoff_created": False,
    }


@router.get("/inspect")
def inspect(request: Request, project: str):
    studio._auth(request)
    return _inspect(studio._project(project))


@router.post("/run")
def run(request: Request, body: RunIn):
    studio._auth(request)
    if not LOCK.acquire(blocking=False):
        raise HTTPException(429, "A V31 fixture task is already running.")
    try:
        return _run(studio._project(body.project), body)
    finally:
        LOCK.release()
