"""Keyboard and mouse simulation.

Backends (tried in order):
  1. pyautogui  — cross-platform, needs X11/Wayland on Linux
  2. xdotool    — Linux fallback for keyboard/mouse without pyautogui
  3. ydotool    — Linux Wayland fallback
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Optional

from src.core.exceptions import AutomationError

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
IS_LINUX   = sys.platform.startswith("linux")


def _has_display() -> bool:
    if IS_WINDOWS or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _pg():
    """Return pyautogui module (lazy, configured)."""
    if not _has_display():
        raise AutomationError(
            "No graphical display detected.\n"
            "  Set DISPLAY env var:  export DISPLAY=:0\n"
            "  Or start Xvfb:        Xvfb :1 -screen 0 1920x1080x24 &\n"
            "                        export DISPLAY=:1"
        )
    try:
        import pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.2
        return pyautogui
    except ImportError as exc:
        raise AutomationError(
            "pyautogui not installed. Run: pip install pyautogui\n"
            "Linux also needs: sudo apt install python3-xlib python3-tk"
        ) from exc


def _xdotool(*args: str, timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(["xdotool"] + list(args), capture_output=True, text=True, timeout=timeout)


def _ydotool(*args: str, timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(["ydotool"] + list(args), capture_output=True, text=True, timeout=timeout)


def _xdotool_ok() -> bool:
    try:
        subprocess.run(["xdotool", "version"], capture_output=True, timeout=3)
        return True
    except (FileNotFoundError, OSError):
        return False


# ─────────────────────────── keyboard ─────────────────────────────────────────

def type_text(text: str, interval: float = 0.03) -> None:
    """Simulate typing text at the current cursor position."""
    # pyautogui
    try:
        _pg().write(text, interval=interval)
        logger.debug("Typed %d chars via pyautogui", len(text))
        return
    except AutomationError:
        pass
    except Exception as exc:
        logger.debug("pyautogui type_text failed: %s", exc)

    # xdotool (Linux)
    if IS_LINUX:
        try:
            delay_ms = max(1, int(interval * 1000))
            _xdotool("type", "--delay", str(delay_ms), "--clearmodifiers", "--", text)
            logger.debug("Typed %d chars via xdotool", len(text))
            return
        except FileNotFoundError:
            pass

        # ydotool (Wayland)
        try:
            _ydotool("type", "--key-delay", str(int(interval * 1000)), "--", text)
            return
        except FileNotFoundError:
            pass

    raise AutomationError(
        "Cannot type text: no automation backend available.\n"
        "  Install pyautogui:  pip install pyautogui\n"
        "  Linux alternative:  sudo apt install xdotool"
    )


def press_key(key: str) -> None:
    """Press a single keyboard key (e.g. 'enter', 'escape', 'f5', 'ctrl')."""
    try:
        _pg().press(key)
        return
    except AutomationError:
        pass
    except Exception as exc:
        logger.debug("pyautogui press_key failed: %s", exc)

    if IS_LINUX:
        try:
            _xdotool("key", "--clearmodifiers", key)
            return
        except FileNotFoundError:
            pass
        try:
            _ydotool("key", key)
            return
        except FileNotFoundError:
            pass

    raise AutomationError(f"Cannot press key '{key}': no automation backend.")


def hotkey(*keys: str) -> None:
    """Execute a keyboard shortcut (e.g. hotkey('ctrl', 's'))."""
    try:
        _pg().hotkey(*keys)
        return
    except AutomationError:
        pass
    except Exception as exc:
        logger.debug("pyautogui hotkey failed: %s", exc)

    if IS_LINUX:
        combo = "+".join(keys)
        try:
            _xdotool("key", "--clearmodifiers", combo)
            return
        except FileNotFoundError:
            pass
        try:
            _ydotool("key", combo)
            return
        except FileNotFoundError:
            pass

    raise AutomationError(f"Cannot execute hotkey {keys}: no automation backend.")


# ─────────────────────────── mouse ────────────────────────────────────────────

def click(x: int, y: int, button: str = "left", clicks: int = 1) -> None:
    """Simulate a mouse click at (x, y)."""
    btn_map = {"left": 1, "middle": 2, "right": 3}

    try:
        _pg().click(x, y, button=button, clicks=clicks)
        return
    except AutomationError:
        pass
    except Exception as exc:
        logger.debug("pyautogui click failed: %s", exc)

    if IS_LINUX:
        btn_num = str(btn_map.get(button, 1))
        try:
            for _ in range(clicks):
                _xdotool("mousemove", str(x), str(y), "click", btn_num)
            return
        except FileNotFoundError:
            pass

    raise AutomationError(f"Cannot click at ({x},{y}): no automation backend.")


def move_to(x: int, y: int, duration: float = 0.2) -> None:
    """Move the mouse cursor to (x, y)."""
    try:
        _pg().moveTo(x, y, duration=duration)
        return
    except AutomationError:
        pass
    except Exception as exc:
        logger.debug("pyautogui move_to failed: %s", exc)

    if IS_LINUX:
        try:
            _xdotool("mousemove", str(x), str(y))
            return
        except FileNotFoundError:
            pass

    raise AutomationError(f"Cannot move mouse to ({x},{y}): no automation backend.")


def scroll(x: int, y: int, direction: str = "down", amount: int = 3) -> None:
    """Scroll the mouse wheel at (x, y)."""
    # xdotool buttons: 4=up, 5=down, 6=left, 7=right
    btn_map = {"up": 4, "down": 5, "left": 6, "right": 7}

    try:
        pg = _pg()
        if direction in ("up", "down"):
            pg.scroll(x, y, clicks=amount if direction == "up" else -amount)
        return
    except AutomationError:
        pass
    except Exception as exc:
        logger.debug("pyautogui scroll failed: %s", exc)

    if IS_LINUX:
        btn = str(btn_map.get(direction, 5))
        try:
            for _ in range(amount):
                _xdotool("mousemove", str(x), str(y), "click", btn)
            return
        except FileNotFoundError:
            pass

    raise AutomationError(f"Cannot scroll at ({x},{y}): no automation backend.")


def drag(start_x: int, start_y: int, end_x: int, end_y: int,
          button: str = "left", duration: float = 0.5) -> None:
    """Click-drag from (start_x, start_y) to (end_x, end_y)."""
    try:
        _pg().drag(start_x, start_y, end_x - start_x, end_y - start_y,
                   button=button, duration=duration, relative=False)
        return
    except AutomationError:
        pass
    except Exception as exc:
        logger.debug("pyautogui drag failed: %s", exc)

    if IS_LINUX:
        btn_num = str({"left": 1, "middle": 2, "right": 3}.get(button, 1))
        try:
            _xdotool(
                "mousemove", str(start_x), str(start_y),
                "mousedown", btn_num,
                "mousemove", str(end_x), str(end_y),
                "mouseup", btn_num,
            )
            return
        except FileNotFoundError:
            pass

    raise AutomationError("Cannot drag: no automation backend.")


# ─────────────────────────── status ───────────────────────────────────────────

def input_status() -> dict:
    """Return availability of input simulation backends."""
    pg_ok = False
    try:
        import pyautogui  # noqa: F401
        pg_ok = True
    except ImportError:
        pass

    xdt_ok = False
    if IS_LINUX:
        try:
            subprocess.run(["xdotool", "version"], capture_output=True, timeout=3)
            xdt_ok = True
        except (FileNotFoundError, OSError):
            pass

    ydt_ok = False
    if IS_LINUX:
        try:
            subprocess.run(["ydotool", "--version"], capture_output=True, timeout=3)
            ydt_ok = True
        except (FileNotFoundError, OSError):
            pass

    return {
        "display":    _has_display(),
        "pyautogui":  pg_ok,
        "xdotool":    xdt_ok if IS_LINUX else None,
        "ydotool":    ydt_ok if IS_LINUX else None,
        "available":  _has_display() and (pg_ok or xdt_ok or ydt_ok),
    }
