"""Developer Studio V27 — Ruby, Lua, Perl, Groovy evidence and gated toolchains.

Inspection is inert. Ruby/Groovy project manifests and language sources are
never evaluated by discovery. External tools, even syntax checks or package
checks, are UNSANDBOXED and require explicit project trust, pinned SHA-256,
per-task consent and an independently reviewed local workspace.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_adapters as adapters
from automoto import developer_index as index
from automoto import developer_jvm as jvm
from automoto import developer_native as native
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/scripting", tags=["developer-scripting"])
VERSION = "1.0.0"
LOCK = threading.Lock()
MAX_SOURCE_BYTES = 128 * 1024
MAX_MANIFEST_BYTES = 512 * 1024
MAX_FILES = 125
MAX_TOTAL_BYTES = 9 * 1024 * 1024
TASK_SECONDS = 90

SUFFIX = {".rb": "ruby", ".rake": "ruby", ".gemspec": "ruby",
          ".lua": "lua", ".rockspec": "lua", ".pl": "perl", ".pm": "perl",
          ".t": "perl", ".groovy": "groovy", ".gvy": "groovy", ".gy": "groovy"}
MANIFESTS = {
    "Gemfile", "Gemfile.lock", ".ruby-version", ".rubocop.yml",
    "Rakefile", ".rspec", "gems.rb", "gems.locked",
    "cpanfile", "cpanfile.snapshot", "META.json", "META.yml",
    "Makefile.PL", "Build.PL", ".perltidyrc",
    ".luacheckrc", "rockspec", "build.gradle", "settings.gradle",
    "gradle.properties", "gradle/wrapper/gradle-wrapper.properties",
}
TOOLS = ("ruby", "gem", "bundle", "rubocop",
         "lua", "luac", "luarocks", "luacheck",
         "perl", "cpanm", "perltidy", "perlcritic",
         "groovy", "groovyc", "gradle", "codenarc")
VERSIONS = {"ruby": ["-v"], "gem": ["--version"], "bundle": ["--version"],
            "rubocop": ["--version"], "lua": ["-v"], "luac": ["-v"],
            "luarocks": ["--version"], "luacheck": ["--version"],
            "perl": ["-v"], "cpanm": ["--version"],
            "perltidy": ["--version"], "perlcritic": ["--version"],
            "groovy": ["--version"], "groovyc": ["--version"],
            "gradle": ["--version"], "codenarc": ["--version"]}
TESTS = {"test/fixture_test.rb": "ruby",
         "test/fixture_test.lua": "lua",
         "test/fixture_test.t": "perl",
         "test/FixtureTest.groovy": "groovy"}
SYMBOL = {
    "ruby": re.compile(r"(?m)^\s*(?:class|module|def)\s+([A-Za-z_]\w{0,70})"),
    "lua": re.compile(r"(?m)^\s*(?:local\s+)?function\s+([A-Za-z_]\w{0,70})"),
    "perl": re.compile(r"(?m)^\s*(?:sub|package)\s+([A-Za-z_]\w{0,70})"),
    "groovy": re.compile(r"(?m)^\s*(?:class|interface|trait|enum|def)\s+([A-Za-z_]\w{0,70})"),
}
RISKS = (
    ("external process", re.compile(
        r"(?i)\b(?:system|exec|spawn|ProcessBuilder|Runtime\.getRuntime|open3|fork|IO\.popen)\b")),
    ("network or dependency resolver", re.compile(
        r"(?i)\b(?:curl|wget|Net::HTTP|open-uri|LWP::UserAgent|HTTP::Tiny|"
        r"@Grab|@Grapes|Grape\.grab|luarocks\s+install|bundle\s+install)\b")),
    ("file deletion", re.compile(
        r"(?i)\b(?:FileUtils\.rm_rf|rm\s+-rf|unlink\b|rmtree\b|deleteDir\b)\b")),
    ("dynamic evaluation or startup hook", re.compile(
        r"(?i)\b(?:eval|BEGIN|END|load|instance_eval|class_eval|"
        r"method_missing|ASTTransformation|metaClass)\b")),
)
GEM = re.compile(r"""(?m)^\s*gem\s+["']([A-Za-z0-9_.-]{1,90})["']""")
CPAN = re.compile(r"""(?m)^\s*(?:requires|recommends|test_requires|build_requires)\s+["']([A-Za-z0-9_:.-]{1,90})["']""")
ROCKS = re.compile(r"""(?m)\b(?:dependencies|build_dependencies)\s*=\s*\{([^}]{0,8000})\}""")
GROOVY_DEP = re.compile(r"""(?m)^\s*(?:implementation|testImplementation|compileOnly|runtimeOnly)\s+["']([^"'\n]{1,140})["']""")
STYLE_LINE_LIMIT = 120

# Fixed executable operations only: no caller-supplied flags or environment.
TASK_TOOL = {
    "ruby_syntax": "ruby", "lua_syntax": "luac",
    "perl_syntax": "perl", "groovy_compile": "groovyc",
    "ruby_test": "ruby", "lua_test": "lua",
    "perl_test": "perl", "groovy_test": "groovy",
    "ruby_lint": "rubocop", "lua_lint": "luacheck",
    "ruby_bundle_check": "bundle",
}

class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    task: Literal["version", "ruby_syntax", "lua_syntax", "perl_syntax",
                  "groovy_compile", "ruby_test", "lua_test", "perl_test", "groovy_test",
                  "ruby_lint", "lua_lint", "ruby_bundle_check"]
    tool: Literal["ruby", "gem", "bundle", "rubocop", "lua", "luac", "luarocks",
                  "luacheck", "perl", "cpanm", "perltidy", "perlcritic",
                  "groovy", "groovyc", "gradle", "codenarc"]
    source: str = Field(default="", max_length=240, pattern=r"^[A-Za-z0-9_./-]*$")
    expected_inventory_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_toolchain_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_script_and_package_risk: Literal[True]


def _language(path: str) -> str | None:
    return SUFFIX.get(Path(path).suffix.lower())


def _relevant(path: str) -> tuple[str | None, bool]:
    leaf = path.rsplit("/", 1)[-1]
    lang = _language(path)
    is_config = path in MANIFESTS or (
        "/" not in path and (leaf.endswith(".gemspec") or leaf.endswith(".rockspec"))
    )
    # Manifest scripts are NOT accepted as test or syntax sources.
    if leaf.endswith((".gemspec", ".rockspec")) or path in {"Rakefile", "Makefile.PL", "Build.PL"}:
        lang = None
    return lang, is_config


def _hints(source: str) -> list[dict]:
    issues = []
    for i, line in enumerate(source.splitlines()[:1200], 1):
        if len(issues) >= 30:
            break
        if line.rstrip(" \t") != line:
            issues.append({"line": i, "kind": "trailing whitespace"})
        if len(line) > STYLE_LINE_LIMIT:
            issues.append({"line": i, "kind": "line longer than 120 characters"})
        if line.startswith("\t"):
            issues.append({"line": i, "kind": "tab indentation"})
    if source and not source.endswith("\n"):
        issues.append({"line": source.count("\n") + 1, "kind": "missing final newline"})
    return issues[:30]


def _inventory(root: Path) -> tuple[list[dict], dict, str, bool]:
    files, manifests, total, incomplete = [], {}, 0, False
    digest = hashlib.sha256(b"automoto-v27-scripting-inventory\0")
    for path, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        lang, is_config = _relevant(path)
        if not lang and not is_config:
            continue
        if len(files) + len(manifests) >= MAX_FILES:
            incomplete = True
            break
        text, sha, size = jvm._read(root, path,
                                    MAX_MANIFEST_BYTES if is_config else MAX_SOURCE_BYTES)
        total += size
        if total > MAX_TOTAL_BYTES:
            incomplete = True
            break
        digest.update(path.encode() + b"\0" + sha.encode() + b"\0")
        risk = [{"kind": kind, "line": text[:match.start()].count("\n") + 1}
                for kind, rx in RISKS if (match := rx.search(text[:MAX_MANIFEST_BYTES]))]
        if is_config:
            manifests[path] = {"path": path, "sha256": sha, "bytes": size,
                               "risk_signals": risk[:12],
                               "evaluated": False}
        if lang:
            files.append({"path": path, "language": lang, "sha256": sha,
                          "bytes": size, "symbols": SYMBOL[lang].findall(text[:30000])[:20],
                          "style_hints": _hints(text), "risk_signals": risk[:12],
                          "fixture_test_path": TESTS.get(path) == lang,
                          "project_code_executed": False})
    # Failure closed for common root build metadata symlinks, rather than
    # silently accepting a missing config file omitted by the index walker.
    for name in MANIFESTS:
        path = root / name
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise HTTPException(403, "Linked package manifest is not admitted.")
    return files, manifests, digest.hexdigest(), incomplete


def _packages(root: Path, manifests: dict) -> dict:
    result = {"ruby": [], "lua": [], "perl": [], "groovy": [],
              "parsed_only": True, "network_used": False,
              "install_started": False, "manifests_evaluated": False}
    if "Gemfile" in manifests:
        text = jvm._read(root, "Gemfile", MAX_MANIFEST_BYTES)[0]
        result["ruby"] = sorted(set(GEM.findall(text)))[:80]
    rocks = [p for p in manifests if p.endswith(".rockspec")]
    for path in rocks[:4]:
        text = jvm._read(root, path, MAX_MANIFEST_BYTES)[0]
        for deps in ROCKS.findall(text):
            result["lua"].extend(re.findall(r"""["']([A-Za-z0-9_.-]{1,90})""", deps)[:50])
    if "cpanfile" in manifests:
        text = jvm._read(root, "cpanfile", MAX_MANIFEST_BYTES)[0]
        result["perl"] = sorted(set(CPAN.findall(text)))[:80]
    if "build.gradle" in manifests:
        text = jvm._read(root, "build.gradle", MAX_MANIFEST_BYTES)[0]
        result["groovy"] = sorted(set(GROOVY_DEP.findall(text)))[:80]
    return result


def _tools(root: Path) -> tuple[list[dict], str]:
    items, digest = [], hashlib.sha256(b"automoto-v27-scripting-tooling\0")
    for name in TOOLS:
        found = shutil.which(name)
        if not found:
            item = {"name": name, "status": "unavailable"}
        elif Path(found).suffix.lower() in (".cmd", ".bat", ".ps1"):
            item = {"name": name, "status": "shell_wrapper_blocked"}
        else:
            try:
                item = {"name": name, "status": "installed_not_executed",
                        **adapters._fingerprint(str(Path(found).absolute()), root)}
            except HTTPException:
                item = {"name": name, "status": "untrusted_executable"}
        items.append(item)
        digest.update(name.encode() + b"\0" + item["status"].encode() + b"\0" +
                      item.get("executable", "").encode() + b"\0" +
                      item.get("sha256", "").encode())
    return items, digest.hexdigest()


def _inspect(root: Path) -> dict:
    files, manifests, sha, incomplete = _inventory(root)
    tools, tool_sha = _tools(root)
    packages = _packages(root, manifests)
    counts = {key: sum(file["language"] == key for file in files)
              for key in ("ruby", "lua", "perl", "groovy")}
    return {"schema": VERSION, "files": files, "manifests": manifests,
            "packages": packages, "language_counts": counts,
            "inventory_sha256": sha, "toolchain_sha256": tool_sha,
            "toolchains": tools, "scan_incomplete": incomplete,
            "warnings": (["Bounded scan incomplete; external tasks refused."] if incomplete else []),
            "formatting": "Read-only cross-language whitespace hints. Ruby RuboCop and Lua Luacheck available only with installed, separately approved tool; Perl/Groovy formatters are discovery-only in V27.",
            "test_policy": "Only fixed test/fixture_test.* paths run by individually consented installed interpreters.",
            "platform": sys.platform,
            "project_trusted": studio._trusted(root, studio._load()),
            "scripts_executed": False, "language_tool_versions_queried": False,
            "package_installation_started": False, "network_access_started": False,
            "operating_system_sandboxed": False, "deployment_started": False,
            "central_agent_studio": "developer",
            "agent_deployment_handoff_required": True}


def _select(data: dict, name: str) -> dict:
    if not name or name.startswith("/") or "\\" in name or ".." in name.split("/"):
        raise HTTPException(422, "Select an inventoried project-relative source.")
    entry = next((f for f in data["files"] if f["path"] == name), None)
    if not entry:
        raise HTTPException(404, "Source was not found in bounded inventory.")
    if data["scan_incomplete"]:
        raise HTTPException(409, "Source scan incomplete; refuse tool execution.")
    return entry


def _stage(root: Path, data: dict, stage: Path) -> None:
    entries = {x["path"]: x for x in data["files"]}
    entries.update(data["manifests"])
    total = 0
    for name, item in sorted(entries.items()):
        if not name or name.startswith("/") or "\\" in name or ".." in name.split("/"):
            raise HTTPException(403, "Unsafe stage path.")
        _, sha, size = jvm._read(root, name, MAX_MANIFEST_BYTES
                                 if name in data["manifests"] else MAX_SOURCE_BYTES)
        if sha != item["sha256"]:
            raise HTTPException(409, "Staged source/manifest changed after consent.")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(413, "Staged project exceeds maximum size.")
        # Open the source with no-follow and verify the actual bytes staged.
        # A second symlink/contents switch must not turn an approved source
        # into an unreviewed script between inventory and execution.
        source = studio._path(root, name)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(source, flags)
            with os.fdopen(fd, "rb") as handle:
                meta = os.fstat(handle.fileno())
                if not stat.S_ISREG(meta.st_mode) or meta.st_size > size:
                    raise HTTPException(409, "Staged source changed size or type.")
                raw = handle.read(size + 1)
        except OSError as exc:
            raise HTTPException(403, "Cannot stage approved regular source.") from exc
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise HTTPException(409, "Source bytes changed during staging.")
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)


def _env(root: Path, tmp: Path, stage: Path) -> dict:
    env = adapters._environment(root)
    for name in ("home", "tmp", "gem-cache", "groovy-cache", "groovy-output"):
        (tmp / name).mkdir(mode=0o700)
    env.update({
        "HOME": str(tmp / "home"), "TMPDIR": str(tmp / "tmp"),
        "GEM_HOME": str(tmp / "gem-cache"), "GEM_PATH": str(tmp / "gem-cache"),
        "BUNDLE_FROZEN": "true", "BUNDLE_DISABLE_SHARED_GEMS": "true",
        "GROOVY_USER_HOME": str(tmp / "groovy-cache"),
        "PERL5LIB": str(stage / "lib"), "LUA_PATH": str(stage / "?.lua") + ";" +
                    str(stage / "?/init.lua"),
        "RUBYOPT": "", "RUBYGEMS_GEMDEPS": "", "CI": "true",
    })
    # Groovy and Gradle use a host Java SDK; only a fully qualified local
    # externally installed JDK path is inherited as an explicit prerequisite.
    java = os.environ.get("JAVA_HOME", "")
    if java and Path(java).is_absolute():
        try:
            resolved = Path(java).resolve(strict=True)
            if resolved.is_dir() and not adapters._disallowed_workspace_executable(resolved, root):
                env["JAVA_HOME"] = str(resolved)
        except (OSError, ValueError):
            pass
    return env


def _command(body: RunIn, data: dict, tool: dict, stage: Path, tmp: Path) -> list[str]:
    exe = tool["executable"]
    if body.task == "version":
        if body.source:
            raise HTTPException(422, "Version query must not specify a source.")
        return [exe, *VERSIONS[body.tool]]
    entry = _select(data, body.source) if body.task != "ruby_bundle_check" else None
    if body.task == "ruby_bundle_check":
        if body.tool != "bundle" or "Gemfile" not in data["manifests"]:
            raise HTTPException(409, "Bundler check requires an inspected Gemfile and Bundler executable.")
        if "Gemfile.lock" not in data["manifests"]:
            raise HTTPException(409, "Bundler lockfile must be present for offline check.")
        return [exe, "check"]
    if entry is None:
        raise HTTPException(422, "Source not found.")
    file = str(stage / entry["path"])
    if body.task in TASK_TOOL and body.tool != TASK_TOOL[body.task]:
        raise HTTPException(422, "Interpreter/tool mismatch for fixed scripting task.")
    if body.task == "ruby_syntax" and entry["language"] == "ruby":
        return [exe, "-c", file]
    if body.task == "lua_syntax" and entry["language"] == "lua":
        return [exe, "-p", file]
    if body.task == "perl_syntax" and entry["language"] == "perl":
        return [exe, "-c", file]
    if body.task == "groovy_compile" and entry["language"] == "groovy":
        return [exe, "-d", str(tmp / "groovy-output"), file]
    if body.task.endswith("_test"):
        expected = body.task.removesuffix("_test")
        if entry["language"] != expected or TESTS.get(entry["path"]) != expected:
            raise HTTPException(403, "Only canonical per-language fixture test paths may execute.")
        if expected == "ruby":
            return [exe, "-Ilib", file]
        if expected == "lua":
            return [exe, file]
        if expected == "perl":
            return [exe, "-Ilib", file]
        if expected == "groovy":
            return [exe, "-cp", str(stage / "lib"), file]
    if body.task == "ruby_lint" and entry["language"] == "ruby":
        return [exe, "--format", "simple", "--force-exclusion", file]
    if body.task == "lua_lint" and entry["language"] == "lua":
        return [exe, "--no-config", "--no-color", file]
    raise HTTPException(422, "Task not available for selected source and interpreter.")


def _run(root: Path, body: RunIn) -> dict:
    adapters._trusted(root)
    snapshot = _inspect(root)
    if snapshot["inventory_sha256"] != body.expected_inventory_sha256 or (
            snapshot["toolchain_sha256"] != body.expected_toolchain_sha256):
        raise HTTPException(409, "Scripting source or installed toolchain changed since approval.")
    exe = next((t for t in snapshot["toolchains"] if t["name"] == body.tool and
                t["status"] == "installed_not_executed"), None)
    if (not exe or exe.get("sha256") != body.expected_sha256 or
            exe.get("executable") != body.expected_executable):
        raise HTTPException(409, "Scripting interpreter fingerprint differs from approval.")
    if body.task != "version" and snapshot["scan_incomplete"]:
        raise HTTPException(409, "Scripting source inventory incomplete.")
    with tempfile.TemporaryDirectory(prefix="automoto-scripting27-") as folder:
        tmp = Path(folder)
        stage = tmp / "project"
        stage.mkdir(mode=0o700)
        if body.task != "version":
            _stage(root, snapshot, stage)
        env = _env(root, tmp, stage)
        cmd = _command(body, snapshot, exe, stage, tmp)
        current = _inspect(root)
        if (current["inventory_sha256"] != body.expected_inventory_sha256 or
                current["toolchain_sha256"] != body.expected_toolchain_sha256):
            raise HTTPException(409, "Scripting source changed during staging.")
        adapters._trusted(root)
        start = time.monotonic()
        result = native._execute(stage, cmd, env, timeout=TASK_SECONDS)
    return {"task": body.task, "source": body.source,
            "status": result["status"], "exit_code": result["exit_code"],
            "output": result["output"][:native.MAX_OUTPUT],
            "elapsed_ms": int((time.monotonic() - start) * 1000),
            "temporary_copy_deleted": True,
            "arbitrary_command_arguments_allowed": False,
            "external_code_unsandboxed": True, "os_network_isolation": False,
            "package_installation_performed": False,
            "deployment_started": False, "agent_handoff_created": False,
            "central_agent_studio": "developer"}


@router.get("/inspect")
def inspect(request: Request, project: str):
    studio._auth(request)
    return _inspect(studio._project(project))


@router.post("/run")
def run(request: Request, body: RunIn):
    studio._auth(request)
    if not LOCK.acquire(blocking=False):
        raise HTTPException(429, "A scripting language tool task is already executing.")
    try:
        return _run(studio._project(body.project), body)
    finally:
        LOCK.release()
