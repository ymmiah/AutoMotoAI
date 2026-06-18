"""AI chat panel — scrollable history, text/voice input, provider selector."""
from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import ttk

from src.ai.base import Message
from src.ui.desktop.theme import COLORS, FONTS

logger = logging.getLogger(__name__)


class ChatPanel(ttk.Frame):
    """
    Central chat interface.

    Parameters
    ----------
    registry      : AIRegistry  — used for actual AI calls.
    on_action     : callable(str) | None — called when AI suggests a desktop action.
    status_cb     : callable(str) | None — called to update the status bar text.
    """

    def __init__(self, parent, registry, on_action=None, status_cb=None, **kw):
        super().__init__(parent, **kw)
        self._registry = registry
        self._on_action = on_action
        self._status_cb = status_cb
        self._history: list[Message] = []
        self._voice_enabled = False
        self._build()

    # ------------------------------------------------------------------ build
    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # -- message area
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
            padx=8, pady=6,
            relief="flat",
            cursor="arrow",
        )
        vsb = ttk.Scrollbar(msg_frame, orient="vertical", command=self._text.yview)
        self._text.configure(yscrollcommand=vsb.set)
        self._text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._text.tag_configure("user",    background=COLORS["user_msg"], foreground=COLORS["fg"],     lmargin1=8, lmargin2=8, rmargin=8, spacing1=4, spacing3=4)
        self._text.tag_configure("bot",     background=COLORS["bot_msg"],  foreground=COLORS["accent"], lmargin1=8, lmargin2=8, rmargin=8, spacing1=4, spacing3=4)
        self._text.tag_configure("system",  foreground=COLORS["fg_dim"],   justify="center", spacing1=2, spacing3=2)
        self._text.tag_configure("error",   foreground=COLORS["red"],      lmargin1=8, spacing1=2, spacing3=2)

        # -- provider selector row
        ctrl = ttk.Frame(self)
        ctrl.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 2))

        ttk.Label(ctrl, text="Provider:", font=FONTS["small"]).pack(side="left")
        self._provider_var = tk.StringVar()
        providers = self._registry.available_providers
        self._provider_combo = ttk.Combobox(
            ctrl, textvariable=self._provider_var,
            values=providers, state="readonly", width=12,
            font=FONTS["small"],
        )
        if providers:
            self._provider_var.set(self._registry.default_provider_name)
        self._provider_combo.pack(side="left", padx=4)

        ttk.Button(ctrl, text="🗑 Clear", command=self._clear_history, width=8).pack(side="right")
        ttk.Button(ctrl, text="📸 Screenshot", command=self._take_screenshot, width=13).pack(side="right", padx=4)

        # -- input row
        inp = ttk.Frame(self)
        inp.grid(row=2, column=0, sticky="ew", padx=4, pady=(0, 4))
        inp.columnconfigure(0, weight=1)

        self._voice_btn = ttk.Button(inp, text="🎤", width=3, command=self._toggle_voice)
        self._voice_btn.grid(row=0, column=1, padx=(0, 4))

        self._input_var = tk.StringVar()
        self._entry = ttk.Entry(inp, textvariable=self._input_var, font=FONTS["input"])
        self._entry.grid(row=0, column=0, sticky="ew")
        self._entry.bind("<Return>", self._send)
        self._entry.focus_set()

        ttk.Button(inp, text="Send ▶", command=self._send, width=8).grid(row=0, column=2)

        self._append_system("AutoMoto AI ready. Type a command or ask a question.")

    # --------------------------------------------------------------- display
    def _append_system(self, text: str):
        self._append("system", f"  {text}  \n")

    def _append_user(self, text: str):
        self._append("user", f"  You: {text}\n")

    def _append_bot(self, text: str):
        self._append("bot", f"  AI:  {text}\n")

    def _append_error(self, text: str):
        self._append("error", f"  ⚠  {text}\n")

    def _append(self, tag: str, text: str):
        self._text.configure(state="normal")
        self._text.insert("end", text, tag)
        self._text.configure(state="disabled")
        self._text.see("end")

    # --------------------------------------------------------------- actions
    def _send(self, _event=None):
        user_text = self._input_var.get().strip()
        if not user_text:
            return
        self._input_var.set("")
        self._append_user(user_text)
        self._entry.config(state="disabled")
        if self._status_cb:
            self._status_cb("Thinking…")
        threading.Thread(target=self._call_ai, args=(user_text,), daemon=True).start()

    def _call_ai(self, user_text: str):
        from src.core.config import ai_config
        if not self._history:
            self._history.append(Message("system", ai_config.system_prompt))
        self._history.append(Message("user", user_text))
        try:
            provider = self._provider_var.get() or None
            reply = self._registry.chat(self._history, provider=provider)
            self._history.append(Message("assistant", reply))
            self.after(0, self._append_bot, reply)
            self.after(0, self._check_for_actions, reply)
            self.after(0, self._set_status, "Ready")
        except Exception as exc:
            self.after(0, self._append_error, str(exc))
            self.after(0, self._set_status, f"Error: {exc}")
        finally:
            self.after(0, lambda: self._entry.config(state="normal"))
            self.after(0, self._entry.focus_set)

    def _check_for_actions(self, reply: str):
        """Parse simple action keywords from AI reply and fire on_action."""
        if not self._on_action:
            return
        lower = reply.lower()
        if "open " in lower or "launch " in lower:
            self._on_action(reply)

    def _clear_history(self):
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
        self._voice_enabled = not self._voice_enabled
        if self._voice_enabled:
            self._voice_btn.configure(text="🔴")
            self._append_system("Voice input ON — click 🔴 to stop, then speak.")
            threading.Thread(target=self._listen_voice, daemon=True).start()
        else:
            self._voice_btn.configure(text="🎤")

    def _listen_voice(self):
        try:
            import speech_recognition as sr
            r = sr.Recognizer()
            with sr.Microphone() as src:
                self.after(0, self._set_status, "Listening…")
                r.adjust_for_ambient_noise(src, duration=0.5)
                audio = r.listen(src, timeout=8, phrase_time_limit=15)
            text = r.recognize_google(audio)
            self.after(0, self._input_var.set, text)
            self.after(0, self._send)
        except Exception as exc:
            self.after(0, self._append_error, f"Voice: {exc}")
        finally:
            self._voice_enabled = False
            self.after(0, self._voice_btn.configure, {"text": "🎤"})
            self.after(0, self._set_status, "Ready")

    def _set_status(self, msg: str):
        if self._status_cb:
            self._status_cb(msg)
