"""Skills: reusable how-to guides the agent can load on demand.

A skill is a folder with a ``SKILL.md``. Optional front matter gives it a name and a
one-line description::

    ---
    name: research-brief
    description: Research a topic on the web and write a short sourced brief.
    ---
    1. web_search ...

Only the names + descriptions go into the system prompt; the agent calls
``load_skill`` to read the full text when a task matches. Your own skills live in
``~/.automoto/skills/<name>/SKILL.md`` and override bundled ones with the same name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from automoto import home

BUNDLED = Path(__file__).parent / "skills_bundled"
FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    bundled: bool

    def body(self) -> str:
        text = self.path.read_text(encoding="utf-8")
        return FM_RE.sub("", text, count=1).strip()


def _parse(path: Path, bundled: bool) -> Skill:
    text = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    m = FM_RE.match(text)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip().strip('"\'')
    body = FM_RE.sub("", text, count=1).strip()
    first = next((ln.strip("# ").strip() for ln in body.splitlines() if ln.strip()), "")
    return Skill(meta.get("name") or path.parent.name, (meta.get("description") or first)[:200], path, bundled)


def discover(user_dir: Path | None = None) -> dict[str, Skill]:
    found: dict[str, Skill] = {}
    for base, bundled in ((BUNDLED, True), (user_dir or home.skills_dir(), False)):
        if not base.is_dir():
            continue
        for p in sorted(base.glob("*/SKILL.md")):
            try:
                s = _parse(p, bundled)
            except OSError:
                continue
            found[s.name] = s  # user skills override bundled ones
    return found


def prompt_block(skills: dict[str, Skill] | None = None) -> str:
    skills = discover() if skills is None else skills
    if not skills:
        return ""
    lines = ["## Skills (call load_skill(name) before following one)"]
    lines += [f"- {s.name}: {s.description}" for s in skills.values()]
    return "\n".join(lines)
