"""
File preview panel — shows content or metadata for the selected path.
Supports: plain text, code, images (requires Pillow), and fallback metadata.
"""
from __future__ import annotations

import logging
import mimetypes
import os
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from src.ui.desktop.theme import COLORS, FONTS

logger = logging.getLogger(__name__)

_TEXT_EXTS = {
    ".txt", ".md", ".rst", ".csv", ".log", ".ini", ".cfg", ".toml",
    ".json", ".yaml", ".yml", ".xml", ".html", ".htm", ".css",
    ".js", ".ts", ".py", ".java", ".c", ".cpp", ".h", ".cs",
    ".go", ".rs", ".sh", ".bat", ".ps1", ".sql", ".env",
}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff"}
_MAX_TEXT_BYTES = 256 * 1024   # 256 KB max preview
_MAX_LINES      = 500


class FilePreview(ttk.Frame):
    """
    Embed this widget in a panel; call `.preview(path)` whenever the selection changes.
    """

    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self._current: Path | None = None
        self._photo = None   # keep Tk image reference alive
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # header
        self._header = ttk.Label(self, text="No file selected", font=FONTS["small"],
                                  foreground=COLORS["fg_dim"], anchor="w")
        self._header.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 2))

        ttk.Separator(self, orient="horizontal").grid(row=0, column=0, sticky="ews", pady=(0, 0))

        # notebook for different preview modes
        self._nb = ttk.Notebook(self)
        self._nb.grid(row=1, column=0, sticky="nsew")

        # -- text tab
        text_frame = ttk.Frame(self._nb)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        self._text = tk.Text(
            text_frame,
            wrap="none",
            state="disabled",
            font=FONTS["mono"],
            background=COLORS["bg2"],
            foreground=COLORS["fg"],
            insertbackground=COLORS["accent"],
            relief="flat",
            padx=6, pady=4,
        )
        vsb = ttk.Scrollbar(text_frame, orient="vertical",   command=self._text.yview)
        hsb = ttk.Scrollbar(text_frame, orient="horizontal", command=self._text.xview)
        self._text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self._nb.add(text_frame, text="  📄 Text  ")

        # -- image tab
        img_frame = ttk.Frame(self._nb)
        img_frame.columnconfigure(0, weight=1)
        img_frame.rowconfigure(0, weight=1)
        self._img_label = ttk.Label(img_frame, anchor="center")
        self._img_label.grid(row=0, column=0, sticky="nsew")
        self._nb.add(img_frame, text="  🖼 Image  ")

        # -- info tab
        info_frame = ttk.Frame(self._nb)
        info_frame.columnconfigure(1, weight=1)
        self._info_rows: list[tuple[ttk.Label, ttk.Label]] = []
        for i, label in enumerate(["Name", "Path", "Size", "Modified", "Type", "Permissions"]):
            k = ttk.Label(info_frame, text=label + ":", font=FONTS["small"],
                          foreground=COLORS["fg_dim"], anchor="e")
            v = ttk.Label(info_frame, text="—", font=FONTS["small"],
                          foreground=COLORS["fg"], anchor="w", wraplength=220)
            k.grid(row=i, column=0, sticky="e", padx=(8, 4), pady=2)
            v.grid(row=i, column=1, sticky="w", padx=(0, 8), pady=2)
            self._info_rows.append((k, v))
        self._nb.add(info_frame, text="  ℹ Info  ")

        # apply tag styles
        self._text.tag_configure("lineno", foreground=COLORS["fg_dim"], font=FONTS["small"])
        self._text.tag_configure("content", foreground=COLORS["fg"])

    # ── public API ────────────────────────────────────────────────────────────

    def preview(self, path: str | Path) -> None:
        p = Path(path)
        self._current = p
        self._update_header(p)
        self._update_info(p)
        ext = p.suffix.lower()

        if ext in _IMAGE_EXTS:
            self._preview_image(p)
            self._nb.select(1)
        elif ext in _TEXT_EXTS or self._is_text_file(p):
            self._preview_text(p)
            self._nb.select(0)
        else:
            self._clear_text("Binary or unsupported file type.\nUse the Info tab for file details.")
            self._nb.select(2)

    def clear(self) -> None:
        self._header.configure(text="No file selected")
        self._clear_text("")
        self._img_label.configure(image="")
        self._photo = None
        for _, v in self._info_rows:
            v.configure(text="—")

    # ── internal helpers ──────────────────────────────────────────────────────

    def _update_header(self, p: Path):
        try:
            size = self._fmt_size(p.stat().st_size) if p.is_file() else ""
        except OSError:
            size = ""
        self._header.configure(text=f"{p.name}  {size}")

    def _update_info(self, p: Path):
        import datetime
        try:
            stat = p.stat()
            values = [
                p.name,
                str(p.parent),
                self._fmt_size(stat.st_size),
                datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                mimetypes.guess_type(str(p))[0] or p.suffix or "Unknown",
                oct(stat.st_mode)[-3:],
            ]
        except OSError:
            values = ["—"] * 6
        for (_, lbl), val in zip(self._info_rows, values):
            lbl.configure(text=val)

    def _preview_text(self, p: Path):
        try:
            raw = p.read_bytes()[:_MAX_TEXT_BYTES]
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1", errors="replace")
            lines = text.splitlines()
            truncated = len(lines) > _MAX_LINES
            lines = lines[:_MAX_LINES]
            self._text.configure(state="normal")
            self._text.delete("1.0", "end")
            width = len(str(len(lines))) + 1
            for i, line in enumerate(lines, 1):
                self._text.insert("end", f"{i:>{width}}  ", "lineno")
                self._text.insert("end", line + "\n", "content")
            if truncated:
                self._text.insert("end", f"\n… (truncated at {_MAX_LINES} lines)", "lineno")
            self._text.configure(state="disabled")
        except OSError as exc:
            self._clear_text(f"Cannot read file: {exc}")

    def _preview_image(self, p: Path):
        try:
            from PIL import Image, ImageTk
            with Image.open(p) as img:
                img.thumbnail((320, 320))
                self._photo = ImageTk.PhotoImage(img)
                self._img_label.configure(image=self._photo,
                                           text=f"{img.width}×{img.height}",
                                           compound="top")
        except ImportError:
            self._img_label.configure(
                image="",
                text="📷 Install Pillow to preview images:\npip install Pillow",
                font=FONTS["small"],
                foreground=COLORS["fg_dim"],
            )
        except Exception as exc:
            self._img_label.configure(image="", text=f"Cannot preview: {exc}", font=FONTS["small"])

    def _clear_text(self, msg: str):
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        if msg:
            self._text.insert("end", msg, "lineno")
        self._text.configure(state="disabled")

    @staticmethod
    def _is_text_file(p: Path) -> bool:
        try:
            with p.open("rb") as fh:
                chunk = fh.read(1024)
            return b"\x00" not in chunk
        except OSError:
            return False

    @staticmethod
    def _fmt_size(size: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.0f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
