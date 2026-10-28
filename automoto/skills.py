"""Skills: reusable how-to guides the agent can load on demand.

A skill is a folder with a ``SKILL.md``. Optional front matter gives it a name and a
one-line description::

    ---
    name: research-brief
    description: Research a topic on the web and write a short sourced brief.
    ---
    1. web_search ...

Skills can declare what they need (v5.2); ``automoto skills`` and the Skills page show
whether this computer has it. ``a|b`` means either one::

    apps: ffmpeg            # ids from automoto/apps.py (list_apps)
    tools: run_app          # agent tools
    env: GITHUB_TOKEN       # environment variables (only checked for presence)
    status: live            # live | unit | untested - how well the procedure is verified

Only the names + descriptions go into the system prompt; the agent calls
``load_skill`` to read the full text when a task matches. Your own skills live in
``~/.automoto/skills/<name>/SKILL.md`` and override bundled ones with the same name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from automoto import home

BUNDLED = Path(__file__).parent / "skills_bundled"
FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    bundled: bool
    meta: dict[str, str] = field(default_factory=dict)

    def needs(self, key: str) -> list[str]:
        return [x.strip() for x in (self.meta.get(key) or "").split(",") if x.strip()]

    def requirements(self, tool_names: set[str] | None = None) -> dict[str, Any]:
        """What the skill needs and whether this computer has it."""
        from automoto import apps, config

        if tool_names is None:
            from automoto import tools as tools_mod

            tool_names = set(tools_mod.build(desktop=True))
        found = apps.detect()
        checks: list[dict[str, Any]] = []
        for a in self.needs("apps"):
            alts = [x.strip() for x in a.split("|")]
            checks.append({"kind": "app", "name": a, "ok": any(found.get(x) for x in alts),
                           "optional": False})
        for a in self.needs("optional_apps"):
            alts = [x.strip() for x in a.split("|")]
            checks.append({"kind": "app", "name": a, "ok": any(found.get(x) for x in alts), "optional": True})
        for t in self.needs("tools"):
            checks.append({"kind": "tool", "name": t, "ok": t in tool_names or t.startswith("mcp__"), "optional": False})
        for e in self.needs("env"):
            alts = [x.strip() for x in e.split("|")]
            checks.append({"kind": "env", "name": e, "ok": any(config.env(x) for x in alts), "optional": True})
        for c in self.needs("connectors"):
            from automoto import mcp_catalog

            checks.append({"kind": "connector", "name": c, "ok": c in mcp_catalog.read_config()["servers"],
                           "optional": True})
        ready = all(c["ok"] for c in checks if not c["optional"])
        if not any(c["kind"] in ("app", "tool") for c in checks):
            # connector-only skills (Canva, Drive, OneDrive) need one of their connectors enabled
            conns = [c for c in checks if c["kind"] == "connector"]
            if conns and not any(c["ok"] for c in conns):
                ready = False
        return {"ready": ready, "checks": checks, "status": self.meta.get("status", "unit"),
                "category": self.meta.get("category", "general")}

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
    return Skill(meta.get("name") or path.parent.name, (meta.get("description") or first)[:200], path, bundled, meta)


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


NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")


def save(name: str, body: str, description: str = "", user_dir: Path | None = None) -> Skill:
    """Create or overwrite a *user* skill (bundled skills are read-only; saving one with the
    same name creates your own override)."""
    name = (name or "").strip().lower()
    if not NAME_RE.match(name):
        raise ValueError("skill name must be kebab-case: a-z, 0-9 and '-' (max 60)")
    body = (body or "").strip()
    if not body:
        raise ValueError("skill body is empty")
    if len(body) > 50_000:
        raise ValueError("skill is too long (max 50k chars)")
    base = user_dir or home.skills_dir()
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    if FM_RE.match(body + "\n"):
        text = body + "\n"
    else:
        desc = re.sub(r"\s+", " ", description or "").strip()[:200]
        text = f"---\nname: {name}\ndescription: {desc}\n---\n{body}\n"
    (d / "SKILL.md").write_text(text, encoding="utf-8")
    return _parse(d / "SKILL.md", False)


def delete(name: str, user_dir: Path | None = None) -> bool:
    """Delete a user skill (never a bundled one)."""
    if not NAME_RE.match(name or ""):
        return False
    d = (user_dir or home.skills_dir()) / name
    f = d / "SKILL.md"
    if not f.is_file():
        return False
    f.unlink()
    try:
        d.rmdir()
    except OSError:
        pass
    return True
