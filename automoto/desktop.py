"""Cross-platform desktop tools (Windows, macOS, Linux).

Every tool declares a risk level:
  * ``safe``    - read-only (list a folder, system info).
  * ``confirm`` - changes something on your machine; the CLI/web UI must ask first.
  * ``danger``  - runs a shell command; always asks, and is off unless
                  ``AUTOMOTO_ALLOW_SHELL=1``.

GUI tools (typing, hotkeys, screenshots) need ``pyautogui`` and a real desktop
session; they report a clear error instead of crashing on headless machines.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from automoto import config

OS = platform.system()  # "Windows" | "Darwin" | "Linux"
OS_LABEL = {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}.get(OS, OS)


class ToolError(Exception):
    pass


def _gui():
    try:
        import pyautogui  # noqa: WPS433

        pyautogui.FAILSAFE = True  # slam the mouse into a corner to abort
        pyautogui.PAUSE = 0.3
        return pyautogui
    except Exception as exc:  # ImportError, or no display on Linux
        raise ToolError(f"GUI automation unavailable ({exc.__class__.__name__}). Install pyautogui and run in a desktop session.") from None


def _workdir() -> Path:
    base = Path(config.env("AUTOMOTO_WORKDIR") or Path.home() / "AutoMoto").expanduser()
    base.mkdir(parents=True, exist_ok=True)
    return base


def _safe_path(p: str) -> Path:
    """Relative paths land in AUTOMOTO_WORKDIR (default ~/AutoMoto)."""
    path = Path(p).expanduser()
    if not path.is_absolute():
        path = _workdir() / path
    return path.resolve()


# -- tools --------------------------------------------------------------------
def open_app(name: str) -> str:
    name = name.strip()
    if not name:
        raise ToolError("app name is empty")
    if OS == "Windows":
        os.startfile(name) if os.path.exists(name) else subprocess.Popen(["cmd", "/c", "start", "", name])  # type: ignore[attr-defined]
    elif OS == "Darwin":
        subprocess.Popen(["open", name] if os.path.exists(name) else ["open", "-a", name])
    else:
        exe = shutil.which(name) or shutil.which(name.lower())
        if exe:
            subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        elif shutil.which("gtk-launch"):
            subprocess.Popen(["gtk-launch", name.lower()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            raise ToolError(f"could not find '{name}' on PATH")
    return f"Opened {name} on {OS_LABEL}"


def open_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url}"


def create_folder(path: str) -> str:
    p = _safe_path(path)
    p.mkdir(parents=True, exist_ok=True)
    return f"Folder ready: {p}"


def create_file(path: str, content: str = "") -> str:
    p = _safe_path(path)
    if p.exists():
        raise ToolError(f"{p} already exists (AutoMoto never overwrites files)")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Created {p} ({len(content)} chars)"


def list_dir(path: str = ".") -> str:
    p = _safe_path(path)
    if not p.is_dir():
        raise ToolError(f"{p} is not a folder")
    items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:200]
    return "\n".join(("📁 " if i.is_dir() else "📄 ") + i.name for i in items) or "(empty)"


def system_info() -> str:
    return f"{OS_LABEL} {platform.release()} · Python {sys.version.split()[0]} · {platform.machine()}"


def screenshot(path: str = "screenshot.png") -> str:
    p = _safe_path(path)
    _gui().screenshot().save(p)
    return str(p)


def type_text(text: str) -> str:
    _gui().write(text, interval=0.02)
    return f"Typed {len(text)} characters"


def hotkey(keys: str) -> str:
    parts = [k.strip().lower() for k in keys.replace("+", " ").split() if k.strip()]
    if not parts:
        raise ToolError("no keys given")
    _gui().hotkey(*parts)
    return f"Pressed {'+'.join(parts)}"


def run_command(command: str) -> str:
    if (config.env("AUTOMOTO_ALLOW_SHELL", "0") or "0").lower() not in ("1", "true", "yes"):
        raise ToolError("shell commands are disabled. Set AUTOMOTO_ALLOW_SHELL=1 to allow them (still confirmed each time).")
    res = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60, cwd=_workdir())
    out = (res.stdout + res.stderr).strip()
    return f"exit {res.returncode}\n{out[-4000:]}"


@dataclass(frozen=True)
class Tool:
    name: str
    risk: str
    args: tuple[str, ...]
    description: str
    fn: Callable[..., str]


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("system_info", "safe", (), "OS, version and Python runtime", system_info),
    Tool("list_dir", "safe", ("path",), "List a folder (relative paths are inside the AutoMoto workdir)", list_dir),
    Tool("open_url", "confirm", ("url",), "Open a web page in the default browser", open_url),
    Tool("open_app", "confirm", ("name",), "Launch an application by name or path", open_app),
    Tool("create_folder", "confirm", ("path",), "Create a folder", create_folder),
    Tool("create_file", "confirm", ("path", "content"), "Create a new text file (never overwrites)", create_file),
    Tool("screenshot", "confirm", ("path",), "Save a screenshot of the screen", screenshot),
    Tool("type_text", "confirm", ("text",), "Type text into the focused window", type_text),
    Tool("hotkey", "confirm", ("keys",), "Press a key combo such as ctrl+s", hotkey),
    Tool("run_command", "danger", ("command",), "Run a shell command (off unless AUTOMOTO_ALLOW_SHELL=1)", run_command),
]}


def tool_manifest() -> str:
    return "\n".join(f"- {t.name}({', '.join(t.args)}) [{t.risk}]: {t.description}" for t in TOOLS.values())


def execute(action: dict[str, Any], *, confirmed: bool = False) -> dict[str, Any]:
    """Run one proposed action. Non-safe tools refuse to run unless ``confirmed``."""
    name = action.get("tool")
    tool = TOOLS.get(name or "")
    if not tool:
        return {"ok": False, "tool": name, "error": f"unknown tool '{name}'"}
    if not config.desktop_enabled():
        return {"ok": False, "tool": name, "error": "desktop tools are disabled (AUTOMOTO_ENABLE_DESKTOP=0)"}
    if tool.risk != "safe" and not confirmed:
        return {"ok": False, "tool": name, "needs_confirmation": True, "risk": tool.risk}
    args = {k: v for k, v in (action.get("args") or {}).items() if k in tool.args}
    try:
        return {"ok": True, "tool": name, "result": tool.fn(**args)}
    except TypeError as exc:
        return {"ok": False, "tool": name, "error": f"bad arguments: {exc}"}
    except ToolError as exc:
        return {"ok": False, "tool": name, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "tool": name, "error": f"{exc.__class__.__name__}: {exc}"}
