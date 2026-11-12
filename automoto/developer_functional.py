"""Developer Studio V29 — inert Scala, F# and Clojure project evidence.

No manifest evaluation, package installation, compilation or execution during
inspection. Individually approved fixed local scripts are UNSANDBOXED: project
trust, fresh SHA-256-pinned binaries and inputs do not isolate host/network.
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

router = APIRouter(prefix="/api/developer/studio/functional", tags=["developer-functional"])
VERSION = "1.0.0"
LOCK = threading.Lock()
MAX_FILES = 120
MAX_SOURCE = 192 * 1024
MAX_MANIFEST = 512 * 1024
MAX_TOTAL = 8 * 1024 * 1024
TIMEOUT = 75

EXTENSIONS = {".scala": "scala", ".sc": "scala", ".fs": "fsharp",
              ".fsi": "fsharp", ".fsx": "fsharp",
              ".clj": "clojure", ".cljs": "clojure", ".cljc": "clojure"}
MANIFESTS = frozenset({
    "build.sbt", "project/build.properties", "project/plugins.sbt",
    "project/Dependencies.scala", ".scalafmt.conf", "scala-cli.json",
    "deps.edn", "bb.edn", "project.clj", "shadow-cljs.edn",
    "global.json", "Directory.Build.props", "Directory.Packages.props",
    "paket.dependencies", "paket.lock", "NuGet.Config",
})
TOOLS = ("scala", "scalac", "sbt", "scala-cli", "dotnet", "fsharpc",
         "clojure", "clj", "lein", "bb", "clj-kondo")
# Never run sbt/lein/bb metadata requests: they can evaluate project code and
# fetch dependencies. Interpreter versions only when consented.
VERSIONS = {"scala": ["-version"], "dotnet": ["--version"],
            "clojure": ["-h"]}
TASK_TOOLS = {"scala_test": "scala", "fsharp_test": "dotnet",
              "clojure_test": "clojure"}
FIXTURES = {"scala_test": "test/Fixture.scala",
            "fsharp_test": "test/Fixture.fsx",
            "clojure_test": "test/fixture_test.clj"}
MARKERS = {"scala_test": "V29_SCALA_PASS 42",
           "fsharp_test": "V29_FSHARP_PASS 42",
           "clojure_test": "V29_CLOJURE_PASS 42"}
DECLARATIONS = {
    "scala": re.compile(r"(?m)^\\s*(?:object|class|trait|enum|def)\\s+([A-Za-z_]\\w{0,70})"),
    "fsharp": re.compile(r"(?m)^\\s*(?:module|namespace|type|let)\\s+([A-Za-z_]\\w{0,70})"),
    "clojure": re.compile(r"(?m)^\\s*\\((?:ns|defn?|defmacro)\\s+([A-Za-z0-9_.?!*+/-]{1,70})"),
}
RISK = (
    ("subprocess or shell", re.compile(r"(?i)\\b(?:ProcessBuilder|sys\\.process|System\\.Diagnostics\\.Process|clojure\\.java\\.shell|shell/sh)\\b")),
    ("network or dependency resolution", re.compile(r"(?i)\\b(?:http-client|HttpClient|java\\.net|java\\.net\\.URL|curl|wget|add-deps|deps/add-lib|load-string)\\b")),
    ("dynamic loading or compilation", re.compile(r"(?i)\\b(?:eval|load-file|require|macroexpand|#=|CompilerServices|TypeProvider)\\b")),
)

class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    task: Literal["version", "scala_test", "fsharp_test", "clojure_test"]
    tool: Literal["scala", "dotnet", "clojure"]
    expected_inventory_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_toolchain_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_code_and_network_risk: Literal[True]

def _kind(path: str) -> tuple[str | None, bool]:
    leaf = path.rsplit("/", 1)[-1]
    # Do not classify build.sbt as executable Scala source.
    manifest = path in MANIFESTS or ("/" not in path and leaf.endswith(".fsproj"))
    language = EXTENSIONS.get(Path(path).suffix.lower())
    if manifest:
        language = None
    if language == "clojure" and path.endswith(".cljs"):
        # ClojureScript source is inventoried, but never passed to JVM runner.
        pass
    return language, manifest

def _inventory(root: Path) -> tuple[list[dict], dict, str, bool]:
    sources, manifests, count, incomplete = [], {}, 0, False
    digest = hashlib.sha256(b"automoto-v29-functional-inventory\\0")
    for name, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        language, manifest = _kind(name)
        if not language and not manifest:
            continue
        if len(sources) + len(manifests) >= MAX_FILES:
            incomplete = True
            break
        raw, sha, size = jvm._read(root, name, MAX_MANIFEST if manifest else MAX_SOURCE)
        count += size
        if count > MAX_TOTAL:
            incomplete = True
            break
        digest.update(name.encode() + b"\\0" + sha.encode() + b"\\0")
        if manifest:
            manifests[name] = {"path": name, "sha256": sha, "bytes": size,
                               "evaluated": False, "resolved_dependencies": False}
        else:
            signals = [{"kind": label, "line": raw[:m.start()].count("\\n") + 1}
                       for label, pattern in RISK if (m := pattern.search(raw[:60000]))]
            sources.append({
                "path": name, "language": language, "sha256": sha, "bytes": size,
                "symbols": DECLARATIONS[language].findall(raw[:60000])[:24],
                "risk_signals": signals,
                "canonical_fixture": name in FIXTURES.values()
                                     and FIXTURES.get(language + "_test") == name,
                "executed": False,
            })
    # Manifest symlinks that an indexed walk skipped must not silently vanish.
    for name in MANIFESTS:
        path = root / name
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise HTTPException(403, "Linked functional build manifest refused.")
    # A linked root F# project file is a build-control surface too.
    for path in root.glob("*.fsproj"):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise HTTPException(403, "Linked F# project manifest refused.")
    return sources, manifests, digest.hexdigest(), incomplete

def _packages(root: Path, manifests: dict) -> dict:
    # Regex extracts only literal-looking coordinates. It never loads project
    # scripts, evaluates EDN readers, traverses a dependency graph or resolves.
    patterns = {
        "scala": [re.compile(r'(?m)"([A-Za-z0-9_.-]{1,75})"\\s*%{1,2}\\s*"([A-Za-z0-9_.-]{1,75})"')],
        "fsharp": [re.compile(r'(?i)<PackageReference\\s+Include="([A-Za-z0-9_.-]{1,75})"')],
        "clojure": [re.compile(r'(?m)(?:[A-Za-z0-9_.-]{1,60}/[A-Za-z0-9_.-]{1,60})\\s*\\{\\s*:mvn/version\\s*"([0-9A-Za-z_.-]{1,60})"')],
    }
    declared = {k: [] for k in patterns}
    for path in manifests:
        data = jvm._read(root, path, MAX_MANIFEST)[0]
        kind = ("scala" if path.endswith(".sbt") else
                "fsharp" if path.endswith(".fsproj") else
                "clojure" if path in ("deps.edn", "project.clj", "bb.edn") else None)
        if kind:
            for pattern in patterns[kind]:
                declared[kind].extend(str(item)[:150] for item in pattern.findall(data)[:30])
    return {"declared_only": True, "dependencies_resolved": False,
            "manifests_evaluated": False, "installer_started": False,
            "coordinates": {key: sorted(set(value))[:60] for key, value in declared.items()}}

def _tools(root: Path) -> tuple[list[dict], str]:
    entries, digest = [], hashlib.sha256(b"automoto-v29-functional-tools\\0")
    for name in TOOLS:
        location = shutil.which(name)
        if not location:
            item = {"name": name, "status": "unavailable"}
        elif Path(location).suffix.lower() in (".cmd", ".bat", ".ps1"):
            item = {"name": name, "status": "shell_wrapper_blocked"}
        else:
            try:
                item = {"name": name, "status": "installed_not_executed",
                        **adapters._fingerprint(str(Path(location).absolute()), root)}
            except HTTPException:
                item = {"name": name, "status": "untrusted_executable"}
        digest.update((name + "\\0" + item["status"] + "\\0" +
                       item.get("sha256", "") + "\\0" +
                       item.get("executable", "")).encode())
        entries.append(item)
    return entries, digest.hexdigest()

def _inspect(root: Path) -> dict:
    sources, manifests, inventory, incomplete = _inventory(root)
    tools, tools_sha = _tools(root)
    return {
        "schema": VERSION, "files": sources, "manifests": manifests,
        "packages": _packages(root, manifests),
        "language_counts": {k: sum(f["language"] == k for f in sources)
                            for k in ("scala", "fsharp", "clojure")},
        "toolchains": tools, "inventory_sha256": inventory,
        "toolchain_sha256": tools_sha, "scan_incomplete": incomplete,
        "warnings": (["Bounded inventory incomplete: reject local execution."]
                     if incomplete else []),
        "project_trusted": studio._trusted(root, studio._load()),
        "source_executed": False, "build_scripts_evaluated": False,
        "package_installation_started": False, "network_access_started": False,
        "operating_system_sandboxed": False, "deployment_started": False,
        "central_agent_studio": "developer",
        "agent_deployment_handoff_required": True,
        "limitations": "Macros, Scala build.sbt, F# type providers, Clojure readers, plugins and code may execute during external builds. Inspection does not certify dependency resolution, compilation or cross-runtime compatibility.",
        "platform": sys.platform,
    }

def _stage(root: Path, snapshot: dict, destination: Path) -> None:
    total = 0
    entries = snapshot["files"] + list(snapshot["manifests"].values())
    for item in entries:
        relative = item["path"]
        if relative.startswith("/") or "\\\\" in relative or ".." in relative.split("/"):
            raise HTTPException(403, "Unsafe functional stage path.")
        source = studio._path(root, relative)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(source, flags)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size != item["bytes"]:
                    raise HTTPException(409, "Functional file changed type or size.")
                payload = stream.read(item["bytes"] + 1)
        except OSError as exc:
            raise HTTPException(403, "Failed to stage approved regular file.") from exc
        if hashlib.sha256(payload).hexdigest() != item["sha256"]:
            raise HTTPException(409, "SHA-pinned functional input changed.")
        total += len(payload)
        if total > MAX_TOTAL:
            raise HTTPException(413, "Functional project exceeds stage limit.")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

def _command(task: str, tool: str, executable: str, snapshot: dict) -> list[str]:
    if task == "version":
        if tool not in VERSIONS:
            raise HTTPException(422, "Tool version query not available.")
        return [executable, *VERSIONS[tool]]
    if TASK_TOOLS.get(task) != tool:
        raise HTTPException(422, "Wrong tool for fixed functional test.")
    expected = FIXTURES[task]
    source = next((entry for entry in snapshot["files"] if entry["path"] == expected), None)
    if not source or (task == "clojure_test" and source["language"] != "clojure"):
        raise HTTPException(409, "Canonical functional fixture missing.")
    if task == "scala_test":
        return [executable, expected]
    if task == "fsharp_test":
        return [executable, "fsi", "--exec", expected]
    if task == "clojure_test":
        return [executable, expected]
    raise HTTPException(422, "Unsupported fixed action.")

def _run(root: Path, body: RunIn) -> dict:
    adapters._trusted(root)
    before = _inspect(root)
    if (before["inventory_sha256"] != body.expected_inventory_sha256 or
            before["toolchain_sha256"] != body.expected_toolchain_sha256):
        raise HTTPException(409, "Functional project or toolchain changed since consent.")
    item = next((t for t in before["toolchains"] if
                 t["name"] == body.tool and t["status"] == "installed_not_executed"), None)
    if (not item or item.get("sha256") != body.expected_sha256 or
            item.get("executable") != body.expected_executable):
        raise HTTPException(409, "Approved functional tool fingerprint changed.")
    if body.task != "version" and before["scan_incomplete"]:
        raise HTTPException(409, "Incomplete source inventory cannot execute.")
    with tempfile.TemporaryDirectory(prefix="automoto-functional29-") as location:
        tmp = Path(location)
        stage = tmp / "project"
        stage.mkdir(mode=0o700)
        if body.task != "version":
            _stage(root, before, stage)
        home = tmp / "home"
        home.mkdir(mode=0o700)
        env = adapters._environment(root)
        env.update({"HOME": str(home), "TMPDIR": str(tmp),
                    "DOTNET_CLI_HOME": str(home), "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
                    "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "NUGET_PACKAGES": str(home / "nuget"),
                    "COURSIER_MODE": "offline", "CLJ_CONFIG": str(home / "clojure"),
                    "LEIN_OFFLINE": "true", "CI": "true"})
        argv = _command(body.task, body.tool, item["executable"], before)
        current = _inspect(root)
        if (current["inventory_sha256"] != body.expected_inventory_sha256 or
                current["toolchain_sha256"] != body.expected_toolchain_sha256):
            raise HTTPException(409, "Project changed during staging.")
        adapters._trusted(root)
        start = time.monotonic()
        completed = native._execute(stage, argv, env, timeout=TIMEOUT)
    valid = (body.task == "version" or
             completed["status"] == "completed" and
             MARKERS[body.task] in completed["output"])
    return {
        "task": body.task,
        "status": (completed["status"] if valid else
                   "validation_failed" if completed["status"] == "completed" else completed["status"]),
        "exit_code": completed["exit_code"], "output": completed["output"][:native.MAX_OUTPUT],
        "elapsed_ms": int((time.monotonic() - start) * 1000),
        "inventory_sha256": before["inventory_sha256"],
        "tool_sha256": item["sha256"], "fixture_marker_matched": (valid if body.task != "version" else None),
        "temporary_copy_deleted": True, "source_modified_by_studio": False,
        "external_code_unsandboxed": True, "os_network_isolation": False,
        "package_installation_started": False, "deployment_started": False,
        "agent_handoff_created": False, "central_agent_studio": "developer",
    }

@router.get("/inspect")
def inspect(request: Request, project: str):
    studio._auth(request)
    return _inspect(studio._project(project))

@router.post("/run")
def run(request: Request, body: RunIn):
    studio._auth(request)
    if not LOCK.acquire(blocking=False):
        raise HTTPException(429, "A functional tool is already running.")
    try:
        return _run(studio._project(body.project), body)
    finally:
        LOCK.release()
