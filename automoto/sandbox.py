"""The agent's own little computer: a workspace jail for files and shell commands.

* Every path is resolved (symlinks included) and must stay inside the workspace
  (default ``~/.automoto/workspace``). ``..``, absolute paths elsewhere and symlinks
  that point outside are refused. Nothing outside the workspace is ever deleted or
  written - there is no tool that could do it.
* Shell commands run with ``cwd`` = workspace, a timeout, and an environment with
  every API key / token / secret variable stripped.
* ``AUTOMOTO_SANDBOX=docker`` (or ``auto`` with Docker available) runs commands in a
  throwaway container (``--network none``, workspace mounted at ``/workspace``,
  memory/CPU/pid limits). ``local`` uses a subprocess.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path

from automoto import config, home

SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "AUTH")
MAX_OUTPUT = 8000


class SandboxError(Exception):
    pass


def root() -> Path:
    return home.workspace()


def resolve(path: str | os.PathLike | None, *, base: Path | None = None) -> Path:
    """Map a user/model supplied path into the workspace or raise SandboxError."""
    base = (base or root()).resolve()
    raw = str(path or ".").strip()
    if raw.startswith("~"):
        raise SandboxError("home-relative paths are outside the workspace")
    p = Path(raw)
    if p.is_absolute():
        # Allow absolute paths only if they already point inside the workspace.
        candidate = p.resolve()
    else:
        candidate = (base / p).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise SandboxError(f"'{raw}' is outside the AutoMoto workspace ({base})") from None
    return candidate


def rel(p: Path) -> str:
    try:
        return str(p.relative_to(root())) or "."
    except ValueError:  # pragma: no cover
        return str(p)


def in_scratch(p: Path) -> bool:
    try:
        p.relative_to(root() / "scratch")
        return True
    except ValueError:
        return False


def clean_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not any(h in k.upper() for h in SECRET_HINTS)}
    env["AUTOMOTO_SANDBOX"] = "1"
    return env


@lru_cache(maxsize=1)
def docker_available() -> bool:
    exe = shutil.which("docker")
    if not exe:
        return False
    try:
        return subprocess.run([exe, "info"], capture_output=True, timeout=8).returncode == 0
    except Exception:
        return False


def mode() -> str:
    m = (config.env("AUTOMOTO_SANDBOX", "auto") or "auto").lower()
    if m == "docker":
        return "docker" if docker_available() else "local"
    if m == "auto":
        return "docker" if docker_available() else "local"
    return "local"


def shell_timeout() -> int:
    try:
        return max(1, min(600, int(config.env("AUTOMOTO_SHELL_TIMEOUT", "60"))))
    except ValueError:
        return 60


def run_shell(command: str, *, timeout: int | None = None) -> dict:
    """Run ``command`` inside the sandbox. Returns {exit, output, mode}."""
    if not command or not command.strip():
        raise SandboxError("empty command")
    timeout = timeout or shell_timeout()
    ws = root()
    m = mode()
    if m == "docker":
        image = config.env("AUTOMOTO_DOCKER_IMAGE", "python:3.12-slim")
        cname = f"automoto-{os.getpid()}-{int(time.time() * 1000) % 10**8}"
        argv = ["docker", "run", "--rm", "--name", cname, "--network", config.env("AUTOMOTO_DOCKER_NETWORK", "none"),
                "--memory", "512m", "--cpus", "1", "--pids-limit", "256",
                "-v", f"{ws}:/workspace", "-w", "/workspace", image, "sh", "-lc", command]
        kw: dict = {}
    else:
        cname = ""
        if sys.platform == "win32":
            argv = ["cmd", "/c", command]
        else:
            argv = ["/bin/sh", "-c", command]
        kw = {"cwd": str(ws), "env": clean_env()}
    popen_kw: dict = {}
    if sys.platform == "win32":
        popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        popen_kw["start_new_session"] = True  # own process group, so a timeout kills children too
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="replace", **kw, **popen_kw)
    except OSError as exc:
        raise SandboxError(f"cannot start shell: {exc}") from None
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        code: int | None = proc.returncode
        note = ""
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        if cname:
            subprocess.run(["docker", "kill", cname], capture_output=True, timeout=15)
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        code, note = None, f"\n[timed out after {timeout}s - process killed]"
    out = (stdout or "") + (("\n" + stderr) if stderr else "")
    if len(out) > MAX_OUTPUT:
        out = "[…truncated…]\n" + out[-MAX_OUTPUT:]
    return {"exit": code, "output": (out.strip() + note).strip(), "mode": m}


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=10)
        else:
            import signal

            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
