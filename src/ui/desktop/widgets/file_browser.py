"""File browser widget — ttk.Treeview with lazy directory loading."""
from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from src.automation.files import (
    create_directory,
    create_file,
    get_drives,
    get_home,
    list_directory,
)
from src.automation.desktop import open_in_file_manager
from src.core.exceptions import FileOperationError
from src.ui.desktop.theme import COLORS, FONTS

logger = logging.getLogger(__name__)

_ICON = {"dir": "📁", "file": "📄", "drive": "💾", "lock": "🔒"}


class FileBrowser(ttk.Frame):
    """
    Left-panel file browser.

    Parameters
    ----------
    on_file_select : callable(Path) | None
        Called when the user double-clicks a file.
    on_path_change : callable(str) | None
        Called with the current path string whenever navigation changes.
    """

    def __init__(self, parent, on_file_select=None, on_path_change=None, **kw):
        super().__init__(parent, **kw)
        self._on_file_select = on_file_select
        self._on_path_change = on_path_change
        self._current_path = get_home()
        self._build()
        self._populate_root()

    # ------------------------------------------------------------------ build
    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # -- toolbar
        tb = ttk.Frame(self)
        tb.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))

        ttk.Button(tb, text="↑", width=3, command=self._go_up).pack(side="left")
        ttk.Button(tb, text="⟳", width=3, command=self._refresh).pack(side="left", padx=2)
        ttk.Button(tb, text="🏠", width=3, command=self._go_home).pack(side="left")
        ttk.Button(tb, text="+ File",   width=7, command=self._new_file).pack(side="left", padx=(6, 0))
        ttk.Button(tb, text="+ Folder", width=8, command=self._new_folder).pack(side="left", padx=2)

        self._path_var = tk.StringVar(value=str(self._current_path))
        path_bar = ttk.Entry(tb, textvariable=self._path_var, font=FONTS["small"])
        path_bar.pack(side="left", fill="x", expand=True, padx=(4, 0))
        path_bar.bind("<Return>", self._navigate_typed)

        # -- tree
        tree_frame = ttk.Frame(self)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        self._tree = ttk.Treeview(
            tree_frame,
            columns=("path", "kind"),
            displaycolumns=("kind",),
            show="tree headings",
            selectmode="browse",
        )
        self._tree.heading("#0",   text="Name", anchor="w")
        self._tree.heading("kind", text="Type", anchor="w")
        self._tree.column("#0",    minwidth=160, width=200, stretch=True)
        self._tree.column("kind",  minwidth=60,  width=70,  stretch=False)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self._tree.bind("<<TreeviewOpen>>", self._on_expand)
        self._tree.bind("<Double-1>",       self._on_double_click)
        self._tree.bind("<Button-3>",       self._context_menu)

        # -- context menu
        self._menu = tk.Menu(self, tearoff=0)
        self._menu.add_command(label="Open",              command=self._action_open)
        self._menu.add_command(label="Open in Explorer",  command=self._action_explore)
        self._menu.add_separator()
        self._menu.add_command(label="New File",          command=self._new_file)
        self._menu.add_command(label="New Folder",        command=self._new_folder)
        self._menu.add_separator()
        self._menu.add_command(label="Copy Path",         command=self._copy_path)

    # --------------------------------------------------------------- populate
    def _populate_root(self):
        self._tree.delete(*self._tree.get_children())
        for drive in get_drives():
            node = self._tree.insert(
                "", "end",
                text=f"{_ICON['drive']} {drive}",
                values=(drive, "Drive"),
            )
            self._tree.insert(node, "end", text="…")   # lazy placeholder
        self._navigate(self._current_path, reset_tree=False)

    def _insert_entries(self, parent_node: str, path: Path):
        """Populate *parent_node* with the contents of *path*."""
        for child in self._tree.get_children(parent_node):
            self._tree.delete(child)
        try:
            for e in list_directory(path):
                icon = _ICON["dir"] if e["is_dir"] else _ICON["file"]
                if e.get("inaccessible"):
                    icon = _ICON["lock"]
                nid = self._tree.insert(
                    parent_node, "end",
                    text=f"{icon} {e['name']}",
                    values=(e["path"], "Folder" if e["is_dir"] else e["ext"] or "File"),
                )
                if e["is_dir"] and not e.get("inaccessible"):
                    self._tree.insert(nid, "end", text="…")   # lazy placeholder
        except FileOperationError as exc:
            self._tree.insert(parent_node, "end", text=f"⚠ {exc}", values=("", ""))

    # ---------------------------------------------------------------- events
    def _on_expand(self, _event):
        nid = self._tree.focus()
        vals = self._tree.item(nid, "values")
        p = Path(vals[0]) if vals and vals[0] else None
        if p and p.is_dir():
            self._insert_entries(nid, p)

    def _on_double_click(self, event):
        nid = self._tree.identify_row(event.y)
        if not nid:
            return
        vals = self._tree.item(nid, "values")
        if not (vals and vals[0]):
            return
        p = Path(vals[0])
        if p.is_dir():
            self._navigate(p)
        elif p.is_file() and self._on_file_select:
            self._on_file_select(p)

    def _context_menu(self, event):
        row = self._tree.identify_row(event.y)
        if row:
            self._tree.selection_set(row)
            self._tree.focus(row)
        self._menu.post(event.x_root, event.y_root)

    # -------------------------------------------------------------- navigate
    def _navigate(self, path: Path, reset_tree: bool = True):
        self._current_path = path
        self._path_var.set(str(path))
        if self._on_path_change:
            self._on_path_change(str(path))
        if reset_tree:
            self._tree.delete(*self._tree.get_children())
            root_node = self._tree.insert(
                "", "end",
                text=f"{_ICON['dir']} {path.name or str(path)}",
                values=(str(path), "Folder"),
                open=True,
            )
            self._insert_entries(root_node, path)

    def _navigate_typed(self, _event=None):
        p = Path(self._path_var.get())
        if p.exists():
            self._navigate(p)
        else:
            messagebox.showwarning("Not Found", f"Path does not exist:\n{p}")

    def _go_up(self):
        self._navigate(self._current_path.parent)

    def _go_home(self):
        self._navigate(get_home())

    def _refresh(self):
        self._navigate(self._current_path)

    # ------------------------------------------------------------ selections
    def _selected_path(self) -> Path | None:
        nid = self._tree.focus()
        if not nid:
            return None
        vals = self._tree.item(nid, "values")
        return Path(vals[0]) if vals and vals[0] else None

    def _action_open(self):
        p = self._selected_path()
        if p and p.is_file() and self._on_file_select:
            self._on_file_select(p)

    def _action_explore(self):
        p = self._selected_path() or self._current_path
        try:
            open_in_file_manager(p)
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def _copy_path(self):
        p = self._selected_path()
        if p:
            self.clipboard_clear()
            self.clipboard_append(str(p))

    def _new_file(self):
        name = simpledialog.askstring("New File", "Enter filename:", parent=self)
        if name:
            try:
                create_file(self._current_path / name)
                self._refresh()
            except FileOperationError as exc:
                messagebox.showerror("Error", str(exc))

    def _new_folder(self):
        name = simpledialog.askstring("New Folder", "Enter folder name:", parent=self)
        if name:
            try:
                create_directory(self._current_path / name)
                self._refresh()
            except FileOperationError as exc:
                messagebox.showerror("Error", str(exc))
