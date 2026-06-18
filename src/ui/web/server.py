"""Flask web server — REST API consumed by the browser SPA."""
from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from src.ai.base import Message
from src.ai.registry import AIRegistry
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


# ────────────────────────────── chat ─────────────────────────────────────────

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
    )
