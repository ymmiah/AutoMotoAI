"""The agent's toolbox. Each tool has a JSON schema (for native tool calling), a base
safety level (``safe`` / ``risky`` / ``blocked``) and a Python function.

File and shell tools are jailed to the sandbox workspace; network tools go through the
SSRF guard; memory and skills tools use ``~/.automoto``.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from automoto import config, netguard, sandbox
from automoto import skills as skills_mod
from automoto.memory import Memory


class ToolFailed(Exception):
    pass


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    level: str  # safe | risky | blocked
    fn: Callable[..., Any]
    group: str = "core"
    hidden: bool = False  # merged into another tool: still runs if called, never offered to the model

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}


@dataclass
class ToolContext:
    memory: Memory | None = None
    skills: dict[str, skills_mod.Skill] = field(default_factory=dict)
    keys: dict[str, str] = field(default_factory=dict)  # per-run BYOK tokens (never logged or stored)
    expand: Callable[[str], list[str]] | None = None  # the agent loop's planner hook for more_tools


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


S = {"type": "string"}
I = {"type": "integer"}


# -- helpers --------------------------------------------------------------------
def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|section|article)>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    text = html.unescape(raw)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _title(raw: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    return html.unescape(m.group(1)).strip()[:200] if m else ""


# -- file tools -----------------------------------------------------------------
OFFICE_EXT = {".docx", ".doc", ".odt", ".rtf", ".xlsx", ".xlsm", ".xls", ".ods", ".pptx", ".ppt", ".odp", ".pdf"}
STRUCT_EXT = {".json", ".jsonl", ".ndjson", ".yaml", ".yml", ".toml", ".xml"}
ARCHIVE_EXT = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".xz", ".txz", ".7z", ".rar"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic"}
TABLE_EXT = {".parquet", ".sqlite", ".sqlite3", ".db"}


def read_file(ctx: ToolContext, path: str, max_chars: int = 12000, tail: int = 0, select: str = "",
              sheet: str = "", first: int = 0, last: int = 0) -> str:
    """Read anything: text, Word/Excel/PowerPoint/PDF, JSON/YAML/XML, archives (listing), images
    (metadata), Parquet/SQLite (profile). One tool instead of nine, so models can't pick the wrong one."""
    p = sandbox.resolve(path, allow_outside=True)
    if not p.is_file():
        raise ToolFailed(f"no such file: {sandbox.rel(p)}")
    ext = p.suffix.lower()
    name = p.name.lower()
    cap = max(200, min(int(max_chars or 12000), 60000))
    if ext in OFFICE_EXT:
        if ext == ".pdf" and (first or last):
            from automoto import data_tools

            return data_tools.pdf_text(ctx, path, first=int(first or 1), last=int(last or 0), max_chars=cap)
        from automoto import office_tools

        return office_tools.read(ctx, path, sheet=sheet or "", max_chars=max(cap, 20000))
    if ext in STRUCT_EXT and select:
        from automoto import data_tools

        return data_tools.data_read(ctx, path, select=select, max_chars=cap)
    if ext in ARCHIVE_EXT or name.endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
        from automoto import archive_tools

        return archive_tools.archive_list(ctx, path)
    if ext in IMAGE_EXT:
        from automoto import data_tools

        return data_tools.image_info(ctx, path) + "\n(To see what is in the picture, the user can attach it to the chat.)"
    if ext in TABLE_EXT:
        from automoto import data_tools

        return data_tools.data_inspect(ctx, path)
    if tail:
        from automoto import data_tools

        return data_tools.text_tail(ctx, path, lines=int(tail))
    data = p.read_bytes()
    if b"\x00" in data[:4096]:
        raise ToolFailed(f"binary file ({ext or 'no extension'}) - it can't be shown as text")
    text = data.decode("utf-8", errors="replace")
    return text if len(text) <= cap else text[:cap] + f"\n[…{len(text) - cap} more chars; use tail=50 for the end]"


def write_file(ctx: ToolContext, path: str, content: str, append: bool = False) -> str:
    p = sandbox.resolve(path, allow_outside=True)
    if p.is_dir():
        raise ToolFailed(f"{sandbox.rel(p)} is a folder")
    p.parent.mkdir(parents=True, exist_ok=True)
    content = str(content)
    if append and p.exists():
        with p.open("a", encoding="utf-8") as fh:
            fh.write(content)
    else:
        p.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} chars to {sandbox.rel(p)}"


def edit_file(ctx: ToolContext, path: str, old: str, new: str, count: int = 1) -> str:
    """Replace an exact snippet in a text file (safer than rewriting the whole file)."""
    p = sandbox.resolve(path, allow_outside=True)
    if not p.is_file():
        raise ToolFailed(f"no such file: {sandbox.rel(p)}")
    text = p.read_text(encoding="utf-8")
    old, new = str(old), str(new)
    if not old:
        raise ToolFailed("old must not be empty")
    found = text.count(old)
    if found == 0:
        raise ToolFailed("old text not found - read_file first and copy it exactly (including spaces)")
    count = 1 if count is None else int(count)
    if count < 0:
        raise ToolFailed("count must be 0 (all) or a positive number")
    if found > 1 and count == 1:
        raise ToolFailed(f"old text appears {found} times - add surrounding lines so it is unique, or set count")
    text = text.replace(old, new, count if count > 0 else -1)
    p.write_text(text, encoding="utf-8")
    return f"edited {sandbox.rel(p)}: replaced {min(found, count) if count > 0 else found} occurrence(s)"


_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", "target", ".mypy_cache"}


def search_files(ctx: ToolContext, pattern: str, path: str = ".", glob: str = "*", max_results: int = 50,
                 context: int = 0) -> str:
    """Grep-like search (regex, case-insensitive) through text files under ``path`` - or inside one
    (large) file when ``path`` is a file (streams logs/CSVs, with ``context`` lines)."""
    import fnmatch
    import os as _os

    base = sandbox.resolve(path, allow_outside=True)
    if base.is_file():
        from automoto import data_tools

        return data_tools.text_search(ctx, path, pattern, regex=True, ignore_case=True, context=int(context or 0),
                                      max_matches=int(max_results or 50))
    if not base.is_dir():
        raise ToolFailed(f"not a folder: {sandbox.rel(base)}")
    try:
        rx = re.compile(str(pattern), re.I)
    except re.error as exc:
        raise ToolFailed(f"bad regex: {exc}") from None
    max_results = max(1, min(int(max_results or 50), 200))
    hits: list[str] = []
    scanned = 0
    for dirpath, dirnames, filenames in _os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".cache"))
        for fn in sorted(filenames):
            if not fnmatch.fnmatch(fn, glob or "*"):
                continue
            fp = Path(dirpath) / fn
            if sandbox.sensitive(fp.resolve()) or scanned > 5000:
                continue
            scanned += 1
            try:
                if fp.stat().st_size > 2_000_000:
                    continue
                with fp.open("r", encoding="utf-8", errors="strict") as fh:
                    for i, line in enumerate(fh, 1):
                        if rx.search(line):
                            hits.append(f"{sandbox.rel(fp)}:{i}: {line.rstrip()[:200]}")
                            if len(hits) >= max_results:
                                return "\n".join(hits) + "\n[…more results; narrow the pattern]"
            except (UnicodeDecodeError, OSError):
                continue
    return "\n".join(hits) or f"no matches for /{pattern}/ in {sandbox.rel(base)}"


def list_dir(ctx: ToolContext, path: str = ".") -> str:
    p = sandbox.resolve(path, allow_outside=True)
    if not p.is_dir():
        raise ToolFailed(f"not a folder: {sandbox.rel(p)}")
    items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    lines = [(f"{i.name}/" if i.is_dir() else f"{i.name}  ({i.stat().st_size} B)") for i in items[:300]]
    more = f"\n[…{len(items) - 300} more]" if len(items) > 300 else ""
    return f"{sandbox.rel(p)}:\n" + ("\n".join(lines) or "(empty)") + more


def run_shell(ctx: ToolContext, command: str, timeout: int = 0) -> str:
    res = sandbox.run_shell(command, timeout=int(timeout) or None)
    return f"[{res['mode']} sandbox] exit {res['exit']}\n{res['output'] or '(no output)'}"


# -- web tools ------------------------------------------------------------------
def web_search(ctx: ToolContext, query: str, max_results: int = 6) -> str:
    """Free web search via DuckDuckGo's HTML endpoint (no key)."""
    query = (query or "").strip()
    if not query:
        raise ToolFailed("empty query")
    r = netguard.request("https://html.duckduckgo.com/html/", method="POST",
                         data=urllib.parse.urlencode({"q": query}).encode(),
                         headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=20)
    if r.status != 200:
        raise ToolFailed(f"search failed (HTTP {r.status})")
    results = parse_ddg(r.text())[: max(1, min(int(max_results or 6), 10))]
    if not results:
        return "No results (DuckDuckGo may be rate limiting; try again or rephrase)."
    return "\n\n".join(f"{i}. {x['title']}\n   {x['url']}\n   {x['snippet']}" for i, x in enumerate(results, 1))


def parse_ddg(page: str) -> list[dict[str, str]]:
    out = []
    for block in re.split(r'<div class="result results_links', page)[1:]:
        a = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not a:
            continue
        url = html.unescape(a.group(1))
        if "duckduckgo.com/l/?" in url:
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(url if url.startswith("http") else "https:" + url).query)
            url = q.get("uddg", [url])[0]
        if "duckduckgo.com/y.js" in url:  # ads
            continue
        sn = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.S)
        out.append({"title": html_to_text(a.group(2)), "url": url,
                    "snippet": html_to_text(sn.group(1)) if sn else ""})
    return out


def fetch_url(ctx: ToolContext, url: str, max_chars: int = 8000) -> str:
    try:
        r = netguard.request(url, timeout=20)
    except netguard.BlockedURL as exc:
        raise ToolFailed(f"blocked: {exc}") from None
    ct = r.content_type.lower()
    raw = r.text()
    if "html" in ct or raw.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        title, text = _title(raw), html_to_text(raw)
    elif any(t in ct for t in ("json", "text", "xml", "javascript", "csv")) or not ct:
        title, text = "", raw
    else:
        return f"HTTP {r.status} {r.url}\n[{ct or 'unknown'} content, {len(r.body)} bytes - not text]"
    max_chars = max(500, min(int(max_chars or 8000), 40000))
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n[…{len(text) - max_chars} more chars]"
    return f"HTTP {r.status} {r.url}\n{('Title: ' + title + chr(10)) if title else ''}\n{text}"


# -- memory & skills -------------------------------------------------------------
def _mem(ctx: ToolContext) -> Memory:
    if ctx.memory is None:
        ctx.memory = Memory()
    return ctx.memory


def remember(ctx: ToolContext, fact: str, tags: str = "") -> str:
    r = _mem(ctx).remember(fact, tags)
    return f"{'already known' if r.get('duplicate') else 'remembered'} as #{r['id']}: {r['text']}"


def recall(ctx: ToolContext, query: str = "") -> str:
    facts = _mem(ctx).recall(query, limit=15)
    return "\n".join(f"#{f['id']} {f['text']}" for f in facts) or "nothing matching in memory"


def forget(ctx: ToolContext, id: int) -> str:
    return f"forgot #{id}" if _mem(ctx).forget(int(id)) else f"no memory #{id}"


def load_skill(ctx: ToolContext, name: str) -> str:
    sk = ctx.skills or skills_mod.discover()
    s = sk.get(name) or next((v for k, v in sk.items() if k.lower() == str(name).lower()), None)
    if not s:
        raise ToolFailed(f"no skill '{name}'. Available: {', '.join(sk) or 'none'}")
    return f"# Skill: {s.name}\n{s.body()}"


# -- local apps (official CLI / scripting routes only) ------------------------------
def more_tools(ctx: ToolContext, need: str) -> str:
    """Ask the task planner for the tools of another capability (Word, spreadsheet, data, web, …)."""
    if ctx.expand is None:
        return "All tools are already available."
    added = ctx.expand(str(need or ""))
    return (f"Now available: {', '.join(added)}. Call them directly." if added else
            "No extra tools matched that need. Describe it differently (e.g. 'spreadsheet', 'zip', 'web search', "
            "'run a command'), or continue with the tools you have.")


def routine(ctx: ToolContext, action: str = "list", name: str = "", schedule: str = "", prompt: str = "") -> str:
    """Create, list or remove a scheduled routine (a prompt the agent runs on a schedule)."""
    from automoto import routines as routines_mod

    store = routines_mod.RoutineStore()
    action = (action or "list").strip().lower()
    if action in ("add", "create", "set", "update"):
        if not (name and schedule and prompt):
            raise ToolFailed("add needs name, schedule ('every 1d' or cron '0 8 * * 1-5') and prompt")
        try:
            r = store.add(name, schedule, prompt)
        except routines_mod.ScheduleError as exc:
            raise ToolFailed(f"{exc} - use 'every 30m', 'every 2h', 'every 1d' or a cron like '0 8 * * *' (08:00 daily)") from None
        return (f"routine '{r.name}' saved: {r.schedule} -> {r.prompt[:120]}. It runs while AutoMoto is open "
                "(the app or `automoto serve`); risky steps are skipped unless auto-approved.")
    if action in ("remove", "delete", "stop"):
        return f"removed routine '{name}'" if store.remove(name) else f"no routine named '{name}'"
    rs = store.load()
    return "\n".join(f"- {r.name}: {r.schedule} ({'on' if r.enabled else 'off'}) -> {r.prompt[:100]}"
                     for r in rs.values()) or "no routines yet"


def _apps():
    from automoto import apps

    return apps


def list_apps(ctx: ToolContext, category: str = "") -> str:
    rows = [a for a in _apps().listing() if not category or category.lower() in a["category"]]
    lines = []
    for a in rows:
        mark = "✓" if a["installed"] else "✗"
        how = "cli" if a["cli"] else ("open + script" if a["script"] else "open")
        lines.append(f"{mark} {a['id']} - {a['name']} [{a['category']}; {how}; {a['status']}]"
                     + (f" - {a['note']}" if a["note"] else ""))
    return "\n".join(lines) or "no apps in that category"


def _app_call(fn_name: str) -> Callable[..., str]:
    def fn(ctx: ToolContext, **kw: Any) -> str:
        apps = _apps()
        try:
            return getattr(apps, fn_name)(**kw)
        except apps.AppError as exc:
            raise ToolFailed(str(exc)) from None
    return fn


# -- desktop bridge (v4 actions, now agent tools) ---------------------------------
def _desktop(name: str) -> Callable[..., str]:
    def fn(ctx: ToolContext, **kw: Any) -> str:
        from automoto import desktop

        res = desktop.execute({"tool": name, "args": {k: str(v) for k, v in kw.items()}}, confirmed=True)
        if not res.get("ok"):
            raise ToolFailed(res.get("error", "failed"))
        return str(res.get("result"))
    return fn


CORE: list[Tool] = [
    Tool("list_dir", "List files in a workspace folder.", _obj({"path": {**S, "description": "folder, relative to the workspace"}}), "safe", list_dir),
    Tool("read_file", "Read ANY file: text/code, Word/Excel/PowerPoint/PDF (headings, tables, slides, notes), "
         "JSON/YAML/XML (select='a.b[0]'), zip/tar/7z (lists contents), images (size/EXIF), Parquet/SQLite (profile). "
         "tail=50 = last lines of a log; first/last = PDF page range; sheet = Excel sheet.",
         _obj({"path": S, "max_chars": I, "tail": I, "select": S, "sheet": S, "first": I, "last": I}, ["path"]),
         "safe", read_file),
    Tool("write_file", "Create or overwrite a text file in the workspace (scratch/ needs no approval). Set append=true to append.",
         _obj({"path": S, "content": S, "append": {"type": "boolean"}}, ["path", "content"]), "risky", write_file),
    Tool("edit_file", "Replace an exact text snippet in a file (read_file first; old must match exactly and be unique unless count is set; count=0 replaces all).",
         _obj({"path": S, "old": S, "new": S, "count": I}, ["path", "old", "new"]), "risky", edit_file),
    Tool("search_files", "Search for a regex in a folder (like grep -rn; skips .git, node_modules, secrets) or inside "
         "one big file such as a log or CSV (path = the file; context = lines around each hit).",
         _obj({"pattern": S, "path": S, "glob": {**S, "description": "file name filter, e.g. *.py"}, "max_results": I,
               "context": I}, ["pattern"]),
         "safe", search_files),
    Tool("run_shell", "Run a shell command inside the sandbox workspace (needs approval). Returns exit code and output.",
         _obj({"command": S, "timeout": {**I, "description": "seconds, default 60"}}, ["command"]), "risky", run_shell),
    Tool("web_search", "Search the web (DuckDuckGo). Returns titles, URLs and snippets.", _obj({"query": S, "max_results": I}, ["query"]), "safe", web_search, "web"),
    Tool("fetch_url", "Fetch a public web page or API (GET) and return its text. Private/internal addresses are blocked.",
         _obj({"url": S, "max_chars": I}, ["url"]), "safe", fetch_url, "web"),
    Tool("remember", "Save a fact about the user or their projects to long-term memory.", _obj({"fact": S, "tags": S}, ["fact"]), "safe", remember, "memory"),
    Tool("recall", "Search long-term memory.", _obj({"query": S}), "safe", recall, "memory"),
    Tool("forget", "Delete one memory by id.", _obj({"id": I}, ["id"]), "risky", forget, "memory"),
    Tool("load_skill", "Load the full instructions of a skill by name.", _obj({"name": S}, ["name"]), "safe", load_skill, "skills"),
    Tool("more_tools", "Get the tools for another kind of work if the ones listed aren't enough, e.g. need='spreadsheet', "
         "'slides', 'zip', 'data', 'web search', 'run a command', 'WordPress', 'images', 'video'.",
         _obj({"need": S}, ["need"]), "safe", more_tools, "skills"),
    Tool("routine", "Schedule a prompt to run automatically (daily digest, weekly report, reminder): action='add' with "
         "name, schedule ('every 1d', 'every 2h' or cron '0 8 * * 1-5' = 08:00 on weekdays) and prompt; 'list'; "
         "'remove' name.", _obj({"action": {"type": "string", "enum": ["add", "list", "remove"]}, "name": S,
                                  "schedule": S, "prompt": S}, ["action"]), "risky", routine, "routines"),
]

APPS: list[Tool] = [
    Tool("list_apps", "List local apps AutoMoto can drive (ffmpeg, ImageMagick, LibreOffice, LaTeX, git, VS Code, Photoshop, AutoCAD…) and whether each is installed.",
         _obj({"category": S}), "safe", list_apps, "apps"),
    Tool("run_app", "Run an installed command-line app without a shell, inside the working folder (needs approval). "
         "app = an id from list_apps (e.g. ffmpeg, imagemagick, libreoffice, tectonic, git, vscode); args = list of arguments.",
         _obj({"app_id": S, "args": {"type": "array", "items": S}, "timeout": I}, ["app_id", "args"]), "risky",
         _app_call("run_app"), "apps"),
    Tool("open_in_app", "Open a file in a desktop app such as Photoshop, Illustrator, Premiere Pro, AutoCAD, GIMP, Blender or VS Code (needs approval).",
         _obj({"app_id": S, "path": S}, ["app_id", "path"]), "risky", _app_call("open_in_app"), "apps"),
    Tool("run_app_script", "Run a script file through an app's official scripting route (needs approval): Photoshop/Illustrator .jsx, "
         "AutoCAD .scr (Windows, target=drawing.dwg), Blender .py, GIMP Script-Fu .scm. Write the script with write_file first.",
         _obj({"app_id": S, "script": S, "target": S, "timeout": I}, ["app_id", "script"]), "risky",
         _app_call("run_app_script"), "apps"),
]

DESKTOP: list[Tool] = [
    Tool("system_info", "OS, version and Python runtime of the user's computer.", _obj({}), "safe", _desktop("system_info"), "desktop"),
    Tool("open_url", "Open a web page in the user's browser.", _obj({"url": S}, ["url"]), "risky", _desktop("open_url"), "desktop"),
    Tool("open_app", "Launch an application by name.", _obj({"name": S}, ["name"]), "risky", _desktop("open_app"), "desktop"),
    Tool("type_text", "Type text into the focused window.", _obj({"text": S}, ["text"]), "risky", _desktop("type_text"), "desktop"),
    Tool("hotkey", "Press a key combo such as ctrl+s.", _obj({"keys": S}, ["keys"]), "risky", _desktop("hotkey"), "desktop"),
]


# Tools merged into a broader one in 5.6.0-beta.3. They still run when a model (or an old skill)
# calls them by name, but they are not offered any more, so the model sees a smaller, clearer set.
MERGED = {"office_read": "read_file", "pdf_text": "read_file", "data_read": "read_file", "text_tail": "read_file",
          "image_info": "read_file", "text_search": "search_files", "archive_inspect": "archive_list",
          "office_render": "office_review", "sqlite_query": "data_query"}


def build(*, desktop: bool = False, extra: list[Tool] | None = None, local_apps: bool = True,
          services: bool = True, office: bool = True, files: bool = True) -> dict[str, Tool]:
    tools = list(CORE)
    if local_apps:
        tools += APPS
    if office:
        from automoto import office_tools

        tools += office_tools.TOOLS
    if files:
        from automoto import archive_tools, data_tools, wp_tools

        tools += archive_tools.TOOLS + wp_tools.TOOLS + data_tools.TOOLS
    if services:
        from automoto import services as services_mod

        tools += services_mod.TOOLS
    if desktop and config.desktop_enabled():
        tools += DESKTOP
    tools += extra or []
    from automoto import local_llm

    if local_llm.offline():  # Offline mode: nothing that needs the internet (connectors included)
        tools = [t for t in tools if t.name not in local_llm.ONLINE_TOOLS and not t.name.startswith("mcp__")]
    out = {t.name: t for t in tools}
    for name, into in MERGED.items():
        t = out.get(name)
        if t is not None and into in out and not t.hidden:
            out[name] = Tool(t.name, f"(merged into {into}) {t.description}", t.parameters, t.level, t.fn, t.group, True)
    return out


def offered(tools: dict[str, Tool]) -> dict[str, Tool]:
    """The tools a model may be shown (merged ones excluded)."""
    return {n: t for n, t in tools.items() if not t.hidden}


def text_manifest(tools: dict[str, Tool]) -> str:
    lines = []
    for t in tools.values():
        props = t.parameters.get("properties", {})
        req = set(t.parameters.get("required", []))
        args = ", ".join(f"{k}{'' if k in req else '?'}" for k in props)
        lines.append(f"- {t.name}({args}) [{t.level}]: {t.description}")
    return "\n".join(lines)


# Argument names models often use instead of ours (only applied when unambiguous).
ARG_ALIASES = {
    "path": ("file", "file_path", "filepath", "filename", "file_name", "path_to_file", "document", "doc",
             "input", "input_path", "src", "source", "fname", "pathname"),
    "url": ("link", "href", "uri", "address"),
    "query": ("q", "search", "search_query", "term", "text"),
    "command": ("cmd", "shell", "script"),
}
PATH_ARGS = ("path", "out", "dest", "to_path", "folder")


def _fix_path(raw: Any) -> Any:
    """Common model slips with paths, mapped back into the workspace (never widens access):
    ``/uploads/x`` (leading slash), ``uploads\\x`` (Windows slashes on Linux) and a bare file
    name that only exists in ``uploads/``."""
    if not isinstance(raw, str) or not raw.strip():
        return raw
    p = raw.strip().strip("`'\"")
    try:
        base = sandbox.root().resolve()
    except Exception:
        return raw
    if "\\" in p and "/" not in p and not Path(p).exists():
        p = p.replace("\\", "/")
    pp = Path(p)
    # "/uploads/x" is root-relative (not absolute) on Windows, so check the leading slash too
    rooted = pp.is_absolute() or (p[:1] in ("/", "\\") and not p.startswith("\\\\"))
    if rooted and not pp.parent.exists():
        rel = p.lstrip("/\\")
        for prefix in ("workspace/", "sandbox/", "home/workspace/"):
            if rel.startswith(prefix) and (base / rel[len(prefix):]).parent.exists():
                rel = rel[len(prefix):]
                break
        if rel and (base / rel).parent.exists():
            return rel
    if not rooted and not (base / p).exists() and "/" not in p and (base / "uploads" / p).is_file():
        return f"uploads/{p}"
    return p


def repair_args(tool: Tool, args: Any) -> dict[str, Any]:
    """Make a model's arguments usable: JSON strings, alias names, number strings, path slips."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    if not isinstance(args, dict):
        return {}
    props = tool.parameters.get("properties", {})
    req = tool.parameters.get("required", [])
    out = dict(args)
    for want, aliases in ARG_ALIASES.items():
        if want in props and want not in out:
            found = [a for a in aliases if a in out and a not in props]
            if len(found) == 1:
                out[want] = out.pop(found[0])
    # one required argument and exactly one unknown argument: that must be it
    unknown = [k for k in out if k not in props]
    missing = [k for k in req if k not in out]
    if len(missing) == 1 and len(unknown) == 1 and isinstance(out[unknown[0]], str):
        out[missing[0]] = out.pop(unknown[0])
    for k, v in list(out.items()):
        typ = props.get(k, {}).get("type")
        if typ == "integer" and isinstance(v, str) and v.strip().lstrip("-").isdigit():
            out[k] = int(v.strip())
        elif typ == "boolean" and isinstance(v, str) and v.strip().lower() in ("true", "false"):
            out[k] = v.strip().lower() == "true"
        elif k in PATH_ARGS and typ in (None, "string"):
            out[k] = _fix_path(v)
    return out


def usage(tool: Tool) -> str:
    """A correct-call example for error messages, so the model can fix its own call."""
    props = tool.parameters.get("properties", {})
    req = list(tool.parameters.get("required", []))
    example: dict[str, Any] = {}
    for k in req:
        t = props.get(k, {}).get("type")
        example[k] = ("uploads/file.pptx" if k == "path" else 1 if t == "integer" else {} if t == "object"
                      else [] if t == "array" else True if t == "boolean" else f"<{k}>")
    opt = [k for k in props if k not in req]
    return (f'Correct call: {json.dumps({"name": tool.name, "arguments": example})} - required: '
            f"{', '.join(req) or 'none'}" + (f"; optional: {', '.join(opt)}" if opt else "") +
            ". File paths are relative to the workspace, e.g. uploads/<file name> for uploaded files.")


def call(tool: Tool, ctx: ToolContext, args: dict[str, Any]) -> tuple[bool, str]:
    """Run a tool; never raises. Returns (ok, output)."""
    props = tool.parameters.get("properties", {})
    args = repair_args(tool, args)
    clean = {k: v for k, v in (args or {}).items() if k in props}
    missing = [k for k in tool.parameters.get("required", []) if k not in clean]
    if missing:
        got = ", ".join(sorted(args)) or "none"
        return False, f"missing argument(s): {', '.join(missing)} (you sent: {got})"
    try:
        out = tool.fn(ctx, **clean)
        return True, out if isinstance(out, str) else json.dumps(out, default=str)[:20000]
    except (ToolFailed, sandbox.SandboxError, netguard.BlockedURL, ValueError) as exc:
        return False, str(exc)
    except TypeError as exc:
        return False, f"bad arguments: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"{exc.__class__.__name__}: {exc}"
