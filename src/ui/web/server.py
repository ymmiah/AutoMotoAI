"""Flask web server — REST API + SSE streaming consumed by the browser SPA."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

from src.ai.base import Message
from src.ai.registry import AIRegistry, EVT_DONE, EVT_ERROR, EVT_TOKEN, EVT_TOOL_CALL, EVT_TOOL_RESULT
from src.automation.files import (
    create_directory,
    create_file,
    delete_path,
    get_drives,
    list_directory,
    rename_path,
)
from src.automation.desktop import (
    get_installed_apps,
    open_application,
    open_in_file_manager,
    take_screenshot,
)
from src.core.config import app_config, server_config
from src.core.exceptions import (
    AutoMotoError,
    FileOperationError,
    NoProviderAvailableError,
)

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"
_registry = AIRegistry()
_conversations: dict[str, list[Message]] = {}   # session_id -> history

app = Flask(__name__, static_folder=str(_STATIC_DIR))
app.secret_key = server_config.secret_key


# ────────────────────────────── helpers ──────────────────────────────────────

def _ok(data=None, **extra):
    payload = {"ok": True}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return jsonify(payload)


def _err(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def _sse(event_type: str, data) -> str:
    """Format a single SSE frame."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# ────────────────────────────── static ───────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(_STATIC_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(_STATIC_DIR, filename)


# ────────────────────────────── info ─────────────────────────────────────────

@app.route("/api/info")
def api_info():
    return _ok({
        "name": app_config.name,
        "version": app_config.version,
        "providers": _registry.available_providers,
        "default_provider": _registry.default_provider_name if _registry.available_providers else None,
    })


# ────────────────────────────── chat (blocking) ───────────────────────────────

@app.route("/api/chat", methods=["POST"])
def api_chat():
    body = request.get_json(silent=True) or {}
    text = (body.get("message") or "").strip()
    session_id = (body.get("session_id") or "default")
    provider = body.get("provider") or None

    if not text:
        return _err("message is required")

    history = _conversations.setdefault(session_id, [])
    if not history:
        from src.core.config import ai_config
        history.append(Message("system", ai_config.system_prompt))

    history.append(Message("user", text))
    try:
        reply = _registry.chat(history, provider=provider)
        history.append(Message("assistant", reply))
        return _ok({"reply": reply, "session_id": session_id})
    except NoProviderAvailableError as exc:
        return _err(str(exc), 503)
    except AutoMotoError as exc:
        return _err(str(exc), 500)


# ────────────────────────────── chat (SSE streaming) ─────────────────────────

@app.route("/api/chat/stream", methods=["POST"])
def api_chat_stream():
    """
    SSE endpoint — yields events as the AI responds.

    Events:
      token       { "text": "…" }
      tool_call   { "name": "…", "args": {…} }
      tool_result { "name": "…", "result": "…", "success": true }
      error       { "message": "…" }
      done        { "full_reply": "…" }
    """
    body = request.get_json(silent=True) or {}
    text = (body.get("message") or "").strip()
    session_id = (body.get("session_id") or "default")
    provider = body.get("provider") or None
    use_tools = bool(body.get("use_tools", True))

    if not text:
        def _no_msg():
            yield _sse("error", {"message": "message is required"})
            yield _sse("done", {"full_reply": ""})
        return Response(stream_with_context(_no_msg()), mimetype="text/event-stream")

    history = _conversations.setdefault(session_id, [])
    if not history:
        from src.core.config import ai_config
        history.append(Message("system", ai_config.system_prompt))
    history.append(Message("user", text))

    @stream_with_context
    def generate():
        full_reply_parts: list[str] = []
        try:
            if use_tools and _registry.available_providers:
                for evt, data in _registry.stream_chat_with_tools(history, provider=provider):
                    if evt == EVT_TOKEN:
                        full_reply_parts.append(data)
                        yield _sse("token", {"text": data})
                    elif evt == EVT_TOOL_CALL:
                        yield _sse("tool_call", {"name": data["name"], "args": data.get("args", {})})
                    elif evt == EVT_TOOL_RESULT:
                        yield _sse("tool_result", {
                            "name": data["name"],
                            "result": data["result"],
                            "success": data["success"],
                        })
                    elif evt == EVT_ERROR:
                        yield _sse("error", {"message": data})
                    elif evt == EVT_DONE:
                        break
            else:
                for token in _registry.stream_chat(history, provider=provider):
                    full_reply_parts.append(token)
                    yield _sse("token", {"text": token})

            full_reply = "".join(full_reply_parts)
            if full_reply:
                history.append(Message("assistant", full_reply))
            yield _sse("done", {"full_reply": full_reply})

        except NoProviderAvailableError as exc:
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {"full_reply": ""})
        except Exception as exc:
            logger.exception("Stream error: %s", exc)
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {"full_reply": ""})

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/chat/clear", methods=["POST"])
def api_chat_clear():
    body = request.get_json(silent=True) or {}
    session_id = body.get("session_id", "default")
    _conversations.pop(session_id, None)
    return _ok()


# ────────────────────────────── filesystem ───────────────────────────────────

@app.route("/api/files/drives")
def api_drives():
    return _ok(get_drives())


@app.route("/api/files/list")
def api_list_dir():
    path = request.args.get("path", "")
    if not path:
        return _err("path is required")
    try:
        return _ok(list_directory(path))
    except FileOperationError as exc:
        return _err(str(exc))


@app.route("/api/files/create-file", methods=["POST"])
def api_create_file():
    body = request.get_json(silent=True) or {}
    path = (body.get("path") or "").strip()
    content = body.get("content", "")
    if not path:
        return _err("path is required")
    try:
        p = create_file(path, content)
        return _ok(str(p))
    except FileOperationError as exc:
        return _err(str(exc))


@app.route("/api/files/create-dir", methods=["POST"])
def api_create_dir():
    body = request.get_json(silent=True) or {}
    path = (body.get("path") or "").strip()
    if not path:
        return _err("path is required")
    try:
        p = create_directory(path)
        return _ok(str(p))
    except FileOperationError as exc:
        return _err(str(exc))


@app.route("/api/files/delete", methods=["POST"])
def api_delete():
    body = request.get_json(silent=True) or {}
    path = (body.get("path") or "").strip()
    if not path:
        return _err("path is required")
    try:
        delete_path(path)
        return _ok()
    except FileOperationError as exc:
        return _err(str(exc))


@app.route("/api/files/rename", methods=["POST"])
def api_rename():
    body = request.get_json(silent=True) or {}
    src = (body.get("src") or "").strip()
    new_name = (body.get("new_name") or "").strip()
    if not src or not new_name:
        return _err("src and new_name are required")
    try:
        p = rename_path(src, new_name)
        return _ok(str(p))
    except FileOperationError as exc:
        return _err(str(exc))


@app.route("/api/files/open-explorer", methods=["POST"])
def api_open_explorer():
    body = request.get_json(silent=True) or {}
    path = (body.get("path") or "").strip()
    if not path:
        return _err("path is required")
    try:
        open_in_file_manager(path)
        return _ok()
    except Exception as exc:
        return _err(str(exc))


# ────────────────────────────── apps ─────────────────────────────────────────

@app.route("/api/apps/list")
def api_apps_list():
    return _ok(get_installed_apps())


@app.route("/api/apps/launch", methods=["POST"])
def api_apps_launch():
    body = request.get_json(silent=True) or {}
    cmd = (body.get("cmd") or "").strip()
    if not cmd:
        return _err("cmd is required")
    try:
        open_application(cmd)
        return _ok()
    except Exception as exc:
        return _err(str(exc))


# ────────────────────────────── screenshot ───────────────────────────────────

@app.route("/api/screenshot", methods=["POST"])
def api_screenshot():
    try:
        path = take_screenshot()
        return _ok(str(path))
    except Exception as exc:
        return _err(str(exc))


# ────────────────────────────── system monitor ───────────────────────────────

@app.route("/api/monitor/snapshot")
def api_monitor_snapshot():
    try:
        from src.automation.monitor import get_system_snapshot
        return _ok(get_system_snapshot())
    except ImportError:
        return _err("psutil not installed — run: pip install psutil", 503)
    except Exception as exc:
        return _err(str(exc), 500)


@app.route("/api/monitor/processes")
def api_monitor_processes():
    limit = min(int(request.args.get("limit", 30)), 100)
    try:
        from src.automation.monitor import get_top_processes
        return _ok(get_top_processes(limit))
    except ImportError:
        return _err("psutil not installed", 503)
    except Exception as exc:
        return _err(str(exc), 500)


@app.route("/api/monitor/kill", methods=["POST"])
def api_monitor_kill():
    body = request.get_json(silent=True) or {}
    pid = body.get("pid")
    if pid is None:
        return _err("pid is required")
    try:
        from src.automation.monitor import kill_process
        msg = kill_process(int(pid))
        return _ok(msg)
    except PermissionError as exc:
        return _err(str(exc), 403)
    except Exception as exc:
        return _err(str(exc), 500)


# ────────────────────────────── documents ────────────────────────────────────

_DOC_OUT_DIR = Path.home() / "Documents" / "AutoMotoAI_Documents"


@app.route("/api/documents/read", methods=["POST"])
def api_doc_read():
    body = request.get_json(silent=True) or {}
    paths = body.get("paths") or []
    if isinstance(paths, str):
        paths = [p.strip() for p in paths.replace(",", "\n").splitlines() if p.strip()]
    if not paths:
        return _err("paths is required")
    try:
        from src.automation.document_reader import build_multi_file_context, read_multiple_files
        results = read_multiple_files(paths)
        context = build_multi_file_context(paths)
        summaries = [
            {"name": r.name, "format": r.format, "ok": r.ok,
             "meta": r.summary_meta, "error": r.error or None}
            for r in results
        ]
        return _ok({"context": context, "files": summaries})
    except Exception as exc:
        return _err(str(exc), 500)


@app.route("/api/documents/combine", methods=["POST"])
def api_doc_combine():
    body = request.get_json(silent=True) or {}
    paths = body.get("paths") or []
    if isinstance(paths, str):
        paths = [p.strip() for p in paths.replace(",", "\n").splitlines() if p.strip()]
    fmt = (body.get("output_format") or "txt").lstrip(".").lower()
    output_path = (body.get("output_path") or "").strip() or None
    if not paths:
        return _err("paths is required")
    try:
        from src.automation.document_writer import combine_documents
        out = combine_documents(paths, fmt, output_path)
        return _ok({"path": str(out), "filename": out.name})
    except Exception as exc:
        return _err(str(exc), 500)


@app.route("/api/documents/create", methods=["POST"])
def api_doc_create():
    body = request.get_json(silent=True) or {}
    content = (body.get("content") or "").strip()
    fmt = (body.get("output_format") or "txt").lstrip(".").lower()
    filename = (body.get("filename") or "").strip() or None
    output_path = (body.get("output_path") or "").strip() or None
    if not content:
        return _err("content is required")
    try:
        from src.automation.document_writer import create_document
        out = create_document(content, fmt, output_path, filename)
        return _ok({"path": str(out), "filename": out.name})
    except Exception as exc:
        return _err(str(exc), 500)


@app.route("/api/documents/convert", methods=["POST"])
def api_doc_convert():
    body = request.get_json(silent=True) or {}
    source_path = (body.get("source_path") or "").strip()
    target_fmt = (body.get("target_format") or "").lstrip(".").lower()
    output_path = (body.get("output_path") or "").strip() or None
    if not source_path or not target_fmt:
        return _err("source_path and target_format are required")
    try:
        from src.automation.document_writer import convert_document
        out = convert_document(source_path, target_fmt, output_path)
        return _ok({"path": str(out), "filename": out.name})
    except Exception as exc:
        return _err(str(exc), 500)


@app.route("/api/documents/download/<path:filename>")
def api_doc_download(filename):
    _DOC_OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = Path(filename).name   # strip any directory traversal
    target = _DOC_OUT_DIR / safe
    if not target.exists():
        return _err("file not found", 404)
    return send_from_directory(str(_DOC_OUT_DIR), safe, as_attachment=True)


# ────────────────────────────── error handlers ───────────────────────────────

@app.errorhandler(404)
def not_found(_e):
    return _err("not found", 404)


@app.errorhandler(500)
def internal_error(e):
    logger.exception("Unhandled error: %s", e)
    return _err("internal server error", 500)


# ────────────────────────────── entry ────────────────────────────────────────

def start_server():
    logger.info(
        "Web server starting at http://%s:%s",
        server_config.host,
        server_config.port,
    )
    app.run(
        host=server_config.host,
        port=server_config.port,
        debug=server_config.debug,
        use_reloader=False,
        threaded=True,
    )
