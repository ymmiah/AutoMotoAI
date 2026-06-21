"""Desktop automation — window control, app launching, screenshots."""
from __future__ import annotations

import datetime
import logging
import os
import subprocess
import sys
from pathlib import Path

from src.core.exceptions import AutomationError

logger = logging.getLogger(__name__)
IS_WINDOWS = sys.platform == "win32"


def open_application(app_name_or_path: str) -> None:
    """Launch an app by executable path or name."""
    p = Path(app_name_or_path)
    try:
        if p.is_file():
            if IS_WINDOWS:
                os.startfile(str(p))
            else:
                subprocess.Popen([str(p)])
        elif IS_WINDOWS:
            subprocess.Popen(
                ["cmd", "/c", "start", "", app_name_or_path],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            subprocess.Popen([app_name_or_path])
        logger.info("Opened: %s", app_name_or_path)
    except Exception as exc:
        raise AutomationError(f"Cannot open '{app_name_or_path}': {exc}") from exc


def open_in_file_manager(path: str | Path) -> None:
    """Show a file or folder in the OS file manager."""
    p = Path(path).resolve()
    try:
        if IS_WINDOWS:
            if p.is_file():
                subprocess.Popen(["explorer", "/select,", str(p)])
            else:
                subprocess.Popen(["explorer", str(p)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p.parent if p.is_file() else p)])
        logger.info("Opened in file manager: %s", p)
    except Exception as exc:
        raise AutomationError(f"Cannot open file manager for '{p}': {exc}") from exc


def take_screenshot(save_path: str | Path | None = None) -> Path:
    """Capture the whole screen and save as PNG."""
    from src.core.config import app_config
    if save_path is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = app_config.screenshots_dir / f"screenshot_{ts}.png"
    out = Path(save_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        import pyautogui
        pyautogui.screenshot().save(str(out))
        logger.info("Screenshot saved: %s", out)
        return out
    except ImportError as exc:
        raise AutomationError("pyautogui not installed. Run: pip install pyautogui") from exc
    except Exception as exc:
        raise AutomationError(f"Screenshot failed: {exc}") from exc


def get_window_list() -> list[str]:
    """Return titles of all visible windows (Windows only)."""
    if not IS_WINDOWS:
        return []
    try:
        import pygetwindow as gw
        return [w.title for w in gw.getAllWindows() if w.title.strip()]
    except Exception:
        return []


def focus_window(title: str) -> None:
    if not IS_WINDOWS:
        raise AutomationError("Window focus is Windows-only.")
    try:
        import pygetwindow as gw
        wins = gw.getWindowsWithTitle(title)
        if not wins:
            raise AutomationError(f"No window found with title '{title}'")
        wins[0].activate()
    except Exception as exc:
        raise AutomationError(f"Cannot focus '{title}': {exc}") from exc


def minimize_window(title: str) -> None:
    if not IS_WINDOWS:
        return
    try:
        import pygetwindow as gw
        for w in gw.getWindowsWithTitle(title):
            w.minimize()
    except Exception as exc:
        raise AutomationError(f"Cannot minimize '{title}': {exc}") from exc


def maximize_window(title: str) -> None:
    if not IS_WINDOWS:
        return
    try:
        import pygetwindow as gw
        for w in gw.getWindowsWithTitle(title):
            w.maximize()
    except Exception as exc:
        raise AutomationError(f"Cannot maximize '{title}': {exc}") from exc


def get_installed_apps() -> list[dict]:
    """Enumerate installed applications (Windows registry-based)."""
    if not IS_WINDOWS:
        return []
    try:
        import winreg
        apps: list[dict] = []
        seen: set[str] = set()
        registry_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for hive, reg_path in registry_paths:
            try:
                with winreg.OpenKey(hive, reg_path) as key:
                    count = winreg.QueryInfoKey(key)[0]
                    for i in range(count):
                        try:
                            sub = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, sub) as sk:
                                name = winreg.QueryValueEx(sk, "DisplayName")[0]
                                if not name or name in seen:
                                    continue
                                seen.add(name)
                                try:
                                    location = winreg.QueryValueEx(sk, "InstallLocation")[0]
                                except (FileNotFoundError, OSError):
                                    location = ""
                                apps.append({"name": name, "location": location})
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                continue
        return sorted(apps, key=lambda a: a["name"].lower())
    except Exception as exc:
        logger.warning("Cannot enumerate installed apps: %s", exc)
        return []
