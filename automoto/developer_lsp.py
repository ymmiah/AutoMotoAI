"""Developer Studio V6: explicit, local-only, bounded Language Server Protocol bridge.

Server binaries are allowlisted by language and NEVER launched until a trusted
workspace owner explicitly confirms startup. LSP servers are third-party code:
project trust and protocol validation are not an OS-level process sandbox.
"""
from __future__ import annotations

import json
import os
import queue
import secrets
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlparse
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_studio as studio
from automoto import developer_languages as languages

router = APIRouter(prefix="/api/developer/studio/lsp", tags=["developer-lsp"])
MAX_WIRE = 512 * 1024
MAX_SOURCE = 128 * 1024
MAX_HEADER = 4096
MAX_SESSIONS = 2
IDLE_SECONDS = 300
REQUEST_TIMEOUT = 8.0
# Explicit fixed command arguments only; never accept an executable or argv from a project.
SERVER_COMMANDS = {
    "python": ("pyright-langserver", "--stdio"),
    "typescript": ("typescript-language-server", "--stdio"),
    "javascript": ("typescript-language-server", "--stdio"),
    "rust": ("rust-analyzer",),
    "go": ("gopls", "serve"),
    "latex": ("texlab",),
    "c": ("clangd", "--background-index=false", "--clang-tidy=false"),
    "cpp": ("clangd", "--background-index=false", "--clang-tidy=false"),
}
METHODS = frozenset({
    "textDocument/hover", "textDocument/completion",
    "textDocument/definition", "textDocument/references",
    "textDocument/rename",
})
SESSIONS: dict[str, "LspSession"] = {}
LOCK = threading.RLock()


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    language: str = Field(min_length=1, max_length=40)
    confirmed: Literal[True]


class SessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=32, max_length=64)
    project: str = Field(min_length=1, max_length=1024)


class DocumentIn(SessionIn):
    path: str = Field(min_length=1, max_length=1024)
    text: Optional[str] = Field(default=None, max_length=MAX_SOURCE)


class QueryIn(DocumentIn):
    method: Literal[
        "textDocument/hover", "textDocument/completion",
        "textDocument/definition", "textDocument/references",
        "textDocument/rename",
    ]
    line: int = Field(ge=0, le=1_000_000)
    character: int = Field(ge=0, le=100_000)
    new_name: Optional[str] = Field(default=None, max_length=128)


def _trusted(root: Path):
    with studio.STATE_LOCK:
        if not studio._trusted(root, studio._load()):
            raise HTTPException(403, "Explicitly trust this project before starting a language server.")


def _binary(language: str, root: Path) -> tuple[str, ...] | None:
    command = SERVER_COMMANDS.get(language)
    if not command:
        return None
    candidate = shutil.which(command[0])
    if not candidate:
        return None
    try:
        resolved = Path(candidate).resolve(strict=True)
        if resolved.is_relative_to(root) or not resolved.is_file() or not os.access(resolved, os.X_OK):
            return None
    except (OSError, ValueError):
        return None
    return (str(resolved), *command[1:])


def _candidate(root: Path, relative: str) -> Path:
    file = studio._path(root, relative)
    if file == root or not file.is_file():
        raise HTTPException(404, "Open a regular file within the approved project.")
    return file


def _uri_allowed(root: Path, value: str) -> Optional[str]:
    if not isinstance(value, str) or len(value) > 4096:
        return None
    try:
        parsed = urlparse(value)
        if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
            return None
        # LSP paths are URLs, including percent-escaped Unicode.
        if os.name == "nt":
            from urllib.request import url2pathname
            file = Path(url2pathname(parsed.path)).resolve()
        else:
            file = Path(unquote(parsed.path)).resolve()
        relative = file.relative_to(root).as_posix()
        checked = studio._path(root, relative)
        return relative if checked == file else None
    except (OSError, HTTPException, UnicodeError, ValueError):
        return None


def _display(value, limit=4096) -> str:
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, dict):
        return _display(value.get("value", ""), limit)
    if isinstance(value, list):
        return "\n".join(_display(x, limit) for x in value)[:limit]
    return ""


def _safe_result(method: str, result, root: Path):
    """Server messages are untrusted; only return bounded inert presentation data."""
    if method == "textDocument/hover":
        contents = result.get("contents", "") if isinstance(result, dict) else ""
        return {"text": _display(contents, 4000)}
    if method == "textDocument/completion":
        if isinstance(result, dict):
            result = result.get("items", [])
        if not isinstance(result, list):
            result = []
        return {"items": [{"label": _display(item.get("label", ""), 160),
                           "detail": _display(item.get("detail", ""), 500)}
                          for item in result[:40] if isinstance(item, dict)]}
    if method in ("textDocument/definition", "textDocument/references"):
        if isinstance(result, dict):
            result = [result]
        if not isinstance(result, list):
            result = []
        places = []
        for item in result[:60]:
            if not isinstance(item, dict):
                continue
            path = _uri_allowed(root, item.get("uri") or item.get("targetUri", ""))
            position = item.get("range") or item.get("targetSelectionRange") or {}
            start = position.get("start", {}) if isinstance(position, dict) else {}
            if path is not None and isinstance(start, dict):
                line, col = start.get("line"), start.get("character")
                if type(line) is int and type(col) is int and 0 <= line < 1_000_000 and 0 <= col < 100_000:
                    places.append({"path": path, "line": line, "character": col})
        return {"locations": places}
    if method == "textDocument/rename":
        # The server's workspace edit is never applied. Return only reviewable
        # bounded data from inside the selected project, no raw arbitrary URIs.
        edits = []
        if isinstance(result, dict):
            for uri, changes in list((result.get("changes") or {}).items())[:20]:
                path = _uri_allowed(root, uri)
                if path is None or not isinstance(changes, list):
                    continue
                for item in changes[:50]:
                    if not isinstance(item, dict) or not isinstance(item.get("range"), dict):
                        continue
                    edits.append({"path": path, "range": item["range"],
                                  "newText": _display(item.get("newText", ""), 1024)})
                    if len(edits) >= 100:
                        break
        return {"preview_only": True, "applied": False, "edits": edits[:100],
                "note": "Rename proposals must be reviewed; V6 never changes source files."}
    return None


class LspSession:
    def __init__(self, root: Path, language: str, command: tuple[str, ...]):
        self.root = root
        self.root_identity = studio._identity(root)
        self.language = language
        self.lock = threading.RLock()
        self.pending: dict[int, queue.Queue] = {}
        self.diagnostics: dict[str, list] = {}
        self.documents: dict[str, int] = {}
        self.sequence = 0
        self.last_used = time.monotonic()
        self.broken = False
        env_keys = ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR",
                    "TMP", "TEMP", "LANG", "LC_ALL", "APPDATA", "LOCALAPPDATA")
        env = {k: v for k, v in os.environ.items() if k in env_keys}
        kwargs = {"cwd": str(root), "stdin": subprocess.PIPE,
                  "stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL,
                  "env": env, "shell": False}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        self.process = subprocess.Popen(list(command), **kwargs)
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def alive(self) -> bool:
        return not self.broken and self.process.poll() is None

    def _send(self, message: dict):
        body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_WIRE:
            raise HTTPException(413, "LSP request exceeds the protocol limit.")
        packet = b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body
        with self.lock:
            if not self.alive():
                raise HTTPException(502, "Language server is unavailable.")
            try:
                self.process.stdin.write(packet)
                self.process.stdin.flush()
            except (OSError, ValueError, BrokenPipeError) as exc:
                self.broken = True
                raise HTTPException(502, "Language server disconnected.") from exc
            self.last_used = time.monotonic()

    def notify(self, method: str, params: dict):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def ask(self, method: str, params: dict, timeout=REQUEST_TIMEOUT):
        with self.lock:
            self.sequence += 1
            number = self.sequence
            response = queue.Queue(maxsize=1)
            self.pending[number] = response
        try:
            self._send({"jsonrpc": "2.0", "id": number, "method": method, "params": params})
            try:
                message = response.get(timeout=timeout)
            except queue.Empty:
                try:
                    self.notify("$/cancelRequest", {"id": number})
                except HTTPException:
                    pass
                raise HTTPException(504, "Language server request timed out.")
            if "error" in message:
                raise HTTPException(502, "Language server returned an error.")
            return message.get("result")
        finally:
            with self.lock:
                self.pending.pop(number, None)

    def _read_frame(self):
        headers = 0
        length = None
        while True:
            line = self.process.stdout.readline(MAX_HEADER + 1)
            if not line:
                raise EOFError()
            headers += len(line)
            if headers > MAX_HEADER:
                raise ValueError("LSP headers exceeded limit")
            if line in (b"\r\n", b"\n"):
                break
            if line.lower().startswith(b"content-length:"):
                try:
                    length = int(line.split(b":", 1)[1].strip())
                except ValueError:
                    raise ValueError("invalid Content-Length") from None
        if length is None or length < 0 or length > MAX_WIRE:
            raise ValueError("invalid LSP payload size")
        remaining = length
        parts = []
        while remaining:
            block = self.process.stdout.read(min(remaining, 16384))
            if not block:
                raise EOFError()
            parts.append(block)
            remaining -= len(block)
        payload = json.loads(b"".join(parts).decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
            raise ValueError("invalid LSP message")
        return payload

    def _read_loop(self):
        try:
            while True:
                item = self._read_frame()
                if "id" in item and "method" not in item:
                    ident = item["id"]
                    with self.lock:
                        waiting = self.pending.get(ident) if type(ident) is int else None
                    if waiting:
                        try:
                            waiting.put_nowait(item)
                        except queue.Full:
                            pass
                    continue
                if "id" in item and "method" in item:
                    # Never allow server-initiated workspace edits, execution or UI actions.
                    reply = {"jsonrpc": "2.0", "id": item["id"],
                             "error": {"code": -32601, "message": "Client method not supported"}}
                    self._send(reply)
                    continue
                if item.get("method") == "textDocument/publishDiagnostics":
                    params = item.get("params") or {}
                    path = _uri_allowed(self.root, params.get("uri", ""))
                    if path is not None and isinstance(params.get("diagnostics"), list):
                        with self.lock:
                            self.diagnostics[path] = params["diagnostics"][:100]
                            if len(self.diagnostics) > 20:
                                self.diagnostics.pop(next(iter(self.diagnostics)))
        except (EOFError, ValueError, UnicodeError, TypeError, OSError):
            pass
        finally:
            self.broken = True
            with self.lock:
                for waiting in self.pending.values():
                    try:
                        waiting.put_nowait({"error": {"code": -32000}})
                    except queue.Full:
                        pass

    def close(self):
        self.broken = True
        try:
            self.process.stdin.close()
        except (OSError, ValueError):
            pass
        if self.process.poll() is None:
            try:
                if os.name != "nt":
                    os.killpg(self.process.pid, signal.SIGTERM)
                else:
                    self.process.terminate()
                self.process.wait(timeout=1.5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    if os.name != "nt":
                        os.killpg(self.process.pid, signal.SIGKILL)
                    else:
                        self.process.kill()
                except (OSError, ProcessLookupError):
                    pass


def _session(body: SessionIn) -> LspSession:
    with LOCK:
        session = SESSIONS.get(body.session_id)
        if session is None:
            raise HTTPException(404, "Language server session not found.")
        root = studio._project(body.project)
        if root != session.root or studio._identity(root) != session.root_identity:
            raise HTTPException(403, "LSP session belongs to another project or changed root.")
        try:
            _trusted(root)
        except HTTPException:
            SESSIONS.pop(body.session_id, None)
            session.close()
            raise
        if not session.alive() or time.monotonic() - session.last_used > IDLE_SECONDS:
            SESSIONS.pop(body.session_id, None)
            session.close()
            raise HTTPException(410, "Language server closed or expired.")
        session.last_used = time.monotonic()
        return session


def _open_document(session: LspSession, relative: str, text: Optional[str]):
    file = _candidate(session.root, relative)
    if text is None:
        text = languages._read(session.root, relative, MAX_SOURCE)
    if text is None:
        raise HTTPException(415, "Only bounded UTF-8 source is supported by the LSP bridge.")
    if len(text.encode("utf-8")) > MAX_SOURCE:
        raise HTTPException(413, "LSP source text is too large.")
    candidate = languages._file_language(relative, text[:4096])
    if candidate["language"] != session.language and not (
        session.language in ("javascript", "typescript") and
        candidate["language"] in ("javascript", "typescript")
    ):
        raise HTTPException(422, "Document language does not match the selected server.")
    uri = file.as_uri()
    version = session.documents.get(relative)
    if version is None:
        session.documents[relative] = 1
        session.notify("textDocument/didOpen", {"textDocument": {
            "uri": uri, "languageId": session.language, "version": 1, "text": text}})
    else:
        session.documents[relative] = version + 1
        session.notify("textDocument/didChange", {
            "textDocument": {"uri": uri, "version": version + 1},
            "contentChanges": [{"text": text}]})
    return uri


@router.get("/servers")
def servers(request: Request, project: str):
    studio._auth(request)
    root = studio._project(project)
    return {"servers": [
        {"language": language, "binary": command[0],
         "status": "available" if _binary(language, root) else "unavailable",
         "requires_trust": True, "requires_explicit_start": True}
        for language, command in SERVER_COMMANDS.items()
    ], "automatic_start": False, "platform_sandbox": False}


@router.post("/start")
def start(request: Request, body: StartIn):
    studio._auth(request)
    root = studio._project(body.project)
    _trusted(root)
    command = _binary(body.language, root)
    if command is None:
        raise HTTPException(422, "Approved language server is not installed or allowed.")
    with LOCK:
        for token, existing in list(SESSIONS.items()):
            if not existing.alive() or time.monotonic() - existing.last_used > IDLE_SECONDS:
                SESSIONS.pop(token, None)
                existing.close()
        if len(SESSIONS) >= MAX_SESSIONS:
            raise HTTPException(429, "Language server session limit reached. Stop another session.")
        try:
            session = LspSession(root, body.language, command)
        except OSError as exc:
            raise HTTPException(502, "Unable to start installed language server.") from exc
        token = secrets.token_hex(24)
        SESSIONS[token] = session
    try:
        reply = session.ask("initialize", {
            "processId": os.getpid(), "clientInfo": {"name": "AutoMoto Developer Studio", "version": "6"},
            "rootUri": root.as_uri(), "workspaceFolders": [{"uri": root.as_uri(), "name": root.name}],
            "capabilities": {"general": {"positionEncodings": ["utf-16"]},
                             "textDocument": {"synchronization": {"didSave": False},
                                              "hover": {"contentFormat": ["plaintext"]},
                                              "completion": {"completionItem": {"snippetSupport": False}},
                                              "definition": {}, "references": {}, "rename": {}}},
            "initializationOptions": {},
            "trace": "off",
        })
        session.notify("initialized", {})
    except (HTTPException, OSError):
        with LOCK:
            SESSIONS.pop(token, None)
        session.close()
        raise
    caps = reply.get("capabilities", {}) if isinstance(reply, dict) else {}
    # Capabilities are untrusted; report only advertised existence, not certification.
    supported = {key: bool(caps.get(key)) for key in
                 ("hoverProvider", "completionProvider", "definitionProvider",
                  "referencesProvider", "renameProvider")}
    return {"session_id": token, "language": body.language,
            "capabilities": supported, "server": command[0],
            "explicit_approval": True, "platform_sandbox": False,
            "source_modified": False}


@router.post("/document")
def document(request: Request, body: DocumentIn):
    studio._auth(request)
    session = _session(body)
    uri = _open_document(session, body.path, body.text)
    return {"path": body.path, "uri": uri, "version": session.documents[body.path],
            "source_modified": False}


@router.post("/query")
def query(request: Request, body: QueryIn):
    studio._auth(request)
    session = _session(body)
    uri = _open_document(session, body.path, body.text)
    params = {"textDocument": {"uri": uri},
              "position": {"line": body.line, "character": body.character}}
    if body.method == "textDocument/references":
        params["context"] = {"includeDeclaration": True}
    if body.method == "textDocument/rename":
        if not body.new_name or not body.new_name.isidentifier():
            raise HTTPException(422, "Choose a valid new identifier for rename preview.")
        params["newName"] = body.new_name
    result = session.ask(body.method, params)
    return {"method": body.method, "result": _safe_result(body.method, result, session.root),
            "source_modified": False, "session_id": body.session_id}


@router.post("/diagnostics")
def diagnostics(request: Request, body: SessionIn):
    studio._auth(request)
    session = _session(body)
    with session.lock:
        items = [{"path": path, "items": [
            {"message": _display(d.get("message", ""), 500),
             "severity": d.get("severity") if type(d.get("severity")) is int and 1 <= d["severity"] <= 4 else 3,
             "range": d.get("range") if isinstance(d.get("range"), dict) else {}}
            for d in values if isinstance(d, dict)][:50]}
            for path, values in list(session.diagnostics.items())[:20]]
    return {"files": items, "source_modified": False}


@router.post("/stop")
def stop(request: Request, body: SessionIn):
    studio._auth(request)
    session = _session(body)
    with LOCK:
        SESSIONS.pop(body.session_id, None)
    session.close()
    return {"stopped": True, "source_modified": False}
