"""Approval policy: every tool call is ``allow`` (runs now), ``ask`` (waits for you) or ``deny``.

Base levels come from each tool (``safe`` / ``risky`` / ``blocked``) and some calls are
re-classified by their arguments (e.g. ``write_file`` into ``scratch/`` is safe, anywhere
else in the workspace is risky; obviously destructive shell commands are blocked).

Configure in ``.env`` (or the GUI's Settings page, which takes precedence):

    AUTOMOTO_APPROVAL=ask        # ask (default) | auto | readonly
    AUTOMOTO_AUTO_APPROVE=write_file,run_shell   # tools that never ask
    AUTOMOTO_BLOCK_TOOLS=open_app,type_text      # tools that never run

``auto`` approves risky calls without asking (only use it inside Docker). ``readonly``
turns every risky call into a denial. Blocked calls can never be approved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from automoto import config, sandbox

ALLOW, ASK, DENY = "allow", "ask", "deny"

_DESTRUCTIVE = re.compile(
    r"(^|[\s;&|(`])(rm|rmdir|del|erase|rd|mv|move|shred|unlink|truncate|chmod|chown|Remove-Item|ri)\b", re.I)
_OUTSIDE = re.compile(r"(\.\.|~|\$HOME|\$\{HOME\}|%USERPROFILE%|%HOMEPATH%|\$env:|(^|\s)/(\s|$|\*)|(^|[\s'\"=])/[A-Za-z]|[A-Za-z]:\\)")
_ALWAYS_BLOCKED = re.compile(
    r"(\bmkfs\b|\bdd\s+[^|]*of=|\bshutdown\b|\breboot\b|\bhalt\b|\bpoweroff\b|:\(\)\s*\{|\bformat\s+[a-z]:|"
    r"\bdiskpart\b|\bsudo\b|\bsu\s|\bcrontab\b|\breg\s+(add|delete)\b|\bsetx\b|curl[^|]*\|\s*(ba|z)?sh|wget[^|]*\|\s*(ba|z)?sh)",
    re.I)


@dataclass
class Decision:
    action: str  # allow | ask | deny
    level: str   # safe | risky | blocked (after argument checks)
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"action": self.action, "level": self.level, "reason": self.reason}


def _csv(name: str) -> set[str]:
    return {x.strip() for x in (config.env(name, "") or "").split(",") if x.strip()}


def mode() -> str:
    try:
        from automoto import settings

        saved = settings.get("approval_mode")
    except Exception:
        saved = None
    m = (saved or config.env("AUTOMOTO_APPROVAL", "ask") or "ask").lower()
    return m if m in ("ask", "auto", "readonly") else "ask"


def classify(tool: str, base: str, args: dict[str, Any]) -> tuple[str, str]:
    """Return (level, reason) for one call, looking at its arguments."""
    if tool == "write_file":
        try:
            p = sandbox.resolve(args.get("path", ""))
        except sandbox.SandboxError as exc:
            return "blocked", str(exc)
        if sandbox.in_scratch(p):
            return "safe", "write inside scratch/"
        if p.exists():
            return "risky", f"overwrites {sandbox.rel(p)}"
        return "risky", f"creates {sandbox.rel(p)} outside scratch/"
    if tool in ("read_file", "list_dir"):
        try:
            sandbox.resolve(args.get("path", "."))
        except sandbox.SandboxError as exc:
            return "blocked", str(exc)
    if tool == "run_shell":
        cmd = str(args.get("command", ""))
        if _ALWAYS_BLOCKED.search(cmd):
            return "blocked", "command matches a never-allowed pattern (system/destructive/pipe-to-shell)"
        if sandbox.mode() != "docker" and _DESTRUCTIVE.search(cmd) and _OUTSIDE.search(cmd):
            return "blocked", "destructive command that may reach outside the workspace"
        return "risky", f"runs a shell command ({sandbox.mode()} sandbox)"
    return base, {"safe": "read-only", "risky": "changes something", "blocked": "blocked"}.get(base, base)


def decide(tool: str, base: str, args: dict[str, Any]) -> Decision:
    level, reason = classify(tool, base, args)
    if tool in _csv("AUTOMOTO_BLOCK_TOOLS"):
        return Decision(DENY, "blocked", "blocked by AUTOMOTO_BLOCK_TOOLS")
    if level == "blocked":
        return Decision(DENY, level, reason)
    if level == "safe":
        return Decision(ALLOW, level, reason)
    m = mode()
    if m == "readonly":
        return Decision(DENY, level, f"{reason} - AUTOMOTO_APPROVAL=readonly")
    if m == "auto" or tool in _csv("AUTOMOTO_AUTO_APPROVE"):
        return Decision(ALLOW, level, f"{reason} - auto-approved by config")
    return Decision(ASK, level, reason)
