"""Developer Studio V13: bounded JS/TS project intelligence and opt-in local tasks.

No project program, package script or installation ever starts during inspection.
Task execution requires exact project trust, a matching manifest checksum,
a freshly fingerprinted system executable and separate per-run approval.
External Node/npm/pnpm/yarn are NOT an operating-system sandbox.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_adapters as adapters
from automoto import developer_index as index
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/javascript", tags=["developer-javascript"])
SCHEMA = "1.0.0"
MAX_MANIFEST = 96 * 1024
MAX_RUN_SECONDS = 20.0
MAX_OUTPUT = 64 * 1024
MAX_DIAGNOSTICS = 75
MAX_TEST_FILES = 60
RUN_LOCK = threading.Lock()
SCRIPTS = ("test", "build", "lint", "typecheck")
MANAGERS = ("npm", "pnpm", "yarn")
TOOLS = ("node", "npm", "pnpm", "yarn")
LOCKFILES = {"package-lock.json": "npm", "npm-shrinkwrap.json": "npm",
             "pnpm-lock.yaml": "pnpm", "yarn.lock": "yarn"}
FRAMEWORKS = {
    "Next.js": "next", "React": "react", "Vue": "vue", "Angular": "@angular/core",
    "Svelte": "svelte", "SvelteKit": "@sveltejs/kit", "Nuxt": "nuxt",
    "Vite": "vite", "Astro": "astro", "Express": "express", "NestJS": "@nestjs/core",
    "Vitest": "vitest", "Jest": "jest", "Playwright": "@playwright/test",
}
TEST_NAME = re.compile(r"(?:^|/)[^/]{1,140}\.(?:test|spec)\.(?:[cm]?[jt]s|tsx|jsx)$", re.I)
JS_NAME = re.compile(r"\.(?:[cm]?js|jsx)$", re.I)
TYPE_SCRIPT_FILE = re.compile(r"\.(?:[cm]?ts|tsx)$", re.I)
NODE_VERSION = re.compile(r"\bv(\d+)\.(\d+)\.(\d+)\b")
TSC_DIAGNOSTIC = re.compile(
    r"^(?P<path>.{1,240})\((?P<line>\d{1,7}),(?P<col>\d{1,6})\): "
    r"(?P<severity>error|warning) (?P<code>TS\d+): (?P<message>.{1,300})$", re.I)
FILE_DIAGNOSTIC = re.compile(
    r"^(?P<path>[^:\r\n]{1,240}):(?P<line>\d{1,7}):(?P<col>\d{1,6}): "
    r"(?P<message>.{1,300})$")
SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,120}$")


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)


class RunIn(ProjectIn):
    task: Literal["tool_version", "node_version", "node_check", "node_test", "tsc_check", "script"]
    tool: Literal["node", "npm", "pnpm", "yarn"]
    relative_file: Optional[str] = Field(default=None, max_length=1024)
    script: Optional[Literal["test", "build", "lint", "typecheck"]] = None
    expected_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_execution_and_write_risk: Literal[True]


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate keys in package.json are ambiguous.")
        result[key] = value
    return result


def _manifest(root: Path) -> tuple[dict, str, list[str]]:
    file = studio._path(root, "package.json")
    if not file.is_file():
        raise HTTPException(404, "No package.json exists at this project root.")
    source = index._source(root, "package.json")
    if source is None or source[2] > MAX_MANIFEST:
        raise HTTPException(422, "package.json cannot be read safely within the size limit.")
    try:
        obj = json.loads(source[0], object_pairs_hook=_unique_keys)
    except (ValueError, TypeError, RecursionError) as exc:
        raise HTTPException(422, "package.json is malformed or contains ambiguous keys.") from exc
    if not isinstance(obj, dict):
        raise HTTPException(422, "package.json must contain an object.")
    deps = {}
    for field in ("dependencies", "devDependencies", "peerDependencies"):
        current = obj.get(field, {})
        if not isinstance(current, dict):
            raise HTTPException(422, "Declared dependency maps must be JSON objects.")
        for name, version in list(current.items())[:500]:
            if isinstance(name, str) and isinstance(version, str):
                deps[name] = version[:100]
    scripts = obj.get("scripts", {})
    if not isinstance(scripts, dict):
        raise HTTPException(422, "Declared package scripts must be a JSON object.")
    supported = {}
    for name in SCRIPTS:
        value = scripts.get(name)
        if isinstance(value, str) and 0 < len(value) <= 2048:
            supported[name] = value
    declared = obj.get("packageManager", "")
    if not isinstance(declared, str):
        declared = ""
    manager = declared.split("@", 1)[0] if declared else None
    if manager not in MANAGERS:
        manager = None
    present = []
    for filename, detected in LOCKFILES.items():
        path = studio._path(root, filename)
        if path.is_file():
            found = index._source(root, filename)
            present.append({"file": filename, "manager": detected,
                            "fingerprint": found[1] if found else None})
    installed = False
    modules = root / "node_modules"
    if modules.exists() and modules.is_dir() and not modules.is_symlink():
        installed = True
    packages = sorted(({"name": name, "version_declared": version}
                       for name, version in deps.items()), key=lambda p: p["name"])
    framework = [{"name": name, "declared_package": key, "declared_version": deps[key]}
                 for name, key in FRAMEWORKS.items() if key in deps]
    summary = {"name": str(obj.get("name", ""))[:160],
               "private": obj.get("private") is True,
               "package_manager_declared": declared[:160],
               "manager": manager,
               "engines_node_declared": (obj.get("engines", {}) or {}).get("node")
               if isinstance(obj.get("engines", {}), dict) else None,
               "frameworks": framework,
               "scripts": supported,
               "lockfiles": present,
               "dependencies_count": len(deps),
               "node_modules_directory_present": installed,
               "typescript_declared": "typescript" in deps,
               "tsconfig_present": studio._path(root, "tsconfig.json").is_file(),
               "package_json_sha256": source[1],
               "lockfile_conflict": len({x["manager"] for x in present}) > 1,
               "automatic_install": False, "automatic_execute": False,
               "runtime_version_verified": False,
               "framework_versions_verified": False,
               "package_installation_verified": False,
               "source_files_modified": False}
    return summary, source[1], list(supported)


def _tests(root: Path) -> tuple[list[str], bool]:
    found = []
    truncated = False
    for item, incomplete in index._walk(root):
        if incomplete:
            truncated = True
        if item and TEST_NAME.search(item) and len(found) < MAX_TEST_FILES:
            # Only supported JS Node-test files can be executed directly;
            # TS tests require a configured project toolchain/script.
            found.append(item)
        elif item and TEST_NAME.search(item):
            truncated = True
    return sorted(found), truncated


def _tools(root: Path) -> list[dict]:
    output = []
    for name in TOOLS:
        available = shutil.which(name)
        if not available:
            output.append({"name": name, "status": "unavailable"})
            continue
        # Batch/cmd wrappers can invoke cmd.exe under Windows despite shell=False;
        # refuse these rather than trusting argument quoting or PATH scripts.
        if Path(available).suffix.lower() in (".cmd", ".bat", ".ps1"):
            output.append({"name": name, "status": "shell_wrapper_blocked"})
            continue
        try:
            checked = adapters._fingerprint(str(Path(available).absolute()), root)
            output.append({"name": name, "status": "installed_not_executed",
                           **checked})
        except HTTPException:
            output.append({"name": name, "status": "not_approved"})
    return output


def _run_file(root: Path, relative: str, pattern: re.Pattern) -> str:
    if not pattern.search(relative):
        raise HTTPException(422, "Choose a supported project-local source or test file.")
    file = studio._path(root, relative)
    if not file.is_file() or index._source(root, relative) is None:
        raise HTTPException(403, "Source file is unsafe, missing or too large.")
    return relative


def _tsc_file(root: Path) -> Path:
    # node_modules is excluded from project browsing by design. This
    # explicit read-only SDK location is only permitted for TypeScript's
    # installed compiler entry point, and rejects all symlink ancestors.
    parts = ("node_modules", "typescript", "bin", "tsc")
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise HTTPException(403, "Linked TypeScript compiler requires manual SDK review.")
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise HTTPException(409, "No approved local TypeScript compiler entry point was found.")
    return path


def _command(root: Path, body: RunIn, summary: dict, executable: str) -> list[str]:
    if body.task == "tool_version":
        if body.relative_file or body.script:
            raise HTTPException(422, "Tool version detection does not accept a source or script.")
        return [executable, "--version"]
    if body.task == "node_version":
        if body.tool != "node" or body.script or body.relative_file:
            raise HTTPException(422, "Version detection accepts Node only.")
        return [executable, "--version"]
    if body.task in ("node_check", "node_test"):
        if body.tool != "node" or body.script or not body.relative_file:
            raise HTTPException(422, "Select Node and an exact project-local source file.")
        match = JS_NAME if body.task == "node_check" else TEST_NAME
        relative = _run_file(root, body.relative_file, match)
        if body.task == "node_test" and not JS_NAME.search(relative):
            raise HTTPException(422, "Native Node tests require .test.js/.mjs/.cjs.")
        return [executable, "--check" if body.task == "node_check" else "--test", relative]
    if body.task == "tsc_check":
        if body.tool != "node" or body.script or body.relative_file:
            raise HTTPException(422, "Typechecking requires an approved Node executable.")
        if not summary["tsconfig_present"] or not summary["typescript_declared"]:
            raise HTTPException(409, "TypeScript and a project tsconfig.json must be declared.")
        tsc = _tsc_file(root)
        return [executable, str(tsc), "--noEmit", "--incremental", "false",
                "--project", "tsconfig.json"]
    if body.task == "script":
        if body.tool not in MANAGERS or not body.script or body.relative_file:
            raise HTTPException(422, "Select one project-defined script and its package manager.")
        if body.script not in summary["scripts"]:
            raise HTTPException(409, "Script no longer exists in package.json.")
        if summary["manager"] and summary["manager"] != body.tool:
            raise HTTPException(409, "Selected package manager conflicts with declared packageManager.")
        if body.tool == "npm":
            return [executable, "--ignore-scripts", "--offline", "--no-audit",
                    "--no-fund", "run", body.script]
        return [executable, "run", body.script]
    raise HTTPException(422, "Unsupported task.")


def _run_task(root: Path, record: dict) -> dict:
    """Bounded real subprocess via the V8 approved/rehashing launch boundary."""
    started = time.monotonic()
    proc = adapters._start(root, record, dap=False)
    output = bytearray()
    overflow = threading.Event()
    timeout = False

    def read_bounded():
        try:
            while True:
                part = proc.stdout.read(4096)
                if not part:
                    break
                remaining = MAX_OUTPUT - len(output)
                output.extend(part[:max(0, remaining)])
                if len(part) > remaining:
                    overflow.set()
                    adapters._terminate(proc)
                    break
        except (OSError, ValueError):
            pass

    reader = threading.Thread(target=read_bounded, daemon=True)
    reader.start()
    try:
        try:
            proc.wait(timeout=MAX_RUN_SECONDS)
        except subprocess.TimeoutExpired:
            timeout = True
            adapters._terminate(proc)
        reader.join(timeout=1)
    finally:
        adapters._terminate(proc)
        if proc.stdout:
            proc.stdout.close()
    return {
        "status": "output_limit" if overflow.is_set() else
                  "timeout" if timeout else
                  "completed" if proc.returncode == 0 else "nonzero_exit",
        "exit_code": proc.returncode,
        "elapsed_ms": int((time.monotonic() - started)*1000),
        "output": output.decode("utf-8", errors="replace"),
        "output_truncated": overflow.is_set(), "timed_out": timeout,
        "explicit_approval": True, "execution_mode": "trusted_local_subprocess",
        "platform_sandbox": False, "source_files_unchanged": "not_verified",
        "registry_modified": False,
    }


def _diagnostics(text: str, root: Path) -> list[dict]:
    out = []
    # Output is entirely untrusted; paths cannot be used for navigation unless
    # they independently resolve into the same project.
    for raw in text.splitlines()[:3000]:
        if len(out) >= MAX_DIAGNOSTICS:
            break
        match = TSC_DIAGNOSTIC.match(raw.strip()) or FILE_DIAGNOSTIC.match(raw.strip())
        if not match:
            continue
        path = match.group("path")
        valid = False
        try:
            if not Path(path).is_absolute():
                valid = studio._path(root, path).is_file()
        except (HTTPException, OSError, ValueError):
            pass
        out.append({"severity": (match.groupdict().get("severity") or "error").lower(),
                    "code": match.groupdict().get("code"),
                    "path": path if valid else None, "line": int(match.group("line")),
                    "column": int(match.group("col")),
                    "message": match.group("message")[:300]})
    return out


@router.get("/inspect")
def inspect(request: Request, project: str):
    studio._auth(request)
    root = studio._project(project)
    data, _, _ = _manifest(root)
    files, truncated = _tests(root)
    return {"schema": SCHEMA, **data, "test_files": files,
            "test_search_truncated": truncated,
            "toolchains": _tools(root),
            "project_trusted": studio._trusted(root, studio._load()),
            "project_execution": "explicit_only_unsandboxed"}


@router.post("/run")
def run(request: Request, body: RunIn):
    studio._auth(request)
    root = studio._project(body.project)
    adapters._trusted(root)
    if not RUN_LOCK.acquire(blocking=False):
        raise HTTPException(429, "A JavaScript toolchain run is already active.")
    try:
        summary, sha, _ = _manifest(root)
        if body.expected_manifest_sha256 != sha:
            raise HTTPException(409, "package.json changed since inspection; re-inspect before running.")
        choice = next((x for x in _tools(root) if x["name"] == body.tool), None)
        if not choice or choice["status"] != "installed_not_executed":
            raise HTTPException(409, "The selected system tool is unavailable or not approved.")
        if choice["sha256"] != body.expected_sha256 or choice["executable"] != body.expected_executable:
            raise HTTPException(409, "Tool executable path or SHA-256 changed; re-inspect.")
        command = _command(root, body, summary, choice["executable"])
        # Re-read manifest/trust and binary just before execution, narrowing the
        # approval-to-execution race; not a filesystem or process sandbox.
        fresh = _manifest(root)[1]
        if fresh != sha:
            raise HTTPException(409, "Project manifest changed during task preparation.")
        again = adapters._fingerprint(choice["executable"], root)
        if again["sha256"] != body.expected_sha256 or again["executable"] != body.expected_executable:
            raise HTTPException(409, "System executable changed during task preparation.")
        adapters._trusted(root)
        record = {"id": "js13-" + body.task, "category": "test" if "test" in body.task else "compiler",
                  "executable": choice["executable"], "sha256": choice["sha256"],
                  "args": command[1:], "project_identity": studio._identity(root)}
        # V8 SDK already supplies process-group termination, bounded output,
        # inherited-environment sanitisation and a strict timeout.
        result = _run_task(root, record)
        result["task"] = body.task
        result["tool"] = body.tool
        result["manifest_sha256"] = sha
        result["diagnostics"] = _diagnostics(result["output"], root)
        result["external_process_unsandboxed"] = True
        result["package_installation_performed_by_app"] = False
        result["network_prevented_by_os"] = False
        result["build_script_exited_zero"] = (
            body.task == "script" and body.script == "build" and result["status"] == "completed")
        result["framework_build_verified"] = False  # Real output and framework acceptance are separate.
        version = NODE_VERSION.search(result["output"]) if body.task in ("node_version", "tool_version") and body.tool == "node" else None
        result["node_runtime_version"] = version.group(0) if version else None
        result["reported_tool_version"] = result["output"].strip()[:120] if body.task in ("node_version", "tool_version") and result["status"] == "completed" else None
        return result
    finally:
        RUN_LOCK.release()
