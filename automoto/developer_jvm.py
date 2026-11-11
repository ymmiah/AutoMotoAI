"""Developer Studio V21: evidence-first Java/JVM and approval-gated JDK/Maven/Gradle.

Inspection never runs a tool. Builds and tests run in a private COPY of the
approved project, under the local user's real privileges; this does NOT
provide an OS, filesystem, or network sandbox. Java build tools may execute
arbitrary plugins, annotation processors and test code.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tempfile
import threading
from pathlib import Path
from typing import Literal

from defusedxml import ElementTree as SafeXML
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_adapters as adapters
from automoto import developer_index as index
from automoto import developer_native as native
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/jvm", tags=["developer-jvm"])
VERSION = "1.0.0"
MAX_MANIFEST = 512 * 1024
MAX_SOURCES = 80
MAX_STAGE = 8 * 1024 * 1024
LOCK = threading.Lock()
MANIFESTS = {
    "pom.xml", "build.gradle", "build.gradle.kts",
    "settings.gradle", "settings.gradle.kts", "gradle.properties",
    "gradle/wrapper/gradle-wrapper.properties", "gradle/libs.versions.toml",
    ".mvn/maven.config", ".mvn/jvm.config",
}
TASKS = ("jdk_version", "javac_version", "maven_version", "gradle_version",
         "jdk_compile", "jdk_smoke", "maven_test", "gradle_build", "gradle_test")
TOOLS = ("java", "javac", "mvn", "gradle", "jdtls")
SRC = (".java", ".kt")
PACKAGE = re.compile(r"(?m)^\s*package\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*){0,20})\s*;?")
CLASS = re.compile(r"(?m)\b(?:class|interface|enum|record)\s+([A-Za-z_]\w{0,90})")
MAIN = re.compile(r"\bstatic\s+void\s+main\s*\(\s*(?:String\s*\[\s*\]|String\s*\.\.\.)")
FRAMEWORKS = {
    "Spring": re.compile(r"(?i)org\.springframework|SpringBootApplication|spring-boot-starter"),
    "JUnit Jupiter": re.compile(r"org\.junit\.jupiter|junit-jupiter"),
    "JUnit 4": re.compile(r"org\.junit\.Test\b|junit:junit"),
    "Kotlin": re.compile(r"org\.jetbrains\.kotlin|kotlin\("),
}
GRADLE_WRAPPER_VERSION = re.compile(r"gradle-(\d+\.\d+(?:\.\d+)?)-(?:bin|all)\.zip")
GRADLE_JDK_RELEASE = re.compile(
    r"(?:JavaLanguageVersion\.of\(|JavaVersion\.VERSION_|sourceCompatibility\s*=\s*['\"]?)"
    r"(\d{1,2})\b"
)
# Official Gradle compatibility matrix, verified November 2026; an advisory,
# never a claim that a particular local JDK has been executed or certified.
GRADLE_MIN_FOR_RUNTIME = {17: (7, 3), 21: (8, 5), 25: (9, 1)}


class RootIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)


class RunIn(RootIn):
    task: Literal["jdk_version", "javac_version", "maven_version", "gradle_version",
                  "jdk_compile", "jdk_smoke", "maven_test", "gradle_build", "gradle_test"]
    tool: Literal["java", "javac", "mvn", "gradle"]
    expected_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_toolchain_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_build_test_and_network_risk: Literal[True]


def _read(root: Path, relative: str, size: int = MAX_MANIFEST) -> tuple[str, str, int]:
    segments = relative.split("/")
    if any(index._excluded(part, i < len(segments) - 1)
           for i, part in enumerate(segments)):
        raise HTTPException(403, "Restricted JVM project input.")
    path = studio._path(root, relative)
    if path == root:
        raise HTTPException(422, "Expected a regular project file.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            meta = os.fstat(stream.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_size > size:
                raise HTTPException(413, "JVM file exceeds inspection bounds.")
            raw = stream.read(size + 1)
        if len(raw) > size or b"\x00" in raw:
            raise HTTPException(413, "JVM input too large or binary.")
        return raw.decode("utf-8-sig"), hashlib.sha256(raw).hexdigest(), len(raw)
    except (UnicodeError, OSError) as exc:
        raise HTTPException(403, "JVM input cannot be safely read.") from exc


def _maven_info(xml: str) -> dict:
    try:
        root = SafeXML.fromstring(xml)
    except (ValueError, SafeXML.ParseError) as exc:
        raise HTTPException(422, "Maven pom.xml is invalid or unsafe XML.") from exc

    def child(parent, name):
        return next((x for x in parent if x.tag.split("}")[-1] == name), None) if parent is not None else None

    def scalar(parent, name):
        value = child(parent, name)
        return (value.text or "").strip()[:100] if value is not None else ""

    props = child(root, "properties")
    java_version = (scalar(props, "maven.compiler.release")
                    or scalar(props, "java.version")
                    or scalar(props, "maven.compiler.source"))
    compiler = child(child(child(root, "build"), "plugins"), "plugin")
    if not java_version and compiler is not None:
        java_version = scalar(child(compiler, "configuration"), "release")
    dependencies = child(root, "dependencies")
    coords = []
    for dep in list(dependencies)[:100] if dependencies is not None else []:
        if dep.tag.split("}")[-1] != "dependency":
            continue
        coords.append((scalar(dep, "groupId") + ":" + scalar(dep, "artifactId"))[:160])
    name = scalar(root, "artifactId")
    if not name or len(name) > 100:
        raise HTTPException(422, "Maven artifactId is missing or invalid.")
    return {"artifact": name, "java_release": java_version[:20],
            "dependencies": coords[:35], "pom_valid": True}


def _gradle_evidence(files: dict[str, str]) -> dict:
    combined = "\n".join(files.get(x, "") for x in
                         ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"))
    wrapper = files.get("gradle/wrapper/gradle-wrapper.properties", "")
    match = GRADLE_WRAPPER_VERSION.search(wrapper)
    release = GRADLE_JDK_RELEASE.search(combined)
    wrapper_version = match.group(1) if match else None
    target = int(release.group(1)) if release else None
    compatibility = "not_assessed"
    if target is not None and wrapper_version is not None and target in GRADLE_MIN_FOR_RUNTIME:
        parts = [int(x) for x in wrapper_version.split(".")[:2]]
        compatibility = ("potential_version_mismatch"
                         if tuple(parts) < GRADLE_MIN_FOR_RUNTIME[target]
                         else "declared_range_matches_reference")
    return {"wrapper_version": wrapper_version, "declared_java": target,
            "compatibility": compatibility,
            "wrapper_executed": False, "wrapper_downloaded": False}


def _manifests(root: Path) -> tuple[dict, dict[str, str]]:
    files = {}
    text_files = {}
    incomplete = False
    warnings = []
    for relative, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        if relative not in MANIFESTS:
            continue
        text, sha, size = _read(root, relative)
        files[relative] = {"sha256": sha, "bytes": size}
        text_files[relative] = text
    # Linked root JVM build control files must never be treated as "missing".
    for name in MANIFESTS:
        candidate = root / name
        if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
            raise HTTPException(403, "Linked JVM build configuration is forbidden.")
    maven = "pom.xml" in files
    gradle = any(x in files for x in ("build.gradle", "build.gradle.kts"))
    if not maven and not gradle:
        warnings.append("No Maven pom.xml or Gradle build script found.")
    if maven and gradle:
        warnings.append("Ambiguous Maven/Gradle root requires a manually selected build.")
    if ".mvn/maven.config" in files or ".mvn/jvm.config" in files:
        warnings.append("Custom Maven config or JVM flags require manual review.")
    if incomplete:
        warnings.append("JVM manifest discovery was incomplete.")
    maven_details = _maven_info(text_files["pom.xml"]) if maven else None
    gradle_details = _gradle_evidence(text_files) if gradle else None
    if gradle_details and gradle_details["compatibility"] == "potential_version_mismatch":
        warnings.append("Declared Java/Gradle wrapper versions may be incompatible.")
    digest = hashlib.sha256(b"automoto-jvm-v21-manifests\0")
    for file, info in sorted(files.items()):
        digest.update(file.encode() + b"\0" + info["sha256"].encode("ascii"))
    return {"manifests": files, "maven": maven_details, "gradle": gradle_details,
            "build_system": "maven" if maven and not gradle else "gradle" if gradle and not maven else "ambiguous" if maven and gradle else "jdk_only",
            "warnings": warnings,
            "safe_to_offer_builds": bool(maven != gradle) and not warnings,
            "manifest_sha256": digest.hexdigest()}, text_files


def _source(root: Path) -> dict:
    files, detected, main_classes = [], set(), []
    digest = hashlib.sha256(b"automoto-jvm-v21-sources\0")
    incomplete = False
    symbols = []
    total = 0
    for relative, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        if not relative.endswith(SRC) or relative.endswith(".gradle.kts"):
            continue
        if len(files) >= MAX_SOURCES:
            incomplete = True
            continue
        record = index._source(root, relative)
        if not record:
            incomplete = True
            continue
        content, sha, size = record
        total += size
        if total > MAX_STAGE:
            incomplete = True
            break
        package = PACKAGE.search(content[:16000])
        package_name = package.group(1) if package else ""
        classes = CLASS.findall(content[:20000])[:16]
        found = [name for name, regex in FRAMEWORKS.items() if regex.search(content[:30000])]
        detected.update(found)
        if relative.endswith(".java") and MAIN.search(content[:30000]) and classes:
            main_classes.append({"file": relative,
                                 "class": package_name + "." + classes[0] if package_name else classes[0],
                                 "test": "/test/" in "/" + relative})
        files.append({"path": relative, "sha256": sha, "bytes": size,
                      "language": "Kotlin" if relative.endswith(".kt") else "Java",
                      "package": package_name, "classes": classes,
                      "framework_hints": found})
        symbols.extend({"path": relative, "name": x} for x in classes[:5])
        digest.update(relative.encode() + b"\0" + sha.encode("ascii"))
    return {"files": files, "symbols": symbols[:80],
            "frameworks": sorted(detected), "main_classes": main_classes[:20],
            "source_sha256": digest.hexdigest(), "incomplete": incomplete,
            "bytes": total}


def _tools(root: Path) -> tuple[list[dict], str]:
    items = []
    digest = hashlib.sha256(b"automoto-jvm-v21-tools\0")
    for name in TOOLS:
        location = shutil.which(name)
        if location is None:
            entry = {"name": name, "status": "unavailable"}
        elif Path(location).suffix.lower() in (".cmd", ".bat", ".ps1"):
            entry = {"name": name, "status": "shell_wrapper_blocked"}
        else:
            try:
                entry = {"name": name, "status": "installed_not_executed",
                         **adapters._fingerprint(str(Path(location).absolute()), root)}
            except HTTPException:
                entry = {"name": name, "status": "not_approved"}
        items.append(entry)
        digest.update(name.encode() + b"\0" + entry["status"].encode() + b"\0" +
                      entry.get("sha256", "").encode())
    return items, digest.hexdigest()


def _inspect(root: Path) -> dict:
    manifest, _ = _manifests(root)
    source = _source(root)
    if source["incomplete"] or not source["files"]:
        manifest["warnings"].append("JVM source inventory is empty or incomplete.")
        manifest["safe_to_offer_builds"] = False
    tools, fingerprint = _tools(root)
    hints = sorted(set(source["frameworks"]) |
                   {"JUnit Jupiter" for x in (manifest["maven"] or {}).get("dependencies", [])
                    if "junit-jupiter" in x} |
                   {"Spring" for x in (manifest["maven"] or {}).get("dependencies", [])
                    if "spring-boot" in x})
    return {"schema": VERSION, **manifest, **source,
            "toolchain_sha256": fingerprint, "toolchains": tools,
            "framework_hints": hints,
            "jdtls": "Use existing separately approved Java LSP when installed; not started by inspection.",
            "project_trusted": studio._trusted(root, studio._load()),
            "project_code_executed": False, "dependency_download_requested": False,
            "central_agent_studio": "developer", "agent_deployment_handoff_required": True,
            "deployment_started": False}


def _tool(summary: dict, name: str) -> dict:
    selected = next((x for x in summary["toolchains"] if x["name"] == name
                     and x["status"] == "installed_not_executed"), None)
    if selected is None:
        raise HTTPException(409, "Required installed JVM tool is unavailable.")
    return selected


def _commands(body: RunIn, summary: dict, stage: Path, temp: Path) -> list[tuple[str, list[str]]]:
    tool = _tool(summary, body.tool)
    cmd = tool["executable"]
    version = {"jdk_version": "java", "javac_version": "javac",
               "maven_version": "mvn", "gradle_version": "gradle"}
    if body.task in version:
        if body.tool != version[body.task]:
            raise HTTPException(422, "Version task does not match selected JVM tool.")
        return [("version", [cmd, "-version" if body.tool == "java" else "--version"
                             if body.tool in ("mvn", "gradle") else "-version"])]
    if summary["incomplete"] or not summary["files"]:
        raise HTTPException(409, "JVM source scan is incomplete.")
    if body.task in ("jdk_compile", "jdk_smoke"):
        if body.tool != "javac":
            raise HTTPException(422, "JDK compilation requires verified javac.")
        _tool(summary, "java")
        java_sources = [str(stage / x["path"]) for x in summary["files"]
                        if x["language"] == "Java"]
        if not java_sources or len(java_sources) > 64:
            raise HTTPException(409, "A bounded Java source set is required.")
        build = temp / "jdk-classes"
        build.mkdir()
        commands = [("compile", [cmd, "-encoding", "UTF-8", "-d", str(build),
                                 *java_sources])]
        if body.task == "jdk_smoke":
            options = [x for x in summary["main_classes"] if x["test"]]
            if len(options) != 1:
                raise HTTPException(409, "Exactly one in-root test main class is required.")
            commands.append(("smoke", [_tool(summary, "java")["executable"],
                                        "-cp", str(build), options[0]["class"]]))
        return commands
    if not summary["safe_to_offer_builds"]:
        raise HTTPException(409, "JVM build script requires human review.")
    if body.task == "maven_test":
        if body.tool != "mvn" or summary["build_system"] != "maven":
            raise HTTPException(422, "Maven task requires an unambiguous Maven project.")
        return [("maven_test", [cmd, "--offline", "-B", "-ntp", "test"])]
    if body.task in ("gradle_build", "gradle_test"):
        if body.tool != "gradle" or summary["build_system"] != "gradle":
            raise HTTPException(422, "Gradle task requires an unambiguous Gradle project.")
        return [("gradle", [cmd, "--offline", "--no-daemon", "--console=plain",
                            "--gradle-user-home", str(temp / "gradle-home"),
                            "--project-cache-dir", str(temp / "gradle-cache"),
                            "build" if body.task == "gradle_build" else "test"])]
    raise HTTPException(422, "Unsupported fixed JVM task.")


def _copy(root: Path, summary: dict, destination: Path) -> None:
    total = 0
    paths = sorted(set(summary["manifests"]) | {item["path"] for item in summary["files"]})
    if len(paths) > MAX_SOURCES + len(MANIFESTS) or summary["incomplete"]:
        raise HTTPException(409, "JVM source staging is incomplete.")
    for relative in paths:
        # Check content hash and no-follow path again, including manifest
        # content after the user consented to the snapshot.
        text, sha, size = _read(root, relative, MAX_STAGE)
        expected = (summary["manifests"].get(relative, {})
                    .get("sha256") or next(
                        (item["sha256"] for item in summary["files"]
                         if item["path"] == relative), None))
        if sha != expected:
            raise HTTPException(409, "JVM file changed during safe staging.")
        total += size
        if total > MAX_STAGE:
            raise HTTPException(413, "JVM staging exceeds the supported project size.")
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")


def _environment(root: Path, summary: dict) -> dict:
    env = adapters._environment(root)
    java = _tool(summary, "java")
    executable = Path(java["executable"])
    if executable.parent.name.lower() != "bin":
        raise HTTPException(409, "Installed Java path cannot identify a JDK home.")
    env["JAVA_HOME"] = str(executable.parent.parent)
    env["JAVA_TOOL_OPTIONS"] = "-Dfile.encoding=UTF-8"
    env["GRADLE_OPTS"] = "-Dorg.gradle.daemon=false"
    env["MAVEN_OPTS"] = "-Djava.awt.headless=true"
    return env


def _run(root: Path, body: RunIn) -> dict:
    adapters._trusted(root)
    before = _inspect(root)
    if (before["manifest_sha256"] != body.expected_manifest_sha256 or
            before["source_sha256"] != body.expected_source_sha256 or
            before["toolchain_sha256"] != body.expected_toolchain_sha256):
        raise HTTPException(409, "JVM source/build/toolchain changed since consent.")
    selected = _tool(before, body.tool)
    if (selected["executable"] != body.expected_executable or
            selected["sha256"] != body.expected_sha256):
        raise HTTPException(409, "JVM tool executable changed since inspection.")
    with tempfile.TemporaryDirectory(prefix="automoto-jvm21-") as tempdir:
        temp = Path(tempdir)
        staged = temp / "project"
        staged.mkdir()
        _copy(root, before, staged)
        commands = _commands(body, before, staged, temp)
        env = _environment(root, before)
        stages = []
        for label, args in commands:
            latest = _inspect(root)
            if (latest["manifest_sha256"] != body.expected_manifest_sha256 or
                    latest["source_sha256"] != body.expected_source_sha256 or
                    latest["toolchain_sha256"] != body.expected_toolchain_sha256):
                raise HTTPException(409, "JVM inputs or installed tools changed before execution.")
            _copy(root, before, staged)
            adapters._trusted(root)
            # Actual external processes operate on a throw-away project COPY.
            result = native._execute(staged, args, env, timeout=90)
            stages.append({"stage": label, **result})
            if result["status"] != "completed":
                break
    output = "\n".join("## " + item["stage"] + "\n" + item["output"] for item in stages)
    failure = next((x for x in stages if x["status"] != "completed"), None)
    return {"task": body.task, "status": failure["status"] if failure else "completed",
            "stages": [{"stage": x["stage"], "status": x["status"],
                        "exit_code": x["exit_code"]} for x in stages],
            "output": output[:96 * 1024],
            "manifest_sha256": body.expected_manifest_sha256,
            "source_sha256": body.expected_source_sha256,
            "temporary_project_deleted": True,
            "original_source_changes_by_tool": "not_os_blocked",
            "external_process_unsandboxed": True,
            "network_prevented_by_os": False,
            "package_download_performed_by_app": False,
            "junit_tests_inferred": "JUnit Jupiter" in before["framework_hints"],
            "jvm_project": before["build_system"],
            "central_agent_studio": "developer",
            "agent_handoff_created": False, "agent_deployment_approved": False,
            "deployment_started": False}


@router.get("/inspect")
def inspect(request: Request, project: str):
    studio._auth(request)
    return _inspect(studio._project(project))


@router.post("/run")
def run(request: Request, body: RunIn):
    studio._auth(request)
    root = studio._project(body.project)
    if not LOCK.acquire(blocking=False):
        raise HTTPException(429, "A Java/JVM tool is already running.")
    try:
        return _run(root, body)
    finally:
        LOCK.release()
