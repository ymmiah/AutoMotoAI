"""
AI Function-Calling framework.

Defines the tools the AI can invoke (open apps, manage files, query system
state, etc.) and the registry that stores + executes them.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Generator

logger = logging.getLogger(__name__)


# ─────────────────────────────── data models ──────────────────────────────────

@dataclass
class ToolParam:
    name: str
    type: str          # JSON-Schema type: string | integer | number | boolean
    description: str
    required: bool = True
    enum: list | None = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    params: list[ToolParam]
    handler: Callable[..., Any]
    requires_confirmation: bool = False   # prompt user before executing


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict


@dataclass
class ToolCallResult:
    id: str
    name: str
    result: str
    success: bool = True


# ───────────────────────────── registry ───────────────────────────────────────

class ToolRegistry:
    """Stores tool definitions and executes them by name."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    @property
    def all_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def execute(self, request: ToolCallRequest) -> ToolCallResult:
        tool = self._tools.get(request.name)
        if not tool:
            return ToolCallResult(request.id, request.name, f"Unknown tool: {request.name}", False)
        try:
            result = tool.handler(**request.arguments)
            result_str = str(result) if result is not None else "Done"
            logger.info("Tool '%s' succeeded: %.80s", request.name, result_str)
            return ToolCallResult(request.id, request.name, result_str, True)
        except Exception as exc:
            logger.error("Tool '%s' failed: %s", request.name, exc)
            return ToolCallResult(request.id, request.name, str(exc), False)

    # ── schema export ──────────────────────────────────────────────────────
    def to_openai_schema(self) -> list[dict]:
        schemas = []
        for t in self._tools.values():
            props, required = {}, []
            for p in t.params:
                prop: dict = {"type": p.type, "description": p.description}
                if p.enum:
                    prop["enum"] = p.enum
                props[p.name] = prop
                if p.required:
                    required.append(p.name)
            schemas.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": {"type": "object", "properties": props, "required": required},
                },
            })
        return schemas

    def to_claude_schema(self) -> list[dict]:
        schemas = []
        for t in self._tools.values():
            props, required = {}, []
            for p in t.params:
                prop: dict = {"type": p.type, "description": p.description}
                if p.enum:
                    prop["enum"] = p.enum
                props[p.name] = prop
                if p.required:
                    required.append(p.name)
            schemas.append({
                "name": t.name,
                "description": t.description,
                "input_schema": {"type": "object", "properties": props, "required": required},
            })
        return schemas


# ─────────────────────────── default tools ────────────────────────────────────

def _build_default_registry() -> ToolRegistry:
    reg = ToolRegistry()

    def _open_app(app_name: str) -> str:
        from src.automation.desktop import open_application
        open_application(app_name)
        return f"Opened '{app_name}'"

    def _screenshot() -> str:
        from src.automation.desktop import take_screenshot
        path = take_screenshot()
        return f"Screenshot saved: {path}"

    def _list_dir(path: str) -> str:
        from src.automation.files import list_directory
        entries = list_directory(path)
        lines = [
            ("📁 " if e["is_dir"] else "📄 ") + e["name"] + (f"  ({e['size']} B)" if not e["is_dir"] else "")
            for e in entries[:60]
        ]
        suffix = f"\n… {len(entries)-60} more items" if len(entries) > 60 else ""
        return "\n".join(lines) + suffix or "(empty directory)"

    def _create_file(path: str, content: str = "") -> str:
        from src.automation.files import create_file
        p = create_file(path, content)
        return f"Created file: {p}"

    def _create_dir(path: str) -> str:
        from src.automation.files import create_directory
        p = create_directory(path)
        return f"Created directory: {p}"

    def _system_info() -> str:
        from src.automation.monitor import get_system_snapshot
        snap = get_system_snapshot()
        return json.dumps(snap, indent=2)

    def _list_processes(limit: int = 20) -> str:
        from src.automation.monitor import get_top_processes
        procs = get_top_processes(limit)
        lines = [f"PID {p['pid']:6d}  CPU {p['cpu']:5.1f}%  MEM {p['mem']:5.1f}%  {p['name']}" for p in procs]
        return "\n".join(lines) or "No processes found"

    def _type_text(text: str) -> str:
        from src.automation.input_sim import type_text
        type_text(text)
        return f"Typed {len(text)} characters"

    def _press_key(key: str) -> str:
        from src.automation.input_sim import press_key
        press_key(key)
        return f"Pressed: {key}"

    def _run_hotkey(keys: str) -> str:
        """keys is '+'-joined, e.g. 'ctrl+s'"""
        from src.automation.input_sim import hotkey
        hotkey(*keys.split("+"))
        return f"Hotkey executed: {keys}"

    def _open_in_explorer(path: str) -> str:
        from src.automation.desktop import open_in_file_manager
        open_in_file_manager(path)
        return f"Opened in file manager: {path}"

    tools = [
        ToolDefinition("open_application",
            "Open an application by name or executable path. E.g. 'notepad', 'chrome', 'calc.exe'.",
            [ToolParam("app_name", "string", "App name or executable path")],
            _open_app),
        ToolDefinition("take_screenshot",
            "Capture the entire screen and save as a PNG file.",
            [], _screenshot),
        ToolDefinition("list_directory",
            "List all files and folders inside a given directory path.",
            [ToolParam("path", "string", "Absolute directory path")],
            _list_dir),
        ToolDefinition("create_file",
            "Create a new file with optional text content.",
            [ToolParam("path", "string", "Absolute file path"),
             ToolParam("content", "string", "Text content to write (optional)", required=False)],
            _create_file, requires_confirmation=True),
        ToolDefinition("create_directory",
            "Create a new directory, including any missing parent directories.",
            [ToolParam("path", "string", "Absolute directory path to create")],
            _create_dir, requires_confirmation=True),
        ToolDefinition("get_system_info",
            "Return current CPU, RAM, disk, and network usage statistics.",
            [], _system_info),
        ToolDefinition("list_processes",
            "Return the top running processes sorted by CPU usage.",
            [ToolParam("limit", "integer", "Maximum processes to return (default 20)", required=False)],
            _list_processes),
        ToolDefinition("type_text",
            "Simulate keyboard typing of text at the current cursor position.",
            [ToolParam("text", "string", "Text to type")],
            _type_text, requires_confirmation=True),
        ToolDefinition("press_key",
            "Press a single keyboard key (e.g. 'enter', 'escape', 'f5', 'tab', 'delete').",
            [ToolParam("key", "string", "Key name as understood by pyautogui")],
            _press_key, requires_confirmation=True),
        ToolDefinition("run_hotkey",
            "Execute a keyboard shortcut. Keys joined by '+', e.g. 'ctrl+s', 'ctrl+shift+t', 'alt+f4'.",
            [ToolParam("keys", "string", "Keys separated by '+'")],
            _run_hotkey, requires_confirmation=True),
        ToolDefinition("open_in_file_manager",
            "Open a file or folder in the system file manager (Windows Explorer).",
            [ToolParam("path", "string", "Path to open in the file manager")],
            _open_in_explorer),
    ]
    for t in tools:
        reg.register(t)
    return reg


tool_registry: ToolRegistry = _build_default_registry()
