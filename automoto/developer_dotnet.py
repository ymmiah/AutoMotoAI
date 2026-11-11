"""V22 C#/.NET: local-only inspection and consent-gated offline MSBuild/testing.

Inspection never invokes dotnet or loads project MSBuild files. Executable
tasks run in a bounded temporary source COPY with a NuGet configuration that
contains no package sources. MSBuild/test assemblies are not OS/network
sandboxed and may act with the full local user's privileges.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Literal

from defusedxml import ElementTree as SafeXML
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_adapters as adapters
from automoto import developer_index as index
from automoto import developer_native as native
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/dotnet", tags=["developer-dotnet"])
SCHEMA = "1.0.0"
MAX_MANIFEST = 512 * 1024
MAX_FILES = 110
MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_OUTPUT = 96 * 1024
MAX_SECONDS = 130
LOCK = threading.Lock()
PROJECT_FILES = {"global.json", "Directory.Build.props", "Directory.Build.targets",
                 "Directory.Packages.props", "NuGet.Config", "nuget.config",
                 "packages.lock.json", ".editorconfig"}
SOURCE_EXT = (".cs", ".razor", ".cshtml")
TOOLS = ("dotnet", "msbuild", "csharp-ls", "OmniSharp")
DEBUG = ("netcoredbg", "vsdbg")
NAMESPACE = re.compile(r"(?m)^\s*namespace\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*){0,20})")
CLASS = re.compile(r"\b(?:class|struct|record|interface|enum)\s+([A-Za-z_]\w{0,100})")
USING = re.compile(r"(?m)^\s*using\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*){0,20})\s*;")
DIAGNOSTIC = re.compile(r"(?m)^(.{1,320}\.(?:cs|razor|cshtml))\((\d{1,8}),(\d{1,8})\)"
                        r":\s*(error|warning)\s+([A-Z]{2,5}\d{3,6})\s*:\s*(.{1,500})")
FRAMEWORK_PATTERNS = {
    "ASP.NET Core": re.compile(r"Microsoft\.NET\.Sdk\.Web|Microsoft\.AspNetCore|WebApplication\.CreateBuilder"),
    "Blazor": re.compile(r"Microsoft\.NET\.Sdk\.Razor|\.razor\b|Microsoft\.AspNetCore\.Components"),
    "xUnit": re.compile(r"(?i)\bxunit\b|\[Fact\]|\[Theory\]"),
    "NUnit": re.compile(r"(?i)\bnunit\b|\[TestFixture\]|\[Test\]"),
}


class RootIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)


class RunIn(RootIn):
    task: Literal["sdk_version", "list_sdks", "msbuild_version", "restore_offline",
                  "build", "test", "run_smoke"]
    tool: Literal["dotnet"]
    expected_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_toolchain_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_msbuild_and_test_execution: Literal[True]


def _read(root: Path, relative: str, limit: int = MAX_MANIFEST) -> tuple[str, str, int]:
    segments = relative.split("/")
    if any(index._excluded(name, i < len(segments) - 1) for i, name in enumerate(segments)):
        raise HTTPException(403, "Restricted .NET project path.")
    path = studio._path(root, relative)
    if path == root:
        raise HTTPException(422, "A regular project file is required.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as file:
            metadata = os.fstat(file.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
                raise HTTPException(413, ".NET project file exceeds inspection bounds.")
            raw = file.read(limit + 1)
        if len(raw) > limit or b"\0" in raw:
            raise HTTPException(413, ".NET project file is too large or binary.")
        return raw.decode("utf-8-sig"), hashlib.sha256(raw).hexdigest(), len(raw)
    except (OSError, UnicodeError) as exc:
        raise HTTPException(403, "Cannot safely read .NET project file.") from exc


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _csproj(xml: str) -> dict:
    try:
        root = SafeXML.fromstring(xml)
    except (ValueError, SafeXML.ParseError) as exc:
        raise HTTPException(422, "Malformed or unsafe MSBuild project XML.") from exc
    if _local_name(root.tag) != "Project":
        raise HTTPException(422, "Expected an MSBuild Project element.")
    sdk = (root.attrib.get("Sdk") or "")[:100]
    values = {}
    packages = []
    unsafe = []
    for element in root.iter():
        kind = _local_name(element.tag)
        if kind in ("Target", "UsingTask", "Import", "Exec", "ProjectReference"):
            unsafe.append(kind)
        if kind in ("TargetFramework", "TargetFrameworks", "OutputType",
                    "IsTestProject", "GenerateProgramFile", "EnableDefaultCompileItems",
                    "RestoreSources") and element.text and kind not in values:
            values[kind] = element.text.strip()[:160]
        if kind in ("PackageReference", "PackageVersion"):
            name = element.attrib.get("Include") or element.attrib.get("Update") or ""
            if re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", name):
                ver = element.attrib.get("Version") or ""
                packages.append({"name": name, "declared_version": ver[:60]})
        if kind == "Sdk" and element.attrib.get("Name"):
            unsafe.append("non-default SDK reference")
        if kind == "Compile" and element.attrib.get("Include"):
            unsafe.append("explicit Compile includes")
    frameworks = values.get("TargetFrameworks", values.get("TargetFramework", ""))
    framework_list = [x.strip()[:45] for x in frameworks.split(";") if x.strip()][:12]
    if len(frameworks.split(";")) > 12:
        unsafe.append("too many target frameworks")
    if not sdk.startswith("Microsoft.NET.Sdk") or sdk not in (
            "Microsoft.NET.Sdk", "Microsoft.NET.Sdk.Web", "Microsoft.NET.Sdk.Razor"):
        unsafe.append("custom or unknown project SDK")
    if values.get("RestoreSources"):
        unsafe.append("custom package source declaration")
    return {"sdk": sdk, "target_frameworks": framework_list,
            "output_type": values.get("OutputType", "Library"),
            "is_test_project": values.get("IsTestProject", "").casefold() == "true",
            "package_references": packages[:45], "unsafe_constructs": sorted(set(unsafe)),
            "explicit_compile_items": bool(values.get("EnableDefaultCompileItems", "").casefold() == "false")}


def _manifests(root: Path) -> dict:
    files = {}
    projects = []
    issues = []
    truncated = False
    for path, warning in index._walk(root):
        if warning:
            truncated = True
            continue
        name = path.split("/")[-1]
        if path not in PROJECT_FILES and not name.endswith((".csproj", ".sln", ".slnx")):
            continue
        if len(files) >= 45:
            truncated = True
            continue
        text, sha, count = _read(root, path)
        files[path] = {"sha256": sha, "bytes": count}
        if name.endswith(".csproj"):
            info = _csproj(text)
            projects.append({"path": path, **info})
            if info["unsafe_constructs"]:
                issues.append("MSBuild project requires review: " + path)
        if path in ("Directory.Build.props", "Directory.Build.targets", "NuGet.Config",
                    "nuget.config", "Directory.Packages.props"):
            issues.append("Custom global MSBuild/NuGet configuration requires review: " + path)
    for name in PROJECT_FILES:
        candidate = root / name
        if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
            raise HTTPException(403, "Linked .NET build control file forbidden.")
    # Root projects are the only supported executable build target. Multi-project
    # solutions are inspected but not silently executed.
    root_projects = [x for x in projects if "/" not in x["path"]]
    if len(projects) != 1 or len(root_projects) != 1:
        issues.append("Exactly one root C# project is required for approved builds.")
    if "global.json" in files:
        text, _, _ = _read(root, "global.json")
        try:
            parsed = json.loads(text)
        except (ValueError, RecursionError) as exc:
            raise HTTPException(422, "Invalid .NET SDK global.json.") from exc
        sdk = parsed.get("sdk", {}) if isinstance(parsed, dict) else {}
        if not isinstance(sdk, dict):
            raise HTTPException(422, "Invalid global.json SDK declaration.")
        wanted = sdk.get("version")
        if wanted is not None and (not isinstance(wanted, str)
                                   or not re.fullmatch(r"\d{1,3}\.\d{1,3}\.\d{1,5}", wanted)):
            raise HTTPException(422, "Unsupported global.json SDK version format.")
        sdk_request = {"requested_version": wanted, "roll_forward": sdk.get("rollForward")}
    else:
        sdk_request = {"requested_version": None, "roll_forward": None}
    if truncated:
        issues.append("Project manifest scan is incomplete.")
    digest = hashlib.sha256(b"automoto-dotnet-v22-manifests\0")
    for path, meta in sorted(files.items()):
        digest.update(path.encode() + b"\0" + meta["sha256"].encode())
    return {"manifests": files, "projects": projects,
            "primary_project": root_projects[0]["path"] if len(root_projects) == 1 else None,
            "sdk_request": sdk_request, "warnings": issues,
            "manifest_scan_incomplete": truncated,
            "safe_to_offer_builds": bool(root_projects) and not issues,
            "manifest_sha256": digest.hexdigest()}


def _source(root: Path) -> dict:
    files, symbols, hints, total = [], [], set(), 0
    incomplete = False
    digest = hashlib.sha256(b"automoto-dotnet-v22-sources\0")
    for path, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        if not path.lower().endswith(SOURCE_EXT):
            continue
        if len(files) >= MAX_FILES:
            incomplete = True
            continue
        record = index._source(root, path)
        if record is None:
            incomplete = True
            continue
        content, sha, bytes_count = record
        total += bytes_count
        if total > MAX_SOURCE_BYTES:
            incomplete = True
            break
        matches = CLASS.findall(content[:32000])[:16]
        space = NAMESPACE.search(content[:10000])
        imports = USING.findall(content[:30000])[:15]
        found = [name for name, pattern in FRAMEWORK_PATTERNS.items()
                 if pattern.search(content[:32000])]
        if path.endswith(".razor"):
            found.append("Blazor")
        hints.update(found)
        files.append({"path": path, "sha256": sha, "bytes": bytes_count,
                      "namespace": space.group(1) if space else None,
                      "types": matches, "using": imports, "framework_hints": sorted(set(found)),
                      "language": "Razor" if path.endswith((".razor", ".cshtml")) else "C#"})
        symbols.extend({"path": path, "name": t} for t in matches[:5])
        digest.update(path.encode() + b"\0" + sha.encode())
    return {"files": files, "symbols": symbols[:85],
            "source_sha256": digest.hexdigest(), "source_scan_incomplete": incomplete,
            "framework_hints": sorted(hints), "bytes": total}


def _tools(root: Path) -> tuple[list[dict], list[dict], str]:
    values, debug = [], []
    digest = hashlib.sha256(b"automoto-dotnet-v22-tools\0")
    for name in (*TOOLS, *DEBUG):
        candidate = shutil.which(name)
        if not candidate:
            entry = {"name": name, "status": "unavailable"}
        elif Path(candidate).suffix.lower() in (".cmd", ".bat", ".ps1"):
            entry = {"name": name, "status": "shell_wrapper_blocked"}
        else:
            try:
                entry = {"name": name, "status": "installed_not_executed",
                         **adapters._fingerprint(str(Path(candidate).absolute()), root)}
            except HTTPException:
                entry = {"name": name, "status": "not_approved"}
        digest.update(name.encode() + b"\0" + entry["status"].encode() + b"\0" +
                      entry.get("sha256", "").encode() + b"\0" +
                      entry.get("executable", "").encode())
        (debug if name in DEBUG else values).append(entry)
    return values, debug, digest.hexdigest()


def _inspect(root: Path) -> dict:
    manifest = _manifests(root)
    source = _source(root)
    if source["source_scan_incomplete"] or not source["files"]:
        manifest["warnings"].append("C# source scan was incomplete or empty.")
        manifest["safe_to_offer_builds"] = False
    hints = set(source["framework_hints"])
    for project in manifest["projects"]:
        if project["sdk"] == "Microsoft.NET.Sdk.Web":
            hints.add("ASP.NET Core")
        if project["sdk"] == "Microsoft.NET.Sdk.Razor":
            hints.add("Blazor")
        for package in project["package_references"]:
            for label, pattern in FRAMEWORK_PATTERNS.items():
                if pattern.search(package["name"]):
                    hints.add(label)
    tools, debug, fingerprint = _tools(root)
    return {"schema": SCHEMA, **manifest, **source,
            "framework_hints": sorted(hints),
            "toolchains": tools, "debug_adapters": debug,
            "toolchain_sha256": fingerprint,
            "installed_sdk_version": None,
            "sdk_version_note": "Installed SDK version is reported only by a separately consented dotnet --version or --list-sdks command; inspection never runs tools.",
            "msbuild": "dotnet msbuild requires separately approved execution.",
            "nuget": "Offline-only restore with an empty NuGet source list; packages may be read from existing local cache.",
            "lsp": "Use separately approved existing C# language server controls; no LSP started.",
            "dap": "Use separately approved existing .NET debugger controls; no debugger attached.",
            "project_trusted": studio._trusted(root, studio._load()),
            "project_code_executed": False,
            "download_or_install_started": False,
            "deployment_started": False, "central_agent_studio": "developer",
            "agent_deployment_handoff_required": True}


def _copy(root: Path, info: dict, stage: Path) -> None:
    if info["manifest_scan_incomplete"] or info["source_scan_incomplete"]:
        raise HTTPException(409, "Incomplete source or project manifests cannot be staged.")
    paths = sorted(set(info["manifests"]) | {x["path"] for x in info["files"]})
    if len(paths) > MAX_FILES + 45:
        raise HTTPException(413, "Too many .NET project source and manifest files.")
    total = 0
    for relative in paths:
        size = MAX_SOURCE_BYTES if relative not in info["manifests"] else MAX_MANIFEST
        text, sha, count = _read(root, relative, size)
        expected = (info["manifests"].get(relative) or next(
            (x for x in info["files"] if x["path"] == relative), {})).get("sha256")
        if not expected or expected != sha:
            raise HTTPException(409, ".NET source or build files changed during staging.")
        total += count
        if total > MAX_SOURCE_BYTES + MAX_MANIFEST * 45:
            raise HTTPException(413, ".NET staging limit exceeded.")
        dest = stage / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")


def _env(root: Path, temp: Path) -> dict:
    env = adapters._environment(root)
    env.update({"DOTNET_CLI_HOME": str(temp / "dotnet-home"),
                "DOTNET_NOLOGO": "1", "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
                "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
                "DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE": "1",
                "DOTNET_MULTILEVEL_LOOKUP": "0",
                "NUGET_CREDENTIALPROVIDERS_PATH": ""})
    (temp / "dotnet-home").mkdir(mode=0o700, exist_ok=True)
    if os.name == "nt":
        # NuGet.ConfigurationDefaults needs ProgramFiles/ProgramFiles(x86)
        # to locate machine-wide defaults. Excluding these paths causes a
        # Windows-only Path.Combine(path1=null) failure during restore.
        # Admit only existing system directories outside approved workspaces;
        # do not restore arbitrary inherited environment variables.
        for name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData"):
            candidate = os.environ.get(name, "")
            if not candidate or len(candidate) > 600:
                continue
            try:
                folder = Path(candidate).resolve(strict=True)
                if (folder.is_dir() and Path(candidate).is_absolute()
                        and not adapters._disallowed_workspace_executable(folder, root)):
                    env[name] = str(folder)
            except (OSError, ValueError):
                continue
    # The existing cache is a read-through local dependency source, NOT a
    # claim of sandboxed execution or a permanent project cache.
    cached = Path.home() / ".nuget" / "packages"
    if cached.is_dir() and not cached.is_symlink():
        env["NUGET_PACKAGES"] = str(cached)
    else:
        env["NUGET_PACKAGES"] = str(temp / "nuget-packages")
    return env


def _commands(task: str, exe: str, info: dict, stage: Path, temp: Path) -> list[tuple[str, list[str]]]:
    if task == "sdk_version":
        return [("sdk_version", [exe, "--version"])]
    if task == "list_sdks":
        return [("sdks", [exe, "--list-sdks"])]
    if task == "msbuild_version":
        return [("msbuild_version", [exe, "msbuild", "-version", "-nologo"])]
    if not info["safe_to_offer_builds"] or not info["primary_project"]:
        raise HTTPException(409, "Unsupported .NET solution, missing source or unsafe MSBuild project.")
    project = str(stage / info["primary_project"])
    config = temp / "NuGet.Config"
    config.write_text('<?xml version="1.0" encoding="utf-8"?>\n'
                      '<configuration><packageSources><clear /></packageSources>'
                      '<disabledPackageSources /></configuration>\n', encoding="utf-8")
    restore = ("restore", [exe, "restore", project, "--configfile", str(config),
                           "--disable-parallel", "--ignore-failed-sources",
                           "-p:NuGetAudit=false"])
    if task == "restore_offline":
        return [restore]
    build = ("build", [exe, "build", project, "--configuration", "Debug",
                       "--no-restore", "--nologo", "-p:ContinuousIntegrationBuild=true"])
    if task == "build":
        return [restore, build]
    if task == "test":
        primary = next((p for p in info["projects"]
                        if p["path"] == info["primary_project"]), None)
        declared = {p["name"].lower() for p in (primary or {}).get("package_references", [])}
        if (primary is None or not primary["is_test_project"] or
                "microsoft.net.test.sdk" not in declared or
                not ({"xunit", "nunit"} & declared)):
            raise HTTPException(409, "A declared xUnit/NUnit project with Microsoft.NET.Test.Sdk is required.")
        test = ("test", [exe, "test", project, "--configuration", "Debug",
                         "--no-build", "--no-restore", "--logger",
                         "console;verbosity=normal"])
        return [restore, build, test]
    if task == "run_smoke":
        if not any(p["path"] == info["primary_project"] and p["output_type"].casefold() == "exe"
                   for p in info["projects"]):
            raise HTTPException(409, "An explicitly declared runnable C# console project is required.")
        return [restore, build, ("run", [exe, "run", "--project", project,
                                          "--configuration", "Debug", "--no-build",
                                          "--no-restore"])]
    raise HTTPException(422, "Unsupported fixed .NET task.")


def _diagnostics(root: Path, output: str) -> list[dict]:
    findings = []
    for match in DIAGNOSTIC.finditer(output[:MAX_OUTPUT]):
        if len(findings) >= 30:
            break
        file, line, column, severity, code, description = match.groups()
        path = None
        try:
            if not Path(file).is_absolute():
                candidate = studio._path(root, file.replace("\\", "/"))
                if candidate.is_file():
                    path = file.replace("\\", "/")
        except (HTTPException, OSError, ValueError):
            pass
        findings.append({"path": path, "line": int(line), "column": int(column),
                         "severity": severity, "code": code,
                         "message": description[:300]})
    return findings


def _run(root: Path, body: RunIn) -> dict:
    adapters._trusted(root)
    before = _inspect(root)
    for key, supplied in (("manifest_sha256", body.expected_manifest_sha256),
                          ("source_sha256", body.expected_source_sha256),
                          ("toolchain_sha256", body.expected_toolchain_sha256)):
        if before[key] != supplied:
            raise HTTPException(409, ".NET source, project or SDK tooling changed since consent.")
    tool = next((x for x in before["toolchains"] if x["name"] == "dotnet"
                 and x["status"] == "installed_not_executed"), None)
    if (body.tool != "dotnet" or tool is None or
            tool["sha256"] != body.expected_sha256 or
            tool["executable"] != body.expected_executable):
        raise HTTPException(409, "Approved .NET executable identity changed.")
    with tempfile.TemporaryDirectory(prefix="automoto-dotnet22-") as work:
        temp = Path(work)
        stage = temp / "project"
        stage.mkdir(mode=0o700)
        _copy(root, before, stage)
        env = _env(root, temp)
        steps = _commands(body.task, tool["executable"], before, stage, temp)
        completed = []
        started = time.monotonic()
        for label, command in steps:
            after = _inspect(root)
            if any(after[key] != getattr(body, "expected_" + key)
                   for key in ("manifest_sha256", "source_sha256", "toolchain_sha256")):
                raise HTTPException(409, ".NET project or executable changed between stages.")
            adapters._trusted(root)
            if label not in ("sdk_version", "sdks", "msbuild_version"):
                _copy(root, before, stage)
            remaining = max(5, int(MAX_SECONDS - (time.monotonic() - started)))
            if remaining <= 5 and completed:
                completed.append({"stage": label, "status": "timeout",
                                  "exit_code": None, "output": "Overall .NET execution budget exceeded.",
                                  "elapsed_ms": 0})
                break
            result = native._execute(stage, command, env, timeout=remaining)
            completed.append({"stage": label, **result})
            if result["status"] != "completed":
                break
    output = "\n".join("## " + result["stage"] + "\n" + result["output"]
                       for result in completed)[:MAX_OUTPUT]
    failed = next((x for x in completed if x["status"] != "completed"), None)
    return {"task": body.task, "status": failed["status"] if failed else "completed",
            "stages": [{"stage": x["stage"], "status": x["status"],
                        "exit_code": x["exit_code"]} for x in completed],
            "output": output, "elapsed_ms": int((time.monotonic() - started) * 1000),
            "diagnostics": _diagnostics(root, output),
            "actual_sdk_version": (completed[0]["output"].strip().splitlines()[-1][:90]
                                   if body.task == "sdk_version" and completed
                                   and completed[0]["status"] == "completed" else None),
            "temporary_project_deleted": True,
            "source_immutability_not_guaranteed": True,
            "external_process_unsandboxed": True, "network_prevented_by_os": False,
            "nuget_sources_disabled_for_restore": True,
            "automatic_package_installation": False,
            "central_agent_studio": "developer", "agent_handoff_created": False,
            "agent_deployment_approved": False, "deployment_started": False}


@router.get("/inspect")
def inspect(request: Request, project: str):
    studio._auth(request)
    return _inspect(studio._project(project))


@router.post("/run")
def run(request: Request, body: RunIn):
    studio._auth(request)
    root = studio._project(body.project)
    if not LOCK.acquire(blocking=False):
        raise HTTPException(429, "Another .NET tool is already executing.")
    try:
        return _run(root, body)
    finally:
        LOCK.release()
