"""Minimal MCP (Model Context Protocol) client for **stdio** servers.

List servers in ``~/.automoto/mcp.json`` (or ``AUTOMOTO_MCP_CONFIG``)::

    {"servers": {
        "fs": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"],
               "env": {}, "trust": false}
    }}

Each server's tools appear to the agent as ``mcp__<server>__<tool>``. They are **risky**
(approval required) unless ``"trust": true``. Only stdio transport is supported.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

from automoto import home
from automoto import tools as tools_mod

PROTOCOL = "2025-06-18"


class MCPError(Exception):
    pass


class StdioServer:
    def __init__(self, name: str, command: str, args: list[str] | None = None, env: dict[str, str] | None = None,
                 timeout: float = 30):
        self.name, self.timeout = name, timeout
        self._id = 0
        self._lock = threading.Lock()
        self._wlock = threading.Lock()
        self.proc = subprocess.Popen([command, *(args or [])], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
                                     env={**os.environ, **(env or {})})
        self._replies: dict[int, dict[str, Any]] = {}
        self._cv = threading.Condition()
        threading.Thread(target=self._read_loop, name=f"mcp-{name}", daemon=True).start()
        self._request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                     "clientInfo": {"name": "automoto", "version": "5.0.0"}})
        self._notify("notifications/initialized")

    def _send(self, msg: dict[str, Any]) -> None:
        if self.proc.poll() is not None:
            raise MCPError(f"{self.name}: server exited")
        assert self.proc.stdin
        with self._wlock:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    def _read_loop(self) -> None:
        assert self.proc.stdout
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                with self._cv:
                    self._replies[msg["id"]] = msg
                    self._cv.notify_all()
        with self._cv:
            self._cv.notify_all()

    def _request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        with self._lock:
            self._id += 1
            rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        with self._cv:
            ok = self._cv.wait_for(lambda: rid in self._replies or self.proc.poll() is not None, timeout=self.timeout)
            msg = self._replies.pop(rid, None)
        if not ok or msg is None:
            raise MCPError(f"{self.name}: no reply to {method} within {self.timeout}s")
        if "error" in msg:
            raise MCPError(f"{self.name}: {msg['error'].get('message', msg['error'])}")
        return msg["result"]

    def list_tools(self) -> list[dict[str, Any]]:
        return self._request("tools/list").get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        res = self._request("tools/call", {"name": name, "arguments": arguments})
        parts = []
        for c in res.get("content", []):
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
            else:
                parts.append(f"[{c.get('type')} content]")
        text = "\n".join(parts) or json.dumps(res.get("structuredContent", {}))[:8000]
        if res.get("isError"):
            raise tools_mod.ToolFailed(text)
        return text

    def close(self) -> None:
        try:
            self.proc.terminate()
        except Exception:
            pass


_SERVERS: dict[str, StdioServer] = {}


def load_config(path: Path | None = None) -> dict[str, Any]:
    p = Path(path or home.mcp_file())
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("servers", {})
    except (OSError, json.JSONDecodeError):
        return {}


def connect_all(path: Path | None = None) -> tuple[list[tools_mod.Tool], list[str]]:
    """Start configured servers and wrap their tools. Returns (tools, errors)."""
    out: list[tools_mod.Tool] = []
    errors: list[str] = []
    for name, cfg in load_config(path).items():
        try:
            srv = _SERVERS.get(name)
            if not srv or srv.proc.poll() is not None:
                srv = StdioServer(name, cfg["command"], cfg.get("args"), cfg.get("env"))
                _SERVERS[name] = srv
            for t in srv.list_tools():
                out.append(wrap(srv, t, trusted=bool(cfg.get("trust"))))
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    return out, errors


def wrap(srv: StdioServer, spec: dict[str, Any], *, trusted: bool = False) -> tools_mod.Tool:
    tname = spec["name"]

    def fn(ctx, **kw):
        return srv.call_tool(tname, kw)

    params = spec.get("inputSchema") or {"type": "object", "properties": {}}
    params.setdefault("properties", {})
    return tools_mod.Tool(f"mcp__{srv.name}__{tname}"[:64], (spec.get("description") or tname)[:400], params,
                          "safe" if trusted else "risky", fn, f"mcp:{srv.name}")


def close_all() -> None:
    for s in _SERVERS.values():
        s.close()
    _SERVERS.clear()
