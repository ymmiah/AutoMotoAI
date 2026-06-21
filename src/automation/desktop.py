"""Desktop automation — app launching, window control, screenshots.

Platform support:
  - Windows: pygetwindow + os.startfile + pyautogui
  - Linux:   xdotool / wmctrl + scrot / gnome-screenshot + xdg-open
  - macOS:   open command + pyautogui screenshots
"""
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
IS_MAC     = sys.platform == "darwin"
IS_LINUX   = sys.platform.startswith("linux")


def _has_display() -> bool:
    """Return True if a graphical display is reachable."""
    if IS_WINDOWS or IS_MAC:
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _run(cmd: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ─────────────────────────── app launching ────────────────────────────────────

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
        elif IS_MAC:
            subprocess.Popen(["open", "-a", app_name_or_path])
        else:
            # Linux: try direct exec, then xdg-open, then gtk-launch
            try:
                subprocess.Popen([app_name_or_path])
            except FileNotFoundError:
                subprocess.Popen(["xdg-open", app_name_or_path])
        logger.info("Opened: %s", app_name_or_path)
    except Exception as exc:
        raise AutomationError(f"Cannot open '{app_name_or_path}': {exc}") from exc


# ─────────────────────────── file manager ─────────────────────────────────────

def open_in_file_manager(path: str | Path) -> None:
    """Show a file or folder in the OS file manager."""
    p = Path(path).resolve()
    try:
        if IS_WINDOWS:
            if p.is_file():
                subprocess.Popen(["explorer", "/select,", str(p)])
            else:
                subprocess.Popen(["explorer", str(p)])
        elif IS_MAC:
            subprocess.Popen(["open", str(p)])
        else:
            target = str(p.parent if p.is_file() else p)
            # Try common file managers in order
            for mgr in ("xdg-open", "nautilus", "dolphin", "thunar", "nemo", "pcmanfm"):
                try:
                    subprocess.Popen([mgr, target])
                    break
                except FileNotFoundError:
                    continue
        logger.info("Opened in file manager: %s", p)
    except Exception as exc:
        raise AutomationError(f"Cannot open file manager for '{p}': {exc}") from exc


# ─────────────────────────── screenshot ───────────────────────────────────────

def take_screenshot(save_path: str | Path | None = None) -> Path:
    """Capture the whole screen and save as PNG.

    Tries (in order): pyautogui → scrot → gnome-screenshot → maim → import (ImageMagick).
    Raises AutomationError if no backend works.
    """
    from src.core.config import app_config
    if save_path is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = app_config.screenshots_dir / f"screenshot_{ts}.png"
    out = Path(save_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # pyautogui (all platforms, needs display)
    if _has_display():
        try:
            import pyautogui
            pyautogui.screenshot().save(str(out))
            logger.info("Screenshot → %s (pyautogui)", out)
            return out
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("pyautogui screenshot failed: %s", exc)

    if IS_LINUX:
        # scrot — lightweight X11 screenshot tool
        try:
            subprocess.run(["scrot", str(out)], check=True, timeout=15, capture_output=True)
            logger.info("Screenshot → %s (scrot)", out)
            return out
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

        # gnome-screenshot
        try:
            subprocess.run(["gnome-screenshot", "-f", str(out)], check=True,
                           timeout=15, capture_output=True)
            logger.info("Screenshot → %s (gnome-screenshot)", out)
            return out
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

        # maim (modern scrot replacement)
        try:
            subprocess.run(["maim", str(out)], check=True, timeout=15, capture_output=True)
            logger.info("Screenshot → %s (maim)", out)
            return out
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

        # ImageMagick import
        try:
            subprocess.run(["import", "-window", "root", str(out)], check=True,
                           timeout=15, capture_output=True)
            logger.info("Screenshot → %s (ImageMagick import)", out)
            return out
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

        # xwd + convert (X Window Dump)
        try:
            xwd_path = str(out) + ".xwd"
            subprocess.run(["xwd", "-root", "-out", xwd_path], check=True,
                           timeout=10, capture_output=True)
            subprocess.run(["convert", xwd_path, str(out)], check=True,
                           timeout=10, capture_output=True)
            Path(xwd_path).unlink(missing_ok=True)
            logger.info("Screenshot → %s (xwd+convert)", out)
            return out
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

    raise AutomationError(
        "No screenshot backend available.\n"
        "  Install one: pip install pyautogui\n"
        "  Linux:       sudo apt install scrot  OR  sudo apt install maim"
    )


# ─────────────────────────── window management ────────────────────────────────

def _xdotool(*args: str, timeout: int = 8) -> subprocess.CompletedProcess:
    return subprocess.run(["xdotool"] + list(args), capture_output=True, text=True, timeout=timeout)


def _wmctrl(*args: str, timeout: int = 8) -> subprocess.CompletedProcess:
    return subprocess.run(["wmctrl"] + list(args), capture_output=True, text=True, timeout=timeout)


def get_window_list() -> list[str]:
    """Return titles of all visible windows."""
    if IS_WINDOWS:
        try:
            import pygetwindow as gw
            return [w.title for w in gw.getAllWindows() if w.title.strip()]
        except Exception:
            return []

    if IS_MAC:
        try:
            script = 'tell application "System Events" to get name of every window of every process'
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
            titles = []
            for item in r.stdout.split(","):
                t = item.strip().strip("{}")
                if t and t != "missing value":
                    titles.append(t)
            return titles
        except Exception:
            return []

    # Linux — wmctrl is most reliable
    try:
        r = _wmctrl("-l")
        if r.returncode == 0:
            titles = []
            for line in r.stdout.splitlines():
                parts = line.split(None, 3)
                if len(parts) >= 4 and parts[3].strip():
                    titles.append(parts[3].strip())
            return titles
    except FileNotFoundError:
        pass

    # xdotool fallback
    try:
        r = _xdotool("search", "--onlyvisible", "--name", "")
        if r.returncode == 0 and r.stdout.strip():
            titles = []
            for wid in r.stdout.strip().split()[:100]:
                t = _xdotool("getwindowname", wid, timeout=3)
                if t.returncode == 0 and t.stdout.strip():
                    titles.append(t.stdout.strip())
            return titles
    except (FileNotFoundError, Exception):
        pass

    return []


def focus_window(title: str) -> None:
    """Bring a window to the foreground by title."""
    if IS_WINDOWS:
        try:
            import pygetwindow as gw
            wins = gw.getWindowsWithTitle(title)
            if not wins:
                raise AutomationError(f"No window found with title '{title}'")
            wins[0].activate()
            return
        except AutomationError:
            raise
        except Exception as exc:
            raise AutomationError(f"Cannot focus '{title}': {exc}") from exc

    if IS_MAC:
        try:
            script = f'tell application "{title}" to activate'
            subprocess.run(["osascript", "-e", script], check=True, timeout=10)
            return
        except Exception as exc:
            raise AutomationError(f"Cannot focus '{title}' on macOS: {exc}") from exc

    # Linux — wmctrl
    try:
        r = _wmctrl("-a", title)
        if r.returncode == 0:
            return
    except FileNotFoundError:
        pass

    # xdotool fallback
    try:
        r = _xdotool("search", "--name", title, "windowfocus", "--sync")
        if r.returncode == 0:
            return
        raise AutomationError(f"No window matching '{title}' found via xdotool")
    except FileNotFoundError:
        pass

    raise AutomationError(
        f"Cannot focus '{title}'. "
        "Install wmctrl (sudo apt install wmctrl) or xdotool (sudo apt install xdotool)."
    )


def minimize_window(title: str) -> None:
    """Minimize a window by title."""
    if IS_WINDOWS:
        try:
            import pygetwindow as gw
            for w in gw.getWindowsWithTitle(title):
                w.minimize()
        except Exception as exc:
            raise AutomationError(f"Cannot minimize '{title}': {exc}") from exc
        return

    if IS_MAC:
        try:
            script = f'tell application "System Events" to set miniaturized of window 1 of process "{title}" to true'
            subprocess.run(["osascript", "-e", script], check=True, timeout=10)
            return
        except Exception as exc:
            raise AutomationError(f"Cannot minimize '{title}' on macOS: {exc}") from exc

    # Linux — xdotool (most reliable for minimize)
    try:
        r = _xdotool("search", "--name", title)
        if r.returncode == 0:
            for wid in r.stdout.strip().split():
                _xdotool("windowminimize", wid)
            return
    except FileNotFoundError:
        pass

    # wmctrl fallback (hide via remove_hidden trick)
    try:
        _wmctrl("-r", title, "-b", "add,hidden")
        return
    except FileNotFoundError:
        pass

    raise AutomationError(
        f"Cannot minimize '{title}'. Install xdotool: sudo apt install xdotool"
    )


def maximize_window(title: str) -> None:
    """Maximize a window by title."""
    if IS_WINDOWS:
        try:
            import pygetwindow as gw
            for w in gw.getWindowsWithTitle(title):
                w.maximize()
        except Exception as exc:
            raise AutomationError(f"Cannot maximize '{title}': {exc}") from exc
        return

    if IS_MAC:
        try:
            script = f'tell application "System Events" to set zoomed of window 1 of process "{title}" to true'
            subprocess.run(["osascript", "-e", script], check=True, timeout=10)
            return
        except Exception as exc:
            raise AutomationError(f"Cannot maximize '{title}' on macOS: {exc}") from exc

    # Linux — wmctrl
    try:
        _wmctrl("-r", title, "-b", "add,maximized_vert,maximized_horz")
        return
    except FileNotFoundError:
        pass

    # xdotool fallback — get window dimensions then resize
    try:
        r = _xdotool("search", "--name", title)
        if r.returncode == 0:
            for wid in r.stdout.strip().split():
                _xdotool("windowactivate", wid)
                _xdotool("windowmove", wid, "0", "0")
                # Get screen size
                disp = _xdotool("getdisplaygeometry")
                if disp.returncode == 0:
                    w, h = disp.stdout.strip().split()
                    _xdotool("windowsize", wid, w, h)
            return
    except FileNotFoundError:
        pass

    raise AutomationError(
        f"Cannot maximize '{title}'. Install wmctrl: sudo apt install wmctrl"
    )


def close_window(title: str) -> None:
    """Close a window by title (graceful — sends close event)."""
    if IS_WINDOWS:
        try:
            import pygetwindow as gw
            for w in gw.getWindowsWithTitle(title):
                w.close()
        except Exception as exc:
            raise AutomationError(f"Cannot close '{title}': {exc}") from exc
        return

    if IS_LINUX:
        try:
            _wmctrl("-c", title)
            return
        except FileNotFoundError:
            pass
        try:
            r = _xdotool("search", "--name", title)
            for wid in r.stdout.strip().split():
                _xdotool("windowclose", wid)
            return
        except FileNotFoundError:
            pass

    raise AutomationError(f"Cannot close '{title}': no backend available")


def move_resize_window(title: str, x: int, y: int, width: int, height: int) -> None:
    """Move and resize a window by title."""
    if IS_WINDOWS:
        try:
            import pygetwindow as gw
            for w in gw.getWindowsWithTitle(title):
                w.moveTo(x, y)
                w.resizeTo(width, height)
        except Exception as exc:
            raise AutomationError(f"Cannot move/resize '{title}': {exc}") from exc
        return

    if IS_LINUX:
        try:
            _wmctrl("-r", title, "-e", f"0,{x},{y},{width},{height}")
            return
        except FileNotFoundError:
            pass
        try:
            r = _xdotool("search", "--name", title)
            for wid in r.stdout.strip().split():
                _xdotool("windowmove", wid, str(x), str(y))
                _xdotool("windowsize", wid, str(width), str(height))
            return
        except FileNotFoundError:
            pass

    raise AutomationError(f"Cannot move/resize '{title}': no backend available")


# ─────────────────────────── installed apps ───────────────────────────────────

def get_installed_apps() -> list[dict]:
    """Enumerate installed applications. Cross-platform."""
    if IS_WINDOWS:
        return _get_installed_apps_windows()
    if IS_LINUX:
        return _get_installed_apps_linux()
    if IS_MAC:
        return _get_installed_apps_mac()
    return []


def _get_installed_apps_windows() -> list[dict]:
    try:
        import winreg
        apps: list[dict] = []
        seen: set[str] = set()
        registry_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
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
                                    loc = winreg.QueryValueEx(sk, "InstallLocation")[0]
                                except (FileNotFoundError, OSError):
                                    loc = ""
                                apps.append({"name": name, "location": loc, "source": "registry"})
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                continue
        return sorted(apps, key=lambda a: a["name"].lower())
    except Exception as exc:
        logger.warning("Windows app enumeration failed: %s", exc)
        return []


def _get_installed_apps_linux() -> list[dict]:
    apps: list[dict] = []
    seen: set[str] = set()

    def _add(name: str, loc: str, source: str) -> None:
        if name and name not in seen:
            seen.add(name)
            apps.append({"name": name, "location": loc, "source": source})

    # .desktop files (XDG applications) — most authoritative on Linux
    xdg_dirs = [
        Path("/usr/share/applications"),
        Path("/usr/local/share/applications"),
        Path.home() / ".local" / "share" / "applications",
        Path("/var/lib/flatpak/exports/share/applications"),
        Path.home() / ".local" / "share" / "flatpak" / "exports" / "share" / "applications",
    ]
    for d in xdg_dirs:
        if not d.is_dir():
            continue
        for desktop_file in sorted(d.glob("*.desktop")):
            try:
                text = desktop_file.read_text(errors="replace")
                name = exec_line = ""
                hidden = nodisplay = False
                for line in text.splitlines():
                    if line.startswith("Name=") and not name:
                        name = line[5:].strip()
                    elif line.startswith("Exec=") and not exec_line:
                        exec_line = line[5:].strip().split()[0]
                    elif line.lower() in ("hidden=true", "nodisplay=true"):
                        hidden = True
                if name and not hidden:
                    _add(name, exec_line, "desktop-file")
            except Exception:
                continue

    # dpkg (Debian/Ubuntu) — fallback when .desktop entries are sparse
    if len(apps) < 5:
        try:
            r = subprocess.run(
                ["dpkg", "--get-selections"],
                capture_output=True, text=True, timeout=15,
            )
            for line in r.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "install":
                    _add(parts[0], "", "dpkg")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # rpm (RHEL/Fedora/CentOS)
    if len(apps) < 5:
        try:
            r = subprocess.run(
                ["rpm", "-qa", "--queryformat", "%{NAME}|%{INSTALLPREFIX}\\n"],
                capture_output=True, text=True, timeout=15,
            )
            for line in r.stdout.splitlines():
                parts = line.split("|", 1)
                _add(parts[0], parts[1] if len(parts) > 1 else "", "rpm")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # flatpak
    try:
        r = subprocess.run(
            ["flatpak", "list", "--columns=name,application"],
            capture_output=True, text=True, timeout=15,
        )
        for line in r.stdout.splitlines()[1:]:
            parts = line.split("\t", 1)
            _add(parts[0].strip(), parts[1].strip() if len(parts) > 1 else "", "flatpak")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # snap
    try:
        r = subprocess.run(["snap", "list"], capture_output=True, text=True, timeout=15)
        for line in r.stdout.splitlines()[1:]:
            parts = line.split()
            if parts:
                _add(parts[0], "", "snap")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return sorted(apps, key=lambda a: a["name"].lower())[:500]


def _get_installed_apps_mac() -> list[dict]:
    apps: list[dict] = []
    app_dirs = [Path("/Applications"), Path.home() / "Applications"]
    for d in app_dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.app")):
            apps.append({"name": p.stem, "location": str(p), "source": "Applications"})
    # Homebrew
    try:
        r = subprocess.run(["brew", "list", "--formula"], capture_output=True,
                           text=True, timeout=15)
        for name in r.stdout.splitlines():
            if name.strip():
                apps.append({"name": name.strip(), "location": "", "source": "brew"})
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return sorted(apps, key=lambda a: a["name"].lower())


# ─────────────────────────── display info ─────────────────────────────────────

def get_screen_size() -> tuple[int, int]:
    """Return (width, height) of the primary screen in pixels."""
    if _has_display():
        try:
            import pyautogui
            return pyautogui.size()
        except Exception:
            pass

    if IS_LINUX:
        try:
            r = _xdotool("getdisplaygeometry")
            if r.returncode == 0:
                w, h = r.stdout.strip().split()
                return int(w), int(h)
        except Exception:
            pass
        try:
            r = subprocess.run(["xrandr"], capture_output=True, text=True, timeout=5)
            for line in r.stdout.splitlines():
                if " connected" in line and "x" in line:
                    import re
                    m = re.search(r"(\d+)x(\d+)\+0\+0", line)
                    if m:
                        return int(m.group(1)), int(m.group(2))
        except Exception:
            pass

    return (1920, 1080)   # sane fallback


def desktop_status() -> dict:
    """Return a dict describing the current desktop automation capabilities."""
    return {
        "display":      _has_display(),
        "platform":     sys.platform,
        "pyautogui":    _check_import("pyautogui"),
        "pygetwindow":  _check_import("pygetwindow") if IS_WINDOWS else None,
        "xdotool":      _cmd_ok("xdotool") if IS_LINUX else None,
        "wmctrl":       _cmd_ok("wmctrl")  if IS_LINUX else None,
        "scrot":        _cmd_ok("scrot")   if IS_LINUX else None,
        "maim":         _cmd_ok("maim")    if IS_LINUX else None,
        "screen_size":  get_screen_size() if _has_display() else None,
    }


def _check_import(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False


def _cmd_ok(cmd: str) -> bool:
    try:
        subprocess.run([cmd, "--version"], capture_output=True, timeout=3)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
