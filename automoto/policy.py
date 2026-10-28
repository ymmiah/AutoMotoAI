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


# Shell commands that mention credential stores are never run (reading them is exfiltration).
_SENSITIVE_SHELL = re.compile(
    r"(\.ssh\b|\bid_(rsa|dsa|ecdsa|ed25519)\b|\.gnupg|\.aws[/\\]|\.azure[/\\]|gcloud[/\\]|\.kube[/\\]config|"
    r"\.docker[/\\]config|\.git-credentials|\.netrc|\.npmrc|\.pypirc|\.password-store|keyrings?[/\\]|Keychains|"
    r"\bsecurity\s+(find|dump)-|\bcmdkey\b|\bvaultcmd\b|Credentials[/\\]|Login Data|Cookies(\.sqlite)?\b|key4\.db|logins\.json|"
    r"\.automoto[/\\](?!workspace)|(^|[\s/\\'\"=<>|;&(])\.env(?!\.(example|sample|template|dist)\b)(\.[\w.-]+)?($|[\s'\";&|)>])|"
    r"\bgh\s+auth\s+(token|status\s+-t|status\s+--show-token)|\bgit\s+credential\b|"
    r"(>>?|\btee\b)\s*\S*(\.bashrc|\.zshrc|\.profile|\.bash_profile|LaunchAgents|autostart))",
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


def _in_scratch(path: str) -> bool:
    try:
        return sandbox.in_scratch(sandbox.resolve(path, allow_outside=True))
    except sandbox.SandboxError:
        return False


def classify(tool: str, base: str, args: dict[str, Any]) -> tuple[str, str]:
    """Return (level, reason) for one call, looking at its arguments."""
    if tool in ("write_file", "edit_file"):
        try:
            p = sandbox.resolve(args.get("path", ""), allow_outside=True)
        except sandbox.SandboxError as exc:
            return "blocked", str(exc)
        if sandbox.is_outside(p):
            return "risky", f"writes outside the workspace: {p}"
        if sandbox.in_scratch(p):
            return "safe", "write inside scratch/"
        if tool == "edit_file":
            return "risky", f"edits {sandbox.rel(p)}"
        if p.exists():
            return "risky", f"overwrites {sandbox.rel(p)}"
        return "risky", f"creates {sandbox.rel(p)}" + (" outside scratch/" if sandbox.is_default_root() else "")
    if tool in ("office_create_docx", "office_create_xlsx", "office_create_pptx"):
        return classify("write_file", base, {"path": args.get("path", "")})
    if tool == "office_edit":
        lvl, why = classify("write_file", base, {"path": args.get("path", "")})
        return ("risky" if lvl == "safe" and not _in_scratch(args.get("path", "")) else lvl), why.replace("overwrites", "edits")
    if tool in ("office_convert", "office_recalc"):
        src = args.get("path", "")
        lvl, why = classify("read_file", base, {"path": src})
        if lvl != "safe":
            return lvl, why
        if tool == "office_recalc" and not args.get("save"):
            return "safe", "read-only (recalculates a temporary copy)"
        try:
            sp = sandbox.resolve(src, allow_outside=True)
        except sandbox.SandboxError as exc:
            return "blocked", str(exc)
        if tool == "office_recalc":
            dest = str(sp.with_name(sp.stem + ".recalc.xlsx"))
        else:
            dest = args.get("out") or str(sp.with_suffix("." + str(args.get("to", "pdf")).lower().lstrip(".")))
        return classify("write_file", base, {"path": dest})
    if tool in ("data_inspect", "data_read", "text_search", "text_tail", "pdf_text", "image_info",
                "data_query", "sqlite_query"):
        lvl, why = classify("read_file", base, {"path": args.get("path", "")})
        if lvl == "blocked" or not args.get("out") or tool not in ("data_query", "sqlite_query"):
            return lvl, why
        return classify("write_file", base, {"path": args["out"]})
    if tool == "data_convert":
        lvl, why = classify("read_file", base, {"path": args.get("path", "")})
        if lvl == "blocked":
            return lvl, why
        return classify("write_file", base, {"path": args.get("out", "")})
    if tool in ("wp_validate", "wp_security_review"):
        return classify("read_file", base, {"path": args.get("path", "")})
    if tool in ("wp_bump_version", "wp_add_guard", "wp_package"):
        src = args.get("src" if tool == "wp_package" else "path", "")
        lvl, why = classify("read_file", base, {"path": src})
        if lvl == "blocked":
            return lvl, why
        dest = args.get("out") or src
        lvl, why = classify("edit_file" if dest == src else "write_file", base, {"path": dest})
        return lvl, why
    if tool in ("archive_list", "archive_inspect", "archive_read"):
        return classify("read_file", base, {"path": args.get("path", "")})
    if tool in ("archive_extract", "archive_create", "archive_repack"):
        srcs = args.get("sources") if tool == "archive_create" else [args.get("path", "")]
        if isinstance(srcs, str):
            srcs = [x.strip() for x in srcs.strip("[]").replace('"', "").split(",") if x.strip()]
        for src in srcs or [""]:
            lvl, why = classify("read_file", base, {"path": src})
            if lvl == "blocked":
                return lvl, why
        dest = args.get("dest" if tool == "archive_extract" else "out", "")
        lvl, why = classify("write_file", base, {"path": dest})
        if lvl == "blocked":
            return lvl, why
        verb = {"archive_extract": "extracts into", "archive_create": "packs into", "archive_repack": "re-packs into"}[tool]
        return lvl, f"{verb} {dest}" + ("" if lvl == "safe" else f" ({why})")
    if tool == "download_file":
        from automoto import netguard

        try:
            netguard.check_url(str(args.get("url", "")))
        except netguard.BlockedURL as exc:
            return "blocked", f"blocked URL: {exc}"
        except Exception as exc:  # DNS failure etc. - the tool reports it
            return "risky", f"downloads {args.get('url', '')} ({exc.__class__.__name__})"
        dest = args.get("path") or "downloads/file"
        lvl, why = classify("write_file", base, {"path": dest})
        if lvl == "blocked":
            return lvl, why
        return "risky", f"downloads {str(args.get('url', ''))[:120]} into {dest}"
    if tool in ("office_read", "office_check", "office_render", "office_review"):
        return classify("read_file", base, {"path": args.get("path", "")})
    if tool in ("read_file", "list_dir", "search_files"):
        try:
            p = sandbox.resolve(args.get("path", "."), allow_outside=True)
        except sandbox.SandboxError as exc:
            return "blocked", str(exc)
        if sandbox.is_outside(p):
            return "risky", f"reads outside the workspace: {p}"
        return "safe", "read-only"
    if tool == "run_shell":
        cmd = str(args.get("command", ""))
        if _ALWAYS_BLOCKED.search(cmd):
            return "blocked", "command matches a never-allowed pattern (system/destructive/pipe-to-shell)"
        if _SENSITIVE_SHELL.search(cmd):
            return "blocked", "command touches credentials, keychains, browser data or AutoMoto's own settings"
        if sandbox.mode() != "docker" and _DESTRUCTIVE.search(cmd) and _OUTSIDE.search(cmd):
            return "blocked", "destructive command that may reach outside the workspace"
        return "risky", f"runs a shell command ({sandbox.mode()} sandbox)"
    if tool in ("run_app", "open_in_app", "run_app_script"):
        from automoto import apps

        app = apps.BY_ID.get(str(args.get("app_id", "")).lower())
        if not app:
            return "risky", "runs a local app"
        if tool == "run_app" and _SENSITIVE_SHELL.search(" ".join(str(a) for a in (args.get("args") or []))):
            return "blocked", "arguments touch credentials, keychains, browser data or AutoMoto's own settings"
        try:
            if tool == "run_app":
                apps.check_args(app, list(args.get("args") or []))
            for k in ("path", "script", "target"):
                if args.get(k):
                    sandbox.resolve(args[k], allow_outside=True)
        except (apps.AppError, sandbox.SandboxError) as exc:
            return "blocked", str(exc)
        what = {"run_app": f"runs {app.name}", "open_in_app": f"opens a file in {app.name}",
                "run_app_script": f"runs a script inside {app.name} (the script can do anything the app can)"}[tool]
        return "risky", what
    if tool == "service_api":
        from automoto import services

        return services.classify(args)
    return base, {"safe": "read-only", "risky": "changes something", "blocked": "blocked"}.get(base, base)


def decide(tool: str, base: str, args: dict[str, Any], *, tainted: bool = False) -> Decision:
    """``tainted``: this run has read web / third-party content, so auto-approval is suspended
    (a prompt injection in that content must never be able to run a risky tool unattended)."""
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
        if tainted:
            return Decision(ASK, level, f"{reason} - asking because this run read web or third-party content")
        return Decision(ALLOW, level, f"{reason} - auto-approved by config")
    return Decision(ASK, level, reason)
