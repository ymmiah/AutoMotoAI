"""Developer Studio V25 — Flutter/Dart and React Native evidence-first tooling.

Inspection is inert and does not start Flutter, Metro, ADB, simulators or scripts.
Approved tasks use SHA-checked temporary copies, fixed commands and explicit
consent. Compilers, package managers, build hooks and tests are NOT sandboxed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Literal

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_adapters as adapters
from automoto import developer_index as index
from automoto import developer_jvm as jvm
from automoto import developer_native as native
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/mobile", tags=["developer-mobile"])
VERSION = "1.0.0"
LOCK = threading.Lock()
MAX_FILES = 130
MAX_TOTAL = 18 * 1024 * 1024
MAX_CONFIG = 512 * 1024
TIMEOUT = 180
MANIFESTS = {
    "pubspec.yaml", "pubspec.lock", "analysis_options.yaml",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "app.json", "metro.config.js", "babel.config.js", "react-native.config.js",
    "tsconfig.json", "android/build.gradle", "android/build.gradle.kts",
    "android/app/build.gradle", "android/app/build.gradle.kts",
    "android/gradle/wrapper/gradle-wrapper.properties",
    "ios/Podfile", "web/index.html", "web/manifest.json",
}
FLUTTER_SOURCE = (".dart",)
RN_SOURCE = (".js", ".jsx", ".ts", ".tsx", ".cjs", ".mjs")
TOOLS = ("flutter", "dart", "node", "npm", "adb", "emulator", "xcrun",
         "flutter-lsp", "dart_language_server", "react-native")
DART_SYMBOL = re.compile(r"(?m)^\s*(?:(?:abstract|sealed|final|base|interface)\s+)*"
                         r"(?:class|enum|mixin|extension|typedef|void|Future<[^>]{1,80}>)\s+"
                         r"([A-Za-z_]\w{0,95})")
JS_SYMBOL = re.compile(r"(?m)^\s*(?:(?:export|default|async|declare)\s+)*"
                       r"(?:function|class|interface|type|const|let)\s+([A-Za-z_$][\w$]{0,90})")
WIDGET = re.compile(r"\b(?:StatelessWidget|StatefulWidget|MaterialApp|CupertinoApp|WidgetTester|runApp)\b")
RN_VIEW = re.compile(r"\b(?:AppRegistry|SafeAreaView|View|Text|StyleSheet|NativeModules|"
                     r"TurboModuleRegistry|useState)\b")
VERSION_TEXT = re.compile(r"^[\d]+\.[\d]+(?:\.[\d]+)?(?:[-+][A-Za-z0-9.]+)?$")
# Only fixed operations. Device queries are explicit and never launch/modify.
TASK_TOOL = {
    "flutter_version": "flutter", "dart_version": "dart", "node_version": "node",
    "npm_version": "npm", "flutter_doctor": "flutter",
    "flutter_devices": "flutter", "flutter_pub_offline": "flutter",
    "flutter_analyze": "flutter", "flutter_test": "flutter", "flutter_build_web": "flutter",
    "rn_node_check": "node", "rn_node_test": "node", "rn_npm_ci_offline": "npm",
}
VERSION_COMMAND = {
    "flutter_version": ("flutter", ["--version"]),
    "dart_version": ("dart", ["--version"]),
    "node_version": ("node", ["--version"]),
    "npm_version": ("npm", ["--version"]),
    "flutter_doctor": ("flutter", ["doctor", "-v"]),
    "flutter_devices": ("flutter", ["devices", "--machine"]),
}


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    task: Literal[
        "flutter_version", "dart_version", "node_version", "npm_version",
        "flutter_doctor", "flutter_devices", "flutter_pub_offline",
        "flutter_analyze", "flutter_test", "flutter_build_web",
        "rn_node_check", "rn_node_test", "rn_npm_ci_offline"
    ]
    tool: Literal["flutter", "dart", "node", "npm"]
    expected_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_toolchain_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_build_packages_and_network_risk: Literal[True]


def _source(path: str) -> bool:
    if path.rsplit("/", 1)[-1] in ("package.json", "Package.swift"):
        return False
    if path.endswith(FLUTTER_SOURCE):
        return path.startswith(("lib/", "test/", "integration_test/")) or "/" not in path
    if path.endswith(RN_SOURCE):
        return path.startswith(("src/", "app/", "test/", "__tests__/")) or "/" not in path
    return False


def _inputs(root: Path) -> tuple[dict, dict, str, str, bool]:
    source, manifest = {}, {}
    digest_s = hashlib.sha256(b"automoto-v25-mobile-source\0")
    digest_m = hashlib.sha256(b"automoto-v25-mobile-manifests\0")
    total, incomplete = 0, False
    for name, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        is_manifest = name in MANIFESTS
        is_source = _source(name)
        if not (is_manifest or is_source):
            continue
        if len(manifest) + len(source) >= MAX_FILES:
            incomplete = True
            continue
        limit = 4 * 1024 * 1024 if name.endswith(("-lock.json", ".lock")) else (MAX_CONFIG if is_manifest else index.MAX_FILE_BYTES)
        text, sha, size = jvm._read(root, name, limit)
        total += size
        if total > MAX_TOTAL:
            incomplete = True
            break
        item = {"path": name, "sha256": sha, "bytes": size}
        if is_manifest:
            manifest[name] = item
            digest_m.update(name.encode() + b"\0" + sha.encode())
        if is_source:
            dart = name.endswith(".dart")
            item.update({"language": "Dart" if dart else
                         ("TypeScript" if name.endswith((".ts", ".tsx")) else "JavaScript"),
                         "symbols": (DART_SYMBOL if dart else JS_SYMBOL).findall(text[:30000])[:14],
                         "widget_hint": bool(WIDGET.search(text[:30000])) if dart else False,
                         "react_native_hint": bool(RN_VIEW.search(text[:30000])) if not dart else False})
            source[name] = item
            digest_s.update(name.encode() + b"\0" + sha.encode())
    for key in MANIFESTS:
        file = root / key
        if file.is_symlink() or getattr(file, "is_junction", lambda: False)():
            raise HTTPException(403, "Linked mobile build configuration is forbidden.")
    return source, manifest, digest_s.hexdigest(), digest_m.hexdigest(), incomplete


def _metadata(root: Path, sources: dict, manifests: dict) -> dict:
    warnings = []
    flutter = "pubspec.yaml" in manifests
    reactnative = "package.json" in manifests
    flutter_info = {"name": None, "dependencies": [], "dev_dependencies": [],
                    "lock_present": "pubspec.lock" in manifests,
                    "widget_hints": False, "web_entry_present": "web/index.html" in manifests}
    rn_info = {"name": None, "version": None, "dependencies": [], "scripts": [],
               "lock_present": "package-lock.json" in manifests,
               "metro_config_present": "metro.config.js" in manifests,
               "native_android_present": any(x.startswith("android/") for x in manifests),
               "native_ios_present": "ios/Podfile" in manifests}
    if flutter:
        text = jvm._read(root, "pubspec.yaml", MAX_CONFIG)[0]
        try:
            config = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise HTTPException(422, "Invalid Flutter pubspec YAML.") from exc
        if not isinstance(config, dict):
            raise HTTPException(422, "Flutter pubspec must contain an object.")
        dependencies = config.get("dependencies") or {}
        dev_dependencies = config.get("dev_dependencies") or {}
        if (not isinstance(dependencies, dict) or not isinstance(dev_dependencies, dict)
                or len(dependencies) > 90 or len(dev_dependencies) > 90):
            raise HTTPException(422, "Invalid or oversized Flutter dependencies.")
        flutter_info.update({
            "name": str(config.get("name", ""))[:100],
            "dependencies": sorted(str(x)[:80] for x in dependencies)[:80],
            "dev_dependencies": sorted(str(x)[:80] for x in dev_dependencies)[:80],
            "widget_hints": any(item.get("widget_hint") for item in sources.values()),
        })
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,70}", flutter_info["name"]):
            warnings.append("Flutter package name is not an approved Dart package identifier.")
        for section in (dependencies, dev_dependencies):
            for name, declaration in section.items():
                if isinstance(declaration, dict) and any(
                    key in declaration for key in ("git", "path", "hosted")
                ):
                    warnings.append("Flutter git/path/hosted dependency requires independent approval.")
                if not isinstance(declaration, (str, dict)):
                    warnings.append("Invalid Flutter package dependency value.")
        if "flutter" not in dependencies:
            warnings.append("Flutter project has no flutter SDK dependency.")
        if "lib/main.dart" not in sources:
            warnings.append("Flutter main entry lib/main.dart missing.")
        if "pubspec_overrides.yaml" in (p.name for p in root.iterdir()):
            warnings.append("Flutter pubspec_overrides.yaml needs manual review.")
    if reactnative:
        content = jvm._read(root, "package.json", MAX_CONFIG)[0]
        try:
            config = json.loads(content)
        except (ValueError, RecursionError) as exc:
            raise HTTPException(422, "Invalid React Native package JSON.") from exc
        if not isinstance(config, dict):
            raise HTTPException(422, "React Native package must contain an object.")
        deps = config.get("dependencies") or {}
        scripts = config.get("scripts") or {}
        if (not isinstance(deps, dict) or not isinstance(scripts, dict)
                or len(deps) > 180 or len(scripts) > 80):
            raise HTTPException(422, "Invalid React Native dependencies/scripts.")
        reactnative = "react-native" in deps
        if reactnative:
            rn_info.update({
                "name": str(config.get("name", ""))[:100],
                "version": str(deps["react-native"])[:64],
                "dependencies": sorted(str(x)[:80] for x in deps)[:130],
                "scripts": sorted(str(x)[:80] for x in scripts)[:80],
            })
            if not VERSION_TEXT.fullmatch(rn_info["version"].lstrip("^~")):
                warnings.append("React Native package version is not a simple semver declaration.")
            if "index.js" not in sources:
                warnings.append("React Native JavaScript index.js entry missing.")
            if any(x in manifests for x in ("yarn.lock", "pnpm-lock.yaml")):
                warnings.append("Yarn/pnpm native workflows require separate package-manager approval.")
            if "metro.config.js" in manifests:
                text = jvm._read(root, "metro.config.js", MAX_CONFIG)[0]
                if re.search(r"(?i)(child_process|execSync|spawnSync|\\.\\.\\/|process\\.env)", text):
                    warnings.append("Metro config contains potentially unsafe external invocation/reference.")
        else:
            reactnative = False
    kind = ("mixed" if flutter and reactnative else
            "flutter" if flutter else "react_native" if reactnative else "unknown")
    if flutter and reactnative:
        warnings.append("Mixed Flutter and React Native roots are inspection-only.")
    if kind == "unknown":
        warnings.append("Neither a Flutter package nor a React Native application was detected.")
    if not sources:
        warnings.append("No bounded Dart/JavaScript/TypeScript source was discovered.")
    if "pubspec.yaml" in manifests and "package.json" in manifests and not reactnative:
        # A Flutter project might also contain helper npm tooling; this is normal.
        pass
    return {"type": kind, "flutter": flutter_info, "react_native": rn_info,
            "warnings": warnings}


def _tools(root: Path) -> tuple[list[dict], str]:
    found, digest = [], hashlib.sha256(b"automoto-v25-mobile-tools\0")
    for name in TOOLS:
        exe = shutil.which(name)
        if not exe:
            entry = {"name": name, "status": "unavailable"}
        elif Path(exe).suffix.lower() in (".bat", ".cmd", ".ps1"):
            entry = {"name": name, "status": "shell_wrapper_blocked"}
        else:
            try:
                entry = {"name": name, "status": "installed_not_executed",
                         **adapters._fingerprint(str(Path(exe).absolute()), root)}
            except HTTPException:
                entry = {"name": name, "status": "untrusted_executable"}
        found.append(entry)
        digest.update(name.encode() + b"\0" + entry["status"].encode() + b"\0" +
                      entry.get("sha256", "").encode() + b"\0" +
                      entry.get("executable", "").encode())
    return found, digest.hexdigest()


def _inspect(root: Path) -> dict:
    sources, manifests, source_sha, manifest_sha, incomplete = _inputs(root)
    data = _metadata(root, sources, manifests)
    if incomplete:
        data["warnings"].append("Mobile source inventory incomplete; tool execution blocked.")
    binaries, tool_sha = _tools(root)
    return {"schema": VERSION, "project_type": data["type"],
            "flutter": data["flutter"], "react_native": data["react_native"],
            "manifests": manifests, "files": list(sources.values()),
            "symbols": [{"path": f["path"], "name": name} for f in sources.values()
                        for name in f["symbols"]][:90],
            "framework_hints": sorted(set(
                ["Flutter widgets"] if data["flutter"]["widget_hints"] else []
            ) | ({"React Native components"} if any(
                x["react_native_hint"] for x in sources.values()) else set())),
            "manifest_sha256": manifest_sha, "source_sha256": source_sha,
            "toolchain_sha256": tool_sha, "toolchains": binaries,
            "warnings": data["warnings"], "safe_to_offer_runs": not data["warnings"],
            "scan_incomplete": incomplete,
            "platform": sys.platform, "device_query_performed": False,
            "device_targets": "not_queried", "simulator_started": False,
            "device_connected": False, "app_installed": False,
            "language_servers": "Dart Analysis Server, TypeScript LSP and RN/Flutter debug adapters need separate approval.",
            "package_manager": "Locked packages and available tools are inspected; no install/download performed.",
            "project_trusted": studio._trusted(root, studio._load()),
            "external_code_executed": False, "dependencies_installed": False,
            "deployment_started": False, "central_agent_studio": "developer",
            "agent_deployment_handoff_required": True}


def _copy(root: Path, data: dict, stage: Path) -> None:
    if not data["safe_to_offer_runs"]:
        raise HTTPException(409, "Mobile build admission failed: resolve warnings and review sources.")
    entries = {x["path"]: x for x in data["files"]}
    entries.update(data["manifests"])
    total = 0
    for name in sorted(entries):
        if not name or name.startswith("/") or ".." in name.split("/"):
            raise HTTPException(403, "Unsafe mobile source staging path.")
        entry = entries[name]
        limit = 4 * 1024 * 1024 if name.endswith(("-lock.json", ".lock")) else (MAX_CONFIG if name in data["manifests"] else index.MAX_FILE_BYTES)
        text, sha, size = jvm._read(root, name, limit)
        if sha != entry["sha256"]:
            raise HTTPException(409, "Mobile source file changed while copying.")
        total += size
        if total > MAX_TOTAL:
            raise HTTPException(413, "Mobile project staging exceeds bound.")
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def _env(root: Path, tmp: Path) -> dict:
    env = adapters._environment(root)
    for name in ("home", "tmp", "pub-cache", "npm-cache"):
        (tmp / name).mkdir(mode=0o700)
    env.update({"HOME": str(tmp / "home"), "TMPDIR": str(tmp / "tmp"),
                "PUB_CACHE": str(tmp / "pub-cache"), "npm_config_cache": str(tmp / "npm-cache"),
                "CI": "true", "FLUTTER_SUPPRESS_ANALYTICS": "true",
                "DART_SUPPRESS_ANALYTICS": "true", "npm_config_audit": "false",
                "npm_config_fund": "false", "npm_config_offline": "true",
                "npm_config_ignore_scripts": "true"})
    # A pre-populated local pub-cache may be read through an approved readonly
    # path, but Flutter SDK cache is external and may still be modified by Flutter.
    cache = Path.home() / ".pub-cache"
    if cache.is_dir() and not cache.is_symlink():
        try:
            cache_path = cache.resolve(strict=True)
            if not adapters._disallowed_workspace_executable(cache_path, root):
                env["PUB_CACHE"] = str(cache_path)
        except (OSError, ValueError):
            pass
    return env


def _commands(body: RunIn, info: dict, stage: Path, tmp: Path, tool: dict) -> list[list[str]]:
    exe = tool["executable"]
    if body.task in VERSION_COMMAND:
        return [[exe, *VERSION_COMMAND[body.task][1]]]
    if not info["safe_to_offer_runs"]:
        raise HTTPException(409, "Unreviewed Flutter/React Native project cannot run tools.")
    if body.task.startswith("flutter_"):
        if info["project_type"] != "flutter" or body.tool != "flutter":
            raise HTTPException(422, "Flutter task requires a Flutter-only project and approved Flutter SDK.")
        pub = [exe, "pub", "get", "--offline"]
        if body.task == "flutter_pub_offline":
            return [pub]
        tail = {"flutter_analyze": ["analyze", "--no-pub"],
                "flutter_test": ["test", "--no-pub"],
                "flutter_build_web": ["build", "web", "--no-pub"]}[body.task]
        if body.task == "flutter_build_web" and not info["flutter"]["web_entry_present"]:
            raise HTTPException(409, "Flutter web bootstrap is missing.")
        return [pub, [exe, *tail]]
    if info["project_type"] != "react_native":
        raise HTTPException(422, "React Native task requires a React Native-only project.")
    if body.task == "rn_npm_ci_offline":
        if body.tool != "npm" or not info["react_native"]["lock_present"]:
            raise HTTPException(409, "An approved npm binary and package-lock.json are required.")
        return [[exe, "ci", "--offline", "--ignore-scripts", "--no-audit", "--no-fund"]]
    if body.tool != "node":
        raise HTTPException(422, "React Native syntax/test tasks require approved Node.")
    if body.task == "rn_node_check":
        if "index.js" not in info["manifests"] and not any(
            x["path"] == "index.js" for x in info["files"]
        ):
            raise HTTPException(409, "React Native index.js not found.")
        return [[exe, "--check", "index.js"]]
    if body.task == "rn_node_test":
        if not any(x["path"] == "test/bridge.test.cjs" for x in info["files"]):
            raise HTTPException(409, "Node bridge smoke test test/bridge.test.cjs missing.")
        return [[exe, "--test", "test/bridge.test.cjs"]]
    raise HTTPException(422, "Unsupported mobile development task.")


def _run(root: Path, body: RunIn) -> dict:
    adapters._trusted(root)
    data = _inspect(root)
    for field in ("source_sha256", "manifest_sha256", "toolchain_sha256"):
        if data[field] != getattr(body, "expected_" + field):
            raise HTTPException(409, "Mobile source or toolchain changed since review.")
    expected = TASK_TOOL[body.task]
    tool = next((t for t in data["toolchains"] if t["name"] == expected
                 and t["status"] == "installed_not_executed"), None)
    if (body.tool != expected or not tool or tool.get("sha256") != body.expected_sha256
            or tool.get("executable") != body.expected_executable):
        raise HTTPException(409, "Approved mobile executable SHA/path mismatch.")
    with tempfile.TemporaryDirectory(prefix="automoto-mobile25-") as dirname:
        tmp = Path(dirname)
        stage = tmp / "project"
        stage.mkdir(mode=0o700)
        if body.task not in VERSION_COMMAND:
            _copy(root, data, stage)
        commands = _commands(body, data, stage, tmp, tool)
        env = _env(root, tmp)
        outputs, started = [], time.monotonic()
        for cmd in commands:
            if body.task not in VERSION_COMMAND:
                latest = _inspect(root)
                if any(latest[field] != getattr(body, "expected_" + field)
                       for field in ("source_sha256", "manifest_sha256", "toolchain_sha256")):
                    raise HTTPException(409, "Mobile project changed during execution.")
                adapters._trusted(root)
            remaining = TIMEOUT - (time.monotonic() - started)
            if remaining <= 5:
                outputs.append({"status": "timeout", "exit_code": None, "output": "Mobile task exceeded time cap.", "elapsed_ms": 0})
                break
            result = native._execute(stage, cmd, env, timeout=int(remaining))
            outputs.append(result)
            if result["status"] != "completed":
                break
    fail = next((x for x in outputs if x["status"] != "completed"), None)
    return {"task": body.task, "status": fail["status"] if fail else "completed",
            "stages": [{"status": x["status"], "exit_code": x["exit_code"]} for x in outputs],
            "output": "\n".join(x["output"] for x in outputs)[:native.MAX_OUTPUT],
            "elapsed_ms": sum(x["elapsed_ms"] for x in outputs),
            "temporary_project_deleted": True, "external_code_unsandboxed": True,
            "os_network_isolation": False, "automatic_online_package_download": False,
            "device_discovery_only": body.task == "flutter_devices",
            "emulator_started": False, "app_installed": False,
            "app_deployed": False, "agent_handoff_created": False,
            "central_agent_studio": "developer", "agent_deployment_approved": False}


@router.get("/inspect")
def inspect(request: Request, project: str):
    studio._auth(request)
    return _inspect(studio._project(project))


@router.post("/run")
def run(request: Request, body: RunIn):
    studio._auth(request)
    if not LOCK.acquire(blocking=False):
        raise HTTPException(429, "A mobile development task is already running.")
    try:
        return _run(studio._project(body.project), body)
    finally:
        LOCK.release()
