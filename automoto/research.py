"""Research library, public developer sources and static project inspection.

Folded in from the "Engineering Studio" overlay (reviewed: see docs/CAPABILITIES.md and the
CHANGELOG). Everything runs through the ONE chat: the planner offers these tools when a task needs
them. Rules kept from the review:

* every public fetch goes through ``netguard`` (SSRF guard, pinned DNS, size/time limits);
* local files go through ``sandbox.resolve`` and the approval policy (outside the workspace = ask);
* nothing here executes code, installs anything or changes source files;
* fetched text is untrusted data (the loop fences it), never instructions.

The library is a small SQLite full-text index in the user's own workspace (``memory/library.sqlite3``),
so in hosted mode every user has their own.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import sqlite3
import time
import zipfile
import zlib
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urldefrag, urlencode, urljoin, urlsplit

from automoto import netguard, sandbox
from automoto.tools import Tool, ToolContext, ToolFailed, _title, html_to_text

MAX_TEXT = 160_000
MAX_FILE = 6_000_000
S = {"type": "string"}
I = {"type": "integer"}


# ---------------------------------------------------------------------------
# Library (FTS5) in memory/library.sqlite3
# ---------------------------------------------------------------------------
def library_path() -> Path:
    from automoto import layout

    return layout.folder("memory") / "library.sqlite3"


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(library_path(), timeout=10)
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS documents (
      id INTEGER PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL, kind TEXT NOT NULL,
      library TEXT NOT NULL DEFAULT '', version TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL,
      body TEXT NOT NULL, added TEXT NOT NULL, UNIQUE(source, kind, library, version));
    CREATE VIRTUAL TABLE IF NOT EXISTS doc_fts USING fts5(title, body, content='documents', content_rowid='id');
    CREATE TRIGGER IF NOT EXISTS doc_ai AFTER INSERT ON documents BEGIN
      INSERT INTO doc_fts(rowid,title,body) VALUES(new.id,new.title,new.body); END;
    CREATE TRIGGER IF NOT EXISTS doc_ad AFTER DELETE ON documents BEGIN
      INSERT INTO doc_fts(doc_fts,rowid,title,body) VALUES('delete',old.id,old.title,old.body); END;
    CREATE TRIGGER IF NOT EXISTS doc_au AFTER UPDATE ON documents BEGIN
      INSERT INTO doc_fts(doc_fts,rowid,title,body) VALUES('delete',old.id,old.title,old.body);
      INSERT INTO doc_fts(rowid,title,body) VALUES(new.id,new.title,new.body); END;""")
    return db


def store(source: str, title: str, body: str, kind: str = "research", library: str = "", version: str = "") -> dict:
    body = (body or "")[:MAX_TEXT]
    if not body.strip():
        raise ToolFailed("nothing readable to save")
    source, title, library, version = source[:1000], (title or source)[:300], library[:100], version[:80]
    digest = hashlib.sha256(body.encode()).hexdigest()
    with closing(_db()) as db, db:
        db.execute("""INSERT INTO documents(source,title,kind,library,version,sha256,body,added) VALUES(?,?,?,?,?,?,?,?)
                      ON CONFLICT(source,kind,library,version) DO UPDATE SET title=excluded.title,
                      sha256=excluded.sha256, body=excluded.body, added=excluded.added""",
                   (source, title, kind, library, version, digest, body, datetime.now(timezone.utc).isoformat()))
        row = db.execute("SELECT id FROM documents WHERE source=? AND kind=? AND library=? AND version=?",
                         (source, kind, library, version)).fetchone()
    return {"id": row["id"], "source": source, "title": title, "kind": kind, "library": library,
            "version": version, "characters": len(body)}


def search(query: str, limit: int = 7, library: str = "", version: str = "") -> list[dict]:
    words = re.findall(r"[\w-]+", query or "", flags=re.UNICODE)[:9]
    if not words:
        raise ToolFailed("give a word or phrase to search for")
    match = " OR ".join('"' + w.replace('"', "") + '"' for w in words)  # quoted: FTS operators can't be injected
    sql = ("SELECT d.id,d.source,d.title,d.kind,d.library,d.version,d.added,"
           "snippet(doc_fts,1,'[',']',' … ',24) AS excerpt FROM doc_fts JOIN documents d ON d.id=doc_fts.rowid "
           "WHERE doc_fts MATCH ?")
    args: list = [match]
    if library:
        sql += " AND d.library=?"
        args.append(library)
    if version:
        sql += " AND d.version=?"
        args.append(version)
    sql += " ORDER BY bm25(doc_fts) LIMIT ?"
    args.append(max(1, min(int(limit), 20)))
    with closing(_db()) as db:
        return [dict(r) for r in db.execute(sql, args).fetchall()]


def documents(limit: int = 200) -> list[dict]:
    with closing(_db()) as db:
        return [dict(r) for r in db.execute(
            "SELECT id,source,title,kind,library,version,added,length(body) AS characters FROM documents "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


def delete(doc_id: int) -> bool:
    with closing(_db()) as db, db:
        return db.execute("DELETE FROM documents WHERE id=?", (int(doc_id),)).rowcount > 0


# ---------------------------------------------------------------------------
# Public fetching (always via netguard)
# ---------------------------------------------------------------------------
def _links(raw: str, base: str) -> list[str]:
    out: list[str] = []
    for href in re.findall(r'(?i)<a\s[^>]*href=["\']([^"\']+)["\']', raw)[:200]:
        u = urldefrag(urljoin(base, href)).url
        if urlsplit(u).scheme in ("http", "https") and u not in out:
            out.append(u[:500])
    return out[:40]


def fetch_public(url: str) -> dict:
    try:
        r = netguard.request(url, timeout=15, total_timeout=50, max_bytes=1_500_000)
    except (netguard.BlockedURL, OSError, TimeoutError) as exc:
        raise ToolFailed(f"couldn't fetch the page: {exc}") from None
    if r.status != 200:
        raise ToolFailed(f"the page answered HTTP {r.status}")
    typ = r.content_type.split(";", 1)[0].lower().strip()
    raw = r.text()
    if "html" in typ or raw.lstrip()[:15].lower().startswith("<!doctype html"):
        title, body, links = _title(raw), html_to_text(raw), _links(raw, r.url)
    elif typ.startswith("text/") or typ in ("application/json", "application/xml", "application/rss+xml",
                                              "application/atom+xml"):
        title, body, links = "", raw, []
    else:
        raise ToolFailed(f"unsupported content type: {typ or 'unknown'}")
    if not body.strip():
        raise ToolFailed("no readable text on that page")
    return {"source": r.url, "title": title or r.url, "body": body[:MAX_TEXT], "links": links}


def crawl_docs(url: str, library: str, version: str, max_pages: int = 4) -> dict:
    """A few same-origin documentation pages, respecting robots.txt; every request re-checked by netguard."""
    from urllib.robotparser import RobotFileParser

    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ToolFailed("give a public http(s) documentation URL")
    origin = f"{parts.scheme}://{parts.netloc.lower()}"
    try:
        robots = netguard.request(origin + "/robots.txt", timeout=12, total_timeout=25, max_bytes=250_000)
    except (netguard.BlockedURL, OSError, TimeoutError) as exc:
        raise ToolFailed(f"couldn't check robots.txt: {exc}") from None
    rule = None
    if robots.status == 200:
        rule = RobotFileParser()
        rule.parse(robots.text().splitlines())
    elif robots.status in (401, 403):
        raise ToolFailed("that site doesn't allow automated reading")
    todo, seen, saved, errors = [urldefrag(url).url], set(), [], []
    max_pages = max(1, min(int(max_pages), 8))
    while todo and len(saved) < max_pages and len(seen) < 60:
        cur = todo.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        cp = urlsplit(cur)
        if f"{cp.scheme}://{cp.netloc.lower()}" != origin or cp.username or cp.password:
            continue
        if rule and not rule.can_fetch("AutoMotoAI", cur):
            errors.append({"url": cur, "reason": "disallowed by robots.txt"})
            continue
        try:
            page = fetch_public(cur)
            fp = urlsplit(page["source"])
            if f"{fp.scheme}://{fp.netloc.lower()}" != origin:
                raise ToolFailed("redirected to another site")
            saved.append(store(page["source"], page["title"], page["body"], "documentation", library, version))
            todo += [x for x in page["links"] if x.startswith(origin) and x not in seen and x not in todo][:25]
        except ToolFailed as exc:
            errors.append({"url": cur, "reason": str(exc)[:180]})
        if todo and len(saved) < max_pages:
            time.sleep(0.25)
    return {"saved": saved, "errors": errors[:20]}


def import_file(path: str) -> dict:
    p = sandbox.resolve(path, allow_outside=True)  # policy already asked if this is outside the workspace
    if not p.is_file():
        raise ToolFailed(f"no such file: {path}")
    if p.stat().st_size > MAX_FILE:
        raise ToolFailed("file is over 6 MB")
    ext = p.suffix.lower()
    if ext in (".srt", ".vtt"):
        text = p.read_text(encoding="utf-8", errors="replace")
        body = "\n".join(ln for ln in text.splitlines() if ln.strip() and ln.strip() != "WEBVTT" and "-->" not in ln
                         and not re.match(r"^\s*\d+\s*$", ln) and not ln.startswith(("NOTE ", "STYLE", "REGION")))
    else:
        from automoto.tools import read_file  # one reader for every format (Office, PDF, text, data…)

        body = read_file(ToolContext(), str(path), max_chars=MAX_TEXT)
    return {"source": "file:" + sandbox.rel(p), "title": p.name, "body": body, "links": []}


def summarise(text: str, max_sentences: int = 5) -> str:
    """Extractive summary: only sentences that are really in the source."""
    stop = set("the a an is are of in to and or for with on by from this that it as at be can will".split())
    pieces = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 32]
    if not pieces:
        return text[:800]
    freq = Counter(w for w in re.findall(r"\b[\w-]{3,}\b", text.lower()) if w not in stop)
    ranked = []
    for i, s in enumerate(pieces[:500]):
        toks = set(re.findall(r"\b[\w-]{3,}\b", s.lower()))
        ranked.append((sum(freq.get(w, 0) for w in toks) / math.sqrt(max(1, len(toks))), i, s))
    chosen = sorted(sorted(ranked, reverse=True)[:max(1, min(max_sentences, 10))], key=lambda z: z[1])
    return " ".join(r[2][:450] for r in chosen)


# ---------------------------------------------------------------------------
# Public developer sources (read-only official APIs)
# ---------------------------------------------------------------------------
PROVIDERS = {"github": "public repositories (GitHub API)", "stackoverflow": "questions (Stack Exchange API)",
             "hackernews": "discussions (HN Algolia)", "bluesky": "public posts (Bluesky AppView)"}


def _json(url: str) -> dict:
    try:
        r = netguard.request(url, timeout=15, total_timeout=35, max_bytes=1_200_000)
    except (netguard.BlockedURL, OSError, TimeoutError) as exc:
        raise ToolFailed(f"request failed: {str(exc)[:200]}") from None
    if r.status != 200:
        raise ToolFailed(f"the source answered HTTP {r.status}" + (" (rate limit)" if r.status in (403, 429) else ""))
    raw = r.body
    if raw[:2] == b"\x1f\x8b":  # gzip, bounded
        d = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
        raw = d.decompress(raw, 5_000_001)
        if len(raw) > 5_000_000 or not d.eof:
            raise ToolFailed("compressed answer too big")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ToolFailed(f"bad answer: {exc}") from None


def discover_search(source: str, query: str, limit: int = 8) -> dict:
    source, query, limit = source.strip().lower(), query.strip(), max(1, min(int(limit), 20))
    if source not in PROVIDERS:
        raise ToolFailed("source must be one of: " + ", ".join(PROVIDERS))
    if not query or len(query) > 250:
        raise ToolFailed("give a search phrase (1-250 characters)")
    rows: list[dict] = []
    if source == "github":
        for x in _json("https://api.github.com/search/repositories?" + urlencode({"q": query, "per_page": limit})).get("items", [])[:limit]:
            rows.append({"title": x.get("full_name", ""), "url": x.get("html_url", ""), "about": x.get("description") or "",
                         "stars": x.get("stargazers_count", 0), "language": x.get("language"), "updated": x.get("updated_at", "")})
    elif source == "stackoverflow":
        from html import unescape

        data = _json("https://api.stackexchange.com/2.3/search/advanced?" + urlencode(
            {"site": "stackoverflow", "q": query, "sort": "relevance", "order": "desc", "pagesize": limit}))
        for x in data.get("items", [])[:limit]:
            rows.append({"title": unescape(x.get("title", "")), "url": x.get("link", ""), "score": x.get("score"),
                         "answered": x.get("is_answered"), "tags": x.get("tags", [])[:8]})
    elif source == "hackernews":
        for x in _json("https://hn.algolia.com/api/v1/search?" + urlencode({"query": query, "hitsPerPage": limit})).get("hits", [])[:limit]:
            rows.append({"title": x.get("title") or x.get("story_title") or "", "points": x.get("points"),
                         "url": x.get("url") or f"https://news.ycombinator.com/item?id={x.get('objectID', '')}"})
    else:
        data = _json("https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?" + urlencode({"q": query, "limit": limit}))
        for x in data.get("posts", [])[:limit]:
            rec, author = x.get("record") or {}, x.get("author") or {}
            pid, handle = (x.get("uri") or "").rsplit("/", 1)[-1], author.get("handle", "")
            rows.append({"text": (rec.get("text") or "")[:500], "author": handle, "date": rec.get("createdAt", ""),
                         "url": f"https://bsky.app/profile/{handle}/post/{pid}" if handle and pid else ""})
    return {"source": source, "query": query, "results": rows}


def read_feed(url: str, limit: int = 15) -> dict:
    from defusedxml import ElementTree as ET

    try:
        r = netguard.request(url, max_bytes=1_000_000, total_timeout=40)
        if r.status != 200:
            raise ToolFailed(f"feed answered HTTP {r.status}")
        root = ET.fromstring(r.body)
    except (netguard.BlockedURL, OSError, ValueError, ET.ParseError) as exc:
        raise ToolFailed(f"couldn't read the feed: {exc}") from None
    atom = "{http://www.w3.org/2005/Atom}"
    out = []
    for item in root.findall(".//item") + root.findall(f".//{atom}entry"):
        def first(*paths):
            for path in paths:
                el = item.find(path)
                if el is not None:
                    return (el.text or el.attrib.get("href") or "").strip()[:800]
            return ""
        out.append({"title": first("title", f"{atom}title"), "url": first("link", f"{atom}link"),
                    "date": first("pubDate", f"{atom}updated")})
        if len(out) >= max(1, min(int(limit), 50)):
            break
    return {"feed": url, "items": out}


# ---------------------------------------------------------------------------
# Static project / file inspection (never runs anything)
# ---------------------------------------------------------------------------
SKIP = {".git", ".venv", "venv", "node_modules", "dist", "build", "target", "__pycache__", ".next", ".cache", "coverage"}
TEXT_EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss", ".vue", ".svelte", ".php", ".json", ".toml",
             ".yaml", ".yml", ".md", ".xml", ".go", ".rs", ".java", ".kt"}
MANIFESTS = {"pyproject.toml", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "requirements.txt",
             "poetry.lock", "Cargo.toml", "go.mod", "composer.json", "Gemfile", "Dockerfile", "docker-compose.yml",
             "compose.yaml"}
CHECKS = [("tls-verification-off", r"\bverify\s*=\s*False\b|rejectUnauthorized\s*:\s*false", "TLS checks may be switched off"),
          ("dynamic-code", r"\beval\s*\(|\bexec\s*\(", "dynamic code execution: review by hand"),
          ("shell", r"\b(?:os\.system|subprocess\.Popen|child_process\.exec)\s*\(", "runs shell commands"),
          ("html-injection", r"\binnerHTML\s*=", "HTML insertion: check the input is cleaned"),
          ("debug-mode", r"\bDEBUG\s*=\s*True\b|WP_DEBUG'?\s*,\s*true", "debug mode on")]


def inspect_file(p: Path) -> dict:
    if p.stat().st_size > 25_000_000:
        raise ToolFailed("file is over 25 MB")
    raw = p.read_bytes()
    magic = ("ELF" if raw.startswith(b"\x7fELF") else "Windows program (PE)" if raw.startswith(b"MZ") else
             "ZIP-based" if raw.startswith(b"PK\x03\x04") else
             "Mach-O" if raw[:4] in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe") else
             "text" if b"\x00" not in raw[:4096] else "binary")
    rep: dict = {"file": sandbox.rel(p), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "format": magic,
                 "executed": False, "findings": []}
    ext = p.suffix.lower()
    if magic == "text" and ext in TEXT_EXTS:
        text = raw.decode("utf-8", errors="replace")
        rep["lines"] = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        if ext == ".py":
            try:
                tree = ast.parse(text)
                rep["symbols"] = [{"name": n.name, "kind": type(n).__name__, "line": n.lineno} for n in ast.walk(tree)
                                  if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))][:100]
                rep["imports"] = sorted({a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
                                        | {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)})[:100]
            except SyntaxError as exc:
                rep["findings"].append({"indicator": "syntax-error", "line": exc.lineno})
        for label, rx, why in CHECKS:
            for m in list(re.finditer(rx, text, re.I))[:5]:
                rep["findings"].append({"indicator": label, "line": text.count("\n", 0, m.start()) + 1, "why": why})
    if zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as z:
            es = z.infolist()
            rep["archive"] = {"entries": len(es), "unpacked_bytes": sum(e.file_size for e in es),
                              "unsafe_names": [e.filename for e in es if e.filename.startswith(("/", "\\")) or ".." in Path(e.filename).parts][:20],
                              "zip_bomb_like": [e.filename for e in es if e.compress_size and e.file_size / e.compress_size > 500][:20]}
    rep["note"] = "Static look only. Matches are things to review, not proven bugs."
    return rep


def inspect_tree(base: Path, max_files: int = 600, selector: str = "") -> dict:
    counts: Counter = Counter()
    manifests, findings, matches = [], [], []
    tokens = [t for t in re.findall(r"[.#]([\w-]+)", selector or "") if len(t) >= 2][:4] or (
        [selector.split(":", 1)[0].strip()] if selector and selector.strip() not in ("*", "body", "html") else [])
    checked, truncated = 0, False
    for folder, dirs, files in os.walk(base, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith(".") and not (Path(folder) / d).is_symlink())
        for name in sorted(files):
            p = Path(folder) / name
            if p.is_symlink() or sandbox.sensitive(p.resolve()):
                continue
            if checked >= max_files:
                truncated = True
                break
            checked += 1
            ext = p.suffix.lower() or "(none)"
            counts[ext] += 1
            rel = p.relative_to(base).as_posix()
            if name in MANIFESTS or rel.startswith(".github/workflows/"):
                manifests.append(rel)
            try:
                if ext in TEXT_EXTS and p.stat().st_size <= 300_000:
                    text = p.read_text(encoding="utf-8", errors="replace")
                    if len(findings) < 60:
                        for label, rx, why in CHECKS:
                            m = re.search(rx, text, re.I)
                            if m:
                                findings.append({"path": rel, "line": text.count("\n", 0, m.start()) + 1,
                                                 "indicator": label, "why": why})
                    if tokens and len(matches) < 40:
                        for i, line in enumerate(text.splitlines(), 1):
                            if any(t.lower() in line.lower() for t in tokens):
                                matches.append({"path": rel, "line": i, "text": line.strip()[:200]})
                                if len(matches) >= 40:
                                    break
            except OSError:
                continue
        if truncated:
            break
    out = {"folder": sandbox.rel(base), "files": checked, "truncated": truncated,
           "kinds": dict(counts.most_common(20)), "manifests": sorted(set(manifests))[:100],
           "findings": findings[:60], "executed": False,
           "note": "Static look only: nothing was run, built or installed. Findings are things to review."}
    if tokens:
        out["selector"] = selector
        out["where_it_appears"] = matches
    return out


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
def library_add(ctx: ToolContext, url: str = "", path: str = "", library: str = "", version: str = "",
                pages: int = 1) -> str:
    """Save a web page, a few docs pages, or a workspace file to the private library."""
    if bool(url) == bool(path):
        raise ToolFailed("give either url= (a public page) or path= (a file in your workspace)")
    if path:
        d = import_file(path)
        return json.dumps(store(d["source"], d["title"], d["body"], "file"))
    if int(pages or 1) > 1:
        if not (library and version):
            raise ToolFailed("to save several docs pages, also give library= and version= (e.g. react, 19)")
        return json.dumps(crawl_docs(url, library, version, int(pages)), ensure_ascii=False)
    d = fetch_public(url)
    kind = "documentation" if library else "research"
    rec = store(d["source"], d["title"], d["body"], kind, library, version)
    return json.dumps({**rec, "summary": summarise(d["body"], 4)}, ensure_ascii=False)


def library_search(ctx: ToolContext, query: str, library: str = "", version: str = "", limit: int = 7) -> str:
    rows = search(query, limit, library, version)
    return json.dumps({"results": rows} if rows else {"results": [], "note": "nothing saved matches; try web_search"},
                      ensure_ascii=False)


def discover(ctx: ToolContext, source: str, query: str, limit: int = 8) -> str:
    return json.dumps(discover_search(source, query, limit), ensure_ascii=False)


def feed(ctx: ToolContext, url: str, limit: int = 15) -> str:
    return json.dumps(read_feed(url, limit), ensure_ascii=False)


def project_inspect(ctx: ToolContext, path: str = ".", selector: str = "") -> str:
    p = sandbox.resolve(path or ".", allow_outside=True)
    if p.is_file():
        return json.dumps(inspect_file(p), ensure_ascii=False)
    if not p.is_dir():
        raise ToolFailed(f"no such file or folder: {path}")
    return json.dumps(inspect_tree(p, selector=selector), ensure_ascii=False)


TOOLS = [
    Tool("library_add", "Save a public web page (url=), several pages of versioned docs (url=, library=, version=, "
         "pages=2-8) or a workspace file (path=) to the user's private searchable library.",
         {"type": "object", "properties": {"url": S, "path": S, "library": S, "version": S, "pages": I}},
         "safe", library_add, "web"),
    Tool("library_search", "Search the user's saved library (pages, docs, files). Results keep their source links.",
         {"type": "object", "properties": {"query": S, "library": S, "version": S, "limit": I}, "required": ["query"]},
         "safe", library_search, "web"),
    Tool("discover", "Search public developer sources: source=github (repos), stackoverflow (questions), "
         "hackernews (discussions) or bluesky (posts). Read-only.",
         {"type": "object", "properties": {"source": S, "query": S, "limit": I}, "required": ["source", "query"]},
         "safe", discover, "web"),
    Tool("read_feed", "Read the latest items from a public RSS or Atom feed URL.",
         {"type": "object", "properties": {"url": S, "limit": I}, "required": ["url"]}, "safe", feed, "web"),
    Tool("project_inspect", "Look at a project folder or one file WITHOUT running it: file kinds, manifests, "
         "risky patterns (eval, shell, TLS off, debug), Python symbols/imports, archive safety, or where a CSS "
         "selector appears (selector='.hero').",
         {"type": "object", "properties": {"path": S, "selector": S}}, "safe", project_inspect, "code"),
]
