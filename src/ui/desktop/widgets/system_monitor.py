"""
System Monitor widget — live CPU / RAM / Disk / Network bars + process list.
Refreshes every second using tkinter's after() scheduler.
Requires psutil (pip install psutil).
"""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk

from src.ui.desktop.theme import COLORS, FONTS

logger = logging.getLogger(__name__)

_REFRESH_MS = 1000   # refresh interval


def _fmt_rate(bps: int) -> str:
    if bps < 1024:
        return f"{bps} B/s"
    if bps < 1024 ** 2:
        return f"{bps/1024:.1f} KB/s"
    return f"{bps/1024**2:.1f} MB/s"


class _MetricBar(ttk.Frame):
    """Single labelled progress bar (CPU, RAM, Disk)."""

    def __init__(self, parent, label: str, color: str = "", **kw):
        super().__init__(parent, **kw)
        self.columnconfigure(1, weight=1)
        ttk.Label(self, text=label, font=FONTS["small"], width=6, anchor="e",
                  foreground=COLORS["fg_dim"]).grid(row=0, column=0, padx=(4, 4))
        self._var = tk.DoubleVar(value=0.0)
        self._bar = ttk.Progressbar(self, variable=self._var, maximum=100, length=100)
        self._bar.grid(row=0, column=1, sticky="ew", padx=(0, 4))
        self._lbl = ttk.Label(self, text="0%", font=FONTS["small"], width=10, foreground=COLORS["fg"])
        self._lbl.grid(row=0, column=2, padx=(0, 4))

    def update(self, percent: float, detail: str = ""):
        self._var.set(min(percent, 100))
        self._lbl.configure(text=f"{percent:.0f}%  {detail}")


class SystemMonitor(ttk.Frame):
    """
    Full system monitor with metric bars and a process table.
    Call .start() to begin auto-refresh, .stop() to halt.
    """

    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self._running = False
        self._after_id = None
        self._build()

    # ── build ─────────────────────────────────────────────────────────────────
    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # metric bars
        bars_frame = ttk.LabelFrame(self, text=" Resources ", padding=4)
        bars_frame.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        bars_frame.columnconfigure(0, weight=1)

        self._cpu  = _MetricBar(bars_frame, "CPU")
        self._ram  = _MetricBar(bars_frame, "RAM")
        self._disk = _MetricBar(bars_frame, "Disk")
        self._cpu .grid(row=0, column=0, sticky="ew", pady=1)
        self._ram .grid(row=1, column=0, sticky="ew", pady=1)
        self._disk.grid(row=2, column=0, sticky="ew", pady=1)

        # network row
        net_frame = ttk.Frame(bars_frame)
        net_frame.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        ttk.Label(net_frame, text="Net ↑", font=FONTS["small"], foreground=COLORS["fg_dim"]).pack(side="left", padx=4)
        self._net_up = ttk.Label(net_frame, text="0 B/s", font=FONTS["small"], foreground=COLORS["green"])
        self._net_up.pack(side="left", padx=2)
        ttk.Label(net_frame, text="↓", font=FONTS["small"], foreground=COLORS["fg_dim"]).pack(side="left", padx=4)
        self._net_dn = ttk.Label(net_frame, text="0 B/s", font=FONTS["small"], foreground=COLORS["accent2"])
        self._net_dn.pack(side="left", padx=2)

        # search + process list
        ctrl = ttk.Frame(self)
        ctrl.grid(row=1, column=0, sticky="ew", padx=4, pady=(4, 0))
        ttk.Label(ctrl, text="🔍", font=FONTS["small"]).pack(side="left")
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._filter_procs)
        ttk.Entry(ctrl, textvariable=self._search_var, font=FONTS["small"], width=14).pack(side="left", padx=4)
        ttk.Button(ctrl, text="⟳", width=3, command=self._refresh_once).pack(side="left")
        ttk.Button(ctrl, text="🔴 Kill", command=self._kill_selected).pack(side="right", padx=4)

        tree_frame = ttk.Frame(self)
        tree_frame.grid(row=2, column=0, sticky="nsew", padx=4, pady=4)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        cols = ("pid", "cpu", "mem", "status")
        self._tree = ttk.Treeview(tree_frame, columns=cols, show="tree headings", selectmode="browse")
        self._tree.heading("#0",     text="Process",  anchor="w")
        self._tree.heading("pid",    text="PID",      anchor="e")
        self._tree.heading("cpu",    text="CPU %",    anchor="e")
        self._tree.heading("mem",    text="MEM %",    anchor="e")
        self._tree.heading("status", text="Status",   anchor="w")
        self._tree.column("#0",     minwidth=100, width=130, stretch=True)
        self._tree.column("pid",    minwidth=50,  width=55,  stretch=False, anchor="e")
        self._tree.column("cpu",    minwidth=50,  width=55,  stretch=False, anchor="e")
        self._tree.column("mem",    minwidth=50,  width=55,  stretch=False, anchor="e")
        self._tree.column("status", minwidth=60,  width=70,  stretch=False)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._all_procs: list[dict] = []

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def start(self):
        self._running = True
        self._refresh()

    def stop(self):
        self._running = False
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None

    # ── refresh ───────────────────────────────────────────────────────────────
    def _refresh(self):
        self._refresh_once()
        if self._running:
            self._after_id = self.after(_REFRESH_MS, self._refresh)

    def _refresh_once(self):
        try:
            from src.automation.monitor import get_system_snapshot, get_top_processes
            snap  = get_system_snapshot()
            procs = get_top_processes(50)
            self._update_bars(snap)
            self._all_procs = procs
            self._filter_procs()
        except Exception as exc:
            logger.debug("Monitor refresh error: %s", exc)

    def _update_bars(self, snap: dict):
        cpu  = snap.get("cpu", {})
        ram  = snap.get("ram", {})
        disk = snap.get("disk", {})
        net  = snap.get("network", {})

        self._cpu.update(cpu.get("percent", 0),
                         f"{cpu.get('count', '')} cores")
        self._ram.update(ram.get("percent", 0),
                         f"{ram.get('used_gb', 0):.1f}/{ram.get('total_gb', 0):.1f} GB")
        self._disk.update(disk.get("percent", 0),
                          f"{disk.get('used_gb', 0):.0f}/{disk.get('total_gb', 0):.0f} GB")
        self._net_up.configure(text=_fmt_rate(net.get("bytes_sent_rate", 0)))
        self._net_dn.configure(text=_fmt_rate(net.get("bytes_recv_rate", 0)))

    def _filter_procs(self, *_):
        q = self._search_var.get().lower()
        filtered = [p for p in self._all_procs if q in p["name"].lower()]
        self._tree.delete(*self._tree.get_children())
        for p in filtered:
            self._tree.insert("", "end",
                              text=p["name"],
                              values=(p["pid"], f"{p['cpu']:.1f}", f"{p['mem']:.1f}", p["status"]))

    # ── kill ──────────────────────────────────────────────────────────────────
    def _kill_selected(self):
        sel = self._tree.focus()
        if not sel:
            return
        vals = self._tree.item(sel, "values")
        name = self._tree.item(sel, "text")
        if not vals:
            return
        pid = int(vals[0])
        if not messagebox.askyesno("Kill Process", f"Kill '{name}' (PID {pid})?"):
            return
        try:
            from src.automation.monitor import kill_process
            msg = kill_process(pid)
            messagebox.showinfo("Done", msg)
            self._refresh_once()
        except PermissionError as exc:
            messagebox.showerror("Permission Denied", str(exc))
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
