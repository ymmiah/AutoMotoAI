"""Main desktop application window."""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk

from src.ai.registry import AIRegistry
from src.core.config import app_config
from src.ui.desktop.theme import COLORS, FONTS
from src.ui.desktop.widgets.app_launcher import AppLauncher
from src.ui.desktop.widgets.chat_panel import ChatPanel
from src.ui.desktop.widgets.file_browser import FileBrowser

logger = logging.getLogger(__name__)


def _apply_theme(root: tk.Tk) -> ttk.Style:
    style = ttk.Style(root)
    # Use a built-in theme as a base then override colours
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    c = COLORS
    style.configure(".",
        background=c["bg"],
        foreground=c["fg"],
        troughcolor=c["bg2"],
        selectbackground=c["accent"],
        selectforeground=c["bg"],
        fieldbackground=c["bg3"],
        bordercolor=c["border"],
        darkcolor=c["bg2"],
        lightcolor=c["bg3"],
        font=FONTS["default"],
    )
    style.configure("TFrame",       background=c["bg"])
    style.configure("TLabel",       background=c["bg"],  foreground=c["fg"])
    style.configure("TEntry",       fieldbackground=c["bg3"], foreground=c["fg"])
    style.configure("TCombobox",    fieldbackground=c["bg3"], foreground=c["fg"])
    style.configure("TButton",
        background=c["bg3"], foreground=c["fg"],
        padding=(6, 3), relief="flat",
    )
    style.map("TButton",
        background=[("active", c["bg_hover"]), ("pressed", c["accent"])],
        foreground=[("active", c["fg"])],
    )
    style.configure("TNotebook",       background=c["bg"],  borderwidth=0)
    style.configure("TNotebook.Tab",   background=c["bg3"], foreground=c["fg_dim"], padding=(10, 4))
    style.map("TNotebook.Tab",
        background=[("selected", c["bg"])],
        foreground=[("selected", c["accent"])],
    )
    style.configure("Treeview",
        background=c["bg2"],  foreground=c["fg"],
        fieldbackground=c["bg2"], rowheight=22,
        borderwidth=0,
    )
    style.map("Treeview",
        background=[("selected", c["accent"])],
        foreground=[("selected", c["bg"])],
    )
    style.configure("Treeview.Heading",
        background=c["bg3"], foreground=c["fg_dim"], relief="flat"
    )
    style.configure("TScrollbar",
        background=c["bg3"], troughcolor=c["bg2"], arrowcolor=c["fg_dim"]
    )
    style.configure("TLabelframe",       background=c["bg"])
    style.configure("TLabelframe.Label", background=c["bg"], foreground=c["accent"])
    style.configure("Horizontal.TSeparator", background=c["border"])
    return style


class DesktopApp:
    """Root tkinter application wrapper."""

    def __init__(self):
        self._registry = AIRegistry()
        self._root = tk.Tk()
        self._root.title(f"{app_config.name}  v{app_config.version}")
        self._root.geometry("1200x720")
        self._root.minsize(900, 600)
        self._root.configure(bg=COLORS["bg"])
        _apply_theme(self._root)
        self._build()
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ build
    def _build(self):
        # ── title bar row ──────────────────────────────────────────────────
        title_bar = ttk.Frame(self._root)
        title_bar.pack(fill="x", padx=8, pady=(6, 0))

        ttk.Label(title_bar, text=f"🤖  {app_config.name}", font=FONTS["title"]).pack(side="left")

        providers_txt = "  |  Providers: " + (
            ", ".join(self._registry.available_providers) if self._registry.available_providers
            else "none configured"
        )
        ttk.Label(title_bar, text=providers_txt, font=FONTS["small"],
                  foreground=COLORS["fg_dim"]).pack(side="left", padx=8)

        ttk.Separator(self._root, orient="horizontal").pack(fill="x", padx=8, pady=4)

        # ── main content (PanedWindow) ──────────────────────────────────────
        pane = ttk.PanedWindow(self._root, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        # LEFT: notebook with File Browser + App Launcher tabs
        left_nb = ttk.Notebook(pane, width=300)
        pane.add(left_nb, weight=1)

        self._file_browser = FileBrowser(
            left_nb,
            on_file_select=self._on_file_selected,
            on_path_change=self._on_path_changed,
        )
        left_nb.add(self._file_browser, text="  📁 Files  ")

        self._app_launcher = AppLauncher(
            left_nb,
            on_launch=self._on_app_launched,
        )
        left_nb.add(self._app_launcher, text="  🚀 Apps  ")

        # RIGHT: chat panel
        self._chat = ChatPanel(
            pane,
            registry=self._registry,
            on_action=self._on_ai_action,
            status_cb=self._set_status,
        )
        pane.add(self._chat, weight=3)

        # ── status bar ──────────────────────────────────────────────────────
        status_bar = ttk.Frame(self._root, relief="sunken")
        status_bar.pack(fill="x", side="bottom")

        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(status_bar, textvariable=self._status_var, font=FONTS["small"],
                  foreground=COLORS["fg_dim"]).pack(side="left", padx=6, pady=2)

        ttk.Label(status_bar, text=f"v{app_config.version}", font=FONTS["small"],
                  foreground=COLORS["fg_dim"]).pack(side="right", padx=6, pady=2)

        if not self._registry.available_providers:
            self._show_no_provider_warning()

    # -------------------------------------------------------------- callbacks
    def _on_file_selected(self, path):
        self._set_status(f"Selected: {path}")
        logger.info("File selected: %s", path)

    def _on_path_changed(self, path: str):
        self._set_status(f"Browsing: {path}")

    def _on_app_launched(self, name: str, _cmd: str):
        self._set_status(f"Launched: {name}")

    def _on_ai_action(self, reply: str):
        logger.debug("AI action suggestion: %s", reply[:80])

    def _set_status(self, msg: str):
        self._status_var.set(msg)

    # ------------------------------------------------------------------ misc
    def _show_no_provider_warning(self):
        messagebox.showwarning(
            "No AI Provider",
            "No AI provider is configured.\n\n"
            "Create a .env file with at least one of:\n"
            "  OPENAI_API_KEY=...\n"
            "  GEMINI_API_KEY=...\n"
            "  ANTHROPIC_API_KEY=...\n"
            "  BLACKBOX_API_KEY=...\n\n"
            "The file browser and app launcher still work without an AI key.",
        )

    def _on_close(self):
        if messagebox.askokcancel("Quit", "Close AutoMoto AI?"):
            self._root.destroy()

    def run(self):
        logger.info("%s desktop app started", app_config.name)
        self._root.mainloop()
