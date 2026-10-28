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

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}


@dataclass
class ToolContext:
    memory: Memory | None = None
    skills: dict[str, skills_mod.Skill] = field(default_factory=dict)


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
def read_file(ctx: ToolContext, path: str, max_chars: int = 12000) -> str:
    p = sandbox.resolve(path)
    if not p.is_file():
        raise ToolFailed(f"no such file: {sandbox.rel(p)}")
    data = p.read_bytes()
    if b"\x00" in data[:4096]:
        raise ToolFailed("binary file - not shown")
    text = data.decode("utf-8", errors="replace")
    max_chars = max(200, min(int(max_chars or 12000), 60000))
    return text if len(text) <= max_chars else text[:max_chars] + f"\n[…{len(text) - max_chars} more chars]"


def write_file(ctx: ToolContext, path: str, content: str, append: bool = False) -> str:
    p = sandbox.resolve(path)
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


def list_dir(ctx: ToolContext, path: str = ".") -> str:
    p = sandbox.resolve(path)
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
    Tool("read_file", "Read a text file from the workspace.", _obj({"path": S, "max_chars": I}, ["path"]), "safe", read_file),
    Tool("write_file", "Create or overwrite a text file in the workspace (scratch/ needs no approval). Set append=true to append.",
         _obj({"path": S, "content": S, "append": {"type": "boolean"}}, ["path", "content"]), "risky", write_file),
    Tool("run_shell", "Run a shell command inside the sandbox workspace (needs approval). Returns exit code and output.",
         _obj({"command": S, "timeout": {**I, "description": "seconds, default 60"}}, ["command"]), "risky", run_shell),
    Tool("web_search", "Search the web (DuckDuckGo). Returns titles, URLs and snippets.", _obj({"query": S, "max_results": I}, ["query"]), "safe", web_search, "web"),
    Tool("fetch_url", "Fetch a public web page or API (GET) and return its text. Private/internal addresses are blocked.",
         _obj({"url": S, "max_chars": I}, ["url"]), "safe", fetch_url, "web"),
    Tool("remember", "Save a fact about the user or their projects to long-term memory.", _obj({"fact": S, "tags": S}, ["fact"]), "safe", remember, "memory"),
    Tool("recall", "Search long-term memory.", _obj({"query": S}), "safe", recall, "memory"),
    Tool("forget", "Delete one memory by id.", _obj({"id": I}, ["id"]), "risky", forget, "memory"),
    Tool("load_skill", "Load the full instructions of a skill by name.", _obj({"name": S}, ["name"]), "safe", load_skill, "skills"),
]

DESKTOP: list[Tool] = [
    Tool("system_info", "OS, version and Python runtime of the user's computer.", _obj({}), "safe", _desktop("system_info"), "desktop"),
    Tool("open_url", "Open a web page in the user's browser.", _obj({"url": S}, ["url"]), "risky", _desktop("open_url"), "desktop"),
    Tool("open_app", "Launch an application by name.", _obj({"name": S}, ["name"]), "risky", _desktop("open_app"), "desktop"),
    Tool("type_text", "Type text into the focused window.", _obj({"text": S}, ["text"]), "risky", _desktop("type_text"), "desktop"),
    Tool("hotkey", "Press a key combo such as ctrl+s.", _obj({"keys": S}, ["keys"]), "risky", _desktop("hotkey"), "desktop"),
]


def build(*, desktop: bool = False, extra: list[Tool] | None = None) -> dict[str, Tool]:
    tools = list(CORE)
    if desktop and config.desktop_enabled():
        tools += DESKTOP
    tools += extra or []
    return {t.name: t for t in tools}


def text_manifest(tools: dict[str, Tool]) -> str:
    lines = []
    for t in tools.values():
        props = t.parameters.get("properties", {})
        req = set(t.parameters.get("required", []))
        args = ", ".join(f"{k}{'' if k in req else '?'}" for k in props)
        lines.append(f"- {t.name}({args}) [{t.level}]: {t.description}")
    return "\n".join(lines)


def call(tool: Tool, ctx: ToolContext, args: dict[str, Any]) -> tuple[bool, str]:
    """Run a tool; never raises. Returns (ok, output)."""
    props = tool.parameters.get("properties", {})
    clean = {k: v for k, v in (args or {}).items() if k in props}
    missing = [k for k in tool.parameters.get("required", []) if k not in clean]
    if missing:
        return False, f"missing argument(s): {', '.join(missing)}"
    try:
        out = tool.fn(ctx, **clean)
        return True, out if isinstance(out, str) else json.dumps(out, default=str)[:20000]
    except (ToolFailed, sandbox.SandboxError, netguard.BlockedURL, ValueError) as exc:
        return False, str(exc)
    except TypeError as exc:
        return False, f"bad arguments: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"{exc.__class__.__name__}: {exc}"
