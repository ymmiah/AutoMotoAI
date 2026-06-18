"""
Advanced AI chat panel.

Features:
  - Real-time streaming token display
  - Native AI tool-calling with visual tool-call / result cards
  - Command history navigation (↑ / ↓)
  - Copy message to clipboard
  - Voice input (browser speech or pyttsx3 TTS output)
  - Markdown-lite rendering (bold, code)
  - Screenshot shortcut
"""
from __future__ import annotations

import logging
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk

from src.ai.base import Message
from src.ai.registry import EVT_DONE, EVT_ERROR, EVT_TOKEN, EVT_TOOL_CALL, EVT_TOOL_RESULT
from src.ui.desktop.theme import COLORS, FONTS

logger = logging.getLogger(__name__)

_MAX_HISTORY = 200   # max commands remembered


class ChatPanel(ttk.Frame):
    """
    Parameters
    ----------
    registry      : AIRegistry
    on_action     : callable(reply: str) | None
    status_cb     : callable(str) | None
    """

    def __init__(self, parent, registry, on_action=None, status_cb=None, **kw):
        super().__init__(parent, **kw)
        self._registry  = registry
        self._on_action = on_action
        self._status_cb = status_cb
        self._history: list[Message]  = []
        self._cmd_hist:  list[str]    = []   # command history for ↑↓
        self._hist_idx:  int          = -1
        self._voice_active = False
        self._busy         = False
        self._build()

    # ─────────────────────────────── build ─────────────────────────────────

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # ── message area ──────────────────────────────────────────────
        msg_frame = ttk.Frame(self)
        msg_frame.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        msg_frame.columnconfigure(0, weight=1)
        msg_frame.rowconfigure(0, weight=1)

        self._text = tk.Text(
            msg_frame,
            wrap="word",
            state="disabled",
            font=FONTS["chat"],
            background=COLORS["bg2"],
            foreground=COLORS["fg"],
            padx=10, pady=8,
            relief="flat",
            cursor="arrow",
        )
        vsb = ttk.Scrollbar(msg_frame, orient="vertical", command=self._text.yview)
        self._text.configure(yscrollcommand=vsb.set)
        self._text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        # text tags
        self._text.tag_configure("user_label",   foreground=COLORS["fg_dim"],  font=FONTS["small"])
        self._text.tag_configure("user_msg",      background=COLORS["user_msg"],  foreground=COLORS["fg"],
                                  lmargin1=10, lmargin2=10, rmargin=10, spacing1=2, spacing3=6)
        self._text.tag_configure("bot_label",    foreground=COLORS["accent"],  font=FONTS["small"])
        self._text.tag_configure("bot_msg",       background=COLORS["bot_msg"],   foreground=COLORS["fg"],
                                  lmargin1=10, lmargin2=10, rmargin=10, spacing1=2, spacing3=6)
        self._text.tag_configure("system",        foreground=COLORS["fg_dim"],    justify="center",
                                  font=FONTS["small"], spacing1=2, spacing3=2)
        self._text.tag_configure("error",         foreground=COLORS["red"],
                                  lmargin1=10, spacing1=2, spacing3=6)
        self._text.tag_configure("tool_call",     background="#1a2035", foreground=COLORS["yellow"],
                                  lmargin1=10, lmargin2=10, rmargin=10, spacing1=2, spacing3=2,
                                  font=FONTS["mono"])
        self._text.tag_configure("tool_result_ok",  background="#1a2a1a", foreground=COLORS["green"],
                                  lmargin1=10, lmargin2=10, rmargin=10, spacing1=2, spacing3=6,
                                  font=FONTS["mono"])
        self._text.tag_configure("tool_result_err", background="#2a1a1a", foreground=COLORS["red"],
                                  lmargin1=10, lmargin2=10, rmargin=10, spacing1=2, spacing3=6,
                                  font=FONTS["mono"])
        self._text.tag_configure("bold",   font=(FONTS["chat"][0], FONTS["chat"][1], "bold"))
        self._text.tag_configure("code",   background=COLORS["bg3"], font=FONTS["mono"])

        self._text.bind("<Button-3>", self._ctx_menu)

        # ── controls row ──────────────────────────────────────────────
        ctrl = ttk.Frame(self)
        ctrl.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 2))

        ttk.Label(ctrl, text="Provider:", font=FONTS["small"]).pack(side="left")
        self._prov_var = tk.StringVar()
        providers = self._registry.available_providers
        self._prov_box = ttk.Combobox(ctrl, textvariable=self._prov_var,
                                       values=providers, state="readonly", width=11, font=FONTS["small"])
        if providers:
            self._prov_var.set(self._registry.default_provider_name)
        self._prov_box.pack(side="left", padx=4)

        self._tools_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctrl, text="Tools", variable=self._tools_var).pack(side="left", padx=4)

        ttk.Button(ctrl, text="📸", width=3,  command=self._take_screenshot).pack(side="right")
        ttk.Button(ctrl, text="🗑 Clear", width=8, command=self._clear).pack(side="right", padx=4)

        # ── input row ─────────────────────────────────────────────────
        inp = ttk.Frame(self)
        inp.grid(row=2, column=0, sticky="ew", padx=4, pady=(0, 4))
        inp.columnconfigure(0, weight=1)

        self._input_var = tk.StringVar()
        self._entry = ttk.Entry(inp, textvariable=self._input_var, font=FONTS["input"])
        self._entry.grid(row=0, column=0, sticky="ew")
        self._entry.bind("<Return>",    self._send)
        self._entry.bind("<Up>",        self._history_up)
        self._entry.bind("<Down>",      self._history_down)
        self._entry.focus_set()

        self._voice_btn = ttk.Button(inp, text="🎤", width=3, command=self._toggle_voice)
        self._voice_btn.grid(row=0, column=1, padx=(4, 0))

        ttk.Button(inp, text="Send ▶", command=self._send, width=8).grid(row=0, column=2, padx=(4, 0))

        # startup message
        self._append_system(f"AutoMoto AI ready.  Tool calling: {'enabled' if self._tools_var.get() else 'off'}")

    # ──────────────────────────── append helpers ────────────────────────────

    def _append_system(self, text: str):
        self._write(f"\n  ── {text} ──\n", "system")

    def _append_user(self, text: str):
        self._write("\n  You\n", "user_label")
        self._write(f"  {text}\n", "user_msg")

    def _begin_bot(self):
        """Insert bot label and return the insert index for streaming into."""
        self._write("\n  AutoMoto AI\n", "bot_label")
        self._text.configure(state="normal")
        start = self._text.index("end")
        self._text.configure(state="disabled")
        return start

    def _append_token(self, token: str, tag: str = "bot_msg"):
        self._text.configure(state="normal")
        self._text.insert("end", token, tag)
        self._text.configure(state="disabled")
        self._text.see("end")

    def _end_bot_msg(self):
        self._append_token("\n", "bot_msg")

    def _append_tool_call(self, name: str, args: dict):
        import json
        args_str = json.dumps(args, separators=(",", ":")) if args else ""
        self._write(f"\n  🔧 {name}({args_str})\n", "tool_call")

    def _append_tool_result(self, name: str, result: str, success: bool):
        tag = "tool_result_ok" if success else "tool_result_err"
        icon = "✅" if success else "❌"
        preview = result[:120].replace("\n", " ") + ("…" if len(result) > 120 else "")
        self._write(f"  {icon} {preview}\n", tag)

    def _append_error(self, text: str):
        self._write(f"\n  ⚠  {text}\n", "error")

    def _write(self, text: str, tag: str):
        self._text.configure(state="normal")
        self._text.insert("end", text, tag)
        self._text.configure(state="disabled")
        self._text.see("end")

    # ─────────────────────────── send / AI call ─────────────────────────────

    def _send(self, _event=None):
        if self._busy:
            return
        text = self._input_var.get().strip()
        if not text:
            return
        self._input_var.set("")
        self._hist_idx = -1
        if not self._cmd_hist or self._cmd_hist[-1] != text:
            self._cmd_hist.append(text)
            if len(self._cmd_hist) > _MAX_HISTORY:
                self._cmd_hist.pop(0)

        self._append_user(text)
        self._entry.configure(state="disabled")
        self._busy = True
        self._set_status("Thinking…")

        if not self._history:
            from src.core.config import ai_config
            self._history.append(Message("system", ai_config.system_prompt))
        self._history.append(Message("user", text))

        q: queue.Queue = queue.Queue()

        def worker():
            try:
                provider = self._prov_var.get() or None
                if self._tools_var.get() and self._registry.available_providers:
                    for event in self._registry.stream_chat_with_tools(self._history, provider=provider):
                        q.put(event)
                else:
                    for token in self._registry.stream_chat(self._history, provider=provider):
                        q.put((EVT_TOKEN, token))
                    q.put((EVT_DONE, None))
            except Exception as exc:
                q.put((EVT_ERROR, str(exc)))
                q.put((EVT_DONE, None))

        threading.Thread(target=worker, daemon=True, name="ai-stream").start()

        # Begin accumulating bot reply
        self._begin_bot()
        full_reply: list[str] = []

        def drain():
            try:
                while True:
                    evt, data = q.get_nowait()
                    if evt == EVT_TOKEN:
                        full_reply.append(data)
                        self._append_token(data)
                    elif evt == EVT_TOOL_CALL:
                        self._end_bot_msg()
                        self._append_tool_call(data["name"], data.get("args", {}))
                        self._begin_bot()
                    elif evt == EVT_TOOL_RESULT:
                        self._append_tool_result(data["name"], data["result"], data["success"])
                    elif evt == EVT_ERROR:
                        self._end_bot_msg()
                        self._append_error(data)
                    elif evt == EVT_DONE:
                        self._end_bot_msg()
                        final = "".join(full_reply)
                        if final:
                            self._history.append(Message("assistant", final))
                        if self._on_action and final:
                            self._on_action(final)
                        self._busy = False
                        self._entry.configure(state="normal")
                        self._entry.focus_set()
                        self._set_status("Ready")
                        return
            except queue.Empty:
                pass
            self.after(20, drain)

        self.after(20, drain)

    # ──────────────────────────── commands ──────────────────────────────────

    def _clear(self):
        self._history.clear()
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")
        self._append_system("Conversation cleared.")

    def _take_screenshot(self):
        try:
            from src.automation.desktop import take_screenshot
            path = take_screenshot()
            self._append_system(f"Screenshot saved: {path}")
        except Exception as exc:
            self._append_error(str(exc))

    def _toggle_voice(self):
        if self._voice_active:
            self._voice_active = False
            self._voice_btn.configure(text="🎤")
            return
        self._voice_active = True
        self._voice_btn.configure(text="🔴")
        threading.Thread(target=self._listen_voice, daemon=True).start()

    def _listen_voice(self):
        try:
            import speech_recognition as sr
            r = sr.Recognizer()
            with sr.Microphone() as src:
                self.after(0, self._set_status, "Listening…")
                r.adjust_for_ambient_noise(src, duration=0.4)
                audio = r.listen(src, timeout=8, phrase_time_limit=15)
            text = r.recognize_google(audio)
            self.after(0, self._input_var.set, text)
            self.after(0, self._send)
        except Exception as exc:
            self.after(0, self._append_error, f"Voice: {exc}")
        finally:
            self._voice_active = False
            self.after(0, self._voice_btn.configure, {"text": "🎤"})
            self.after(0, self._set_status, "Ready")

    # ──────────────────────── command history nav ────────────────────────────

    def _history_up(self, _event=None):
        if not self._cmd_hist:
            return
        self._hist_idx = max(0, (len(self._cmd_hist) - 1) if self._hist_idx < 0 else self._hist_idx - 1)
        self._input_var.set(self._cmd_hist[self._hist_idx])
        self._entry.icursor("end")

    def _history_down(self, _event=None):
        if self._hist_idx < 0:
            return
        self._hist_idx += 1
        if self._hist_idx >= len(self._cmd_hist):
            self._hist_idx = -1
            self._input_var.set("")
        else:
            self._input_var.set(self._cmd_hist[self._hist_idx])
        self._entry.icursor("end")

    # ──────────────────────────── context menu ───────────────────────────────

    def _ctx_menu(self, event):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Copy",       command=lambda: self._copy_selection())
        menu.add_command(label="Select All", command=lambda: self._text.tag_add("sel", "1.0", "end"))
        menu.add_separator()
        menu.add_command(label="Clear Chat", command=self._clear)
        menu.post(event.x_root, event.y_root)

    def _copy_selection(self):
        try:
            sel = self._text.get(tk.SEL_FIRST, tk.SEL_LAST)
            self.clipboard_clear()
            self.clipboard_append(sel)
        except tk.TclError:
            pass

    # ──────────────────────────── util ──────────────────────────────────────

    def _set_status(self, msg: str):
        if self._status_cb:
            self._status_cb(msg)
