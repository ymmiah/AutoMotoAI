"""One tidy workspace per user, with a folder for each kind of thing.

    uploads/    files you give the assistant
    artifacts/  files it makes, grouped as artifacts/<date>-<task>/   (new files here need no approval)
    projects/   your code and longer projects
    memory/     MEMORY.md (a readable copy of what it remembers) and library.sqlite3 (saved pages/docs)
    skills/     notes and drafts for your own playbooks (installed skills live in Settings > Skills)
    logs/       a dated log of what it did (one file per month)
    scratch/    temporary files (no approval needed)

In hosted mode every user has their own workspace, so all of this is per user.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from automoto import brand, sandbox

FOLDERS: dict[str, str] = {
    "uploads": "files you give me",
    "artifacts": "files I make, grouped by date and task",
    "projects": "your code and longer projects",
    "memory": "what I remember (MEMORY.md) and your saved library",
    "skills": "notes and drafts for your own playbooks",
    "logs": "a dated log of what I did",
    "scratch": "temporary files",
}


def ensure(root: Path | None = None) -> Path:
    """Create the folders (cheap, idempotent) in the user's default workspace."""
    root = root or sandbox.default_root()
    for name in FOLDERS:
        (root / name).mkdir(parents=True, exist_ok=True)
    readme = root / "README.md"
    if not readme.exists():
        lines = [f"# Your {brand.short()} workspace", "", "| Folder | What's in it |", "|---|---|"]
        lines += [f"| `{k}/` | {v} |" for k, v in FOLDERS.items()]
        readme.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def folder(name: str) -> Path:
    """A layout folder in the user's default workspace (created if missing)."""
    if name not in FOLDERS:
        raise ValueError(f"unknown folder {name}")
    p = sandbox.default_root() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def slug(text: str, n: int = 5) -> str:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    stop = {"a", "an", "the", "of", "to", "for", "and", "my", "me", "please", "can", "you", "i", "it", "this", "with",
            "make", "create", "write", "in", "on"}
    keep = [w for w in words if w not in stop][:n] or ["task"]
    return "-".join(keep)[:48]


def artifact_dir(goal: str, when: float | None = None) -> str:
    """Workspace-relative folder for this task's files, e.g. ``artifacts/2026-10-31-budget-report``."""
    return f"artifacts/{time.strftime('%Y-%m-%d', time.localtime(when))}-{slug(goal)}"


def in_artifacts(p: Path) -> bool:
    try:
        p.relative_to((sandbox.default_root() / "artifacts").resolve())
        return sandbox.is_default_root()
    except ValueError:
        return False


def log(line: str) -> None:
    """Append one line to logs/<YYYY-MM>.md (best effort)."""
    try:
        f = folder("logs") / f"{time.strftime('%Y-%m')}.md"
        with f.open("a", encoding="utf-8") as fh:
            fh.write(f"- {time.strftime('%Y-%m-%d %H:%M')} {line.strip()[:600]}\n")
    except OSError:
        pass
