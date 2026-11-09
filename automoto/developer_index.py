"""Developer Studio V7: private, bounded, incremental source-symbol indexing.

Read-only: never execute project files, language servers or build tools. Python
uses the standard AST/tokenizer; other languages use clearly marked heuristic
patterns, not a claimed semantic parser or a bundled Tree-sitter grammar.
"""
from __future__ import annotations

import ast
import hashlib
import io
import os
import re
import stat
import threading
import tokenize
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_languages as language, developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/index", tags=["developer-index"])
SCHEMA = "1.0.0"
MAX_FILES = 250
MAX_DIRS = 160
MAX_DIR_ITEMS = 320
MAX_SCAN_DEPTH = 8
MAX_TOTAL_BYTES = 6 * 1024 * 1024
MAX_FILE_BYTES = 96 * 1024
MAX_SYMBOLS = 4000
MAX_TOKENS = 8000
MAX_GLOBAL_SYMBOLS = 5000
MAX_GLOBAL_TOKENS = 20000
MAX_RESULTS = 100
MAX_CACHES = 3
EXCLUDED_DIRS = frozenset({
    "vendor", "target", "coverage", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".gradle", ".terraform", "bower_components",
    "__generated__", "generated", ".turbo", "out", ".venv", "node_modules",
    "dist", "build", ".git", ".next",
})
EXCLUDED_FILES = frozenset({
    ".npmrc", ".pypirc", "id_rsa", "id_ed25519", "credentials",
    "secrets.json", "secrets.yaml", "secrets.yml",
})
EXCLUDED_SUFFIXES = frozenset({
    ".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3", ".db", ".env",
})
CACHE: "OrderedDict[tuple, dict]" = OrderedDict()
LOCK = threading.RLock()

# Anchored and short-line-bounded heuristics; no arbitrary regex from clients.
PATTERNS = {
    "javascript": re.compile(r"^\s*(?:(?:export|default|async)\s+)*(?:function\s*\*?\s*|class\s+|(?:const|let|var)\s+)([A-Za-z_$][\w$]*)"),
    "typescript": re.compile(r"^\s*(?:(?:export|declare|default|abstract|async)\s+)*(?:function\s*\*?\s*|class\s+|interface\s+|type\s+|enum\s+|(?:const|let|var)\s+)([A-Za-z_$][\w$]*)"),
    "rust": re.compile(r"^\s*(?:(?:pub(?:\([^)]{0,50}\))?|async|unsafe)\s+)*(?:fn\s+|struct\s+|enum\s+|trait\s+|mod\s+|type\s+|const\s+)([A-Za-z_]\w*)"),
    "go": re.compile(r"^\s*(?:(?:func\s+(?:\([^)]{0,100}\)\s*)?)|(?:type\s+)|(?:var\s+)|(?:const\s+))([A-Za-z_]\w*)"),
    "java": re.compile(r"^\s*(?:(?:public|private|protected|static|final|abstract|sealed)\s+)*(?:class\s+|interface\s+|enum\s+|record\s+)([A-Za-z_]\w*)"),
    "kotlin": re.compile(r"^\s*(?:(?:public|private|internal|suspend|data|open|sealed)\s+)*(?:class\s+|interface\s+|object\s+|fun\s+|val\s+|var\s+)([A-Za-z_]\w*)"),
    "swift": re.compile(r"^\s*(?:(?:public|private|internal|static|final|open)\s+)*(?:class\s+|struct\s+|enum\s+|protocol\s+|func\s+|let\s+|var\s+)([A-Za-z_]\w*)"),
    "php": re.compile(r"^\s*(?:(?:public|private|protected|static|abstract|final)\s+)*(?:class\s+|interface\s+|trait\s+|function\s+)([A-Za-z_]\w*)"),
    "csharp": re.compile(r"^\s*(?:(?:public|private|protected|internal|static|sealed|partial|abstract)\s+)*(?:class\s+|struct\s+|interface\s+|enum\s+|record\s+)([A-Za-z_]\w*)"),
    "cpp": re.compile(r"^\s*(?:(?:template\s*<[^>]{0,120}>\s*)?)(?:class\s+|struct\s+|enum\s+|namespace\s+)([A-Za-z_]\w*)"),
    "c": re.compile(r"^\s*(?:struct\s+|enum\s+|typedef\s+struct\s+)([A-Za-z_]\w*)"),
    "ruby": re.compile(r"^\s*(?:def\s+|class\s+|module\s+)([A-Za-z_]\w*[?!]?)"),
    "bash": re.compile(r"^\s*(?:function\s+)?([A-Za-z_]\w*)\s*\(\s*\)\s*\{"),
    "css": re.compile(r"^\s*([.#][A-Za-z_][\w-]{0,100})\s*(?:[,:{])"),
}
TOKEN = re.compile(r"(?<![\w$])([A-Za-z_$][\w$]{0,127})(?![\w$])")
HTML_REGION = re.compile(r"<(?P<tag>script|style)\b(?P<attrs>[^>]{0,512})>(?P<body>.*?)</(?P=tag)\s*>",
                         re.IGNORECASE | re.DOTALL)
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.{1,140}?)\s*#*\s*$")


def _utf16_column(line: str, characters: int) -> int:
    """LSP/Monaco columns are UTF-16 code units, not Python codepoints."""
    return len(line[:characters].encode("utf-16-le")) // 2


def _ast_column(line: str, utf8_bytes: int) -> int:
    """Python AST offsets are UTF-8 bytes; convert to Monaco UTF-16."""
    prefix = line.encode("utf-8")[:utf8_bytes].decode("utf-8", errors="ignore")
    return len(prefix.encode("utf-16-le")) // 2


class RootIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)


class SymbolIn(RootIn):
    query: str = Field(default="", max_length=100)
    path: Optional[str] = Field(default=None, max_length=1024)


class ReferenceIn(RootIn):
    identifier: str = Field(min_length=1, max_length=128)
    path: Optional[str] = Field(default=None, max_length=1024)


class OutlineIn(RootIn):
    path: str = Field(min_length=1, max_length=1024)
    text: Optional[str] = Field(default=None, max_length=MAX_FILE_BYTES)


def _excluded(name: str, is_dir: bool = False) -> bool:
    low = name.casefold()
    if studio._forbidden(name) or low in EXCLUDED_FILES:
        return True
    if is_dir and low in EXCLUDED_DIRS:
        return True
    if not is_dir and (Path(low).suffix in EXCLUDED_SUFFIXES or
                       low.startswith((".env", "secret.", "credentials."))):
        return True
    return False


def _walk(root: Path):
    """Yield approved ordinary file paths with deterministic finite traversal."""
    todo = [(root, 0)]
    dirs = files = 0
    incomplete = False
    while todo and dirs < MAX_DIRS and files < MAX_FILES:
        directory, depth = todo.pop(0)
        dirs += 1
        try:
            with os.scandir(directory) as listing:
                items = []
                for entry in listing:
                    if len(items) >= MAX_DIR_ITEMS:
                        incomplete = True
                        break
                    items.append(entry)
            items.sort(key=lambda entry: entry.name.casefold())
        except OSError:
            incomplete = True
            continue
        for entry in items:
            if entry.is_symlink():
                continue
            child = Path(entry.path)
            if getattr(child, "is_junction", lambda: False)():
                continue
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                if _excluded(entry.name, is_dir):
                    continue
                if not is_dir and not entry.is_file(follow_symlinks=False):
                    continue
                relative = child.relative_to(root).as_posix()
                if studio._path(root, relative) != child:
                    continue
                if is_dir:
                    if depth < MAX_SCAN_DEPTH:
                        todo.append((child, depth + 1))
                    else:
                        incomplete = True
                elif files < MAX_FILES:
                    files += 1
                    yield relative, None
                else:
                    incomplete = True
            except (HTTPException, ValueError, OSError):
                continue
    if todo or dirs >= MAX_DIRS or files >= MAX_FILES:
        incomplete = True
    if incomplete:
        yield None, "Project scan was bounded or some directories could not be inspected."


def _source(root: Path, relative: str) -> Optional[tuple[str, str, int]]:
    """Read a bounded regular file from its no-follow descriptor."""
    if any(_excluded(part, idx < len(relative.split("/")) - 1)
           for idx, part in enumerate(relative.split("/"))):
        return None
    path = studio._path(root, relative)
    if path == root:
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_FILE_BYTES:
                return None
            raw = stream.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES or b"\x00" in raw:
            return None
        return raw.decode("utf-8-sig"), hashlib.sha256(raw).hexdigest(), len(raw)
    except (HTTPException, OSError, UnicodeError):
        return None


def _python(text: str):
    """AST definitions plus token references, preserving source locations."""
    symbols, tokens = [], []
    try:
        tree = ast.parse(text)
    except (SyntaxError, RecursionError, ValueError, MemoryError) as exc:
        return [], [], "invalid_syntax", type(exc).__name__
    source_lines = text.splitlines()
    def visit(node, scope=""):
        if len(symbols) >= MAX_SYMBOLS:
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            label = node.name
            symbols.append({"name": label, "qualified_name": scope + label,
                            "kind": kind, "line": node.lineno - 1,
                            "character": _ast_column(source_lines[node.lineno - 1], node.col_offset),
                            "confidence": "syntax"})
            scope += label + "."
        for item in ast.iter_child_nodes(node):
            visit(item, scope)
    try:
        visit(tree)
    except RecursionError:
        return [], [], "invalid_syntax", "RecursionError"
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.NAME:
                tokens.append({"name": token.string, "line": token.start[0] - 1,
                               "character": _utf16_column(source_lines[token.start[0] - 1], token.start[1])})
                if len(tokens) >= MAX_TOKENS:
                    break
    except (tokenize.TokenError, IndentationError):
        pass
    return symbols, tokens, "ast", None


def _heuristic(text: str, lang: str, offset: int = 0):
    """Deterministic best-effort symbols; NEVER claim AST semantics."""
    regex = PATTERNS.get(lang)
    symbols, tokens = [], []
    for row, original in enumerate(text.splitlines()[:4000]):
        line = original[:4096]
        stripped = line.lstrip()
        if lang != "markdown" and stripped.startswith(("//", "/*", "*", "# ", "-- ")):
            continue
        if lang == "markdown":
            found = HEADING.match(line)
            if found:
                symbols.append({"name": found.group(2), "qualified_name": found.group(2),
                                "kind": "heading", "line": offset + row,
                                "character": _utf16_column(line, line.index("#")),
                                "confidence": "heuristic"})
        elif regex:
            found = regex.match(line)
            if found:
                name = found.group(1)
                symbols.append({"name": name, "qualified_name": name, "kind": "declaration",
                                "line": offset + row,
                                "character": _utf16_column(line, found.start(1)),
                                "confidence": "heuristic"})
        for match in TOKEN.finditer(line):
            tokens.append({"name": match.group(1), "line": offset + row,
                           "character": _utf16_column(line, match.start(1))})
            if len(tokens) >= MAX_TOKENS:
                break
        if len(symbols) >= MAX_SYMBOLS or len(tokens) >= MAX_TOKENS:
            break
    return symbols, tokens


def _parse(relative: str, text: str, digest: str) -> dict:
    detected = language._file_language(relative, text[:4096])
    lang = detected["language"]
    symbols, refs, regions = [], [], []
    parser, parse_error = "unavailable", None
    if lang == "python":
        symbols, refs, parser, parse_error = _python(text)
    elif lang == "html":
        parser = "embedded_heuristic"
        for item in list(HTML_REGION.finditer(text))[:16]:
            kind = item.group("tag").lower()
            if kind == "script" and re.search(
                r'\btype\s*=\s*["\'](?:application/json|application/ld\+json)["\']',
                item.group("attrs"), re.I,
            ):
                continue
            begin = text.count("\n", 0, item.start("body"))
            end = text.count("\n", 0, item.end("body"))
            child_lang = "javascript" if kind == "script" else "css"
            s, t = _heuristic(item.group("body")[:16384], child_lang, begin)
            symbols.extend(s)
            refs.extend(t)
            regions.append({"language": child_lang, "start_line": begin, "end_line": end})
    elif lang in PATTERNS or lang == "markdown":
        symbols, refs = _heuristic(text, lang)
        parser = "heuristic"
    return {"path": relative, "sha256": digest, "language": lang,
            "parser": parser, "parse_error": parse_error,
            "symbols": symbols[:MAX_SYMBOLS], "references": refs[:MAX_TOKENS],
            "embedded_regions": regions, "confidence": detected["confidence"]}


def _key(root: Path):
    identity = studio._identity(root)
    return (str(root), identity["device"], identity["inode"])


def _refresh(root: Path) -> dict:
    key = _key(root)
    with LOCK:
        previous = CACHE.get(key, {"files": {}, "generation": 0})
        files = {}
        seen_bytes = 0
        updated = reused = skipped = 0
        symbol_total = token_total = 0
        truncated = False
        for relative, warning in _walk(root):
            if warning:
                truncated = True
                continue
            try:
                source = _source(root, relative)
            except HTTPException:
                continue
            if source is None:
                skipped += 1
                continue
            text, sha, size = source
            if size + seen_bytes > MAX_TOTAL_BYTES:
                truncated = True
                break
            seen_bytes += size
            old = previous["files"].get(relative)
            if old and old["sha256"] == sha and not old.get("budget_truncated"):
                entry = old
                reused += 1
            else:
                entry = _parse(relative, text, sha)
                updated += 1
            remaining_symbols = max(0, MAX_GLOBAL_SYMBOLS - symbol_total)
            remaining_tokens = max(0, MAX_GLOBAL_TOKENS - token_total)
            if len(entry["symbols"]) > remaining_symbols or len(entry["references"]) > remaining_tokens:
                truncated = True
                entry = {**entry, "symbols": entry["symbols"][:remaining_symbols],
                         "references": entry["references"][:remaining_tokens],
                         "budget_truncated": True}
            files[relative] = entry
            symbol_total += len(entry["symbols"])
            token_total += len(entry["references"])
        # Never present an incomplete scan as a full, authoritative index.
        removed = len(set(previous["files"]) - set(files))
        generation = previous["generation"] + int(bool(updated or removed or truncated != previous.get("truncated")))
        state = {"root": str(root), "files": files, "generation": generation,
                 "truncated": truncated, "inspected_bytes": seen_bytes}
        CACHE[key] = state
        CACHE.move_to_end(key)
        while len(CACHE) > MAX_CACHES:
            CACHE.popitem(last=False)
        return {"schema_version": SCHEMA, "generation": generation,
                "indexed_files": len(files), "reparsed_files": updated,
                "reused_files": reused, "removed_files": removed, "skipped_files": skipped,
                "inspected_bytes": seen_bytes, "truncated": truncated,
                "symbol_count": symbol_total, "token_count": token_total,
                "source_modified": False, "source_executed": False,
                "index_persisted": False}


def _state(root: Path):
    _refresh(root)  # rehash every bounded source so edits and deletions cannot be stale
    return CACHE[_key(root)]


@router.post("/refresh")
def refresh(request: Request, body: RootIn):
    studio._auth(request)
    root = studio._project(body.project)
    return _refresh(root)


@router.post("/symbols")
def symbols(request: Request, body: SymbolIn):
    studio._auth(request)
    root = studio._project(body.project)
    if body.path is not None:
        studio._path(root, body.path)
    state = _state(root)
    needle = body.query.casefold()
    items = []
    for path, file in state["files"].items():
        if body.path is not None and path != body.path:
            continue
        for item in file["symbols"]:
            if needle not in item["name"].casefold():
                continue
            items.append({"path": path, "language": file["language"],
                          "parser": file["parser"], **item})
            if len(items) >= MAX_RESULTS:
                break
        if len(items) >= MAX_RESULTS:
            break
    return {"items": items, "truncated": len(items) >= MAX_RESULTS or state["truncated"],
            "generation": state["generation"], "source_modified": False}


@router.post("/references")
def references(request: Request, body: ReferenceIn):
    studio._auth(request)
    root = studio._project(body.project)
    if body.path is not None:
        studio._path(root, body.path)
    if not body.identifier.isidentifier() and not re.fullmatch(r"[A-Za-z_$][\w$]{0,127}", body.identifier):
        raise HTTPException(422, "Enter a source identifier, not a search expression.")
    state = _state(root)
    matches = []
    for path, file in state["files"].items():
        if body.path is not None and path != body.path:
            continue
        for token in file["references"]:
            if token["name"] == body.identifier:
                matches.append({"path": path, "line": token["line"],
                                "character": token["character"],
                                "confidence": "lexical", "parser": file["parser"]})
                if len(matches) >= MAX_RESULTS:
                    break
        if len(matches) >= MAX_RESULTS:
            break
    return {"identifier": body.identifier, "items": matches,
            "truncated": len(matches) >= MAX_RESULTS or state["truncated"],
            "meaning": "lexical occurrences, not cross-module semantic references",
            "generation": state["generation"], "source_modified": False}


@router.post("/outline")
def outline(request: Request, body: OutlineIn):
    studio._auth(request)
    root = studio._project(body.project)
    candidate = studio._path(root, body.path)
    if candidate == root or _excluded(candidate.name) or not candidate.is_file():
        raise HTTPException(404, "Choose an existing non-restricted source file.")
    if body.text is not None:
        if len(body.text.encode("utf-8")) > MAX_FILE_BYTES:
            raise HTTPException(413, "Editor source exceeds indexing limit.")
        # Unsaved editor content is private, in memory only, never saved by V7.
        parsed = _parse(body.path, body.text, hashlib.sha256(body.text.encode()).hexdigest())
        return {"path": body.path, "parser": parsed["parser"],
                "parse_error": parsed["parse_error"], "symbols": parsed["symbols"][:MAX_RESULTS],
                "embedded_regions": parsed["embedded_regions"],
                "unsaved_copy": True, "source_modified": False}
    source = _source(root, body.path)
    if source is None:
        raise HTTPException(415, "Cannot index this restricted, large or non-UTF-8 file.")
    text, sha, _ = source
    parsed = _parse(body.path, text, sha)
    return {"path": body.path, "parser": parsed["parser"],
            "parse_error": parsed["parse_error"], "symbols": parsed["symbols"][:MAX_RESULTS],
            "embedded_regions": parsed["embedded_regions"],
            "unsaved_copy": False, "source_modified": False}
