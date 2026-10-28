"""Long-term memory: SQLite at ``~/.automoto/memory.db``.

* ``facts``   - things worth remembering about you and your projects.
* ``journal`` - a dated log of what the agent did (tasks, routines, tool use).

``prompt_block()`` renders a compact summary for the system prompt.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from automoto import home

_LOCK = threading.Lock()
SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '',
  created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS journal (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  kind TEXT NOT NULL,
  text TEXT NOT NULL
);
"""


class Memory:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or home.memory_db())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as c, c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    # -- facts ---------------------------------------------------------------
    def remember(self, text: str, tags: str = "") -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise ValueError("nothing to remember")
        text = text[:1000]
        with _LOCK, closing(self._conn()) as c, c:
            dup = c.execute("SELECT id FROM facts WHERE lower(text)=lower(?)", (text,)).fetchone()
            if dup:
                return {"id": dup["id"], "text": text, "duplicate": True}
            cur = c.execute("INSERT INTO facts(text, tags, created) VALUES (?,?,?)", (text, tags[:200], time.time()))
            return {"id": cur.lastrowid, "text": text}

    def recall(self, query: str = "", limit: int = 10) -> list[dict[str, Any]]:
        words = [w for w in (query or "").lower().split() if len(w) > 1][:8]
        with closing(self._conn()) as c:
            rows = c.execute("SELECT * FROM facts ORDER BY id DESC").fetchall()
        facts = [dict(r) for r in rows]
        if words:
            scored = []
            for f in facts:
                hay = (f["text"] + " " + f["tags"]).lower()
                s = sum(1 for w in words if w in hay)
                if s:
                    scored.append((s, f))
            facts = [f for _, f in sorted(scored, key=lambda x: (-x[0], -x[1]["id"]))]
        return facts[:limit]

    def forget(self, fact_id: int) -> bool:
        with _LOCK, closing(self._conn()) as c, c:
            return c.execute("DELETE FROM facts WHERE id=?", (int(fact_id),)).rowcount > 0

    def facts(self) -> list[dict[str, Any]]:
        return self.recall("", limit=500)

    # -- journal -------------------------------------------------------------
    def log(self, kind: str, text: str) -> None:
        with _LOCK, closing(self._conn()) as c, c:
            c.execute("INSERT INTO journal(ts, kind, text) VALUES (?,?,?)", (time.time(), kind[:40], text[:2000]))

    def journal(self, limit: int = 20) -> list[dict[str, Any]]:
        with closing(self._conn()) as c:
            rows = c.execute("SELECT * FROM journal ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # -- prompt --------------------------------------------------------------
    def prompt_block(self, max_facts: int = 25, max_journal: int = 5) -> str:
        facts = self.facts()[:max_facts]
        jr = self.journal(max_journal)
        if not facts and not jr:
            return ""
        lines = ["## What you remember (memory)"]
        lines += [f"- [#{f['id']}] {f['text']}" for f in facts] or ["- (no facts yet)"]
        if jr:
            lines.append("## Recent journal")
            lines += [f"- {time.strftime('%Y-%m-%d %H:%M', time.localtime(j['ts']))} {j['kind']}: {j['text'][:160]}"
                      for j in jr]
        return "\n".join(lines)
