"""Developer Studio V26 — shell evidence and tightly restricted fixture execution.

Inspection is inert. Script diagnostics run only fixed, approved interpreters
against a staged copy. Fixture execution accepts a deliberately tiny literal
output-only grammar; it is NOT an arbitrary shell runner or an OS sandbox.
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

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_adapters as adapters
from automoto import developer_index as index
from automoto import developer_jvm as jvm
from automoto import developer_native as native
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/shell", tags=["developer-shell"])
VERSION = "1.0.0"
MAX_FILES = 120
MAX_SCRIPT_BYTES = 96 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_SECONDS = 30
LOCK = threading.Lock()
TOOLS = ("bash", "zsh", "fish", "pwsh", "powershell", "cmd.exe", "shellcheck")
SUFFIX_TO_LANGUAGE = {
    ".sh": "bash", ".bash": "bash", ".zsh": "zsh", ".fish": "fish",
    ".ps1": "powershell", ".psm1": "powershell",
    ".bat": "batch", ".cmd": "batch",
}
# Deliberate fixed-name subset, not user-selected general-purpose script execution.
FIXTURE_PATHS = {
    "scripts/smoke.sh": "bash", "scripts/smoke.bash": "bash",
    "scripts/smoke.zsh": "zsh", "scripts/smoke.fish": "fish",
    "scripts/smoke.ps1": "powershell", "scripts/smoke.cmd": "batch",
    "scripts/smoke.bat": "batch",
}
IDENT = r"[A-Za-z0-9_./:-]{1,90}"
OUT = r"[A-Za-z0-9_:-]{1,90}"
RE_ECHO = re.compile(r"echo (" + OUT + r")\Z")
RE_PRINTF = re.compile(r"printf '%s\\n' '(" + OUT + r")'\Z")
RE_PWSH = re.compile(r"Write-Output '(" + OUT + r")'\Z")
RE_BATCH = re.compile(r"echo (" + OUT + r")\Z", re.I)
SHEBANG = re.compile(r"#!(?:/usr/bin/env |/bin/)(?:bash|sh|zsh|fish)\Z")
RISK = (
    ("recursive deletion", re.compile(r"(?i)\b(?:rm\s+-[rf]|Remove-Item\b|rmdir\s+/s|del\s+/[fq])")),
    ("privilege or policy modification", re.compile(
        r"(?i)\b(?:sudo\b|Set-ExecutionPolicy\b|chmod\s+-R\b|takeown\b|icacls\b)")),
    ("network or external execution", re.compile(
        r"(?i)\b(?:curl\b|wget\b|Invoke-WebRequest\b|Invoke-RestMethod\b|"
        r"Invoke-Expression\b|Start-Process\b|eval\b|iex\b)")),
    ("credential or environment access", re.compile(
        r"(?i)(?:\.env\b|/\.ssh\b|\\\.ssh\b|AWS_SECRET_ACCESS_KEY|"
        r"PRIVATE_KEY|Get-Credential\b)")),
    ("shell substitution or background execution", re.compile(
        r"(?m)(?:\$\(|\x60|[|;&<>])")),
)
VERSION_COMMANDS = {
    "bash": ["--version"], "zsh": ["--version"], "fish": ["--version"],
    "pwsh": ["-NoLogo", "-NoProfile", "-NonInteractive", "-Version"],
    "powershell": ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                   "$PSVersionTable.PSVersion.ToString()"],
    "cmd.exe": ["/D", "/Q", "/C", "ver"], "shellcheck": ["--version"],
}


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    task: Literal["version", "syntax", "shellcheck", "fixture_smoke"]
    script: str = Field(default="", max_length=230, pattern=r"^[A-Za-z0-9_./-]*$")
    tool: Literal["bash", "zsh", "fish", "pwsh", "powershell", "cmd.exe", "shellcheck"]
    expected_inventory_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_toolchain_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_interpreter_risk: Literal[True]


def _language(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1]
    if name.casefold() == "dockerfile":
        return None
    return SUFFIX_TO_LANGUAGE.get(Path(path).suffix.casefold())


def _fixture_safe(path: str, language: str, source: str) -> bool:
    """Permit only literal-output smoke fixtures; never general shell code.

    These grammar checks intentionally reject variables, substitutions, paths,
    globs, quotes inside arguments, pipes, redirections, newlines in values,
    environment access, functions, external programs, loops and conditionals.
    """
    if FIXTURE_PATHS.get(path) != language or not source.endswith("\n"):
        return False
    if "\r" in source or any(ord(char) < 32 and char != "\n" for char in source):
        return False
    commands = []
    for line in source.splitlines():
        if len(line) > 125:
            return False
        if line.startswith("#!"):
            if commands or not SHEBANG.fullmatch(line):
                return False
            continue
        if not line:
            continue
        if language in ("bash", "zsh", "fish"):
            if line == "set -eu" and language != "fish" and not commands:
                continue
            if RE_ECHO.fullmatch(line) or RE_PRINTF.fullmatch(line) or line == "exit 0":
                commands.append(line)
                continue
        elif language == "powershell":
            if RE_PWSH.fullmatch(line) or line == "exit 0":
                commands.append(line)
                continue
        elif language == "batch":
            if line.lower() == "@echo off" and not commands:
                continue
            if RE_BATCH.fullmatch(line) or line.lower() == "exit /b 0":
                commands.append(line)
                continue
        return False
    # A smoke fixture must produce a visible marker and may only exit cleanly.
    return bool(commands) and any(
        RE_ECHO.fullmatch(line) or RE_PRINTF.fullmatch(line) or
        RE_PWSH.fullmatch(line) or RE_BATCH.fullmatch(line)
        for line in commands
    ) and len(commands) <= 4


def _inventory(root: Path) -> tuple[list[dict], str, bool]:
    files, total, incomplete = [], 0, False
    digest = hashlib.sha256(b"automoto-v26-shell-inventory\0")
    for name, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        lang = _language(name)
        if not lang:
            continue
        if len(files) >= MAX_FILES:
            incomplete = True
            continue
        source, sha, size = jvm._read(root, name, MAX_SCRIPT_BYTES)
        total += size
        if total > MAX_TOTAL_BYTES:
            incomplete = True
            break
        risks = [{"kind": kind, "line": source[:m.start()].count("\n") + 1}
                 for kind, pattern in RISK if (m := pattern.search(source[:MAX_SCRIPT_BYTES]))]
        if (name in FIXTURE_PATHS and (root / name).is_symlink()):
            raise HTTPException(403, "A linked shell smoke script cannot be approved.")
        item = {"path": name, "language": lang, "sha256": sha, "bytes": size,
                "lines": source.count("\n") + (0 if source.endswith("\n") else 1),
                "risk_signals": risks[:12],
                "fixture_smoke_eligible": _fixture_safe(name, lang, source),
                "analysis_only": True}
        files.append(item)
        digest.update(name.encode() + b"\0" + sha.encode() + b"\0")
    for name in FIXTURE_PATHS:
        file = root / name
        if file.is_symlink() or getattr(file, "is_junction", lambda: False)():
            raise HTTPException(403, "Linked shell smoke script cannot be approved.")
    return files, digest.hexdigest(), incomplete


def _tools(root: Path) -> tuple[list[dict], str]:
    result = []
    digest = hashlib.sha256(b"automoto-v26-shell-toolchain\0")
    for name in TOOLS:
        candidate = shutil.which(name)
        if not candidate:
            tool = {"name": name, "status": "unavailable"}
        elif Path(candidate).suffix.lower() in (".bat", ".cmd", ".ps1"):
            tool = {"name": name, "status": "shell_wrapper_blocked"}
        else:
            try:
                tool = {"name": name, "status": "installed_not_executed",
                        **adapters._fingerprint(str(Path(candidate).absolute()), root)}
            except HTTPException:
                tool = {"name": name, "status": "untrusted_executable"}
        result.append(tool)
        digest.update(name.encode() + b"\0" + tool["status"].encode() + b"\0" +
                      tool.get("sha256", "").encode() + b"\0" +
                      tool.get("executable", "").encode())
    return result, digest.hexdigest()


def _inspect(root: Path) -> dict:
    files, digest, incomplete = _inventory(root)
    tooling, toolsha = _tools(root)
    languages = sorted({file["language"] for file in files})
    summary = {lang: sum(file["language"] == lang for file in files)
               for lang in languages}
    risky = sum(bool(file["risk_signals"]) for file in files)
    return {"schema": VERSION, "files": files, "language_counts": summary,
            "inventory_sha256": digest, "toolchain_sha256": toolsha,
            "scan_incomplete": incomplete, "risk_files": risky,
            "tools": tooling, "platform": sys.platform,
            "fixture_count": sum(file["fixture_smoke_eligible"] for file in files),
            "project_trusted": studio._trusted(root, studio._load()),
            "inspection_executed_code": False,
            "scripts_executed": False, "device_or_network_isolated": False,
            "safe_execution_policy": "Strict fixed-path, literal-output-only fixture grammar; no general scripts.",
            "syntax_policy": "Explicit diagnostics require trusted project, tool hash and consent.",
            "shellcheck_policy": "Optional installed ShellCheck; Bash/sh subset only.",
            "powershell_policy": "PowerShell AST Parser::ParseFile only for syntax checks; no script execution.",
            "batch_policy": "No general Batch syntax checker. Only fixed-name literal-output fixture execution.",
            "warnings": (["Source inventory reached traversal/size limits; reject tasks until reviewed."]
                         if incomplete else []),
            "central_agent_studio": "developer", "agent_deployment_handoff_required": True,
            "deployment_started": False}


def _select(data: dict, name: str) -> dict:
    if not name or ".." in name.split("/") or "\\" in name or name.startswith("/"):
        raise HTTPException(422, "Select an approved project-relative script.")
    script = next((file for file in data["files"] if file["path"] == name), None)
    if not script:
        raise HTTPException(404, "Script is missing from bounded inventory.")
    if data["scan_incomplete"]:
        raise HTTPException(409, "Bounded inventory incomplete; refuse shell operation.")
    return script


def _stage(root: Path, stage: Path, script: dict) -> Path:
    source, sha, _ = jvm._read(root, script["path"], MAX_SCRIPT_BYTES)
    if sha != script["sha256"]:
        raise HTTPException(409, "Shell script changed after approval.")
    target = stage / script["path"]
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return target


def _pwsh_syntax(tool: str, name: str) -> list[str]:
    # File name is regex-limited and confirmed against the inventory. A single
    # quoted path is generated inside an unprivileged temporary project.
    safe_path = name.replace("'", "''")
    code = (
        "$tokens=$null;$issues=$null;"
        "[System.Management.Automation.Language.Parser]::ParseFile("
        "'" + safe_path + "',[ref]$tokens,[ref]$issues)|Out-Null;"
        "if($issues.Count -gt 0){$issues | ForEach-Object {Write-Output $_.Message};exit 1};"
        "Write-Output 'V26_POWERSHELL_PARSE_PASS'"
    )
    return [tool, "-NoProfile", "-NonInteractive", "-NoLogo", "-Command", code]


def _command(body: RunIn, item: dict | None, tool: dict, stage: Path) -> list[str]:
    exe = tool["executable"]
    if body.task == "version":
        if body.script:
            raise HTTPException(422, "Version queries do not accept script paths.")
        return [exe, *VERSION_COMMANDS[body.tool]]
    if item is None:
        raise HTTPException(422, "Select a script for diagnostics or smoke.")
    script = str(stage / item["path"])
    language = item["language"]
    if body.task == "shellcheck":
        if language != "bash" or body.tool != "shellcheck":
            raise HTTPException(422, "ShellCheck is only admitted for sh/Bash scripts.")
        return [exe, "--norc", "--shell=bash", "--format=gcc", script]
    if body.task == "syntax":
        if language in ("bash", "zsh", "fish") and body.tool == language:
            prefix = {"bash": ["--noprofile", "--norc", "-n"],
                      "zsh": ["-f", "-n"], "fish": ["--no-config", "-n"]}[language]
            return [exe, *prefix, script]
        if language == "powershell" and body.tool in ("pwsh", "powershell"):
            return _pwsh_syntax(exe, item["path"])
        raise HTTPException(422, "No supported non-executing syntax check for this tool/script.")
    if body.task == "fixture_smoke":
        if not item["fixture_smoke_eligible"]:
            raise HTTPException(403, "Script does not match the literal-only fixture grammar.")
        if language in ("bash", "zsh", "fish") and body.tool == language:
            prefix = {"bash": ["--noprofile", "--norc"],
                      "zsh": ["-f"], "fish": ["--no-config"]}[language]
            return [exe, *prefix, script]
        if language == "powershell" and body.tool in ("pwsh", "powershell"):
            return [exe, "-NoProfile", "-NonInteractive", "-NoLogo", "-File", script]
        if language == "batch" and body.tool == "cmd.exe" and os.name == "nt":
            return [exe, "/D", "/Q", "/C", script]
        raise HTTPException(422, "Interpreter does not match the approved fixture.")
    raise HTTPException(422, "Unsupported shell task.")


def _run(root: Path, body: RunIn) -> dict:
    adapters._trusted(root)
    data = _inspect(root)
    if (data["inventory_sha256"] != body.expected_inventory_sha256 or
            data["toolchain_sha256"] != body.expected_toolchain_sha256):
        raise HTTPException(409, "Shell project inventory or toolchain changed since consent.")
    tool = next((tool for tool in data["tools"] if tool["name"] == body.tool and
                 tool["status"] == "installed_not_executed"), None)
    if (not tool or tool.get("sha256") != body.expected_sha256 or
            tool.get("executable") != body.expected_executable):
        raise HTTPException(409, "Approved interpreter fingerprint changed.")
    item = None if body.task == "version" else _select(data, body.script)
    with tempfile.TemporaryDirectory(prefix="automoto-shell-v26-") as work:
        stage = Path(work)
        stage.chmod(0o700)
        if item is not None:
            _stage(root, stage, item)
        cmd = _command(body, item, tool, stage)
        again = _inspect(root)
        if (again["inventory_sha256"] != body.expected_inventory_sha256 or
                again["toolchain_sha256"] != body.expected_toolchain_sha256):
            raise HTTPException(409, "Shell inventory or interpreter changed during staging.")
        adapters._trusted(root)
        env = adapters._environment(root)
        env.update({"AUTOMOTO_SHELL_FIXTURE": "1", "CI": "true"})
        started = time.monotonic()
        outcome = native._execute(stage, cmd, env, timeout=MAX_SECONDS)
    return {"task": body.task, "script": body.script,
            "status": outcome["status"], "exit_code": outcome["exit_code"],
            "output": outcome["output"][:native.MAX_OUTPUT],
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "temporary_copy_deleted": True,
            "fixture_grammar_enforced": body.task == "fixture_smoke",
            "arbitrary_script_execution": False,
            "os_network_isolation": False, "external_process_unsandboxed": True,
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
        raise HTTPException(429, "Shell diagnostic task already running.")
    try:
        return _run(studio._project(body.project), body)
    finally:
        LOCK.release()
