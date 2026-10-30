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
# Gemini 3 (OpenAI-compatible endpoint) returns a "thought signature" with each function call
# and rejects the next request (400) if it is not sent back. Calls made by another provider or
# parsed from text have none; Google documents this placeholder for that case.
GEMINI_SKIP_SIGNATURE = {"google": {"thought_signature": "skip_thought_signature_validator"}}


def _openai_call(c: dict[str, Any], provider: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {"id": c["id"], "type": "function",
                           "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
    if provider == "gemini":  # other providers may reject unknown fields, so only for Gemini
        extra = c.get("extra") if c.get("provider") == "gemini" else None
        out["extra_content"] = extra or GEMINI_SKIP_SIGNATURE
    return out


def render_openai(messages: list[dict[str, Any]], provider: str | None = None) -> list[dict[str, Any]]:
    out = []
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            out.append({"role": "assistant", "content": m.get("content") or None,
                        "tool_calls": [_openai_call(c, provider) for c in m["tool_calls"]]})
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
        call = {"id": getattr(tc, "id", None) or new_id(), "name": fn.name, "arguments": _args(fn.arguments)}
        extra = getattr(tc, "extra_content", None) or (getattr(tc, "model_extra", None) or {}).get("extra_content")
        if isinstance(extra, dict):
            call["extra"] = extra  # e.g. Gemini's thought signature - sent back on the next request
        calls.append(call)
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


# -- lenient parsing of malformed text tool calls ------------------------------------
# Some models (seen with Gemini and smaller NIM models) write tool calls as plain text in
# odd shapes: ``office_read(path="x")``, ``<invoke name="office_read">…``, JSON with
# "parameters" instead of "arguments", or even ``office_readpathuploads/x.pptx`` (name, argument
# name and value glued together). We run such a call only when it is unambiguous: a known tool,
# every required argument present, and (for the loose shapes) at the very end of the reply.
_FUNC_TAG_RE = re.compile(r"<function\s*=\s*([\w.\-]+)\s*>\s*(\{.*?\})\s*</function>", re.S | re.I)
_INVOKE_RE = re.compile(r"<invoke\s+name\s*=\s*[\"']([\w.\-]+)[\"']\s*>(.*?)</invoke>", re.S | re.I)
_PARAM_RE = re.compile(r"<parameter\s+name\s*=\s*[\"']([\w\-]+)[\"']\s*>(.*?)</parameter>", re.S | re.I)
_KV_RE = re.compile(r"([A-Za-z_]\w*)\s*[=:]\s*(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|[^,\s)]+)")
_PROMISE_RE = re.compile(
    r"\b(let me (?:try|retry|attempt|call|use|read|open)|i(?:'ll| will) (?:now |)(?:try|retry|attempt|call|use|read|open)|"
    r"try(?:ing)? again|i will now|i'll now|one moment|calling (?:the )?\w+ (?:tool|function)|"
    r"issue with the (?:function|tool) call|(?:function|tool) call (?:failed|didn't work|did not work))\b",
    re.I)


def _obj_call(obj: Any, specs: dict[str, tuple[list[str], list[str]]]) -> dict[str, Any] | None:
    if not isinstance(obj, dict):
        return None
    fn = obj.get("function")
    name = obj.get("name") or obj.get("tool") or obj.get("tool_name") or (fn if isinstance(fn, str) else None)
    raw = obj.get("arguments", obj.get("args", obj.get("parameters", obj.get("input"))))
    if isinstance(fn, dict):
        name = name or fn.get("name")
        raw = raw if raw is not None else fn.get("arguments", fn.get("parameters"))
    if name not in specs:
        return None
    return _complete(name, _args(raw if raw is not None else {}), specs)


def _complete(name: str, args: dict[str, Any], specs) -> dict[str, Any] | None:
    props, req = specs[name]
    if not isinstance(args, dict):
        return None
    if any(k not in args for k in req):
        # one missing required argument + one unknown one -> tools.repair_args maps it later
        unknown = [k for k in args if k not in props]
        if not (len([k for k in req if k not in args]) == 1 and len(unknown) == 1):
            return None
    return {"id": new_id(), "name": name, "arguments": args}


def _unquote(v: str) -> Any:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'`":
        v = v[1:-1]
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    return v


def specs_from_schemas(schemas: list[dict[str, Any]]) -> dict[str, tuple[list[str], list[str]]]:
    out = {}
    for s in schemas or []:
        f = s.get("function", s)
        params = f.get("parameters", {}) or {}
        out[f["name"]] = (list(params.get("properties", {})), list(params.get("required", [])))
    return out


def parse_loose_calls(text: str, specs: dict[str, tuple[list[str], list[str]]]) -> tuple[str, list[dict[str, Any]]]:
    """Strict JSON blocks first (``parse_text_calls``), then the lenient shapes described above."""
    text = text or ""
    clean, calls = parse_text_calls(text, set(specs))
    if calls:
        return clean, calls
    found: list[tuple[tuple[int, int], dict[str, Any]]] = []
    # 1. tag shapes: <function=x>{...}</function>, <invoke name="x"><parameter name="k">v</parameter></invoke>
    for m in _FUNC_TAG_RE.finditer(text):
        try:
            c = _complete(m.group(1), _args(json.loads(m.group(2))), specs) if m.group(1) in specs else None
        except json.JSONDecodeError:
            c = None
        if c:
            found.append((m.span(), c))
    for m in _INVOKE_RE.finditer(text):
        if m.group(1) in specs:
            c = _complete(m.group(1), {k: _unquote(v) for k, v in _PARAM_RE.findall(m.group(2))}, specs)
            if c:
                found.append((m.span(), c))
    for name in specs:  # <office_read><path>x</path></office_read>
        for m in re.finditer(rf"<{re.escape(name)}>(.*?)</{re.escape(name)}>", text, re.S):
            args = {k: _unquote(v) for k, v in re.findall(r"<([A-Za-z_]\w*)>(.*?)</\1>", m.group(1), re.S)}
            c = _complete(name, args, specs)
            if c:
                found.append((m.span(), c))
    # 2. JSON objects anywhere (no fence), e.g. {"name": "x", "parameters": {...}}
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{\s*\"(?:name|tool|tool_name|function)\"", text):
        if any(a <= m.start() < b for (a, b), _ in found):
            continue  # inside an object (or tag) we already took
        try:
            obj, end = dec.raw_decode(text, m.start())
        except json.JSONDecodeError:
            continue
        c = _obj_call(obj, specs)
        if c:
            found.append(((m.start(), end), c))
    if found:
        return _cut(text, [s for s, _ in found]), [c for _, c in found][:5]
    # 3. tail shapes: name(...)  /  name path=x  /  namepathvalue (glued)
    tail = text.rstrip().rstrip("`").rstrip()
    for name in sorted(specs, key=len, reverse=True):
        props, req = specs[name]
        m = re.search(rf"(?:^|[^\w]){re.escape(name)}\s*\(\s*(.*?)\s*\)\s*$", tail, re.S)
        if m:
            inner = m.group(1)
            args: Any = None
            if inner.startswith("{"):
                try:
                    args = json.loads(inner)
                except json.JSONDecodeError:
                    args = None
            elif inner:
                args = {k: _unquote(v) for k, v in _KV_RE.findall(inner)}
                if not args and len(req) == 1:
                    args = {req[0]: _unquote(inner)}
            c = _complete(name, args, specs) if isinstance(args, dict) else None
            if c:
                return _cut(text, [(text.rfind(name, 0, m.end()), len(text))]), [c]
        if len(req) == 1:
            p = re.escape(req[0])
            m = re.search(rf"(?:^|[^\w]){re.escape(name)}[\s:`\-]*{p}\s*[:=]?\s*[\"'`]?([^\n\"'`]+?)[\"'`]?\s*$", tail)
            if m and m.group(1).strip():
                c = _complete(name, {req[0]: _unquote(m.group(1))}, specs)
                if c:
                    return _cut(text, [(text.rfind(name, 0, m.end()), len(text))]), [c]
    return text, []


def _cut(text: str, spans: list[tuple[int, int]]) -> str:
    for a, b in sorted(spans, reverse=True):
        text = text[:a] + text[b:]
    return re.sub(r"```(?:tool|json)?\s*```", "", text).strip()


def looks_like_failed_call(text: str, names: set[str] | list[str]) -> str:
    """Why a reply without (runnable) tool calls looks like a broken or merely promised tool call;
    empty string if it looks like a real final answer."""
    t = (text or "").strip()
    if not t:
        return ""
    tail = t[-400:]
    if re.search(r"```tool|<tool_call|<function\s*=|<invoke\s|\"arguments\"\s*:", t, re.I):
        return "tool-call syntax that could not be read"
    for n in names:
        if re.search(rf"(?:^|[^\w]){re.escape(n)}(?:\s*\(|\s*\{{|\s+[A-Za-z_]+\s*[=:]|[a-z]\S*$)", tail):
            return f"a call to {n} written as text"
    if _PROMISE_RE.search(tail) and len(t) < 1200:
        return "a promise to act without a tool call"
    return ""


def strip_failed_call(text: str, names: set[str] | list[str]) -> str:
    """Remove a dangling raw tool call from the end of a final answer (never show it to people)."""
    t = (text or "").rstrip()
    cut = len(t)
    for n in names:
        i = t.rfind(n)
        if i >= 0 and len(t) - i < 400 and (i == 0 or not (t[i - 1].isalnum() or t[i - 1] == "_")):
            cut = min(cut, i)
    for rx in (r"```tool", r"<tool_call", r"<function\s*=", r"<invoke\s"):
        m = re.search(rx, t, re.I)
        if m:
            cut = min(cut, m.start())
    return t[:cut].rstrip(" `\n:")
