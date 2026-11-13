"""AutoMoto Developer Studio V23: evidence-first Kotlin/Android Gradle workflows.

Inspection is inert. Approved Gradle tasks operate on a SHA-checked bounded
temporary copy, but project build scripts and tests are NOT OS/network sandboxed.
The emulator and device are never started, connected, flashed or reset here.
"""
from __future__ import annotations

import hashlib
import os
import re
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
from automoto import developer_jvm as jvm
from automoto import developer_native as native
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/android", tags=["developer-android"])
SCHEMA = "1.0.0"
MAX_INPUTS = 105
MAX_BYTES = 8 * 1024 * 1024
MAX_SECONDS = 130
LOCK = threading.Lock()
CONFIG = {"settings.gradle", "settings.gradle.kts", "build.gradle", "build.gradle.kts",
          "gradle.properties", "gradle/libs.versions.toml",
          "gradle/wrapper/gradle-wrapper.properties", "app/build.gradle",
          "app/build.gradle.kts", "app/proguard-rules.pro", "app/src/main/AndroidManifest.xml",
          "app/src/androidTest/AndroidManifest.xml"}
SRC_ENDINGS = (".kt", ".java")
XML_PREFIXES = ("app/src/main/res/", "app/src/androidTest/res/")
JAVA_PACKAGE = re.compile(r"(?m)^\s*package\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*){0,20})\s*;?")
SYMBOL = re.compile(r"(?m)^\s*(?:(?:public|private|internal|suspend|data|sealed|open)\s+)*"
                    r"(?:fun|class|object|interface|enum\s+class)\s+([A-Za-z_]\w{0,90})")
GRADLE_WRAPPER = re.compile(r"gradle-(\d+\.\d+(?:\.\d+)?)-(?:bin|all)\.zip")
AGP_VERSION = re.compile(r"(?:com\.android\.(?:application|library)[\"']?\)?\s+version\s+[\"']"
                         r"|com\.android\.tools\.build:gradle:)(\d+\.\d+(?:\.\d+)?)")
KOTLIN_VERSION = re.compile(r"(?:org\.jetbrains\.kotlin\.(?:jvm|android)[\"']?\)?\s+version\s+[\"']"
                            r"|kotlin\(\"(?:jvm|android)\"\)\s+version\s+\")(\d+\.\d+(?:\.\d+)?)")
COMPOSE = re.compile(r"(?i)androidx\.compose|@Composable|org\.jetbrains\.kotlin\.plugin\.compose|"
                     r"buildFeatures\s*\{[^}]{0,300}compose\s*=\s*true")
# Conservative, well-scoped advisories; not a claim of full plugin matrix coverage.
AGP_MIN_GRADLE = {"8.7": (8, 9), "8.8": (8, 10, 2), "8.9": (8, 11, 1),
                  "8.10": (8, 11, 1), "8.11": (8, 13), "8.12": (8, 13),
                  "8.13": (8, 13), "9.0": (9, 1)}
TOOLS = ("gradle", "java", "kotlinc", "kotlin", "adb", "emulator", "kotlin-language-server")


class RootIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)


class RunIn(RootIn):
    task: Literal["gradle_version", "java_version", "adb_version",
                  "kotlin_build", "kotlin_test", "android_assemble", "android_unit_test"]
    tool: Literal["gradle", "java", "adb"]
    expected_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_toolchain_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_gradle_and_test_risk: Literal[True]


def _inputs(root: Path) -> tuple[dict, dict, str, str, bool]:
    files, manifests = {}, {}
    digest_m = hashlib.sha256(b"automoto-android-v23-manifests\0")
    digest_s = hashlib.sha256(b"automoto-android-v23-sources\0")
    total = 0
    incomplete = False
    for name, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        is_manifest = name in CONFIG
        is_source = name.endswith(SRC_ENDINGS) or (
            name.startswith(XML_PREFIXES) and name.endswith(".xml"))
        if not is_source and not is_manifest:
            continue
        if len(files) + len(manifests) >= MAX_INPUTS:
            incomplete = True
            continue
        text, sha, size = jvm._read(root, name, index.MAX_FILE_BYTES if is_source else 512 * 1024)
        total += size
        if total > MAX_BYTES:
            incomplete = True
            break
        item = {"path": name, "sha256": sha, "bytes": size}
        if is_manifest:
            manifests[name] = item
            digest_m.update(name.encode() + b"\0" + sha.encode())
        if is_source:
            item["language"] = "Kotlin" if name.endswith(".kt") else (
                "Java" if name.endswith(".java") else "Android XML")
            if name.endswith(SRC_ENDINGS):
                package = JAVA_PACKAGE.search(text[:16000])
                item["package"] = package.group(1) if package else None
                item["symbols"] = SYMBOL.findall(text[:30000])[:12]
                item["compose_hint"] = bool(COMPOSE.search(text[:30000]))
            files[name] = item
            digest_s.update(name.encode() + b"\0" + sha.encode())
    for name in CONFIG:
        candidate = root / name
        if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
            raise HTTPException(403, "Linked Android/Gradle build configuration forbidden.")
    return files, manifests, digest_s.hexdigest(), digest_m.hexdigest(), incomplete


def _manifest_meta(root: Path, manifests: dict) -> dict:
    root_build = next((x for x in ("build.gradle.kts", "build.gradle") if x in manifests), None)
    app_build = next((x for x in ("app/build.gradle.kts", "app/build.gradle") if x in manifests), None)
    settings = next((x for x in ("settings.gradle.kts", "settings.gradle") if x in manifests), None)
    wrapper = manifests.get("gradle/wrapper/gradle-wrapper.properties")
    scripts = []
    for name in (root_build, app_build, settings):
        if name:
            scripts.append(jvm._read(root, name)[0])
    combined = "\n".join(scripts)
    wrapper_ver = None
    if wrapper:
        content = jvm._read(root, wrapper["path"])[0]
        match = GRADLE_WRAPPER.search(content)
        wrapper_ver = match.group(1) if match else None
    agp = AGP_VERSION.search(combined)
    kgp = KOTLIN_VERSION.search(combined)
    agp_ver = agp.group(1) if agp else None
    kgp_ver = kgp.group(1) if kgp else None
    android = bool(app_build and ("com.android.application" in combined or
                                   "com.android.library" in combined))
    kotlin_jvm = bool(not android and ("org.jetbrains.kotlin.jvm" in combined or
                                       'kotlin("jvm")' in combined or "kotlin('jvm')" in combined))
    warnings = []
    if not settings or not root_build:
        warnings.append("Root settings and build Gradle scripts are both required.")
    if not android and not kotlin_jvm:
        warnings.append("Project is not a recognised Kotlin/JVM or single-module Android build.")
    if android and (not app_build or "app/src/main/AndroidManifest.xml" not in manifests):
        warnings.append("Android module build or AndroidManifest.xml is missing.")
    if settings:
        contents = jvm._read(root, settings)[0]
        if android and not re.search(r"include\s*\(?\s*[\"']:app[\"']", contents):
            warnings.append("Exactly one declared :app Android module is required.")
        if re.search(r"(?i)(includeBuild|flatDir|mavenLocal|credentials|username|password)", contents):
            warnings.append("Nonstandard Gradle settings need a separate build review.")
    if "gradle.properties" in manifests:
        warnings.append("Custom gradle.properties requires manual review (possible credentials).")
    if android and app_build:
        script = jvm._read(root, app_build)[0]
        if re.search(r"(?i)(signingConfigs|storePassword|keyPassword|applicationVariants|externalNativeBuild)", script):
            warnings.append("Android custom signing/native configuration needs human review.")
    if android and not agp_ver:
        warnings.append("Android Gradle plugin version cannot be verified from static scripts.")
    if not kgp_ver and kotlin_jvm:
        warnings.append("Kotlin plugin version not statically pinned.")
    if not kgp_ver and android and "org.jetbrains.kotlin.android" in combined:
        warnings.append("Kotlin Android plugin version not statically pinned.")
    version_advisory = "not_assessed"
    if agp_ver and wrapper_ver:
        minimum = AGP_MIN_GRADLE.get(".".join(agp_ver.split(".")[:2]))
        if minimum:
            parts = tuple(int(x) for x in wrapper_ver.split("."))
            parts += (0,) * max(0, len(minimum) - len(parts))
            required = minimum + (0,) * max(0, len(parts) - len(minimum))
            version_advisory = "declared_incompatible" if parts < required else "declared_minimum_met"
            if version_advisory == "declared_incompatible":
                warnings.append("Declared Android Gradle plugin requires a newer Gradle wrapper.")
    if android:
        try:
            xml = jvm._read(root, "app/src/main/AndroidManifest.xml")[0]
            manifest = SafeXML.fromstring(xml)
            if manifest.tag.rsplit("}", 1)[-1] != "manifest":
                raise HTTPException(422, "Invalid Android manifest root.")
            package = (manifest.attrib.get("package") or "")[:120]
        except (ValueError, SafeXML.ParseError) as exc:
            raise HTTPException(422, "Invalid or unsafe Android manifest XML.") from exc
    else:
        package = None
    return {"type": "android" if android else "kotlin_jvm" if kotlin_jvm else "unknown",
            "root_build": root_build, "app_build": app_build, "settings": settings,
            "wrapper_version": wrapper_ver, "agp_version": agp_ver,
            "kotlin_plugin_version": kgp_ver,
            "agp_gradle_advisory": version_advisory, "android_manifest_package": package,
            "compose_detected": bool(COMPOSE.search(combined)),
            "warnings": warnings}


def _sdk(root: Path) -> dict:
    # Read existing SDK paths only. Android SDK licensing/installation is NEVER
    # performed by inspection or approved Gradle tasks.
    result = {"status": "not_configured", "platforms": [], "build_tools": [],
              "adb_present": False, "emulator_present": False,
              "emulator_started": False, "device_connected": False}
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        raw = os.environ.get(key)
        if not raw or len(raw) > 2048:
            continue
        try:
            path = Path(raw).resolve(strict=True)
            if (not Path(raw).is_absolute() or not path.is_dir()
                    or adapters._disallowed_workspace_executable(path, root)):
                continue
            platforms = path / "platforms"
            build_tools = path / "build-tools"
            if not platforms.is_dir() or not build_tools.is_dir():
                continue
            result = {"status": "installed_not_executed", "root": str(path),
                      "platforms": sorted(p.name for p in platforms.iterdir()
                                          if p.is_dir() and re.fullmatch(r"android-\d{1,3}", p.name))[:20],
                      "build_tools": sorted(p.name for p in build_tools.iterdir()
                                            if p.is_dir() and re.fullmatch(r"\d+\.\d+\.\d+", p.name))[:20],
                      "adb_present": (path / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")).is_file(),
                      "emulator_present": (path / "emulator" / ("emulator.exe" if os.name == "nt" else "emulator")).is_file(),
                      "emulator_started": False, "device_connected": False}
            break
        except (OSError, ValueError):
            continue
    return result


def _tools(root: Path, sdk: dict) -> tuple[list[dict], str]:
    tools = []
    digest = hashlib.sha256(b"automoto-android-v23-tools\0")
    for name in TOOLS:
        location = shutil.which(name)
        if not location and name in ("adb", "emulator") and sdk.get("root"):
            location = str(Path(sdk["root"]) / ("platform-tools" if name == "adb" else "emulator") /
                           (name + (".exe" if os.name == "nt" else "")))
            if not Path(location).is_file():
                location = None
        if not location:
            item = {"name": name, "status": "unavailable"}
        elif Path(location).suffix.lower() in (".bat", ".cmd", ".ps1"):
            item = {"name": name, "status": "shell_wrapper_blocked"}
        else:
            try:
                item = {"name": name, "status": "installed_not_executed",
                        **adapters._fingerprint(str(Path(location).absolute()), root)}
            except HTTPException:
                item = {"name": name, "status": "untrusted_executable"}
        digest.update(name.encode() + b"\0" + item["status"].encode() + b"\0" +
                      item.get("sha256", "").encode() + b"\0" +
                      item.get("executable", "").encode())
        tools.append(item)
    return tools, digest.hexdigest()


def _inspect(root: Path) -> dict:
    files, manifests, sha_s, sha_m, incomplete = _inputs(root)
    meta = _manifest_meta(root, manifests)
    if incomplete or not files:
        meta["warnings"].append("Kotlin/Android source inventory is incomplete or empty.")
    sdk = _sdk(root)
    tools, sha_t = _tools(root, sdk)
    hints = sorted({"Jetpack Compose" for v in files.values() if v.get("compose_hint")} |
                   {"Jetpack Compose"} if meta["compose_detected"] else
                   {"Jetpack Compose" for v in files.values() if v.get("compose_hint")})
    return {"schema": SCHEMA, "project_type": meta["type"],
            "manifests": manifests, "files": list(files.values()),
            "symbols": [{"path": x["path"], "name": s} for x in files.values()
                        for s in x.get("symbols", [])][:90],
            "manifest_sha256": sha_m, "source_sha256": sha_s,
            "toolchain_sha256": sha_t, "scan_incomplete": incomplete,
            "gradle": {k: v for k, v in meta.items() if k != "warnings"},
            "warnings": meta["warnings"], "framework_hints": hints,
            "android_sdk": sdk, "toolchains": tools,
            "safe_to_offer_runs": not meta["warnings"] and not incomplete and bool(files),
            "emulator": "Emulator discovery only. No emulator, ADB device or app started by this Studio.",
            "kotlin_lsp": "Kotlin LSP support is conditional; use separately approved installed language server controls.",
            "project_trusted": studio._trusted(root, studio._load()),
            "project_code_executed": False, "gradle_wrapper_executed": False,
            "packages_downloaded": False, "deployment_started": False,
            "central_agent_studio": "developer", "agent_deployment_handoff_required": True}


def _copy(root: Path, data: dict, stage: Path) -> None:
    if data["scan_incomplete"] or not data["safe_to_offer_runs"]:
        raise HTTPException(409, "Android/Kotlin project requires review before execution.")
    paths = sorted({x["path"] for x in data["files"]} | set(data["manifests"]))
    if len(paths) > MAX_INPUTS:
        raise HTTPException(413, "Android project exceeds bounded staging limits.")
    total = 0
    for name in paths:
        text, sha, size = jvm._read(root, name, index.MAX_FILE_BYTES
                                   if name not in data["manifests"] else 512 * 1024)
        expected = data["manifests"].get(name)
        if expected is None:
            expected = next((x for x in data["files"] if x["path"] == name), None)
        if not expected or sha != expected["sha256"]:
            raise HTTPException(409, "Android/Kotlin project changed while copying.")
        total += size
        if total > MAX_BYTES:
            raise HTTPException(413, "Android project staging exceeds size cap.")
        dest = stage / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")


def _env(root: Path, temp: Path, sdk: dict) -> dict:
    env = adapters._environment(root)
    env.update({"GRADLE_USER_HOME": str(temp / "gradle-home"),
                "GRADLE_OPTS": "-Dorg.gradle.daemon=false",
                "JAVA_TOOL_OPTIONS": "-Dfile.encoding=UTF-8",
                "ANDROID_SDK_HOME": str(temp / "android-home")})
    for folder in (temp / "gradle-home", temp / "android-home"):
        folder.mkdir(mode=0o700)
    # Gradle's read-only dependency cache allows offline resolution of
    # previously obtained artifacts without granting the task write access
    # to the user's normal Gradle home. No cache present => clear failure.
    # Gradle requires GRADLE_RO_DEP_CACHE to point to the parent directory
    # containing modules-2, NOT to modules-2 itself. This directory is an
    # existing local dependency cache, not a network repository.
    cache = Path.home() / ".gradle" / "caches"
    if ((cache / "modules-2").is_dir() and not cache.is_symlink()
            and not (cache / "modules-2").is_symlink()):
        try:
            resolved = cache.resolve(strict=True)
            if not adapters._disallowed_workspace_executable(resolved, root):
                env["GRADLE_RO_DEP_CACHE"] = str(resolved)
        except (OSError, ValueError):
            pass
    if sdk["status"] == "installed_not_executed":
        env["ANDROID_HOME"] = sdk["root"]
        env["ANDROID_SDK_ROOT"] = sdk["root"]
    for value in jvm._locator_values(os.environ):
        home = jvm._approved_jdk_home(value, root)
        if home is not None:
            env["JAVA_HOME"] = str(home)
            break
    return env


def _run(root: Path, body: RunIn) -> dict:
    adapters._trusted(root)
    data = _inspect(root)
    if any(data[x] != getattr(body, "expected_" + x) for x in
           ("manifest_sha256", "source_sha256", "toolchain_sha256")):
        raise HTTPException(409, "Android/Kotlin project or executable changed since approval.")
    selected = next((t for t in data["toolchains"] if t["name"] == body.tool and
                     t["status"] == "installed_not_executed"), None)
    if (not selected or selected["sha256"] != body.expected_sha256 or
            selected["executable"] != body.expected_executable):
        raise HTTPException(409, "Tool executable differs from the approved SHA-256 fingerprint.")
    versions = {"gradle_version": ("gradle", ["--version"]),
                "java_version": ("java", ["-version"]),
                "adb_version": ("adb", ["version"])}
    if body.task in versions and body.tool != versions[body.task][0]:
        raise HTTPException(422, "Version query requires its matching approved executable.")
    if body.task not in versions:
        if body.tool != "gradle" or not data["safe_to_offer_runs"]:
            raise HTTPException(409, "Kotlin/Android execution requires an approved Gradle workspace.")
        if data["project_type"] == "android":
            if not body.task.startswith("android_"):
                raise HTTPException(422, "This is an Android Gradle project.")
            if (data["android_sdk"]["status"] != "installed_not_executed"
                    or not data["android_sdk"]["platforms"]
                    or not data["android_sdk"]["build_tools"]):
                raise HTTPException(409, "Installed Android SDK platform and build tools required.")
        elif data["project_type"] == "kotlin_jvm" and not body.task.startswith("kotlin_"):
            raise HTTPException(422, "This is a Kotlin/JVM Gradle project.")
        elif data["project_type"] not in ("android", "kotlin_jvm"):
            raise HTTPException(409, "Unsupported or incomplete Gradle project.")
    with tempfile.TemporaryDirectory(prefix="automoto-android23-") as tmp:
        temp = Path(tmp)
        stage = temp / "project"
        stage.mkdir(mode=0o700)
        if body.task not in versions:
            _copy(root, data, stage)
        env = _env(root, temp, data["android_sdk"])
        if body.task in versions:
            cmd = [selected["executable"], *versions[body.task][1]]
        else:
            task = {"kotlin_build": "build", "kotlin_test": "test",
                    "android_assemble": ":app:assembleDebug",
                    "android_unit_test": ":app:testDebugUnitTest"}[body.task]
            cmd = [selected["executable"], "--offline", "--no-daemon", "--console=plain",
                   "--gradle-user-home", str(temp / "gradle-home"), "-p", str(stage), task]
        latest = _inspect(root)
        if any(latest[x] != getattr(body, "expected_" + x) for x in
               ("manifest_sha256", "source_sha256", "toolchain_sha256")):
            raise HTTPException(409, "Android/Kotlin inputs changed during execution preparation.")
        adapters._trusted(root)
        result = native._execute(stage, cmd, env, timeout=MAX_SECONDS)
    return {"task": body.task, "status": result["status"],
            "output": result["output"], "exit_code": result["exit_code"],
            "elapsed_ms": result["elapsed_ms"],
            "temporary_project_deleted": True,
            "external_process_unsandboxed": True,
            "network_prevented_by_os": False, "build_requested_offline": body.task not in versions,
            "project_source_immutability_not_guaranteed": True,
            "emulator_started": False, "device_touched": False,
            "automatic_package_installation": False, "deployment_started": False,
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
        raise HTTPException(429, "A Kotlin/Android task is already running.")
    try:
        return _run(studio._project(body.project), body)
    finally:
        LOCK.release()
