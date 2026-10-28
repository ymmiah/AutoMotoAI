"""Saved conversations: SQLite at ``~/.automoto/conversations.db``.

A conversation has a title (auto-generated from the first user message, renameable) and an
ordered list of messages. Assistant messages carry ``meta`` (provider, model, steps, tool
events) so the GUI can redraw tool-step cards when you reopen a chat. API keys are never
stored here.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from automoto import home

_LOCK = threading.Lock()
SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  mode TEXT NOT NULL DEFAULT 'agent',
  created REAL NOT NULL,
  updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  meta TEXT NOT NULL DEFAULT '{}',
  created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);
"""
MAX_EVENTS = 200


def make_title(content: Any, limit: int = 60) -> str:
    """Short title from the first user message (text parts only)."""
    if isinstance(content, list):
        text = " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
        if not text.strip() and any(isinstance(p, dict) and p.get("type") == "image_url" for p in content):
            text = "Image question"
    else:
        text = str(content or "")
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"(\*\*|__|`+|^#+\s*|^>\s*)", "", text, flags=re.M)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "New chat"
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    if len(first) <= limit:
        return first[0].upper() + first[1:]
    cut = first[:limit].rsplit(" ", 1)[0] or first[:limit]
    return cut[0].upper() + cut[1:] + "…"


def _slim_meta(meta: dict[str, Any] | None) -> dict[str, Any]:
    meta = dict(meta or {})
    meta.pop("keys", None)
    ev = meta.get("events")
    if isinstance(ev, list):
        slim = []
        for e in ev[-MAX_EVENTS:]:
            if e.get("type") == "thinking":
                continue
            e = dict(e)
            if isinstance(e.get("output"), str) and len(e["output"]) > 2000:
                e["output"] = e["output"][:2000] + "…"
            slim.append(e)
        meta["events"] = slim
    return meta


class Conversations:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or home.home() / "conversations.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as c, c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    def create(self, title: str = "New chat", mode: str = "agent") -> dict[str, Any]:
        now = time.time()
        cid = uuid.uuid4().hex[:12]
        with _LOCK, closing(self._conn()) as c, c:
            c.execute("INSERT INTO conversations(id, title, mode, created, updated) VALUES (?,?,?,?,?)",
                      (cid, (title or "New chat")[:120], mode if mode in ("agent", "chat") else "agent", now, now))
        return self.get(cid, with_messages=False)  # type: ignore[return-value]

    def list(self, query: str = "", limit: int = 200) -> list[dict[str, Any]]:
        q = (query or "").strip().lower()
        with closing(self._conn()) as c:
            if q:
                rows = c.execute(
                    "SELECT DISTINCT c.* FROM conversations c LEFT JOIN messages m ON m.conversation_id=c.id "
                    "WHERE lower(c.title) LIKE ? OR lower(m.content) LIKE ? ORDER BY c.updated DESC LIMIT ?",
                    (f"%{q}%", f"%{q}%", limit)).fetchall()
            else:
                rows = c.execute("SELECT * FROM conversations ORDER BY updated DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get(self, cid: str, *, with_messages: bool = True) -> dict[str, Any] | None:
        with closing(self._conn()) as c:
            row = c.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
            if not row:
                return None
            out = dict(row)
            if with_messages:
                out["messages"] = [
                    {"id": m["id"], "role": m["role"], "content": json.loads(m["content"]),
                     "meta": json.loads(m["meta"]), "created": m["created"]}
                    for m in c.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (cid,))]
        return out

    def add_message(self, cid: str, role: str, content: Any, meta: dict[str, Any] | None = None) -> int:
        now = time.time()
        with _LOCK, closing(self._conn()) as c, c:
            row = c.execute("SELECT title, (SELECT count(*) FROM messages WHERE conversation_id=?) AS n "
                            "FROM conversations WHERE id=?", (cid, cid)).fetchone()
            if not row:
                raise KeyError(cid)
            cur = c.execute("INSERT INTO messages(conversation_id, role, content, meta, created) VALUES (?,?,?,?,?)",
                            (cid, role, json.dumps(content), json.dumps(_slim_meta(meta)), now))
            if role == "user" and row["n"] == 0 and row["title"] in ("New chat", ""):
                c.execute("UPDATE conversations SET title=? WHERE id=?", (make_title(content), cid))
            c.execute("UPDATE conversations SET updated=? WHERE id=?", (now, cid))
            return int(cur.lastrowid)

    def rename(self, cid: str, title: str) -> bool:
        title = re.sub(r"\s+", " ", title or "").strip()[:120]
        if not title:
            return False
        with _LOCK, closing(self._conn()) as c, c:
            return c.execute("UPDATE conversations SET title=? WHERE id=?", (title, cid)).rowcount > 0

    def set_mode(self, cid: str, mode: str) -> bool:
        if mode not in ("agent", "chat"):
            return False
        with _LOCK, closing(self._conn()) as c, c:
            return c.execute("UPDATE conversations SET mode=? WHERE id=?", (mode, cid)).rowcount > 0

    def delete(self, cid: str) -> bool:
        with _LOCK, closing(self._conn()) as c, c:
            c.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
            return c.execute("DELETE FROM conversations WHERE id=?", (cid,)).rowcount > 0

    def history(self, cid: str, limit: int = 20) -> list[dict[str, Any]]:
        """Last ``limit`` user/assistant messages in chat format, for the next model call."""
        conv = self.get(cid)
        if not conv:
            raise KeyError(cid)
        msgs = [{"role": m["role"], "content": m["content"]} for m in conv["messages"]
                if m["role"] in ("user", "assistant")]
        return msgs[-limit:]
