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
            from src.core.sandbox import execute_with_timeout
            result = execute_with_timeout(tool.handler, **request.arguments)
            result_str = str(result) if result is not None else "Done"
            logger.info("Tool '%s' succeeded: %.80s", request.name, result_str)
            return ToolCallResult(request.id, request.name, result_str, True)
        except TimeoutError as exc:
            logger.error("Tool '%s' timed out: %s", request.name, exc)
            return ToolCallResult(request.id, request.name, f"Timeout: {exc}", False)
        except PermissionError as exc:
            logger.warning("Tool '%s' sandbox blocked: %s", request.name, exc)
            return ToolCallResult(request.id, request.name, f"Sandbox denied: {exc}", False)
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

    # ── document tools ────────────────────────────────────────────────────
    def _read_file_tool(path: str) -> str:
        from src.automation.document_reader import read_file
        result = read_file(path)
        if not result.ok:
            return f"[ERROR] {result.error}"
        return result.as_context()

    def _read_multiple_files_tool(paths: str) -> str:
        """paths is a newline- or comma-separated list of file paths."""
        import re as _re
        from src.automation.document_reader import build_multi_file_context
        path_list = [p.strip() for p in _re.split(r"[\n,]+", paths) if p.strip()]
        if not path_list:
            return "[ERROR] No paths provided"
        return build_multi_file_context(path_list)

    def _summarize_files_tool(paths: str, focus: str = "") -> str:
        """Read files and return a structured summary."""
        import re as _re
        from src.automation.document_reader import read_multiple_files
        path_list = [p.strip() for p in _re.split(r"[\n,]+", paths) if p.strip()]
        if not path_list:
            return "[ERROR] No paths provided"
        results = read_multiple_files(path_list)
        parts = []
        for r in results:
            if r.ok:
                meta = ", ".join(f"{k}={v}" for k, v in r.summary_meta.items())
                snippet = r.content[:800].replace("\n", " ")
                tail = "…" if len(r.content) > 800 else ""
                focus_note = f"  Focus: {focus}\n" if focus else ""
                parts.append(f"File: {r.name}  [{r.format}]  {meta}\n{focus_note}Preview: {snippet}{tail}")
            else:
                parts.append(f"File: {r.name}  [ERROR: {r.error}]")
        return "\n\n".join(parts)

    def _combine_files_tool(paths: str, output_format: str = "txt", output_path: str = "") -> str:
        import re as _re
        from src.automation.document_writer import combine_documents
        path_list = [p.strip() for p in _re.split(r"[\n,]+", paths) if p.strip()]
        if not path_list:
            return "[ERROR] No paths provided"
        out = combine_documents(path_list, output_format, output_path or None)
        return f"Combined {len(path_list)} file(s) → {out}"

    def _create_document_tool(content: str, output_format: str = "txt",
                               filename: str = "", output_path: str = "") -> str:
        from src.automation.document_writer import create_document
        out = create_document(content, output_format, output_path or None, filename or None)
        return f"Document created: {out}"

    def _convert_document_tool(source_path: str, target_format: str,
                                output_path: str = "") -> str:
        from src.automation.document_writer import convert_document
        out = convert_document(source_path, target_format, output_path or None)
        return f"Converted → {out}"

    # ── voice tools ───────────────────────────────────────────────────────
    def _speak_tool(text: str, rate: int = 175) -> str:
        from src.automation.voice import speak_to_file, get_audio_dir
        import datetime as _dt, hashlib as _hl
        ts   = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = _hl.md5(text[:64].encode()).hexdigest()[:8]
        out  = get_audio_dir() / f"tts_{ts}_{slug}.wav"
        speak_to_file(text, out, rate=rate)
        return f"Speech synthesized → {out.name}"

    def _listen_tool(timeout: int = 10) -> str:
        from src.automation.voice import listen
        return listen(timeout=timeout)

    def _transcribe_tool(audio_path: str, language: str = "en") -> str:
        from src.automation.voice import transcribe_file
        return transcribe_file(audio_path, language=language)

    # ── window management tools ───────────────────────────────────────────
    def _list_windows_tool() -> str:
        from src.automation.desktop import get_window_list
        wins = get_window_list()
        return "\n".join(f"• {w}" for w in wins) or "(no windows found)"

    def _focus_window_tool(title: str) -> str:
        from src.automation.desktop import focus_window
        focus_window(title)
        return f"Focused: {title}"

    def _minimize_window_tool(title: str) -> str:
        from src.automation.desktop import minimize_window
        minimize_window(title)
        return f"Minimized: {title}"

    def _maximize_window_tool(title: str) -> str:
        from src.automation.desktop import maximize_window
        maximize_window(title)
        return f"Maximized: {title}"

    def _close_window_tool(title: str) -> str:
        from src.automation.desktop import close_window
        close_window(title)
        return f"Closed: {title}"

    # ── dialog tools ──────────────────────────────────────────────────────
    def _show_dialog_tool(title: str, message: str, kind: str = "info") -> str:
        from src.automation.dialog import show_message
        show_message(title, message, kind)
        return f"Dialog shown: [{kind}] {title}"

    def _ask_yes_no_tool(title: str, message: str) -> str:
        from src.automation.dialog import ask_yes_no
        result = ask_yes_no(title, message)
        return "yes" if result else "no"

    def _ask_input_tool(title: str, prompt: str, default: str = "") -> str:
        from src.automation.dialog import ask_input
        result = ask_input(title, prompt, default)
        return result if result is not None else "(cancelled)"

    def _open_file_dialog_tool(title: str = "Open File", initial_dir: str = "") -> str:
        from src.automation.dialog import open_file_dialog
        result = open_file_dialog(title=title, initial_dir=initial_dir)
        return result if result else "(cancelled)"

    def _save_file_dialog_tool(title: str = "Save File", default_name: str = "") -> str:
        from src.automation.dialog import save_file_dialog
        result = save_file_dialog(title=title, default_name=default_name)
        return result if result else "(cancelled)"

    # ── click / scroll / drag tools ───────────────────────────────────────
    def _click_tool(x: int, y: int, button: str = "left") -> str:
        from src.automation.input_sim import click
        click(x, y, button=button)
        return f"Clicked ({x},{y}) with {button} button"

    def _scroll_tool(x: int, y: int, direction: str = "down", amount: int = 3) -> str:
        from src.automation.input_sim import scroll
        scroll(x, y, direction=direction, amount=amount)
        return f"Scrolled {direction} × {amount} at ({x},{y})"

    def _drag_tool(start_x: int, start_y: int, end_x: int, end_y: int) -> str:
        from src.automation.input_sim import drag
        drag(start_x, start_y, end_x, end_y)
        return f"Dragged ({start_x},{start_y}) → ({end_x},{end_y})"

    def _generate_image_tool(
        prompt: str,
        style: str = "photo",
        size: str = "square",
        quality: str = "hd",
    ) -> str:
        from src.ai.image_generator import image_generator
        result = image_generator.generate(prompt, style=style, size=size, quality=quality)
        return (
            f"Image generated successfully!\n"
            f"Filename : {result.filename}\n"
            f"Size     : {result.width}×{result.height} px\n"
            f"Style    : {result.style}\n"
            f"Provider : {result.provider}\n"
            f"Time     : {result.generation_time}s\n"
            f"Saved to : ~/Documents/AutoMotoAI_Documents/images/{result.filename}\n"
            + (f"Revised prompt: {result.revised_prompt}" if result.revised_prompt else "")
        )

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
        ToolDefinition("read_file",
            "Read a single file and return its content. Supports PDF, DOCX, PPTX, XLSX, CSV, and all text/code formats.",
            [ToolParam("path", "string", "Absolute path of the file to read")],
            _read_file_tool),
        ToolDefinition("read_multiple_files",
            "Read multiple files concurrently and return their combined content as a structured context block. "
            "Supports PDF, DOCX, PPTX, XLSX, CSV, and text files.",
            [ToolParam("paths", "string", "Comma- or newline-separated list of absolute file paths")],
            _read_multiple_files_tool),
        ToolDefinition("summarize_files",
            "Read one or more files and return a concise structured summary of each, "
            "including metadata (page count, row count, etc.) and a content preview.",
            [ToolParam("paths", "string", "Comma- or newline-separated list of absolute file paths"),
             ToolParam("focus", "string", "Optional topic or question to focus the summary on", required=False)],
            _summarize_files_tool),
        ToolDefinition("combine_files",
            "Merge multiple source files into a single output document. "
            "The merged content is saved to ~/Documents/AutoMotoAI_Documents/ by default.",
            [ToolParam("paths", "string", "Comma- or newline-separated list of source file paths"),
             ToolParam("output_format", "string", "Output format: txt, md, html, docx, pdf, xlsx, csv", required=False,
                       enum=["txt", "md", "html", "docx", "pdf", "xlsx", "csv"]),
             ToolParam("output_path", "string", "Optional absolute output path (overrides default directory)", required=False)],
            _combine_files_tool),
        ToolDefinition("create_document",
            "Create a new document from text content and save it in the requested format. "
            "Content may use basic Markdown (# headings, **bold**, `code`).",
            [ToolParam("content", "string", "Text/Markdown content for the document"),
             ToolParam("output_format", "string", "Output format: txt, md, html, docx, pdf, xlsx, csv",
                       enum=["txt", "md", "html", "docx", "pdf", "xlsx", "csv"]),
             ToolParam("filename", "string", "Base filename without extension (optional)", required=False),
             ToolParam("output_path", "string", "Optional absolute output path", required=False)],
            _create_document_tool),
        ToolDefinition("convert_document",
            "Convert an existing file from its current format to a different output format.",
            [ToolParam("source_path", "string", "Absolute path of the source file"),
             ToolParam("target_format", "string", "Target format: txt, md, html, docx, pdf, xlsx, csv",
                       enum=["txt", "md", "html", "docx", "pdf", "xlsx", "csv"]),
             ToolParam("output_path", "string", "Optional absolute output path", required=False)],
            _convert_document_tool),
        ToolDefinition("generate_image",
            "Generate a professional image from a text description using DALL-E 3. "
            "Supports styles: photo, logo, poster, social, print, icon, product, character, background, infographic. "
            "Sizes: square (1:1), landscape (16:9), portrait (9:16). "
            "Quality: hd or standard. The image is saved to ~/Documents/AutoMotoAI_Documents/images/.",
            [ToolParam("prompt", "string", "Detailed description of the image to generate"),
             ToolParam("style", "string",
                       "Visual style preset: photo, logo, poster, social, print, icon, product, character, background, infographic",
                       required=False,
                       enum=["photo", "logo", "poster", "social", "print", "icon",
                             "product", "character", "background", "infographic"]),
             ToolParam("size", "string", "Canvas size: square (1:1), landscape (16:9), portrait (9:16)",
                       required=False, enum=["square", "landscape", "portrait"]),
             ToolParam("quality", "string", "Generation quality: hd or standard",
                       required=False, enum=["hd", "standard"])],
            _generate_image_tool),
        # ── voice ──────────────────────────────────────────────────────────
        ToolDefinition("speak",
            "Synthesize text as speech and save to a WAV audio file. "
            "Uses espeak, pyttsx3, or festival depending on what is installed.",
            [ToolParam("text", "string", "Text to synthesize"),
             ToolParam("rate", "integer", "Speech rate in words per minute (default 175)", required=False)],
            _speak_tool),
        ToolDefinition("listen",
            "Record audio from the microphone and return the transcribed text. "
            "Requires a connected microphone and PyAudio.",
            [ToolParam("timeout", "integer", "Max seconds to wait for speech (default 10)", required=False)],
            _listen_tool),
        ToolDefinition("transcribe_audio",
            "Transcribe an audio file (WAV/MP3/OGG) to text using OpenAI Whisper or Google STT.",
            [ToolParam("audio_path", "string", "Absolute path to the audio file"),
             ToolParam("language", "string", "Language code (e.g. en, fr, de)", required=False)],
            _transcribe_tool),
        # ── window management ───────────────────────────────────────────────
        ToolDefinition("list_windows",
            "Return the titles of all visible windows on the desktop.",
            [], _list_windows_tool),
        ToolDefinition("focus_window",
            "Bring a window to the foreground by its title.",
            [ToolParam("title", "string", "Full or partial window title")],
            _focus_window_tool),
        ToolDefinition("minimize_window",
            "Minimize (hide to taskbar) a window by its title.",
            [ToolParam("title", "string", "Full or partial window title")],
            _minimize_window_tool),
        ToolDefinition("maximize_window",
            "Maximize a window to fill the screen.",
            [ToolParam("title", "string", "Full or partial window title")],
            _maximize_window_tool),
        ToolDefinition("close_window",
            "Close a window gracefully by its title.",
            [ToolParam("title", "string", "Full or partial window title")],
            _close_window_tool),
        # ── GUI dialogs ─────────────────────────────────────────────────────
        ToolDefinition("show_dialog",
            "Display a GUI message dialog on the desktop (info, warning, or error).",
            [ToolParam("title", "string", "Dialog window title"),
             ToolParam("message", "string", "Message body text"),
             ToolParam("kind", "string", "Dialog type: info, warning, or error",
                       required=False, enum=["info", "warning", "error"])],
            _show_dialog_tool),
        ToolDefinition("ask_yes_no",
            "Display a Yes/No GUI dialog and return the user's answer.",
            [ToolParam("title", "string", "Dialog window title"),
             ToolParam("message", "string", "Question to display")],
            _ask_yes_no_tool),
        ToolDefinition("ask_input_dialog",
            "Show a GUI text-input dialog and return what the user typed.",
            [ToolParam("title", "string", "Dialog window title"),
             ToolParam("prompt", "string", "Prompt message shown above the input field"),
             ToolParam("default", "string", "Pre-filled default value", required=False)],
            _ask_input_tool),
        ToolDefinition("open_file_dialog",
            "Show a native file-picker dialog so the user can select a file to open. "
            "Returns the absolute path of the chosen file.",
            [ToolParam("title", "string", "Dialog title", required=False),
             ToolParam("initial_dir", "string", "Starting directory", required=False)],
            _open_file_dialog_tool),
        ToolDefinition("save_file_dialog",
            "Show a native save-file dialog and return the path chosen by the user.",
            [ToolParam("title", "string", "Dialog title", required=False),
             ToolParam("default_name", "string", "Default filename", required=False)],
            _save_file_dialog_tool),
        # ── mouse actions ───────────────────────────────────────────────────
        ToolDefinition("mouse_click",
            "Simulate a mouse click at screen coordinates (x, y).",
            [ToolParam("x", "integer", "X coordinate in pixels"),
             ToolParam("y", "integer", "Y coordinate in pixels"),
             ToolParam("button", "string", "Mouse button: left, middle, or right",
                       required=False, enum=["left", "middle", "right"])],
            _click_tool, requires_confirmation=True),
        ToolDefinition("mouse_scroll",
            "Scroll the mouse wheel at (x, y).",
            [ToolParam("x", "integer", "X coordinate"),
             ToolParam("y", "integer", "Y coordinate"),
             ToolParam("direction", "string", "Scroll direction: up or down",
                       required=False, enum=["up", "down", "left", "right"]),
             ToolParam("amount", "integer", "Number of scroll clicks (default 3)", required=False)],
            _scroll_tool, requires_confirmation=True),
        ToolDefinition("mouse_drag",
            "Click and drag from one screen position to another.",
            [ToolParam("start_x", "integer", "Start X coordinate"),
             ToolParam("start_y", "integer", "Start Y coordinate"),
             ToolParam("end_x", "integer", "End X coordinate"),
             ToolParam("end_y", "integer", "End Y coordinate")],
            _drag_tool, requires_confirmation=True),
    ]
    for t in tools:
        reg.register(t)
    return reg


tool_registry: ToolRegistry = _build_default_registry()
