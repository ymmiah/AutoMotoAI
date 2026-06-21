"""App launcher widget — searchable list of installed Windows applications."""
from __future__ import annotations

import logging
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from src.ui.desktop.theme import FONTS

logger = logging.getLogger(__name__)

_COMMON_APPS = [
    {"name": "Notepad",         "cmd": "notepad.exe"},
    {"name": "Calculator",      "cmd": "calc.exe"},
    {"name": "Paint",           "cmd": "mspaint.exe"},
    {"name": "File Explorer",   "cmd": "explorer.exe"},
    {"name": "Task Manager",    "cmd": "taskmgr.exe"},
    {"name": "Command Prompt",  "cmd": "cmd.exe"},
    {"name": "PowerShell",      "cmd": "powershell.exe"},
    {"name": "Settings",        "cmd": "ms-settings:"},
    {"name": "Snipping Tool",   "cmd": "SnippingTool.exe"},
    {"name": "WordPad",         "cmd": "wordpad.exe"},
    {"name": "Control Panel",   "cmd": "control.exe"},
    {"name": "Regedit",         "cmd": "regedit.exe"},
    {"name": "Device Manager",  "cmd": "devmgmt.msc"},
    {"name": "Disk Management", "cmd": "diskmgmt.msc"},
    {"name": "Resource Monitor","cmd": "resmon.exe"},
]


class AppLauncher(ttk.Frame):
    """
    Searchable list of applications. Double-click or Enter to launch.

    Parameters
    ----------
    on_launch : callable(name, cmd) | None
        Fired after a successful launch attempt.
    """

    def __init__(self, parent, on_launch=None, **kw):
        super().__init__(parent, **kw)
        self._on_launch = on_launch
        self._all_apps: list[dict] = []
        self._build()
        self._load_apps()

    # ------------------------------------------------------------------ build
    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # -- search bar
        search_frame = ttk.Frame(self)
        search_frame.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        search_frame.columnconfigure(1, weight=1)
        ttk.Label(search_frame, text="🔍", font=FONTS["default"]).grid(row=0, column=0, padx=(0, 4))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._filter)
        ttk.Entry(search_frame, textvariable=self._search_var, font=FONTS["input"]).grid(
            row=0, column=1, sticky="ew"
        )

        # -- list
        list_frame = ttk.Frame(self)
        list_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self._listbox = tk.Listbox(
            list_frame,
            selectmode="single",
            activestyle="none",
            font=FONTS["default"],
        )
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self._listbox.yview)
        self._listbox.configure(yscrollcommand=sb.set)
        self._listbox.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        self._listbox.bind("<Double-1>", self._launch_selected)
        self._listbox.bind("<Return>",   self._launch_selected)

        # -- launch button
        ttk.Button(self, text="▶  Launch", command=self._launch_selected).grid(
            row=2, column=0, pady=(0, 4), sticky="ew", padx=4
        )

        # -- reload button
        ttk.Button(self, text="⟳  Reload installed apps", command=self._load_apps).grid(
            row=3, column=0, pady=(0, 4), sticky="ew", padx=4
        )

    # ------------------------------------------------------------------- data
    def _load_apps(self):
        self._all_apps = list(_COMMON_APPS)
        if sys.platform == "win32":
            try:
                from src.automation.desktop import get_installed_apps
                installed = get_installed_apps()
                names = {a["name"] for a in self._all_apps}
                for app in installed:
                    if app["name"] not in names:
                        self._all_apps.append({"name": app["name"], "cmd": app["location"] or app["name"]})
            except Exception as exc:
                logger.warning("Could not enumerate installed apps: %s", exc)
        self._all_apps.sort(key=lambda a: a["name"].lower())
        self._render(self._all_apps)

    def _render(self, apps: list[dict]):
        self._listbox.delete(0, tk.END)
        for app in apps:
            self._listbox.insert(tk.END, app["name"])

    def _filter(self, *_):
        query = self._search_var.get().lower()
        filtered = [a for a in self._all_apps if query in a["name"].lower()]
        self._render(filtered)

    # ----------------------------------------------------------------- launch
    def _launch_selected(self, _event=None):
        idx = self._listbox.curselection()
        if not idx:
            return
        name = self._listbox.get(idx[0])
        app = next((a for a in self._all_apps if a["name"] == name), None)
        if not app:
            return
        try:
            from src.automation.desktop import open_application
            open_application(app["cmd"])
            if self._on_launch:
                self._on_launch(app["name"], app["cmd"])
        except Exception as exc:
            messagebox.showerror("Launch Failed", str(exc))
