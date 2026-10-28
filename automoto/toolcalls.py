"""Tool-call plumbing shared by every provider.

The agent keeps one *neutral* history (OpenAI-style)::

    {"role": "assistant", "content": "...", "tool_calls": [{"id": "c1", "name": "list_dir", "arguments": {...}}]}
    {"role": "tool", "tool_call_id": "c1", "name": "list_dir", "content": "..."}

and renders it per provider right before each call, so failover can switch provider
(and even switch between native tool calling and the JSON-in-text fallback) mid-task.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

TOOL_BLOCK_RE = re.compile(r"```(?:tool|tool_call|json)?\s*(\{.*?\})\s*```", re.S | re.I)
TOOL_TAG_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S | re.I)


@dataclass
class Turn:
    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    mode: str = "native"  # native | text
    tried: list[dict[str, Any]] = field(default_factory=list)


def new_id() -> str:
    return "call_" + uuid.uuid4().hex[:12]


def _args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


# -- text fallback --------------------------------------------------------------
TEXT_PROTOCOL = """## How to use tools (text protocol)
To call a tool, reply with ONLY a fenced block like this (one call per block, nothing after it):

```tool
{"name": "list_dir", "arguments": {"path": "."}}
```

You will then receive the tool result in the next message. When the task is finished, reply
normally with NO tool block."""


def parse_text_calls(text: str, known: set[str]) -> tuple[str, list[dict[str, Any]]]:
    """Find JSON tool calls in a plain-text reply. Returns (text_without_calls, calls)."""
    calls, spans = [], []
    for rx in (TOOL_BLOCK_RE, TOOL_TAG_RE):
        for m in rx.finditer(text or ""):
            try:
                obj = json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            name = obj.get("name") or obj.get("tool")
            if name not in known:
                continue
            calls.append({"id": new_id(), "name": name, "arguments": _args(obj.get("arguments", obj.get("args", {})))})
            spans.append(m.span())
    if not calls:
        stripped = (text or "").strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                obj = json.loads(stripped)
                name = obj.get("name") or obj.get("tool")
                if name in known:
                    return "", [{"id": new_id(), "name": name,
                                 "arguments": _args(obj.get("arguments", obj.get("args", {})))}]
            except (json.JSONDecodeError, AttributeError):
                pass
        return text, []
    clean = text
    for a, b in sorted(spans, reverse=True):
        clean = clean[:a] + clean[b:]
    return clean.strip(), calls[:5]


def schema_manifest(schemas: list[dict[str, Any]]) -> str:
    lines = []
    for s in schemas or []:
        f = s.get("function", s)
        props = f.get("parameters", {}).get("properties", {})
        req = set(f.get("parameters", {}).get("required", []))
        args = ", ".join(f"{k}{'' if k in req else '?'}" for k in props)
        lines.append(f"- {f['name']}({args}): {f.get('description', '')}")
    return "\n".join(lines)


def render_text(messages: list[dict[str, Any]], schemas: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Flatten tool calls/results into plain chat; add the text protocol to the system prompt."""
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role == "assistant":
            body = m.get("content") or ""
            for c in m.get("tool_calls") or []:
                body += "\n```tool\n" + json.dumps({"name": c["name"], "arguments": c["arguments"]}) + "\n```"
            out.append({"role": "assistant", "content": body.strip() or "(calling tool)"})
        elif role == "tool":
            txt = f"Tool result for {m.get('name')} ({m.get('tool_call_id')}):\n{m.get('content')}"
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], str) and out[-1].get("_tool"):
                out[-1]["content"] += "\n\n" + txt
            else:
                out.append({"role": "user", "content": txt, "_tool": True})
        else:
            out.append({k: v for k, v in m.items() if k in ("role", "content")})
    for m in out:
        m.pop("_tool", None)
    if schemas:
        proto = TEXT_PROTOCOL + "\n\nAvailable tools:\n" + schema_manifest(schemas)
        if out and out[0]["role"] == "system" and isinstance(out[0]["content"], str):
            out[0] = {"role": "system", "content": out[0]["content"] + "\n\n" + proto}
        else:
            out.insert(0, {"role": "system", "content": proto})
    return out


# -- OpenAI-compatible native ------------------------------------------------------
def render_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            out.append({"role": "assistant", "content": m.get("content") or None, "tool_calls": [
                {"id": c["id"], "type": "function",
                 "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                for c in m["tool_calls"]]})
        elif role == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": str(m.get("content", ""))})
        else:
            out.append({k: v for k, v in m.items() if k in ("role", "content")})
    return out


def parse_openai_message(msg: Any) -> tuple[str, list[dict[str, Any]]]:
    text = (getattr(msg, "content", None) or "").strip()
    calls = []
    for tc in getattr(msg, "tool_calls", None) or []:
        fn = getattr(tc, "function", None)
        if not fn or not getattr(fn, "name", None):
            continue
        calls.append({"id": getattr(tc, "id", None) or new_id(), "name": fn.name, "arguments": _args(fn.arguments)})
    return text, calls


# -- Anthropic native --------------------------------------------------------------
def anthropic_tools(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"name": s["function"]["name"], "description": s["function"]["description"],
             "input_schema": s["function"]["parameters"]} for s in schemas]


def render_anthropic(messages: list[dict[str, Any]], to_blocks) -> tuple[str, list[dict[str, Any]]]:
    """``to_blocks`` is providers._to_anthropic (handles system + images)."""
    plain: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            blocks += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["arguments"]}
                       for c in m["tool_calls"]]
            plain.append({"role": "assistant", "content": blocks, "_raw": True})
        elif role == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": str(m.get("content", ""))}
            if plain and plain[-1].get("_tool"):
                plain[-1]["content"].append(block)
            else:
                plain.append({"role": "user", "content": [block], "_raw": True, "_tool": True})
        else:
            plain.append(m)
    system_parts, out = [], []
    for m in plain:
        if m.get("_raw"):
            out.append({"role": m["role"], "content": m["content"]})
        else:
            s, conv = to_blocks([m])
            if s:
                system_parts.append(s)
            out += conv
    return "\n\n".join(system_parts), out
