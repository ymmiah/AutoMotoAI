"""The agent's own little computer: a workspace jail for files and shell commands.

* Every path is resolved (symlinks included) and must stay inside the workspace
  (default ``~/.automoto/workspace``). ``..``, absolute paths elsewhere and symlinks
  that point outside are refused. Nothing outside the workspace is ever deleted or
  written - there is no tool that could do it.
* Shell commands run with ``cwd`` = workspace, a timeout, and an environment with
  every API key / token / secret variable stripped.
* **Extra roots** (v5.2): folders you add in Settings (``allowed_roots``) or
  ``AUTOMOTO_ALLOWED_ROOTS`` (``os.pathsep``-separated), e.g. a VS Code project or
  ``~/Documents``. Absolute or ``~`` paths inside them are reachable, but every access
  outside the workspace needs approval. A task can also *use* one of them as its root
  (the VS Code extension does this for the open folder).
* **Sensitive paths are never reachable**, even inside an extra root: SSH/GPG/cloud
  credentials, keychains, browser profiles, shell start-up files, ``.env`` and key files,
  system folders and AutoMoto's own settings and databases.
* ``AUTOMOTO_SANDBOX=docker`` (or ``auto`` with Docker available) runs commands in a
  throwaway container (``--network none``, workspace mounted at ``/workspace``,
  memory/CPU/pid limits). ``local`` uses a subprocess.
"""

from __future__ import annotations

import contextvars
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path, PurePath
from typing import Iterator

from automoto import config, home

SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "AUTH")
MAX_OUTPUT = 8000


class SandboxError(Exception):
    pass


_ROOT: contextvars.ContextVar[Path | None] = contextvars.ContextVar("automoto_root", default=None)


def default_root() -> Path:
    return home.workspace()


def root() -> Path:
    """The current task's working root: the workspace, or an allowed folder the task chose."""
    return _ROOT.get() or default_root()


def is_default_root() -> bool:
    return _ROOT.get() is None


def _under(p: Path, base: Path) -> bool:
    try:
        p.relative_to(base)
        return True
    except ValueError:
        return False


# -- sensitive paths ------------------------------------------------------------------
_HOME_SENSITIVE = [
    ".automoto", ".ssh", ".gnupg", ".aws", ".azure", ".config/gcloud", ".kube", ".docker", ".config/gh", ".password-store",
    ".local/share/keyrings", ".mozilla", ".thunderbird", ".config/google-chrome", ".config/chromium",
    ".config/BraveSoftware", ".config/microsoft-edge", ".config/autostart", ".vscode/extensions",
    ".bashrc", ".bash_profile", ".bash_login", ".profile", ".zshrc", ".zprofile", ".zshenv", ".config/fish",
    "Library/Keychains", "Library/Cookies", "Library/Safari", "Library/LaunchAgents", "Library/Mail",
    "Library/Application Support/Google/Chrome", "Library/Application Support/Firefox",
    "Library/Application Support/Microsoft Edge", "Library/Application Support/BraveSoftware",
    "AppData/Local/Google/Chrome", "AppData/Local/Microsoft/Edge", "AppData/Roaming/Mozilla",
    "AppData/Local/BraveSoftware", "AppData/Roaming/Microsoft/Credentials", "AppData/Local/Microsoft/Credentials",
    "AppData/Roaming/Microsoft/Protect", "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup",
]
_SYSTEM_DIRS = ["/etc", "/bin", "/sbin", "/usr", "/boot", "/dev", "/proc", "/sys", "/var", "/root", "/lib",
                "/lib64", "/opt/homebrew/etc", "/System", "/Library", "/private/etc", "/private/var",
                "C:/Windows", "C:/Program Files", "C:/Program Files (x86)", "C:/ProgramData"]
_SECRET_NAME = re.compile(
    r"^(\.env(?!\.(example|sample|template|dist)$)(\..+)?|id_(rsa|dsa|ecdsa|ed25519)(\.pub)?|\.netrc|\.pgpass|\.git-credentials|\.npmrc|\.pypirc|"
    r"(credentials|secrets?|service[-_]account)(\.[\w-]+)?\.(json|ya?ml|toml|ini)|.*\.(pem|key|p12|pfx|kdbx|keychain|keychain-db|ovpn))$",
    re.I)


def _norm(p: PurePath) -> str:
    s = str(p).replace("\\", "/")
    return s.lower() if sys.platform in ("win32", "darwin") else s


def sensitive(p: Path) -> str | None:
    """Why ``p`` must never be touched by the agent, or None. ``p`` should be resolved."""
    if _SECRET_NAME.match(p.name):
        # everywhere, even in the sandbox: a cloned project's .env or key file is still a secret
        return f"'{p.name}' looks like a secret or key file"
    ws = default_root()
    if _under(p, ws):
        return None  # the agent's own sandbox
    try:
        data = home.home().resolve()
    except OSError:  # pragma: no cover
        data = None
    if data and _under(p, data):
        return "AutoMoto's own settings, memory and conversations"
    sp, hp = _norm(p), _norm(Path.home().resolve())
    for rel_ in _HOME_SENSITIVE:
        q = f"{hp}/{_norm(PurePath(rel_))}"
        if sp == q or sp.startswith(q + "/"):
            return f"~/{rel_} holds credentials, browser data or start-up scripts"
    for d in _SYSTEM_DIRS:
        q = _norm(PurePath(d))
        if sp == q or sp.startswith(q + "/"):
            if sp.startswith(hp + "/") or sp.startswith(_norm(Path(tempfile.gettempdir()).resolve()) + "/"):
                break  # home under /var/home or /root, or the temp folder (/private/var/folders on macOS)
            return f"{d} is a system folder"
    if p.parent == p:
        return "the filesystem root"
    return None


def extra_roots() -> list[Path]:
    """Folders outside the workspace the user allowed (Settings ``allowed_roots`` + env)."""
    from automoto import tenancy

    if tenancy.current() is not None:
        return []  # hosted users only ever get their own workspace
    raw: list[str] = []
    try:
        from automoto import settings

        raw += list(settings.get("allowed_roots") or [])
    except Exception:
        pass
    raw += [x for x in (config.env("AUTOMOTO_ALLOWED_ROOTS", "") or "").split(os.pathsep) if x.strip()]
    out: list[Path] = []
    for r in raw:
        try:
            p = Path(r).expanduser().resolve()
        except OSError:
            continue
        if p.is_dir() and not sensitive(p) and p != Path.home().resolve().parent and p not in out:
            out.append(p)
    return out


def check_root(path: str | os.PathLike) -> Path:
    """Validate a folder a task wants to use as its root (must be an allowed extra root or inside one)."""
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise SandboxError(f"not a folder: {p}")
    why = sensitive(p)
    if why:
        raise SandboxError(f"{p} is off limits: {why}")
    if _under(p, default_root()):
        return p
    if not any(_under(p, r) for r in extra_roots()):
        raise SandboxError(f"{p} is not in your allowed folders (Settings → Files)")
    return p


@contextmanager
def use_root(path: str | os.PathLike | None) -> Iterator[Path]:
    """Run a block with ``path`` (an allowed folder) as the working root."""
    if not path:
        yield root()
        return
    p = check_root(path)
    tok = _ROOT.set(p)
    try:
        yield p
    finally:
        _ROOT.reset(tok)


def resolve(path: str | os.PathLike | None, *, base: Path | None = None, allow_outside: bool = False) -> Path:
    """Map a user/model supplied path into the working root or raise SandboxError.

    With ``allow_outside`` absolute and ``~`` paths inside an allowed extra root are accepted too
    (callers must then treat the access as risky - see ``is_outside``). Sensitive paths are always refused.
    """
    base = (base or root()).resolve()
    raw = str(path or ".").strip()
    if raw.startswith("~"):
        if not allow_outside:
            raise SandboxError("home-relative paths are outside the workspace")
        candidate = Path(raw).expanduser().resolve()
    else:
        p = Path(raw)
        candidate = p.resolve() if p.is_absolute() else (base / p).resolve()
    why = sensitive(candidate)
    if why:
        raise SandboxError(f"'{raw}' is off limits: {why}")
    if _under(candidate, base):
        return candidate
    if allow_outside and any(_under(candidate, r) for r in extra_roots()):
        return candidate
    hint = " (add the folder in Settings → Files to allow it)" if allow_outside else ""
    raise SandboxError(f"'{raw}' is outside the AutoMoto workspace ({base}){hint}")


def is_outside(p: Path) -> bool:
    """True when ``p`` is outside the current working root (an extra-root access)."""
    return not _under(p, root().resolve())


def rel(p: Path) -> str:
    try:
        return p.relative_to(root().resolve()).as_posix() or "."  # forward slashes on every OS
    except ValueError:
        return p.as_posix()


def in_scratch(p: Path) -> bool:
    """Writes here never ask. Only the default workspace has a scratch area."""
    return is_default_root() and _under(p, default_root() / "scratch")


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
