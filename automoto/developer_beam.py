"""Developer Studio V30 — inert Elixir/Erlang/Gleam evidence and gated BEAM fixtures.

Inspection never loads mix.exs, rebar.config or source code. External interpreters
are NOT sandboxed: executing approved code can read/modify host files and network.
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
import tomllib
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_adapters as adapters
from automoto import developer_index as index
from automoto import developer_jvm as jvm
from automoto import developer_native as native
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/beam", tags=["developer-beam"])
VERSION = "1.0.0"
LOCK = threading.Lock()
MAX_FILES = 130
MAX_SOURCE = 192 * 1024
MAX_MANIFEST = 512 * 1024
MAX_TOTAL = 8 * 1024 * 1024
TIMEOUT = 95
LANGUAGES = {"elixir", "erlang", "gleam"}
SUFFIX = {".ex": "elixir", ".exs": "elixir", ".erl": "erlang",
          ".hrl": "erlang", ".escript": "erlang", ".gleam": "gleam"}
MANIFESTS = frozenset({
    "mix.exs", "mix.lock", ".formatter.exs", ".credo.exs",
    "rebar.config", "rebar.lock", "rebar.config.script",
    "erlang.mk", "gleam.toml", "manifest.toml", ".tool-versions",
})
TOOLS = ("elixir", "elixirc", "mix", "erl", "erlc", "escript",
         "rebar3", "gleam", "elixir-ls")
VERSION_ARGS = {"elixir": ["--version"], "gleam": ["--version"],
                "erl": ["-version"]}
TASK_TOOLS = {"elixir_test": "elixir", "erlang_test": "escript",
              "gleam_test": "gleam"}
FIXTURES = {
    "elixir_test": "test/v30_fixture.exs",
    "erlang_test": "test/v30_fixture.escript",
    "gleam_test": "src/v30_fixture.gleam",
}
MARKERS = {"elixir_test": "V30_ELIXIR_PASS 42",
           "erlang_test": "V30_ERLANG_PASS 42",
           "gleam_test": "V30_GLEAM_PASS 42"}
SYMBOLS = {
    "elixir": re.compile(r"(?m)^\s*(?:defmodule|defp?|defmacro)\s+([A-Za-z_][\w.!?]{0,79})"),
    "erlang": re.compile(r"(?m)^\s*(?:-module\s*\(|-export\s*\(|([a-z][a-z0-9_]{0,70})\s*\()"),
    "gleam": re.compile(r"(?m)^\s*(?:pub\s+)?(?:fn|type|const)\s+([a-zA-Z_]\w{0,70})"),
}
RISKS = (
    ("subprocess or external call", re.compile(
        r"(?i)\b(?:System\.cmd|Port\.open|:os\.cmd|os:cmd|open_port|erlang:open_port)\b")),
    ("network or dependency activity", re.compile(
        r"(?i)\b(?:HTTPoison|Finch|Req\.get|:httpc|httpc:request|:gen_tcp|gen_tcp:connect|Mix\.Task\.run)\b")),
    ("dynamic code or build hook", re.compile(
        r"(?i)\b(?:Code\.eval|Code\.require_file|eval_string|apply|@external|on_load)\b")),
)
ELIXIR_DEP = re.compile(r'\{\s*:([a-z][a-z0-9_]{0,60})\s*,\s*"([~><= 0-9A-Za-z_.-]{1,70})"')
ERLANG_DEP = re.compile(r'\{\s*([a-z][a-z0-9_]{0,60})\s*,\s*"([0-9A-Za-z_.-]{1,70})"')
GLEAM_DEP = re.compile(r'(?m)^\s*([a-z][a-z0-9_]{0,60})\s*=\s*"([^"\n]{1,80})"')

class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    task: Literal["version", "elixir_test", "erlang_test", "gleam_test"]
    tool: Literal["elixir", "erl", "escript", "gleam"]
    expected_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_toolchain_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_beam_and_network_risk: Literal[True]

def _kind(path: str) -> tuple[str | None, bool]:
    leaf = path.rsplit("/", 1)[-1]
    manifest = path in MANIFESTS
    lang = SUFFIX.get(Path(leaf).suffix.lower())
    if manifest:
        lang = None
    return lang, manifest

def _inventory(root: Path) -> tuple[list[dict], dict, str, bool]:
    files, manifests, total, incomplete = [], {}, 0, False
    digest = hashlib.sha256(b"automoto-beam-v30-inventory\0")
    for name, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        lang, manifest = _kind(name)
        if not lang and not manifest:
            continue
        if len(files) + len(manifests) >= MAX_FILES:
            incomplete = True
            break
        text, sha, size = jvm._read(root, name, MAX_MANIFEST if manifest else MAX_SOURCE)
        total += size
        if total > MAX_TOTAL:
            incomplete = True
            break
        digest.update(name.encode() + b"\0" + sha.encode() + b"\0")
        if manifest:
            manifests[name] = {"path": name, "sha256": sha, "bytes": size,
                               "evaluated": False, "dependencies_resolved": False}
        else:
            signals = [
                {"kind": label, "line": text[:match.start()].count("\n") + 1}
                for label, pattern in RISKS
                if (match := pattern.search(text[:60000]))
            ]
            if lang == "erlang":
                symbols = re.findall(r"(?m)^\s*([a-z][a-z0-9_]{0,70})\s*\(", text[:60000])[:24]
            else:
                symbols = SYMBOLS[lang].findall(text[:60000])[:24]
            files.append({
                "path": name, "language": lang, "sha256": sha,
                "bytes": size, "symbols": symbols,
                "risk_signals": signals,
                "canonical_fixture": FIXTURES.get(lang + "_test") == name,
                "source_executed": False,
            })
    # A symlink may be omitted by the walker. Canonical sources and build
    # controls must not silently disappear into a seemingly complete inventory.
    for name in [*MANIFESTS, *FIXTURES.values()]:
        entry = root / name
        if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
            raise HTTPException(403, "Linked BEAM manifest or canonical fixture is forbidden.")
    return files, manifests, digest.hexdigest(), incomplete

def _declared_packages(root: Path, manifests: dict) -> dict:
    coords = {"elixir": [], "erlang": [], "gleam": []}
    for name in manifests:
        source = jvm._read(root, name, MAX_MANIFEST)[0]
        if name == "mix.exs":
            coords["elixir"] = [":".join(item) for item in ELIXIR_DEP.findall(source)[:55]]
        elif name == "rebar.config":
            coords["erlang"] = [":".join(item) for item in ERLANG_DEP.findall(source)[:55]]
        elif name == "gleam.toml":
            # We cannot trust a TOML parse as installed package evidence.
            coords["gleam"] = GLEAM_DEP.findall(source)[:55]
    return {"coordinates": coords, "parsed_only": True,
            "manifests_evaluated": False, "dependencies_resolved": False,
            "installation_started": False, "network_started": False}

def _tools(root: Path) -> tuple[list[dict], str]:
    tools, digest = [], hashlib.sha256(b"automoto-beam-v30-tools\0")
    for name in TOOLS:
        location = shutil.which(name)
        if not location:
            info = {"name": name, "status": "unavailable"}
        elif Path(location).suffix.lower() in (".bat", ".cmd", ".ps1"):
            info = {"name": name, "status": "shell_wrapper_blocked"}
        else:
            try:
                info = {"name": name, "status": "installed_not_executed",
                        **adapters._fingerprint(str(Path(location).absolute()), root)}
            except HTTPException:
                info = {"name": name, "status": "untrusted_executable"}
        digest.update((name + "\0" + info["status"] + "\0" +
                       info.get("executable", "") + "\0" +
                       info.get("sha256", "")).encode())
        tools.append(info)
    return tools, digest.hexdigest()

def _inspect(root: Path) -> dict:
    files, manifests, inv_sha, incomplete = _inventory(root)
    binaries, tool_sha = _tools(root)
    return {
        "schema": VERSION, "files": files, "manifests": manifests,
        "packages": _declared_packages(root, manifests),
        "language_counts": {name: sum(f["language"] == name for f in files)
                            for name in ("elixir", "erlang", "gleam")},
        "toolchains": binaries,
        "inventory_sha256": inv_sha, "toolchain_sha256": tool_sha,
        "scan_incomplete": incomplete,
        "warnings": (["Bounded BEAM inventory incomplete; execution refused."]
                     if incomplete else []),
        "project_trusted": studio._trusted(root, studio._load()),
        "source_executed": False, "manifest_evaluated": False,
        "dependency_installed": False, "network_started": False,
        "deployment_started": False, "os_network_isolation": False,
        "central_agent_studio": "developer",
        "agent_deployment_handoff_required": True,
        "platform": sys.platform,
        "limitations": "Macros, Mix/Rebar build hooks, Gleam compilation and BEAM code may execute or fetch dependencies during approved external tasks. Source inspection is inert.",
    }

def _gleam_prerequisites(root: Path, snapshot: dict) -> None:
    if "gleam.toml" not in snapshot["manifests"]:
        raise HTTPException(409, "Gleam fixture requires reviewed gleam.toml.")
    try:
        raw = jvm._read(root, "gleam.toml", MAX_MANIFEST)[0]
        metadata = tomllib.loads(raw)
    except (OSError, ValueError, UnicodeError) as exc:
        raise HTTPException(422, "Invalid Gleam TOML manifest.") from exc
    if not isinstance(metadata, dict):
        raise HTTPException(422, "Invalid Gleam project definition.")
    if (metadata.get("name") != "v30_fixture" or
            metadata.get("target", "erlang") != "erlang" or
            set(metadata) - {"name", "version", "target", "dependencies", "dev-dependencies"} or
            not isinstance(metadata.get("version"), str) or
            metadata.get("dependencies", {}) != {} or
            metadata.get("dev-dependencies", {}) != {}):
        raise HTTPException(409, "Gleam execution requires an isolated, dependency-free v30_fixture project.")
    if any(f["language"] == "gleam" and f["path"] != FIXTURES["gleam_test"]
           for f in snapshot["files"]):
        raise HTTPException(409, "Only the fixed Gleam fixture source may run.")

def _stage(root: Path, snapshot: dict, stage: Path) -> None:
    total = 0
    for info in [*snapshot["files"], *snapshot["manifests"].values()]:
        name = info["path"]
        if not name or name.startswith("/") or chr(92) in name or ".." in name.split("/"):
            raise HTTPException(403, "Unsafe relative BEAM input.")
        original = studio._path(root, name)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(original, flags)
            with os.fdopen(fd, "rb") as handle:
                st = os.fstat(handle.fileno())
                if not stat.S_ISREG(st.st_mode) or st.st_size != info["bytes"]:
                    raise HTTPException(409, "BEAM input size/type changed.")
                data = handle.read(st.st_size + 1)
        except OSError as exc:
            raise HTTPException(403, "Cannot read approved regular BEAM file.") from exc
        if hashlib.sha256(data).hexdigest() != info["sha256"]:
            raise HTTPException(409, "BEAM input modified after approval.")
        total += len(data)
        if total > MAX_TOTAL:
            raise HTTPException(413, "BEAM staging limit exceeded.")
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

def _command(body: RunIn, snapshot: dict) -> list[str]:
    exe = body.expected_executable
    if body.task == "version":
        if body.tool not in VERSION_ARGS:
            raise HTTPException(422, "Unsupported installed version operation.")
        return [exe, *VERSION_ARGS[body.tool]]
    if TASK_TOOLS.get(body.task) != body.tool:
        raise HTTPException(422, "Tool/task mismatch.")
    expected = FIXTURES[body.task]
    if not any(entry["path"] == expected and entry["canonical_fixture"]
               for entry in snapshot["files"]):
        raise HTTPException(409, "Missing required SHA-inventoried BEAM fixture.")
    if body.task == "elixir_test":
        return [exe, expected]
    if body.task == "erlang_test":
        return [exe, expected]
    if body.task == "gleam_test":
        return [exe, "run", "--target", "erlang", "--no-print-progress"]
    raise HTTPException(422, "Unapproved BEAM action.")

def _run(root: Path, body: RunIn) -> dict:
    adapters._trusted(root)
    before = _inspect(root)
    if (before["inventory_sha256"] != body.expected_inventory_sha256 or
            before["toolchain_sha256"] != body.expected_toolchain_sha256):
        raise HTTPException(409, "Approved BEAM source/toolchain inventory changed.")
    selected = next((t for t in before["toolchains"]
                     if t["name"] == body.tool and
                     t["status"] == "installed_not_executed"), None)
    if (not selected or selected.get("executable") != body.expected_executable or
            selected.get("sha256") != body.expected_sha256):
        raise HTTPException(409, "Installed BEAM interpreter fingerprint changed.")
    if body.task != "version":
        if before["scan_incomplete"]:
            raise HTTPException(409, "Incomplete BEAM scan cannot execute.")
        if body.task == "gleam_test":
            _gleam_prerequisites(root, before)
    with tempfile.TemporaryDirectory(prefix="automoto-beam30-") as folder:
        tmp = Path(folder)
        stage = tmp / "project"
        stage.mkdir(mode=0o700)
        if body.task != "version":
            _stage(root, before, stage)
        home = tmp / "home"
        home.mkdir(mode=0o700)
        env = adapters._environment(root)
        env.update({
            "HOME": str(home), "TMPDIR": str(tmp),
            "MIX_HOME": str(home / "mix"),
            "HEX_HOME": str(home / "hex"),
            "REBAR_CACHE_DIR": str(home / "rebar"),
            "GLEAM_HOME": str(home / "gleam"),
            "ERL_CRASH_DUMP": str(home / "erl_crash.dump"),
            "CI": "true",
        })
        cmd = _command(body, before)
        after = _inspect(root)
        if (after["inventory_sha256"] != body.expected_inventory_sha256 or
                after["toolchain_sha256"] != body.expected_toolchain_sha256):
            raise HTTPException(409, "BEAM inputs changed while staging.")
        adapters._trusted(root)
        start = time.monotonic()
        output = native._execute(stage, cmd, env, timeout=TIMEOUT)
    marker_ok = body.task == "version" or MARKERS[body.task] in output["output"]
    status = (output["status"] if marker_ok or output["status"] != "completed"
              else "validation_failed")
    return {
        "task": body.task, "tool": body.tool,
        "status": status, "exit_code": output["exit_code"],
        "output": output["output"][:native.MAX_OUTPUT],
        "fixture_marker_matched": marker_ok if body.task != "version" else None,
        "elapsed_ms": int((time.monotonic() - start) * 1000),
        "inventory_sha256": before["inventory_sha256"],
        "tool_sha256": selected["sha256"],
        "temporary_copy_deleted": True, "original_sources_preserved_by_studio": True,
        "external_code_unsandboxed": True, "os_network_isolation": False,
        "package_installer_called_by_studio": False,
        "runtime_network_activity_not_proven_absent": True,
        "deployment_started": False, "agent_handoff_created": False,
        "central_agent_studio": "developer",
    }

@router.get("/inspect")
def inspect(request: Request, project: str):
    studio._auth(request)
    return _inspect(studio._project(project))

@router.post("/run")
def run(request: Request, body: RunIn):
    studio._auth(request)
    if not LOCK.acquire(blocking=False):
        raise HTTPException(429, "A BEAM-language task is already running.")
    try:
        return _run(studio._project(body.project), body)
    finally:
        LOCK.release()
