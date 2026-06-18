"""
Settings dialog — persists user preferences to ~/.automotoai/settings.json.
Open with: SettingsDialog(parent).show()
"""
from __future__ import annotations

import json
import logging
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from src.ui.desktop.theme import COLORS, FONTS

logger = logging.getLogger(__name__)

_SETTINGS_FILE = Path.home() / ".automotoai" / "settings.json"


def load_settings() -> dict:
    try:
        if _SETTINGS_FILE.exists():
            return json.loads(_SETTINGS_FILE.read_text("utf-8"))
    except Exception as exc:
        logger.warning("Could not load settings: %s", exc)
    return {}


def save_settings(data: dict) -> None:
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(json.dumps(data, indent=2), "utf-8")
    logger.info("Settings saved to %s", _SETTINGS_FILE)


_defaults: dict = {
    "ai": {
        "temperature": 0.3,
        "max_tokens": 1024,
        "use_tools": True,
        "max_tool_rounds": 6,
        "confirm_tools": True,
    },
    "voice": {
        "tts_rate": 175,
        "tts_volume": 0.9,
        "language": "en-US",
    },
    "interface": {
        "font_size": 10,
        "show_system_monitor": True,
        "show_file_preview": True,
    },
    "automation": {
        "screenshot_dir": str(Path.home() / "Pictures" / "AutoMotoAI"),
        "confirm_destructive": True,
    },
}


class SettingsDialog:
    def __init__(self, parent: tk.Widget):
        self._parent = parent
        self._data   = {**_defaults, **load_settings()}

    def show(self) -> dict | None:
        dlg = tk.Toplevel(self._parent)
        dlg.title("AutoMoto AI — Settings")
        dlg.geometry("480x420")
        dlg.resizable(False, False)
        dlg.configure(bg=COLORS["bg"])
        dlg.grab_set()
        dlg.transient(self._parent)

        nb = ttk.Notebook(dlg)
        nb.pack(fill="both", expand=True, padx=12, pady=(12, 0))

        vars_: dict = {}

        # ── AI tab ──────────────────────────────────────────────────────
        ai_tab = ttk.Frame(nb)
        nb.add(ai_tab, text="  🤖 AI  ")
        ai_cfg = self._data.get("ai", {})

        def add_row(parent, row, label, widget_fn):
            ttk.Label(parent, text=label, font=FONTS["small"],
                      foreground=COLORS["fg_dim"]).grid(row=row, column=0, sticky="e", padx=(12,6), pady=4)
            w = widget_fn(parent)
            w.grid(row=row, column=1, sticky="w", padx=(0, 12), pady=4)
            return w

        ai_tab.columnconfigure(1, weight=1)
        v_temp = tk.DoubleVar(value=ai_cfg.get("temperature", 0.3))
        v_tok  = tk.IntVar(value=ai_cfg.get("max_tokens", 1024))
        v_tools= tk.BooleanVar(value=ai_cfg.get("use_tools", True))
        v_conf = tk.BooleanVar(value=ai_cfg.get("confirm_tools", True))
        v_rounds = tk.IntVar(value=ai_cfg.get("max_tool_rounds", 6))

        add_row(ai_tab, 0, "Temperature (0–1):",
                lambda p: ttk.Spinbox(p, from_=0.0, to=1.0, increment=0.05,
                                      textvariable=v_temp, width=8, format="%.2f"))
        add_row(ai_tab, 1, "Max tokens:",
                lambda p: ttk.Spinbox(p, from_=64, to=8192, increment=64,
                                      textvariable=v_tok, width=8))
        add_row(ai_tab, 2, "Enable tool calling:",
                lambda p: ttk.Checkbutton(p, variable=v_tools))
        add_row(ai_tab, 3, "Confirm before tool exec:",
                lambda p: ttk.Checkbutton(p, variable=v_conf))
        add_row(ai_tab, 4, "Max tool rounds:",
                lambda p: ttk.Spinbox(p, from_=1, to=20, increment=1,
                                      textvariable=v_rounds, width=8))

        vars_["ai"] = {"temperature": v_temp, "max_tokens": v_tok,
                       "use_tools": v_tools, "confirm_tools": v_conf,
                       "max_tool_rounds": v_rounds}

        # ── Voice tab ───────────────────────────────────────────────────
        voice_tab = ttk.Frame(nb)
        nb.add(voice_tab, text="  🎤 Voice  ")
        v_cfg = self._data.get("voice", {})
        voice_tab.columnconfigure(1, weight=1)

        v_rate = tk.IntVar(value=v_cfg.get("tts_rate", 175))
        v_vol  = tk.DoubleVar(value=v_cfg.get("tts_volume", 0.9))
        v_lang = tk.StringVar(value=v_cfg.get("language", "en-US"))

        add_row(voice_tab, 0, "TTS speed (wpm):",
                lambda p: ttk.Spinbox(p, from_=80, to=300, increment=10,
                                      textvariable=v_rate, width=8))
        add_row(voice_tab, 1, "TTS volume (0–1):",
                lambda p: ttk.Spinbox(p, from_=0.0, to=1.0, increment=0.1,
                                      textvariable=v_vol, width=8, format="%.1f"))
        add_row(voice_tab, 2, "Language / locale:",
                lambda p: ttk.Entry(p, textvariable=v_lang, width=12))

        vars_["voice"] = {"tts_rate": v_rate, "tts_volume": v_vol, "language": v_lang}

        # ── Interface tab ───────────────────────────────────────────────
        ui_tab = ttk.Frame(nb)
        nb.add(ui_tab, text="  🎨 Interface  ")
        ui_cfg = self._data.get("interface", {})
        ui_tab.columnconfigure(1, weight=1)

        v_fs   = tk.IntVar(value=ui_cfg.get("font_size", 10))
        v_mon  = tk.BooleanVar(value=ui_cfg.get("show_system_monitor", True))
        v_prev = tk.BooleanVar(value=ui_cfg.get("show_file_preview", True))

        add_row(ui_tab, 0, "Font size:",
                lambda p: ttk.Spinbox(p, from_=8, to=18, increment=1,
                                      textvariable=v_fs, width=6))
        add_row(ui_tab, 1, "Show system monitor:",
                lambda p: ttk.Checkbutton(p, variable=v_mon))
        add_row(ui_tab, 2, "Show file preview:",
                lambda p: ttk.Checkbutton(p, variable=v_prev))

        vars_["interface"] = {"font_size": v_fs, "show_system_monitor": v_mon,
                               "show_file_preview": v_prev}

        # ── Automation tab ──────────────────────────────────────────────
        auto_tab = ttk.Frame(nb)
        nb.add(auto_tab, text="  ⚙ Automation  ")
        a_cfg = self._data.get("automation", {})
        auto_tab.columnconfigure(1, weight=1)

        v_ss_dir = tk.StringVar(value=a_cfg.get("screenshot_dir", ""))
        v_confirm = tk.BooleanVar(value=a_cfg.get("confirm_destructive", True))

        add_row(auto_tab, 0, "Screenshot folder:",
                lambda p: ttk.Entry(p, textvariable=v_ss_dir, width=28))
        add_row(auto_tab, 1, "Confirm destructive actions:",
                lambda p: ttk.Checkbutton(p, variable=v_confirm))

        vars_["automation"] = {"screenshot_dir": v_ss_dir, "confirm_destructive": v_confirm}

        # ── buttons ─────────────────────────────────────────────────────
        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(fill="x", padx=12, pady=10)

        result: dict | None = None

        def on_save():
            nonlocal result
            built: dict = {}
            for section, mapping in vars_.items():
                built[section] = {k: v.get() for k, v in mapping.items()}
            try:
                save_settings(built)
                result = built
                dlg.destroy()
            except Exception as exc:
                messagebox.showerror("Save Failed", str(exc), parent=dlg)

        ttk.Button(btn_frame, text="Save", command=on_save).pack(side="right", padx=4)
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side="right")

        dlg.wait_window()
        return result
