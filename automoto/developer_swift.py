"""Developer Studio V24: Swift/SwiftPM, SwiftUI, Objective-C and Xcode evidence.

Inspection does not invoke source code, package manifests, Xcode or Simulator.
Explicitly approved SwiftPM/Xcode tasks operate on a bounded private COPY.
Swift manifests, Xcode targets and compiled code are NOT OS/network sandboxed.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
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
from automoto import developer_jvm as jvm
from automoto import developer_native as native
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/swift", tags=["developer-swift"])
SCHEMA = "1.0.0"
MAX_FILES = 120
MAX_TOTAL = 9 * 1024 * 1024
MAX_INPUT = 512 * 1024
TIME_LIMIT = 150
LOCK = threading.Lock()
SOURCES = (".swift", ".m", ".mm", ".h")
CONFIG_FILES = {"Package.swift", "Package.resolved", "Info.plist"}
TOOLS = ("swift", "swiftc", "sourcekit-lsp", "xcodebuild", "xcrun", "lldb", "lldb-dap")
SWIFT_DECL = re.compile(r"(?m)^[ \t]*(?:(?:public|private|fileprivate|open|internal|final|static|"
                        r"@MainActor|@main|actor|nonisolated)\s+)*"
                        r"(?:struct|class|enum|protocol|extension|func|actor)\s+([A-Za-z_]\w{0,95})")
OBJC_DECL = re.compile(r"(?m)^\s*@(?:interface|protocol|implementation)\s+([A-Za-z_]\w{0,95})")
IMPORT = re.compile(r"(?m)^\s*(?:@testable\s+)?import\s+([A-Za-z_]\w{0,90})")
SWIFTUI = re.compile(r"(?i)\bimport\s+SwiftUI\b|\b(?:WindowGroup|ViewBuilder|NavigationStack|"
                     r"@State|@Observable|@Environment)\b")
XCODE_BUNDLE = re.compile(r"PRODUCT_BUNDLE_IDENTIFIER\s*=\s*([A-Za-z][A-Za-z0-9._-]{2,120})\s*;")
IOS_TARGET = re.compile(r"IPHONEOS_DEPLOYMENT_TARGET\s*=\s*([0-9]{1,2}\.[0-9]{1,2})\s*;")
PACKAGE_TARGET = re.compile(r'(?s)\.executableTarget\s*\(\s*name\s*:\s*"([A-Za-z_][A-Za-z0-9_-]{0,63})"')
UNSAFE_SWIFTPM = re.compile(r"(?i)\.package\s*\(|\.binaryTarget\s*\(|\.plugin\s*\(|"
                             r"\.macro\s*\(|\.systemLibrary\s*\(|\.product\s*\(|\.unsafeFlags\s*\(|"
                             r"Process\s*\(|URLSession|Foundation\.Process")
UNSAFE_XCODE = ("PBXShellScriptBuildPhase", "XCRemoteSwiftPackageReference",
                "XCSwiftPackageProductDependency", "PBXContainerItemProxy",
                "PBXTargetDependency", "PBXLegacyTarget", "PBXAggregateTarget",
                "CODE_SIGN_ENTITLEMENTS", "PROVISIONING_PROFILE_SPECIFIER",
                "DEVELOPMENT_TEAM")
TASK_TO_TOOL = {"swift_version": "swift", "swiftc_version": "swiftc",
                "xcode_version": "xcodebuild", "simulator_list": "xcrun",
                "swift_build": "swift", "swift_test": "swift",
                "swift_smoke": "swift", "ios_simulator_build": "xcodebuild"}


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    task: Literal["swift_version", "swiftc_version", "xcode_version",
                  "simulator_list", "swift_build", "swift_test",
                  "swift_smoke", "ios_simulator_build"]
    tool: Literal["swift", "swiftc", "xcodebuild", "xcrun"]
    expected_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_toolchain_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_compiler_manifest_and_network_risk: Literal[True]


def _relevant(path: str) -> tuple[bool, bool]:
    low = path.lower()
    leaf = path.rsplit("/", 1)[-1]
    source = low.endswith(SOURCES)
    manifest = (leaf in CONFIG_FILES or
                (path.endswith(".xcodeproj/project.pbxproj") and path.count("/") == 1) or
                (".xcodeproj/xcshareddata/xcschemes/" in path and path.endswith(".xcscheme")) or
                (path.endswith(".xcworkspace/contents.xcworkspacedata")))
    return source, manifest


def _inputs(root: Path) -> tuple[dict, dict, str, str, bool]:
    sources, manifests = {}, {}
    dig_s = hashlib.sha256(b"automoto-swift-v24-source\0")
    dig_m = hashlib.sha256(b"automoto-swift-v24-manifests\0")
    total, incomplete = 0, False
    for path, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        source, manifest = _relevant(path)
        if not source and not manifest:
            continue
        if len(sources) + len(manifests) >= MAX_FILES:
            incomplete = True
            continue
        text, sha, size = jvm._read(root, path, MAX_INPUT if manifest else index.MAX_FILE_BYTES)
        total += size
        if total > MAX_TOTAL:
            incomplete = True
            break
        entry = {"path": path, "sha256": sha, "bytes": size}
        if manifest:
            manifests[path] = entry
            dig_m.update(path.encode() + b"\0" + sha.encode())
        if source:
            is_swift = path.lower().endswith(".swift")
            entry.update({"language": "Swift" if is_swift else "Objective-C",
                          "symbols": (SWIFT_DECL if is_swift else OBJC_DECL).findall(text[:32000])[:15],
                          "imports": IMPORT.findall(text[:32000])[:16] if is_swift else [],
                          "swiftui_hint": bool(is_swift and SWIFTUI.search(text[:32000]))})
            sources[path] = entry
            dig_s.update(path.encode() + b"\0" + sha.encode())
    # Explicitly refuse a linked build manifest in a location that was skipped
    # by the index traversal; no side-effectful tool is offered in that case.
    for name in ("Package.swift", "Package.resolved"):
        file = root / name
        if file.is_symlink() or getattr(file, "is_junction", lambda: False)():
            raise HTTPException(403, "Linked SwiftPM manifest is forbidden.")
    return sources, manifests, dig_s.hexdigest(), dig_m.hexdigest(), incomplete


def _metadata(root: Path, manifest: dict) -> dict:
    warnings = []
    projects = sorted(x for x in manifest if x.endswith(".xcodeproj/project.pbxproj"))
    has_package = "Package.swift" in manifest
    if len(projects) > 1 or (has_package and projects):
        warnings.append("Ambiguous mixed SwiftPM/Xcode workspace; inspection only.")
    kind = ("swiftpm" if has_package and not projects else
            "xcode_ios" if len(projects) == 1 and not has_package else "unknown")
    package = {"declared_executable": None, "external_dependencies": False,
               "manifest_evaluated": False}
    ios = {"project": projects[0].split("/", 1)[0] if len(projects) == 1 else None,
           "scheme": None, "bundle_ids": [], "deployment_targets": [],
           "swiftui_hint": False, "build_scripts_detected": False}
    if has_package:
        text, _, _ = jvm._read(root, "Package.swift")
        marker = PACKAGE_TARGET.search(text[:MAX_INPUT])
        package["declared_executable"] = marker.group(1) if marker else None
        package["external_dependencies"] = bool(UNSAFE_SWIFTPM.search(text))
        if package["external_dependencies"]:
            warnings.append("SwiftPM manifest declares remote, plugin, macro or unsafe build facilities.")
        # Local target dependencies are permitted. External package references
        # and plugin hooks are rejected above, not inferred from any target's
        # ordinary `dependencies: ["LocalTarget"]` declaration.
        if not re.search(r"//\s*swift-tools-version\s*:\s*\d+\.\d+", text[:250]):
            warnings.append("SwiftPM tools version is not declared.")
    if projects:
        path = projects[0]
        text, _, _ = jvm._read(root, path)
        ios.update({"scheme": path.split("/", 1)[0][:-len(".xcodeproj")],
                    "bundle_ids": sorted(set(XCODE_BUNDLE.findall(text)))[:15],
                    "deployment_targets": sorted(set(IOS_TARGET.findall(text)))[:15],
                    "swiftui_hint": "SwiftUI" in text,
                    "build_scripts_detected": "PBXShellScriptBuildPhase" in text})
        for token in UNSAFE_XCODE:
            if token in text:
                warnings.append("Xcode requires manual review: " + token)
        # A portable, auditable single-target project must have a shared scheme.
        scheme = ios["scheme"]
        expected = f"{ios['project']}/xcshareddata/xcschemes/{scheme}.xcscheme"
        if expected not in manifest:
            warnings.append("Xcode shared build scheme is absent.")
        if not ios["bundle_ids"]:
            warnings.append("No declared iOS bundle identifier.")
        if not ios["deployment_targets"]:
            warnings.append("No iOS minimum deployment target.")
    if not sources_or_project(root, kind):
        warnings.append("Swift source or supported project structure missing.")
    if kind == "unknown":
        warnings.append("A single root SwiftPM package or one iOS Xcode project is required.")
    if any(x.endswith(".xcworkspace/contents.xcworkspacedata") for x in manifest):
        warnings.append("Xcode workspace dependencies are not supported for execution.")
    return kind, package, ios, warnings


def sources_or_project(root: Path, kind: str) -> bool:
    # This is only a cheap structural check; the complete inventory is
    # assessed independently before execution.
    return kind in ("swiftpm", "xcode_ios")


def _tools(root: Path) -> tuple[list[dict], str]:
    found = []
    digest = hashlib.sha256(b"automoto-swift-v24-tooling\0")
    for name in TOOLS:
        loc = shutil.which(name)
        if not loc:
            entry = {"name": name, "status": "unavailable"}
        elif Path(loc).suffix.casefold() in (".cmd", ".bat", ".ps1"):
            entry = {"name": name, "status": "shell_wrapper_blocked"}
        else:
            try:
                entry = {"name": name, "status": "installed_not_executed",
                         **adapters._fingerprint(str(Path(loc).absolute()), root)}
            except HTTPException:
                entry = {"name": name, "status": "not_approved"}
        found.append(entry)
        digest.update(name.encode() + b"\0" + entry["status"].encode() + b"\0" +
                      entry.get("sha256", "").encode() + b"\0" +
                      entry.get("executable", "").encode())
    return found, digest.hexdigest()


def _inspect(root: Path) -> dict:
    sources, manifests, source_sha, manifest_sha, incomplete = _inputs(root)
    kind, package, ios, warnings = _metadata(root, manifests)
    if incomplete or not sources:
        warnings.append("Swift source inventory is incomplete or empty.")
    tools, tools_sha = _tools(root)
    hints = sorted(set(["SwiftUI"] if any(x["swiftui_hint"] for x in sources.values()) else []) |
                   set(["Objective-C"] if any(x["language"] == "Objective-C" for x in sources.values()) else []))
    return {"schema": SCHEMA, "project_type": kind,
            "manifests": manifests, "files": list(sources.values()),
            "symbols": [{"path": x["path"], "name": name}
                        for x in sources.values() for name in x["symbols"]][:90],
            "swiftpm": package, "ios": ios, "framework_hints": hints,
            "warnings": warnings,
            "safe_to_offer_builds": not warnings and not incomplete and bool(sources),
            "source_sha256": source_sha, "manifest_sha256": manifest_sha,
            "toolchain_sha256": tools_sha, "toolchains": tools,
            "platform": sys.platform,
            "xcode_build_available_only_on_macos": True,
            "swiftpm_cross_platform": True, "simulator_status": "not_queried",
            "simulator_started": False, "device_connected": False,
            "sourcekit_lsp": "SourceKit-LSP discovery only; existing separately approved LSP controls own launch.",
            "debugger": "LLDB discovery only; existing separately approved DAP controls own launch.",
            "project_trusted": studio._trusted(root, studio._load()),
            "project_code_executed": False, "package_manifest_evaluated": False,
            "package_download_started": False, "device_installed_to": False,
            "deployment_started": False, "central_agent_studio": "developer",
            "agent_deployment_handoff_required": True}


def _copy(root: Path, info: dict, stage: Path) -> None:
    if not info["safe_to_offer_builds"]:
        raise HTTPException(409, "Swift project is ambiguous, incomplete or requires build review.")
    paths = sorted(set(info["manifests"]) | {x["path"] for x in info["files"]})
    total = 0
    for name in paths:
        text, sha, size = jvm._read(root, name, MAX_INPUT
                                   if name in info["manifests"] else index.MAX_FILE_BYTES)
        expected = info["manifests"].get(name) or next(
            (x for x in info["files"] if x["path"] == name), None)
        if not expected or expected["sha256"] != sha:
            raise HTTPException(409, "Swift source or build configuration changed during staging.")
        total += size
        if total > MAX_TOTAL:
            raise HTTPException(413, "Swift project copy exceeds memory budget.")
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def _env(root: Path, temp: Path) -> dict:
    env = adapters._environment(root)
    for sub in ("home", "tmp", "cache", "scratch", "config", "security", "derived"):
        (temp / sub).mkdir(mode=0o700, exist_ok=True)
    env.update({"HOME": str(temp / "home"),
                "TMPDIR": str(temp / "tmp"),
                "SWIFTPM_DISABLE_TELEMETRY": "1",
                "SWIFT_DETERMINISTIC_HASHING": "1"})
    if sys.platform == "darwin":
        developer = os.environ.get("DEVELOPER_DIR", "")
        if (developer and Path(developer).is_absolute() and
                Path(developer).is_dir() and len(developer) <= 500):
            try:
                resolved = Path(developer).resolve(strict=True)
                if not adapters._disallowed_workspace_executable(resolved, root):
                    env["DEVELOPER_DIR"] = str(resolved)
            except (OSError, ValueError):
                pass
    return env


def _commands(body: RunIn, tool: dict, data: dict, stage: Path, temp: Path) -> list[list[str]]:
    exe = tool["executable"]
    if body.task in ("swift_version", "swiftc_version"):
        return [[exe, "--version"]]
    if body.task == "xcode_version":
        return [[exe, "-version"]]
    if body.task == "simulator_list":
        return [[exe, "simctl", "list", "-j", "devices", "available"]]
    if not data["safe_to_offer_builds"]:
        raise HTTPException(409, "Swift project is not approved for execution.")
    if body.task in ("swift_build", "swift_test", "swift_smoke"):
        if data["project_type"] != "swiftpm":
            raise HTTPException(422, "SwiftPM operation requires a root Package.swift.")
        options = ["--package-path", str(stage),
                   "--scratch-path", str(temp / "scratch"),
                   "--cache-path", str(temp / "cache"),
                   "--config-path", str(temp / "config"),
                   "--security-path", str(temp / "security"),
                   "--disable-automatic-resolution", "--jobs", "2"]
        build = [exe, "build", *options]
        if body.task == "swift_build":
            return [build]
        if body.task == "swift_test":
            return [[exe, "test", *options]]
        target = data["swiftpm"]["declared_executable"]
        if not target:
            raise HTTPException(409, "A single declared executable target is needed for smoke execution.")
        return [build, [exe, "run", *options, "--skip-build", target]]
    if body.task == "ios_simulator_build":
        if sys.platform != "darwin" or data["project_type"] != "xcode_ios":
            raise HTTPException(409, "iOS simulator builds require macOS, Xcode and one reviewed project.")
        project = data["ios"]["project"]
        scheme = data["ios"]["scheme"]
        if not project or not scheme:
            raise HTTPException(409, "No approved shared iOS Xcode scheme.")
        return [[exe, "-project", str(stage / project),
                 "-scheme", scheme,
                 "-configuration", "Debug",
                 "-sdk", "iphonesimulator",
                 "-destination", "generic/platform=iOS Simulator",
                 "-derivedDataPath", str(temp / "derived"),
                 "-disableAutomaticPackageResolution",
                 "-quiet", "CODE_SIGNING_ALLOWED=NO", "build"]]
    raise HTTPException(422, "Unsupported Swift task.")


def _run(root: Path, body: RunIn) -> dict:
    adapters._trusted(root)
    current = _inspect(root)
    for name in ("source_sha256", "manifest_sha256", "toolchain_sha256"):
        if current[name] != getattr(body, "expected_" + name):
            raise HTTPException(409, "Swift project or toolchain changed after approval.")
    required = TASK_TO_TOOL[body.task]
    tool = next((x for x in current["toolchains"] if x["name"] == required and
                 x["status"] == "installed_not_executed"), None)
    if not tool or body.tool != required or tool.get("sha256") != body.expected_sha256 or (
            tool.get("executable") != body.expected_executable):
        raise HTTPException(409, "Swift executable location or SHA-256 fingerprint changed.")
    if body.task in ("xcode_version", "simulator_list", "ios_simulator_build") and sys.platform != "darwin":
        raise HTTPException(409, "Xcode and iOS Simulator are available only on supported macOS.")
    with tempfile.TemporaryDirectory(prefix="automoto-swift24-") as work:
        temp = Path(work)
        stage = temp / "project"
        stage.mkdir(mode=0o700)
        if body.task not in ("swift_version", "swiftc_version", "xcode_version", "simulator_list"):
            _copy(root, current, stage)
        env = _env(root, temp)
        commands = _commands(body, tool, current, stage, temp)
        started, stages = time.monotonic(), []
        for index_step, cmd in enumerate(commands):
            if (index_step or body.task not in ("swift_version", "swiftc_version",
                                                 "xcode_version", "simulator_list")):
                fresh = _inspect(root)
                if any(fresh[name] != getattr(body, "expected_" + name)
                       for name in ("source_sha256", "manifest_sha256", "toolchain_sha256")):
                    raise HTTPException(409, "Swift project changed during execution.")
                adapters._trusted(root)
            remaining = TIME_LIMIT - (time.monotonic() - started)
            if remaining < 5:
                stages.append({"status": "timeout", "exit_code": None,
                               "output": "Overall Swift task time budget exceeded.", "elapsed_ms": 0})
                break
            stage_result = native._execute(stage, cmd, env, timeout=int(remaining))
            stages.append(stage_result)
            if stage_result["status"] != "completed":
                break
    out = "\n".join(x["output"] for x in stages)
    failed = next((x for x in stages if x["status"] != "completed"), None)
    return {"task": body.task,
            "status": failed["status"] if failed else "completed",
            "stages": [{"status": x["status"], "exit_code": x["exit_code"]}
                       for x in stages],
            "output": out[:native.MAX_OUTPUT],
            "elapsed_ms": sum(x["elapsed_ms"] for x in stages),
            "temporary_project_deleted": True,
            "external_process_unsandboxed": True,
            "os_network_isolation": False,
            "automatic_dependency_download": False,
            "simulator_started": False,
            "device_installed_to": False,
            "production_signed": False, "deployment_started": False,
            "central_agent_studio": "developer", "agent_handoff_created": False,
            "agent_deployment_approved": False}


@router.get("/inspect")
def inspect(request: Request, project: str):
    studio._auth(request)
    return _inspect(studio._project(project))


@router.post("/run")
def run(request: Request, body: RunIn):
    studio._auth(request)
    if not LOCK.acquire(blocking=False):
        raise HTTPException(429, "A Swift/Xcode task is already running.")
    try:
        return _run(studio._project(body.project), body)
    finally:
        LOCK.release()
