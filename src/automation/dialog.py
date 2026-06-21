"""Cross-platform GUI dialogs — tkinter primary, zenity/kdialog fallbacks."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
IS_MAC     = sys.platform == "darwin"


def _has_display() -> bool:
    """Return True if a graphical display is reachable."""
    if IS_WINDOWS or IS_MAC:
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _tk_ok() -> bool:
    """Return True if tkinter is importable and a display is available."""
    if not _has_display():
        return False
    try:
        import tkinter  # noqa: F401
        return True
    except ImportError:
        return False


def _zenity(*args: str, timeout: int = 300) -> tuple[int, str]:
    r = subprocess.run(["zenity"] + list(args), capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout.strip()


def _kdialog(*args: str, timeout: int = 300) -> tuple[int, str]:
    r = subprocess.run(["kdialog"] + list(args), capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout.strip()


def _tk_root():
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    return root


# ─────────────────────────── message ──────────────────────────────────────────

def show_message(title: str, message: str, kind: str = "info") -> None:
    """Display a message dialog (kind: 'info' | 'warning' | 'error').

    Falls back to logger.info when no display is available.
    """
    if not _has_display():
        logger.info("[DIALOG %s] %s — %s", kind.upper(), title, message)
        return

    if _tk_ok():
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = _tk_root()
            getattr(messagebox, {
                "error":   "showerror",
                "warning": "showwarning",
            }.get(kind, "showinfo"))(title, message, parent=root)
            root.destroy()
            return
        except Exception as exc:
            logger.debug("tkinter show_message failed: %s", exc)

    try:
        _zenity(f"--{kind}", f"--title={title}", f"--text={message}")
        return
    except Exception:
        pass

    try:
        if kind == "error":
            _kdialog("--error", message, "--title", title)
        elif kind == "warning":
            _kdialog("--sorry", message, "--title", title)
        else:
            _kdialog("--msgbox", message, "--title", title)
    except Exception:
        logger.info("[%s] %s — %s", kind.upper(), title, message)


# ─────────────────────────── yes / no ─────────────────────────────────────────

def ask_yes_no(title: str, message: str) -> bool:
    """Display a Yes/No dialog. Returns True if the user chose Yes."""
    if not _has_display():
        raise RuntimeError("No display available for interactive dialogs.")

    if _tk_ok():
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = _tk_root()
            result = messagebox.askyesno(title, message, parent=root)
            root.destroy()
            return bool(result)
        except Exception as exc:
            logger.debug("tkinter ask_yes_no failed: %s", exc)

    try:
        code, _ = _zenity("--question", f"--title={title}", f"--text={message}")
        return code == 0
    except Exception:
        pass

    try:
        code, _ = _kdialog("--yesno", message, "--title", title)
        return code == 0
    except Exception:
        pass

    raise RuntimeError("No dialog backend available. Install zenity (sudo apt install zenity).")


# ─────────────────────────── text input ───────────────────────────────────────

def ask_input(title: str, prompt: str, default: str = "") -> Optional[str]:
    """Display a text-input dialog. Returns the entered string, or None if cancelled."""
    if not _has_display():
        raise RuntimeError("No display available for interactive dialogs.")

    if _tk_ok():
        try:
            import tkinter as tk
            from tkinter import simpledialog
            root = _tk_root()
            result = simpledialog.askstring(title, prompt, initialvalue=default, parent=root)
            root.destroy()
            return result
        except Exception as exc:
            logger.debug("tkinter ask_input failed: %s", exc)

    try:
        code, out = _zenity(
            "--entry", f"--title={title}", f"--text={prompt}", f"--entry-text={default}"
        )
        return out if code == 0 else None
    except Exception:
        pass

    try:
        code, out = _kdialog("--inputbox", prompt, default, "--title", title)
        return out if code == 0 else None
    except Exception:
        pass

    raise RuntimeError("No dialog backend available. Install zenity (sudo apt install zenity).")


# ─────────────────────────── file / folder pickers ────────────────────────────

def open_file_dialog(
    title: str = "Open File",
    filetypes: Optional[list[tuple[str, str]]] = None,
    initial_dir: str = "",
) -> Optional[str]:
    """Show an open-file dialog. Returns the selected path, or None."""
    if not _has_display():
        raise RuntimeError("No display available for file dialogs.")

    if _tk_ok():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = _tk_root()
            kw: dict = {"title": title}
            if filetypes:
                kw["filetypes"] = filetypes
            if initial_dir:
                kw["initialdir"] = initial_dir
            result = filedialog.askopenfilename(**kw)
            root.destroy()
            return result or None
        except Exception as exc:
            logger.debug("tkinter open_file_dialog failed: %s", exc)

    try:
        args = ["--file-selection", f"--title={title}"]
        if initial_dir:
            args.append(f"--filename={initial_dir}/")
        code, out = _zenity(*args)
        return out if code == 0 and out else None
    except Exception:
        pass

    raise RuntimeError("No file dialog backend available. Install zenity (sudo apt install zenity).")


def save_file_dialog(
    title: str = "Save File",
    default_name: str = "",
    filetypes: Optional[list[tuple[str, str]]] = None,
    initial_dir: str = "",
) -> Optional[str]:
    """Show a save-file dialog. Returns the chosen path, or None."""
    if not _has_display():
        raise RuntimeError("No display available for file dialogs.")

    if _tk_ok():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = _tk_root()
            kw: dict = {"title": title}
            if filetypes:
                kw["filetypes"] = filetypes
            if default_name:
                kw["initialfile"] = default_name
            if initial_dir:
                kw["initialdir"] = initial_dir
            result = filedialog.asksaveasfilename(**kw)
            root.destroy()
            return result or None
        except Exception as exc:
            logger.debug("tkinter save_file_dialog failed: %s", exc)

    try:
        args = ["--file-selection", "--save", f"--title={title}"]
        if default_name:
            args.append(f"--filename={default_name}")
        code, out = _zenity(*args)
        return out if code == 0 and out else None
    except Exception:
        pass

    raise RuntimeError("No file dialog backend available. Install zenity (sudo apt install zenity).")


def open_folder_dialog(
    title: str = "Select Folder",
    initial_dir: str = "",
) -> Optional[str]:
    """Show a folder-selection dialog. Returns the chosen path, or None."""
    if not _has_display():
        raise RuntimeError("No display available for folder dialogs.")

    if _tk_ok():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = _tk_root()
            kw: dict = {"title": title, "mustexist": True}
            if initial_dir:
                kw["initialdir"] = initial_dir
            result = filedialog.askdirectory(**kw)
            root.destroy()
            return result or None
        except Exception as exc:
            logger.debug("tkinter open_folder_dialog failed: %s", exc)

    try:
        args = ["--file-selection", "--directory", f"--title={title}"]
        if initial_dir:
            args.append(f"--filename={initial_dir}/")
        code, out = _zenity(*args)
        return out if code == 0 and out else None
    except Exception:
        pass

    raise RuntimeError("No folder dialog backend available. Install zenity (sudo apt install zenity).")


# ─────────────────────────── status ───────────────────────────────────────────

def dialog_status() -> dict:
    """Return availability of each dialog backend."""
    tk_ok = _tk_ok()
    zenity_ok = False
    kdialog_ok = False
    try:
        subprocess.run(["zenity", "--version"], capture_output=True, timeout=3)
        zenity_ok = True
    except Exception:
        pass
    try:
        subprocess.run(["kdialog", "--version"], capture_output=True, timeout=3)
        kdialog_ok = True
    except Exception:
        pass
    return {
        "display": _has_display(),
        "tkinter": tk_ok,
        "zenity":  zenity_ok,
        "kdialog": kdialog_ok,
        "available": tk_ok or zenity_ok or kdialog_ok,
    }
