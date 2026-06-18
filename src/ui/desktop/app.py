"""Main desktop application window — integrates all advanced widgets."""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk

from src.ai.registry import AIRegistry
from src.core.config import app_config
from src.ui.desktop.settings_dialog import SettingsDialog, load_settings
from src.ui.desktop.theme import COLORS, FONTS
from src.ui.desktop.widgets.app_launcher import AppLauncher
from src.ui.desktop.widgets.chat_panel import ChatPanel
from src.ui.desktop.widgets.file_browser import FileBrowser
from src.ui.desktop.widgets.file_preview import FilePreview
from src.ui.desktop.widgets.system_monitor import SystemMonitor

logger = logging.getLogger(__name__)


def _apply_theme(root: tk.Tk) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    c = COLORS
    style.configure(".",
        background=c["bg"], foreground=c["fg"],
        troughcolor=c["bg2"], selectbackground=c["accent"], selectforeground=c["bg"],
        fieldbackground=c["bg3"], bordercolor=c["border"],
        darkcolor=c["bg2"], lightcolor=c["bg3"], font=FONTS["default"],
    )
    for name, opts in {
        "TFrame":             {"background": c["bg"]},
        "TLabel":             {"background": c["bg"],  "foreground": c["fg"]},
        "TLabelframe":        {"background": c["bg"]},
        "TLabelframe.Label":  {"background": c["bg"],  "foreground": c["accent"]},
        "TEntry":             {"fieldbackground": c["bg3"], "foreground": c["fg"]},
        "TCombobox":          {"fieldbackground": c["bg3"], "foreground": c["fg"]},
        "TSpinbox":           {"fieldbackground": c["bg3"], "foreground": c["fg"]},
        "TCheckbutton":       {"background": c["bg"],  "foreground": c["fg"]},
        "TScrollbar":         {"background": c["bg3"], "troughcolor": c["bg2"], "arrowcolor": c["fg_dim"]},
        "TProgressbar":       {"background": c["accent"], "troughcolor": c["bg3"]},
        "TNotebook":          {"background": c["bg"],  "borderwidth": 0},
        "TNotebook.Tab":      {"background": c["bg3"], "foreground": c["fg_dim"], "padding": (10, 4)},
        "TButton":            {"background": c["bg3"], "foreground": c["fg"], "padding": (6, 3), "relief": "flat"},
        "Treeview":           {"background": c["bg2"], "foreground": c["fg"],
                               "fieldbackground": c["bg2"], "rowheight": 22, "borderwidth": 0},
        "Treeview.Heading":   {"background": c["bg3"], "foreground": c["fg_dim"], "relief": "flat"},
        "TSeparator":         {"background": c["border"]},
    }.items():
        style.configure(name, **opts)
    style.map("TButton",
              background=[("active", c["bg_hover"]), ("pressed", c["accent"])],
              foreground=[("active", c["fg"])])
    style.map("TNotebook.Tab",
              background=[("selected", c["bg"])],
              foreground=[("selected", c["accent"])])
    style.map("Treeview",
              background=[("selected", c["accent"])],
              foreground=[("selected", c["bg"])])
    return style


class DesktopApp:
    def __init__(self):
        self._registry = AIRegistry()
        self._settings = load_settings()
        self._root = tk.Tk()
        self._root.title(f"{app_config.name}  v{app_config.version}")
        self._root.geometry("1380x780")
        self._root.minsize(1000, 620)
        self._root.configure(bg=COLORS["bg"])
        _apply_theme(self._root)
        self._build()
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ──────────────────────────────── build ──────────────────────────────────

    def _build(self):
        self._build_menu()

        # ── title bar ──────────────────────────────────────────────────
        title_bar = ttk.Frame(self._root)
        title_bar.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Label(title_bar, text=f"🤖  {app_config.name}", font=FONTS["title"]).pack(side="left")
        prov_txt = "  |  " + (", ".join(self._registry.available_providers) or "⚠ no provider")
        ttk.Label(title_bar, text=prov_txt, font=FONTS["small"],
                  foreground=COLORS["fg_dim"]).pack(side="left", padx=6)
        ttk.Separator(self._root, orient="horizontal").pack(fill="x", padx=8, pady=4)

        # ── outer pane: sidebar | chat+preview ────────────────────────
        outer = ttk.PanedWindow(self._root, orient="horizontal")
        outer.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        # LEFT SIDEBAR ─────────────────────────────────────────────────
        left_nb = ttk.Notebook(outer, width=300)
        outer.add(left_nb, weight=1)

        # Files tab
        self._file_browser = FileBrowser(
            left_nb,
            on_file_select=self._on_file_selected,
            on_path_change=self._on_path_changed,
        )
        left_nb.add(self._file_browser, text="  📁 Files  ")

        # Apps tab
        self._app_launcher = AppLauncher(left_nb, on_launch=self._on_app_launched)
        left_nb.add(self._app_launcher, text="  🚀 Apps  ")

        # Monitor tab
        self._monitor = SystemMonitor(left_nb)
        left_nb.add(self._monitor, text="  📊 Monitor  ")
        left_nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # RIGHT: vertical pane — chat (top) / file preview (bottom)
        right_pane = ttk.PanedWindow(outer, orient="vertical")
        outer.add(right_pane, weight=4)

        self._chat = ChatPanel(
            right_pane,
            registry=self._registry,
            on_action=self._on_ai_action,
            status_cb=self._set_status,
        )
        right_pane.add(self._chat, weight=3)

        # File preview panel (collapsible)
        if self._settings.get("interface", {}).get("show_file_preview", True):
            preview_frame = ttk.LabelFrame(right_pane, text=" File Preview ")
            right_pane.add(preview_frame, weight=1)
            preview_frame.columnconfigure(0, weight=1)
            preview_frame.rowconfigure(0, weight=1)
            self._preview = FilePreview(preview_frame)
            self._preview.grid(row=0, column=0, sticky="nsew")
        else:
            self._preview = None

        # ── status bar ─────────────────────────────────────────────────
        sb = ttk.Frame(self._root, relief="sunken")
        sb.pack(fill="x", side="bottom")
        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(sb, textvariable=self._status_var, font=FONTS["small"],
                  foreground=COLORS["fg_dim"]).pack(side="left", padx=6, pady=2)
        ttk.Label(sb, text=f"v{app_config.version}", font=FONTS["small"],
                  foreground=COLORS["fg_dim"]).pack(side="right", padx=6, pady=2)

        if not self._registry.available_providers:
            self._show_no_provider_warning()

    def _build_menu(self):
        menubar = tk.Menu(self._root, bg=COLORS["bg2"], fg=COLORS["fg"],
                          activebackground=COLORS["accent"], activeforeground=COLORS["bg"],
                          tearoff=0)

        file_menu = tk.Menu(menubar, tearoff=0, bg=COLORS["bg2"], fg=COLORS["fg"],
                             activebackground=COLORS["accent"], activeforeground=COLORS["bg"])
        file_menu.add_command(label="⚙  Settings…", command=self._open_settings)
        file_menu.add_separator()
        file_menu.add_command(label="📸  Take Screenshot",
                              command=lambda: self._chat._take_screenshot())
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=0, bg=COLORS["bg2"], fg=COLORS["fg"],
                             activebackground=COLORS["accent"], activeforeground=COLORS["bg"])
        view_menu.add_command(label="🗑  Clear Chat",
                              command=lambda: self._chat._clear())
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0, bg=COLORS["bg2"], fg=COLORS["fg"],
                             activebackground=COLORS["accent"], activeforeground=COLORS["bg"])
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self._root.configure(menu=menubar)

    # ──────────────────────────── callbacks ──────────────────────────────────

    def _on_file_selected(self, path):
        self._set_status(f"Selected: {path}")
        if self._preview:
            self._preview.preview(path)

    def _on_path_changed(self, path: str):
        self._set_status(f"Browsing: {path}")

    def _on_app_launched(self, name: str, _cmd: str):
        self._set_status(f"Launched: {name}")

    def _on_ai_action(self, reply: str):
        logger.debug("AI action reply: %.60s…", reply)

    def _on_tab_changed(self, _event):
        try:
            nb = _event.widget
            current_tab = nb.tab(nb.select(), "text")
            if "Monitor" in current_tab:
                self._monitor.start()
            else:
                self._monitor.stop()
        except Exception:
            pass

    def _set_status(self, msg: str):
        self._status_var.set(msg)

    # ──────────────────────────── dialogs ────────────────────────────────────

    def _open_settings(self):
        result = SettingsDialog(self._root).show()
        if result:
            self._settings = result
            self._set_status("Settings saved.")

    def _show_about(self):
        messagebox.showinfo(
            "About AutoMoto AI",
            f"{app_config.name}  v{app_config.version}\n\n"
            "Intelligent Windows desktop automation.\n\n"
            "AI providers available:\n" +
            "\n".join(f"  • {p}" for p in self._registry.available_providers) or "  None configured",
        )

    def _show_no_provider_warning(self):
        messagebox.showwarning(
            "No AI Provider Configured",
            "Add at least one API key to .env:\n\n"
            "  OPENAI_API_KEY=...\n"
            "  GEMINI_API_KEY=...\n"
            "  ANTHROPIC_API_KEY=...\n"
            "  BLACKBOX_API_KEY=...\n\n"
            "File browser, App launcher, and System Monitor work without an AI key.",
        )

    def _on_close(self):
        self._monitor.stop()
        if messagebox.askokcancel("Quit", "Close AutoMoto AI?"):
            self._root.destroy()

    def run(self):
        logger.info("%s desktop app started", app_config.name)
        self._root.mainloop()
