"""Developer Studio V35: emerging languages (Zig, Mojo, Odin, MoonBit, Nim, Crystal).

Inspection is inert: it reads bounded source files and manifests, fingerprints
installed toolchains without running them, and attaches AutoMoto's own
version-aware capability notes. A separate approved "toolchain check" builds
and runs a tiny example program that ships inside AutoMoto (never project code)
in a temporary folder. That check only exists for languages whose official
toolchain AutoMoto has proved in CI (Zig, Nim, Crystal, Odin). Mojo and MoonBit
are inspection only in this version. Toolchain processes are NOT OS-sandboxed.
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
from automoto import developer_native as native
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/emerging", tags=["developer-emerging"])
VERSION = "1.0.0"
LOCK = threading.Lock()
MAX_FILES = 160
MAX_SOURCE = 192 * 1024
MAX_TOTAL = 8 * 1024 * 1024
TIMEOUT = 240
REVIEWED = "2026-11"
LANGUAGES = ("zig", "nim", "crystal", "odin", "mojo", "moonbit")

EXTENSIONS = {
    ".zig": "zig", ".zon": "zig",
    ".nim": "nim", ".nims": "nim", ".nimble": "nim",
    ".cr": "crystal",
    ".odin": "odin",
    ".mojo": "mojo", ".\U0001F525": "mojo",
    ".mbt": "moonbit", ".mbti": "moonbit",
}
MANIFESTS = {
    "build.zig": "zig", "build.zig.zon": "zig",
    "shard.yml": "crystal", "shard.lock": "crystal",
    "moon.mod.json": "moonbit", "moon.pkg.json": "moonbit",
    "mojoproject.toml": "mojo", "pixi.toml": "mojo",
    "ols.json": "odin", "odinfmt.json": "odin",
    "nim.cfg": "nim", "config.nims": "nim",
}
# Executables looked up on PATH. Package managers are listed, never run.
TOOLS = {
    "zig": ("zig",), "nim": ("nim", "nimble"), "crystal": ("crystal", "shards"),
    "odin": ("odin",), "mojo": ("mojo", "magic", "pixi"), "moonbit": ("moon",),
}
RUNNABLE = {"zig": "zig", "nim": "nim", "crystal": "crystal", "odin": "odin"}

# AutoMoto's own example programs. They print a marker and the compiler version.
FIXTURES = {
    "zig": ("v35_check.zig",
            'const std = @import("std");\nconst builtin = @import("builtin");\n\n'
            'fn answer() u32 {\n    return 6 * 7;\n}\n\n'
            'pub fn main() void {\n'
            '    std.debug.print("V35_ZIG_PASS {d} version={s}\\n", .{ answer(), builtin.zig_version_string });\n}\n'),
    "nim": ("v35_check.nim",
            'proc answer(): int = 6 * 7\n\n'
            'echo "V35_NIM_PASS ", answer(), " version=", NimVersion\n'),
    "crystal": ("v35_check.cr",
                'def answer : Int32\n  6 * 7\nend\n\n'
                'puts "V35_CRYSTAL_PASS #{answer} version=#{Crystal::VERSION}"\n'),
    "odin": ("v35_check.odin",
             'package v35_check\n\nimport "core:fmt"\n\n'
             'answer :: proc() -> int {\n\treturn 6 * 7\n}\n\n'
             'main :: proc() {\n\tfmt.printf("V35_ODIN_PASS %d version=%s\\n", answer(), ODIN_VERSION)\n}\n'),
}
MARKERS = {lang: f"V35_{lang.upper()}_PASS 42" for lang in RUNNABLE}
MARKER_LINE = re.compile(r"(?m)^(V35_[A-Z]+_PASS 42)(?: version=(\S{1,40}))?\s*$")

# Version-aware capability notes, maintained by AutoMoto (not by the language projects).
CAPABILITIES = {
    "zig": {
        "label": "Zig", "maturity": "pre-1.0",
        "summary": "Fast systems language. Still before 1.0, so code written for one 0.x release often needs small edits for the next.",
        "check_offered": True, "ci_verified_hosts": ["linux"],
        "tested_from": "0.14.0", "tested_to": "0.17",
        "manifests": ["build.zig", "build.zig.zon"],
        "build_runs_project_code": "build.zig is a Zig program; building a project runs it.",
        "official_site": "https://ziglang.org/download/",
        "install": {"macos": "brew install zig", "linux": "https://ziglang.org/download/",
                    "windows": "https://ziglang.org/download/"},
    },
    "nim": {
        "label": "Nim", "maturity": "stable",
        "summary": "Readable language that compiles to C. Nim 2 changed memory management defaults, so Nim 1.x code can behave differently.",
        "check_offered": True, "ci_verified_hosts": ["linux"],
        "tested_from": "2.0.0", "tested_to": "2.4",
        "needs": "A C compiler (gcc or clang) on PATH.",
        "manifests": ["*.nimble", "nim.cfg", "config.nims"],
        "build_runs_project_code": "staticExec, gorge and .nims scripts run at compile time.",
        "official_site": "https://nim-lang.org/install.html",
        "install": {"macos": "brew install nim", "linux": "https://nim-lang.org/install.html",
                    "windows": "https://nim-lang.org/install.html"},
    },
    "crystal": {
        "label": "Crystal", "maturity": "stable",
        "summary": "Ruby-like syntax with compiled speed. AutoMoto only proves Crystal on Linux; other systems are reported but not verified.",
        "check_offered": True, "ci_verified_hosts": ["linux"],
        "tested_from": "1.10.0", "tested_to": "1.22",
        "manifests": ["shard.yml", "shard.lock"],
        "build_runs_project_code": "Macros can run programs at compile time ({{ run(...) }}).",
        "official_site": "https://crystal-lang.org/install/",
        "install": {"macos": "brew install crystal", "linux": "https://crystal-lang.org/install/",
                    "windows": "https://crystal-lang.org/install/"},
    },
    "odin": {
        "label": "Odin", "maturity": "pre-1.0 (monthly dev releases)",
        "summary": "Simple systems language for games and tools. There is no 1.0 yet; the core library can change between monthly releases.",
        "check_offered": True, "ci_verified_hosts": ["linux"],
        "tested_from": "dev-2025-01", "tested_to": "dev-2026-11",
        "needs": "clang on Linux and macOS, or the Visual Studio build tools on Windows.",
        "manifests": ["ols.json", "odinfmt.json"],
        "build_runs_project_code": "#load and foreign imports pull files and libraries in at build time.",
        "official_site": "https://odin-lang.org/docs/install/",
        "install": {"macos": "brew install odin", "linux": "https://odin-lang.org/docs/install/",
                    "windows": "https://odin-lang.org/docs/install/"},
    },
    "mojo": {
        "label": "Mojo", "maturity": "preview",
        "summary": "Python-style language for AI and fast code, from Modular. Preview: Linux and macOS only (no native Windows). AutoMoto reads Mojo files but does not run them yet.",
        "check_offered": False, "ci_verified_hosts": [],
        "manifests": ["mojoproject.toml", "pixi.toml"],
        "build_runs_project_code": "Not evaluated by AutoMoto.",
        "official_site": "https://docs.modular.com/mojo/manual/get-started",
        "install": {"macos": "https://docs.modular.com/mojo/manual/get-started",
                    "linux": "https://docs.modular.com/mojo/manual/get-started",
                    "windows": "Not supported natively. Use WSL, then follow the Linux steps."},
    },
    "moonbit": {
        "label": "MoonBit", "maturity": "beta (pre-1.0)",
        "summary": "Young language for WebAssembly and the cloud. Its tools are still pre-1.0, so AutoMoto reads MoonBit files but does not run them yet.",
        "check_offered": False, "ci_verified_hosts": [],
        "manifests": ["moon.mod.json", "moon.pkg.json"],
        "build_runs_project_code": "Not evaluated by AutoMoto.",
        "official_site": "https://www.moonbitlang.com/download/",
        "install": {"macos": "https://www.moonbitlang.com/download/",
                    "linux": "https://www.moonbitlang.com/download/",
                    "windows": "https://www.moonbitlang.com/download/"},
    },
}
DECLARATIONS = {
    "zig": re.compile(r"(?m)^\s*(?:pub\s+)?(?:fn|const|var)\s+([A-Za-z_]\w{0,69})"),
    "nim": re.compile(r"(?m)^\s*(?:proc|func|method|iterator|template|macro|type)\s+([A-Za-z_]\w{0,69})"),
    "crystal": re.compile(r"(?m)^\s*(?:def|class|module|struct|macro)\s+([A-Za-z_][\w:.?!]{0,69})"),
    "odin": re.compile(r"(?m)^\s*([A-Za-z_]\w{0,69})\s*::\s*(?:proc|struct|enum|union)\b"),
    "mojo": re.compile(r"(?m)^\s*(?:fn|def|struct|trait)\s+([A-Za-z_]\w{0,69})"),
    "moonbit": re.compile(r"(?m)^\s*(?:pub\s+)?(?:fn|struct|enum|trait|type)\s+([A-Za-z_]\w{0,69})"),
}
RISKS = {
    "zig": (("runs other programs", r"std\.process\.Child|std\.ChildProcess|execv"),
            ("network access", r"std\.http|std\.net"),
            ("C interop", r"@cImport|extern\s+\"c\"")),
    "nim": (("runs code while compiling", r"\b(?:staticExec|gorge|gorgeEx|staticRead)\b"),
            ("runs other programs", r"\b(?:osproc|execProcess|execCmd|execShellCmd|startProcess)\b"),
            ("network access", r"\b(?:httpclient|asyncnet|net\.newSocket)\b"),
            ("C interop", r"\{\.\s*(?:compile|passL|passC|emit)\b")),
    "crystal": (("runs code while compiling", r"\{\{\s*run\s*\(|`[^`\n]{1,200}`"),
                ("runs other programs", r"\bProcess\.(?:run|new|exec)\b|\bsystem\s*\("),
                ("network access", r"\bHTTP::(?:Client|Server)\b|\bTCPSocket\b"),
                ("C interop", r"(?m)^\s*lib\s+[A-Z]")),
    "odin": (("runs other programs", r"os2?\.process_(?:start|exec)|core:os/os2"),
             ("network access", r"\"core:net\""),
             ("C interop", r"\bforeign\s+import\b")),
    "mojo": (("runs Python or other programs", r"\bPython\.import_module\b|\bsubprocess\b"),
             ("C interop", r"\bexternal_call\b")),
    "moonbit": (("foreign functions", r"\bextern\s+\"(?:c|C|js|wasm)\""),),
}
RISK_PATTERNS = {lang: tuple((label, re.compile(pattern)) for label, pattern in items)
                 for lang, items in RISKS.items()}
REQUIREMENTS = (
    ("zig", "build.zig.zon", re.compile(r"\.minimum_zig_version\s*=\s*\"([0-9][^\"]{0,30})\"")),
    ("nim", ".nimble", re.compile(r"(?m)requires\s*\(?\s*\"nim\s*(?:>=|==|>)?\s*([0-9][0-9.]{0,20})")),
    ("crystal", "shard.yml", re.compile(r"(?m)^crystal:\s*[\"']?\s*(?:[<>=~]+\s*)?([0-9][0-9.]{0,20})")),
    ("mojo", "mojoproject.toml", re.compile(r"(?m)^\s*(?:mojo|max|modular)\s*=\s*\"[<>=~^ ]*([0-9][^\"]{0,30})\"")),
    ("mojo", "pixi.toml", re.compile(r"(?m)^\s*(?:mojo|max|modular)\s*=\s*\"[<>=~^ ]*([0-9][^\"]{0,30})\"")),
)


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    language: Literal["zig", "nim", "crystal", "odin"]
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_toolchain: Literal[True]


def _read(root: Path, relative: str) -> tuple[str, str, int]:
    path = studio._path(root, relative)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            meta = os.fstat(stream.fileno())
            if not stat.S_ISREG(meta.st_mode):
                raise HTTPException(403, "Only regular files can be inspected.")
            if meta.st_size > MAX_SOURCE:
                raise HTTPException(413, "A source file is larger than the inspection limit.")
            raw = stream.read(MAX_SOURCE + 1)
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(403, "A source file cannot be read safely.") from exc
    if len(raw) > MAX_SOURCE:
        raise HTTPException(413, "A source file is larger than the inspection limit.")
    return raw.decode("utf-8", errors="replace"), hashlib.sha256(raw).hexdigest(), len(raw)


def _kind(name: str) -> tuple[str | None, bool]:
    leaf = name.rsplit("/", 1)[-1]
    if leaf in MANIFESTS:
        return MANIFESTS[leaf], True
    if leaf.endswith(".nimble"):
        return "nim", True
    return EXTENSIONS.get(Path(leaf).suffix.lower()), False


def _version_tuple(text: str) -> tuple | None:
    text = (text or "").strip()
    dev = re.fullmatch(r"dev-(\d{4})-(\d{2})[a-z]?", text)
    if dev:
        return ("dev", int(dev.group(1)), int(dev.group(2)))
    numbers = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    if not numbers:
        return None
    return tuple(int(part or 0) for part in numbers.groups())


def classify(language: str, version: str | None) -> dict:
    """Map an installed or requested version onto AutoMoto's tested range."""
    cap = CAPABILITIES[language]
    if not version:
        return {"version": None, "support": "unknown",
                "note": "Version not known yet. Run the toolchain check to read it."}
    found = _version_tuple(version)
    low = _version_tuple(cap.get("tested_from", ""))
    high = _version_tuple(cap.get("tested_to", ""))
    if found is None or low is None or high is None or type(found[0]) is not type(low[0]):
        return {"version": version, "support": "unrecognised",
                "note": "AutoMoto could not read this version number, so it makes no promises about it."}
    if found < low:
        return {"version": version, "support": "older_than_tested",
                "note": f"Older than AutoMoto has tested ({cap['tested_from']}). Updating is recommended."}
    width = 3 if found[0] == "dev" else 2
    if found[:width] > high[:width]:
        return {"version": version, "support": "newer_than_tested",
                "note": f"Newer than AutoMoto has tested (up to {cap['tested_to']}). It will probably work; report anything odd."}
    note = "Inside the range AutoMoto has tested."
    if cap["maturity"].startswith("pre-1.0"):
        note += " The language itself is still pre-1.0."
    return {"version": version, "support": "tested", "note": note}


def _inventory(root: Path) -> tuple[list[dict], list[dict], dict, str, bool]:
    files, manifests, requirements, total, incomplete = [], [], {}, 0, False
    digest = hashlib.sha256(b"automoto-v35-emerging-inventory\0")
    for name, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        language, manifest = _kind(name)
        if not language:
            continue
        if len(files) + len(manifests) >= MAX_FILES:
            incomplete = True
            break
        contents, sha, size = _read(root, name)
        total += size
        if total > MAX_TOTAL:
            incomplete = True
            break
        digest.update(name.encode("utf-8") + b"\0" + sha.encode("ascii") + b"\0")
        if manifest:
            manifests.append({"path": name, "language": language, "sha256": sha, "bytes": size,
                              "evaluated": False, "dependencies_installed": False})
            for lang, suffix, pattern in REQUIREMENTS:
                if lang == language and name.endswith(suffix) and lang not in requirements:
                    match = pattern.search(contents[:60000])
                    if match:
                        requirements[lang] = {"path": name, "requires": match.group(1)}
            continue
        text = contents[:60000]
        signals = [{"kind": label, "line": text[:m.start()].count("\n") + 1}
                   for label, pattern in RISK_PATTERNS[language]
                   if (m := pattern.search(text))]
        files.append({"path": name, "language": language, "sha256": sha, "bytes": size,
                      "symbols": DECLARATIONS[language].findall(text)[:24],
                      "risk_signals": signals, "executed": False})
    for name in MANIFESTS:
        target = root / name
        if target.is_symlink() or getattr(target, "is_junction", lambda: False)():
            raise HTTPException(403, "A linked language manifest is not allowed.")
    return files, manifests, requirements, digest.hexdigest(), incomplete


def _tools(root: Path) -> list[dict]:
    entries = []
    for language, names in TOOLS.items():
        for name in names:
            binary = shutil.which(name)
            if not binary:
                item = {"status": "unavailable"}
            elif Path(binary).suffix.lower() in (".cmd", ".bat", ".ps1"):
                item = {"status": "shell_wrapper_blocked"}
            else:
                try:
                    item = {"status": "installed_not_executed",
                            **adapters._fingerprint(str(Path(binary).absolute()), root)}
                except HTTPException:
                    item = {"status": "untrusted_executable"}
            entries.append({"language": language, "name": name,
                            "role": "compiler" if name == RUNNABLE.get(language) or
                            (language in ("mojo", "moonbit") and name == names[0]) else "helper",
                            **item})
    return entries


def _host() -> str:
    return "windows" if os.name == "nt" else "macos" if sys.platform == "darwin" else "linux"


def _inspect(root: Path) -> dict:
    files, manifests, requirements, inventory_sha, incomplete = _inventory(root)
    tools = _tools(root)
    host = _host()
    languages = []
    for language in LANGUAGES:
        cap = CAPABILITIES[language]
        compiler = next((t for t in tools if t["language"] == language and t["role"] == "compiler"), None)
        installed = bool(compiler and compiler["status"] == "installed_not_executed")
        requirement = requirements.get(language)
        mojo_windows = language == "mojo" and host == "windows"
        languages.append({
            "language": language, "label": cap["label"], "maturity": cap["maturity"],
            "summary": cap["summary"],
            "files": sum(f["language"] == language for f in files),
            "manifests": [m["path"] for m in manifests if m["language"] == language],
            "installed": installed,
            "host_supported": not mojo_windows,
            "compiler": compiler,
            "project_requires": requirement,
            "project_requirement_support": classify(language, requirement["requires"]) if requirement else None,
            "check_offered": cap["check_offered"] and installed and not incomplete,
            "check_unavailable_reason": (None if cap["check_offered"] and installed and not incomplete else
                                         "This version of AutoMoto reads these files but does not run this language yet."
                                         if not cap["check_offered"] else
                                         "Not installed on this computer." if not installed else
                                         "The project scan was incomplete."),
            "ci_verified_hosts": cap["ci_verified_hosts"],
            "verified_on_this_host_by_ci": host in cap["ci_verified_hosts"],
            "needs": cap.get("needs"),
            "build_runs_project_code": cap["build_runs_project_code"],
            "install_hint": cap["install"][host],
            "official_site": cap["official_site"],
        })
    return {
        "schema": VERSION, "capabilities_reviewed": REVIEWED, "host": host,
        "languages": languages, "files": files, "manifests": manifests,
        "toolchains": tools, "inventory_sha256": inventory_sha,
        "scan_incomplete": incomplete,
        "project_trusted": studio._trusted(root, studio._load()),
        "source_executed": False, "manifest_evaluated": False,
        "dependencies_installed": False, "network_started": False,
        "deployment_started": False, "release_ready_claimed": False,
        "central_agent_studio": "developer",
        "limitations": ("Declarations and risk signals are pattern matches, not a compiler. "
                        "Manifests are read, never evaluated. Version support notes are "
                        "AutoMoto's own and were last reviewed " + REVIEWED + ". The toolchain "
                        "check runs AutoMoto's own tiny example, not your project, and the "
                        "compiler is not OS-sandboxed. Mojo and MoonBit are inspection only."),
    }


def _check(root: Path, body: CheckIn) -> dict:
    adapters._trusted(root)
    tools = _tools(root)
    chosen = next((t for t in tools if t["language"] == body.language and
                   t["name"] == RUNNABLE[body.language] and
                   t["status"] == "installed_not_executed"), None)
    if not chosen:
        raise HTTPException(409, f"{CAPABILITIES[body.language]['label']} is not installed on this computer.")
    if chosen.get("executable") != body.expected_executable or chosen.get("sha256") != body.expected_sha256:
        raise HTTPException(409, "The compiler changed since you approved it. Check again.")
    filename, source = FIXTURES[body.language]
    with tempfile.TemporaryDirectory(prefix="automoto-v35-") as directory:
        folder = Path(directory)
        stage = folder / "check"
        stage.mkdir(mode=0o700)
        (stage / filename).write_text(source, encoding="utf-8")
        home = folder / "home"
        home.mkdir(mode=0o700)
        cache = folder / "cache"
        cache.mkdir(mode=0o700)
        exe = body.expected_executable
        command = {
            "zig": [exe, "run", filename],
            "nim": [exe, "r", "--hints:off", "--colors:off", f"--nimcache:{cache / 'nim'}", filename],
            "crystal": [exe, "run", "--no-color", filename],
            "odin": [exe, "run", filename, "-file"],
        }[body.language]
        env = adapters._environment(root)
        env.update({
            "HOME": str(home), "USERPROFILE": str(home), "TMPDIR": str(folder),
            "TEMP": str(folder), "TMP": str(folder),
            "XDG_CACHE_HOME": str(cache), "XDG_CONFIG_HOME": str(home / "config"),
            "ZIG_GLOBAL_CACHE_DIR": str(cache / "zig-global"),
            "ZIG_LOCAL_CACHE_DIR": str(cache / "zig-local"),
            "CRYSTAL_CACHE_DIR": str(cache / "crystal"),
            "NIMBLE_DIR": str(home / "nimble"),
            "CI": "true", "NO_COLOR": "1",
        })
        # Re-verify the exact compiler bytes immediately before it runs.
        again = next((t for t in _tools(root) if t["language"] == body.language and
                      t["name"] == RUNNABLE[body.language]), {})
        if again.get("sha256") != body.expected_sha256:
            raise HTTPException(409, "The compiler changed while preparing the check.")
        started = time.monotonic()
        output = native._execute(stage, command, env, timeout=TIMEOUT)
    text = output["output"]
    match = next((m for m in MARKER_LINE.finditer(text) if m.group(1) == MARKERS[body.language]), None)
    status = output["status"]
    if status == "completed" and not match:
        status = "validation_failed"
    version = match.group(2) if match else None
    return {
        "language": body.language, "status": status, "passed": status == "completed",
        "exit_code": output["exit_code"], "output": text[:native.MAX_OUTPUT],
        "marker_matched": bool(match), "version": version,
        "version_support": classify(body.language, version),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "tool_sha256": chosen["sha256"], "example_source": "bundled_with_automoto",
        "project_code_executed": False, "temporary_copy_deleted": True,
        "external_code_unsandboxed": True, "os_network_isolation": False,
        "package_installer_called_by_studio": False, "deployment_started": False,
        "central_agent_studio": "developer",
    }


@router.get("/inspect")
def inspect(request: Request, project: str):
    studio._auth(request)
    return _inspect(studio._project(project))


@router.post("/check")
def check(request: Request, body: CheckIn):
    studio._auth(request)
    if not LOCK.acquire(blocking=False):
        raise HTTPException(429, "A toolchain check is already running.")
    try:
        return _check(studio._project(body.project), body)
    finally:
        LOCK.release()
