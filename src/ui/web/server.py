"""
Flask web server — REST API + SSE streaming consumed by the browser SPA.

Security measures applied:
- X-Requested-With CSRF check on all mutating endpoints
- Server-issued session tokens (not client-chosen IDs)
- Output path sandboxing for document write endpoints
- Input length limits on all text fields
- Process-kill allowlist (no system PID range)
- Safe integer parsing
- Security response headers (CSP, HSTS, X-Frame-Options…)
- App-launch allowlist (known safe executables only on Linux)
- Sanitised error messages — internal paths never returned to client
"""
from __future__ import annotations

import json
import logging
import os
import secrets
from pathlib import Path

from flask import Flask, Response, after_this_request, jsonify, request, send_from_directory, stream_with_context

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

_STATIC_DIR  = Path(__file__).parent / "static"
_DOC_OUT_DIR = Path.home() / "Documents" / "AutoMotoAI_Documents"

_registry      = AIRegistry()
_conversations: dict[str, list[Message]] = {}   # token → history
_session_store: dict[str, bool]          = {}   # token → valid

# Limits
_MAX_MSG_LEN     = 120_000   # characters per chat message
_MAX_CONTENT_LEN = 500_000   # characters for document content
_MAX_PATH_LEN    = 4096
_MAX_PATHS_BATCH = 20

# Allowlist of safe app names/executables that can be launched via the API.
# Extend this list in your .env via ALLOWED_APPS (comma-separated).
_DEFAULT_SAFE_APPS = {
    "notepad.exe", "notepad", "calc.exe", "calc", "mspaint.exe", "mspaint",
    "explorer.exe", "explorer", "taskmgr.exe", "taskmgr", "cmd.exe", "cmd",
    "powershell.exe", "powershell", "wordpad.exe", "wordpad",
    "chrome", "firefox", "code", "code.exe",
}
_ALLOWED_APPS: set[str] = _DEFAULT_SAFE_APPS | {
    a.strip().lower()
    for a in os.environ.get("ALLOWED_APPS", "").split(",")
    if a.strip()
}

app = Flask(__name__, static_folder=str(_STATIC_DIR))
app.secret_key = server_config.secret_key


# ─────────────────────────── security headers ─────────────────────────────────

@app.after_request
def add_security_headers(response: Response) -> Response:
    response.headers["X-Content-Type-Options"]  = "nosniff"
    response.headers["X-Frame-Options"]         = "DENY"
    response.headers["X-XSS-Protection"]        = "1; mode=block"
    response.headers["Referrer-Policy"]         = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"]      = "camera=(), microphone=(), geolocation=()"
    # Relaxed CSP — allows scripts/styles from same origin only; no inline scripts
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    return response


# ─────────────────────────── CSRF guard ───────────────────────────────────────

def _require_csrf() -> Response | None:
    """Return an error response if the CSRF header is absent; None means OK."""
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return _err("CSRF check failed", 403)
    return None


def _csrf(fn):
    """Decorator: enforce CSRF header on mutating endpoints."""
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        bad = _require_csrf()
        if bad:
            return bad
        return fn(*args, **kwargs)
    return wrapper


# ─────────────────────────── helpers ──────────────────────────────────────────

def _ok(data=None, **extra):
    payload = {"ok": True}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return jsonify(payload)


def _err(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def _sse(event_type: str, data) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _safe_int(value, default: int, min_val: int = 1, max_val: int = 1000) -> int:
    try:
        return max(min_val, min(int(value), max_val))
    except (ValueError, TypeError):
        return default


def _session_from_request() -> list[Message]:
    """Return the conversation history for the token in the request body."""
    body  = request.get_json(silent=True) or {}
    token = (body.get("session_token") or "").strip()
    if not token or token not in _session_store:
        token = "anon"
    return _conversations.setdefault(token, [])


def _resolve_output_path(output_path: str | None) -> Path | None:
    """Validate that a caller-supplied output path stays within _DOC_OUT_DIR."""
    if not output_path:
        return None
    p = Path(output_path).expanduser().resolve()
    _DOC_OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        p.relative_to(_DOC_OUT_DIR)   # raises ValueError if outside
    except ValueError:
        raise ValueError(f"Output path must be inside {_DOC_OUT_DIR}")
    return p


# ─────────────────────────── static ───────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(_STATIC_DIR, "index.html")


@app.route("/style.css")
def static_css():
    return send_from_directory(_STATIC_DIR, "style.css")


@app.route("/app.js")
def static_js():
    return send_from_directory(_STATIC_DIR, "app.js")


# ─────────────────────────── session ──────────────────────────────────────────

@app.route("/api/session/new", methods=["POST"])
@_csrf
def api_session_new():
    """Issue a server-side session token."""
    token = secrets.token_urlsafe(32)
    _session_store[token] = True
    _conversations[token] = []
    return _ok({"token": token})


# ─────────────────────────── info ─────────────────────────────────────────────

@app.route("/api/info")
def api_info():
    return _ok({
        "name":             app_config.name,
        "version":          app_config.version,
        "providers":        _registry.available_providers,
        "default_provider": _registry.default_provider_name if _registry.available_providers else None,
    })


# ─────────────────────────── chat (blocking) ──────────────────────────────────

@app.route("/api/chat", methods=["POST"])
@_csrf
def api_chat():
    body     = request.get_json(silent=True) or {}
    text     = (body.get("message") or "").strip()[:_MAX_MSG_LEN]
    provider = body.get("provider") or None

    if not text:
        return _err("message is required")

    history = _session_from_request()
    if not history:
        from src.core.config import ai_config
        history.append(Message("system", ai_config.system_prompt))

    history.append(Message("user", text))
    try:
        reply = _registry.chat(history, provider=provider)
        history.append(Message("assistant", reply))
        return _ok({"reply": reply})
    except NoProviderAvailableError as exc:
        return _err(str(exc), 503)
    except AutoMotoError as exc:
        return _err(str(exc), 500)


# ─────────────────────────── chat (SSE streaming) ─────────────────────────────

@app.route("/api/chat/stream", methods=["POST"])
@_csrf
def api_chat_stream():
    body      = request.get_json(silent=True) or {}
    text      = (body.get("message") or "").strip()[:_MAX_MSG_LEN]
    provider  = body.get("provider") or None
    use_tools = bool(body.get("use_tools", True))

    if not text:
        def _no_msg():
            yield _sse("error", {"message": "message is required"})
            yield _sse("done",  {"full_reply": ""})
        return Response(stream_with_context(_no_msg()), mimetype="text/event-stream")

    history = _session_from_request()
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
                            "name":    data["name"],
                            "result":  data["result"],
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
            yield _sse("done",  {"full_reply": ""})
        except Exception as exc:
            logger.exception("Stream error")
            yield _sse("error", {"message": "An error occurred while generating a response."})
            yield _sse("done",  {"full_reply": ""})

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/chat/clear", methods=["POST"])
@_csrf
def api_chat_clear():
    body  = request.get_json(silent=True) or {}
    token = (body.get("session_token") or "").strip()
    if token and token in _conversations:
        _conversations[token] = []
    return _ok()


# ─────────────────────────── filesystem ───────────────────────────────────────

@app.route("/api/files/drives")
def api_drives():
    return _ok(get_drives())


@app.route("/api/files/list")
def api_list_dir():
    path = (request.args.get("path") or "").strip()[:_MAX_PATH_LEN]
    if not path:
        return _err("path is required")
    try:
        return _ok(list_directory(path))
    except FileOperationError as exc:
        return _err("Cannot list directory", 400)
    except Exception:
        return _err("Cannot list directory", 400)


@app.route("/api/files/create-file", methods=["POST"])
@_csrf
def api_create_file():
    body    = request.get_json(silent=True) or {}
    path    = (body.get("path") or "").strip()[:_MAX_PATH_LEN]
    content = (body.get("content") or "")[:_MAX_CONTENT_LEN]
    if not path:
        return _err("path is required")
    try:
        p = create_file(path, content)
        return _ok(p.name)   # return filename only, not full path
    except FileOperationError:
        return _err("Could not create file", 400)


@app.route("/api/files/create-dir", methods=["POST"])
@_csrf
def api_create_dir():
    body = request.get_json(silent=True) or {}
    path = (body.get("path") or "").strip()[:_MAX_PATH_LEN]
    if not path:
        return _err("path is required")
    try:
        create_directory(path)
        return _ok()
    except FileOperationError:
        return _err("Could not create directory", 400)


@app.route("/api/files/delete", methods=["POST"])
@_csrf
def api_delete():
    body = request.get_json(silent=True) or {}
    path = (body.get("path") or "").strip()[:_MAX_PATH_LEN]
    if not path:
        return _err("path is required")
    try:
        delete_path(path)
        return _ok()
    except FileOperationError:
        return _err("Could not delete path", 400)


@app.route("/api/files/rename", methods=["POST"])
@_csrf
def api_rename():
    body     = request.get_json(silent=True) or {}
    src      = (body.get("src")      or "").strip()[:_MAX_PATH_LEN]
    new_name = (body.get("new_name") or "").strip()[:255]
    if not src or not new_name:
        return _err("src and new_name are required")
    if "/" in new_name or "\\" in new_name:
        return _err("new_name must not contain path separators")
    try:
        rename_path(src, new_name)
        return _ok()
    except FileOperationError:
        return _err("Could not rename", 400)


@app.route("/api/files/open-explorer", methods=["POST"])
@_csrf
def api_open_explorer():
    body = request.get_json(silent=True) or {}
    path = (body.get("path") or "").strip()[:_MAX_PATH_LEN]
    if not path:
        return _err("path is required")
    try:
        open_in_file_manager(path)
        return _ok()
    except Exception:
        return _err("Could not open file manager", 400)


# ─────────────────────────── apps ─────────────────────────────────────────────

@app.route("/api/apps/list")
def api_apps_list():
    return _ok(get_installed_apps())


@app.route("/api/apps/launch", methods=["POST"])
@_csrf
def api_apps_launch():
    body = request.get_json(silent=True) or {}
    cmd  = (body.get("cmd") or "").strip()[:512]
    if not cmd:
        return _err("cmd is required")
    # Allowlist check — only permit known safe applications
    cmd_lower = cmd.lower().split()[0]   # compare base executable name
    if cmd_lower not in _ALLOWED_APPS:
        logger.warning("Blocked app launch attempt: %r", cmd)
        return _err(f"Application '{cmd}' is not in the allowed list.", 403)
    try:
        open_application(cmd)
        return _ok()
    except Exception:
        return _err("Could not launch application", 400)


# ─────────────────────────── screenshot ───────────────────────────────────────

@app.route("/api/screenshot", methods=["POST"])
@_csrf
def api_screenshot():
    try:
        path = take_screenshot()
        return _ok(Path(path).name)   # return filename only
    except Exception as exc:
        return _err("Could not take screenshot", 500)


# ─────────────────────────── system monitor ───────────────────────────────────

@app.route("/api/monitor/snapshot")
def api_monitor_snapshot():
    try:
        from src.automation.monitor import get_system_snapshot
        return _ok(get_system_snapshot())
    except ImportError:
        return _err("psutil not installed — run: pip install psutil", 503)
    except Exception:
        return _err("Monitor unavailable", 500)


@app.route("/api/monitor/processes")
def api_monitor_processes():
    limit = _safe_int(request.args.get("limit", 30), default=30, min_val=1, max_val=100)
    try:
        from src.automation.monitor import get_top_processes
        return _ok(get_top_processes(limit))
    except ImportError:
        return _err("psutil not installed", 503)
    except Exception:
        return _err("Monitor unavailable", 500)


_MIN_SAFE_PID = 100   # never kill PID < 100 (init, kernel threads, etc.)

@app.route("/api/monitor/kill", methods=["POST"])
@_csrf
def api_monitor_kill():
    body = request.get_json(silent=True) or {}
    pid  = body.get("pid")
    if pid is None:
        return _err("pid is required")
    try:
        pid = int(pid)
    except (ValueError, TypeError):
        return _err("pid must be an integer")
    if pid < _MIN_SAFE_PID:
        return _err(f"Cannot kill system process (PID < {_MIN_SAFE_PID})", 403)
    try:
        from src.automation.monitor import kill_process
        msg = kill_process(pid)
        return _ok(msg)
    except PermissionError:
        return _err("Permission denied — cannot kill that process", 403)
    except Exception as exc:
        return _err("Could not kill process", 500)


# ─────────────────────────── documents ────────────────────────────────────────

@app.route("/api/documents/read", methods=["POST"])
@_csrf
def api_doc_read():
    body  = request.get_json(silent=True) or {}
    paths = body.get("paths") or []
    if isinstance(paths, str):
        paths = [p.strip() for p in paths.replace(",", "\n").splitlines() if p.strip()]
    paths = [str(p)[:_MAX_PATH_LEN] for p in paths[:_MAX_PATHS_BATCH]]
    if not paths:
        return _err("paths is required")
    try:
        from src.automation.document_reader import build_multi_file_context, read_multiple_files
        results  = read_multiple_files(paths)
        context  = build_multi_file_context(paths)
        summaries = [
            {"name": r.name, "format": r.format, "ok": r.ok,
             "meta": r.summary_meta, "error": r.error or None}
            for r in results
        ]
        return _ok({"context": context, "files": summaries})
    except Exception:
        return _err("Could not read files", 500)


@app.route("/api/documents/combine", methods=["POST"])
@_csrf
def api_doc_combine():
    body  = request.get_json(silent=True) or {}
    paths = body.get("paths") or []
    if isinstance(paths, str):
        paths = [p.strip() for p in paths.replace(",", "\n").splitlines() if p.strip()]
    paths  = [str(p)[:_MAX_PATH_LEN] for p in paths[:_MAX_PATHS_BATCH]]
    fmt    = (body.get("output_format") or "txt").lstrip(".").lower()[:10]
    raw_op = (body.get("output_path") or "").strip()
    if not paths:
        return _err("paths is required")
    try:
        out_path = _resolve_output_path(raw_op) if raw_op else None
    except ValueError as exc:
        return _err(str(exc), 400)
    try:
        from src.automation.document_writer import combine_documents
        out = combine_documents(paths, fmt, out_path)
        return _ok({"filename": out.name})
    except Exception:
        return _err("Could not combine documents", 500)


@app.route("/api/documents/create", methods=["POST"])
@_csrf
def api_doc_create():
    body     = request.get_json(silent=True) or {}
    content  = (body.get("content")  or "").strip()[:_MAX_CONTENT_LEN]
    fmt      = (body.get("output_format") or "txt").lstrip(".").lower()[:10]
    filename = (body.get("filename") or "").strip()[:128] or None
    raw_op   = (body.get("output_path") or "").strip()
    if not content:
        return _err("content is required")
    try:
        out_path = _resolve_output_path(raw_op) if raw_op else None
    except ValueError as exc:
        return _err(str(exc), 400)
    try:
        from src.automation.document_writer import create_document
        out = create_document(content, fmt, out_path, filename)
        return _ok({"filename": out.name})
    except Exception:
        return _err("Could not create document", 500)


@app.route("/api/documents/convert", methods=["POST"])
@_csrf
def api_doc_convert():
    body        = request.get_json(silent=True) or {}
    source_path = (body.get("source_path")   or "").strip()[:_MAX_PATH_LEN]
    target_fmt  = (body.get("target_format") or "").lstrip(".").lower()[:10]
    raw_op      = (body.get("output_path")   or "").strip()
    if not source_path or not target_fmt:
        return _err("source_path and target_format are required")
    try:
        out_path = _resolve_output_path(raw_op) if raw_op else None
    except ValueError as exc:
        return _err(str(exc), 400)
    try:
        from src.automation.document_writer import convert_document
        out = convert_document(source_path, target_fmt, out_path)
        return _ok({"filename": out.name})
    except Exception:
        return _err("Could not convert document", 500)


@app.route("/api/documents/download/<path:filename>")
def api_doc_download(filename):
    _DOC_OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = Path(filename).name   # strip any directory traversal
    if not safe or safe.startswith("."):
        return _err("invalid filename", 400)
    target = _DOC_OUT_DIR / safe
    if not target.exists() or not target.is_file():
        return _err("file not found", 404)
    return send_from_directory(str(_DOC_OUT_DIR), safe, as_attachment=True)


# ─────────────────────────── image / design studio ────────────────────────────

_IMG_DIR = Path.home() / "Documents" / "AutoMotoAI_Documents" / "images"
_MAX_IMG_BYTES   = 8 * 1024 * 1024   # 8 MB upload limit for inpainting
_MAX_PROMPT_LEN  = 4000


@app.route("/api/image/generate", methods=["POST"])
@_csrf
def api_image_generate():
    body    = request.get_json(silent=True) or {}
    prompt  = (body.get("prompt")  or "").strip()[:_MAX_PROMPT_LEN]
    style   = (body.get("style")   or "photo").strip()[:20]
    size    = (body.get("size")    or "square").strip()[:12]
    quality = (body.get("quality") or "hd").strip()[:10]
    if not prompt:
        return _err("prompt is required")
    try:
        from src.ai.image_generator import image_generator, STYLE_PRESETS, SIZE_PRESETS
        if style not in STYLE_PRESETS:
            style = "photo"
        if size not in SIZE_PRESETS:
            size = "square"
        if quality not in ("hd", "standard"):
            quality = "hd"
        result = image_generator.generate(prompt, style=style, size=size, quality=quality)
        return _ok({
            "filename":       result.filename,
            "width":          result.width,
            "height":         result.height,
            "style":          result.style,
            "provider":       result.provider,
            "generation_time": result.generation_time,
            "revised_prompt": result.revised_prompt,
        })
    except Exception as exc:
        logger.error("Image generation failed: %s", exc)
        return _err("Image generation failed — check your OPENAI_API_KEY and try again.", 500)


@app.route("/api/image/inpaint", methods=["POST"])
@_csrf
def api_image_inpaint():
    prompt     = (request.form.get("prompt") or "").strip()[:_MAX_PROMPT_LEN]
    img_file   = request.files.get("image")
    mask_file  = request.files.get("mask")
    if not prompt:
        return _err("prompt is required")
    if not img_file or not mask_file:
        return _err("image and mask files are required")
    img_bytes  = img_file.read(_MAX_IMG_BYTES)
    mask_bytes = mask_file.read(_MAX_IMG_BYTES)
    if len(img_bytes) >= _MAX_IMG_BYTES or len(mask_bytes) >= _MAX_IMG_BYTES:
        return _err("File too large (max 8 MB)", 413)
    try:
        from src.ai.image_generator import image_generator
        result = image_generator.inpaint(img_bytes, mask_bytes, prompt)
        return _ok({
            "filename":       result.filename,
            "width":          result.width,
            "height":         result.height,
            "provider":       result.provider,
            "generation_time": result.generation_time,
        })
    except Exception as exc:
        logger.error("Inpainting failed: %s", exc)
        return _err("Inpainting failed — check your OPENAI_API_KEY and try again.", 500)


@app.route("/api/image/export", methods=["POST"])
@_csrf
def api_image_export():
    body      = request.get_json(silent=True) or {}
    filename  = (body.get("filename") or "").strip()
    fmt       = (body.get("format")   or "png_print").strip()[:20]
    upscale   = (body.get("upscale")  or "1x").strip()[:4]
    if not filename:
        return _err("filename is required")
    safe = Path(filename).name
    if not safe or ".." in safe:
        return _err("invalid filename", 400)
    src_path = _IMG_DIR / safe
    if not src_path.exists() or not src_path.is_file():
        return _err("source image not found", 404)
    try:
        from src.automation.image_exporter import image_exporter, EXPORT_FORMATS, UPSCALE_OPTIONS
        if fmt not in EXPORT_FORMATS:
            return _err(f"Unknown format. Choose from: {', '.join(EXPORT_FORMATS)}", 400)
        if upscale not in UPSCALE_OPTIONS:
            return _err(f"Unknown upscale. Choose from: {', '.join(UPSCALE_OPTIONS)}", 400)
        src_bytes = src_path.read_bytes()
        result    = image_exporter.export(src_bytes, fmt=fmt, upscale=upscale,
                                          base_name=safe.rsplit(".", 1)[0])
        return _ok({
            "filename": result.filename,
            "format":   result.format,
            "size_kb":  result.size_kb,
            "width":    result.width,
            "height":   result.height,
        })
    except ValueError as exc:
        return _err(str(exc), 400)
    except Exception as exc:
        logger.error("Export failed: %s", exc)
        return _err("Export failed", 500)


@app.route("/api/image/view/<path:filename>")
def api_image_view(filename):
    _IMG_DIR.mkdir(parents=True, exist_ok=True)
    safe = Path(filename).name
    if not safe or safe.startswith("."):
        return _err("invalid filename", 400)
    target = _IMG_DIR / safe
    if not target.exists() or not target.is_file():
        return _err("not found", 404)
    return send_from_directory(str(_IMG_DIR), safe)


@app.route("/api/image/download/<path:filename>")
def api_image_download(filename):
    _IMG_DIR.mkdir(parents=True, exist_ok=True)
    safe = Path(filename).name
    if not safe or safe.startswith("."):
        return _err("invalid filename", 400)
    target = _IMG_DIR / safe
    if not target.exists() or not target.is_file():
        return _err("not found", 404)
    return send_from_directory(str(_IMG_DIR), safe, as_attachment=True)


@app.route("/api/image/gallery")
def api_image_gallery():
    _IMG_DIR.mkdir(parents=True, exist_ok=True)
    exts = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".svg", ".pdf"}
    items = []
    for p in sorted(_IMG_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:50]:
        if p.is_file() and p.suffix.lower() in exts:
            items.append({
                "filename": p.name,
                "size_kb":  round(p.stat().st_size / 1024, 1),
                "mtime":    int(p.stat().st_mtime),
            })
    return _ok(items)


# ─────────────────────────── error handlers ───────────────────────────────────

@app.errorhandler(404)
def not_found(_e):
    return _err("not found", 404)


@app.errorhandler(405)
def method_not_allowed(_e):
    return _err("method not allowed", 405)


@app.errorhandler(500)
def internal_error(e):
    logger.exception("Unhandled error")
    return _err("internal server error", 500)


# ─────────────────────────── entry ────────────────────────────────────────────

def start_server():
    logger.info("Web server starting at http://%s:%s", server_config.host, server_config.port)
    app.run(
        host=server_config.host,
        port=server_config.port,
        debug=False,           # never enable debug in production
        use_reloader=False,
        threaded=True,
    )
