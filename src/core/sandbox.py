"""
Sandboxed execution environment for AI tool calls.

Provides four layers of protection:

1. Execution timeout
   Each tool call is executed in a worker thread via
   concurrent.futures.ThreadPoolExecutor.  If it exceeds TOOL_TIMEOUT_SECONDS
   the future is cancelled and a TimeoutError is raised.

2. Resource tracking
   A per-session ResourceGuard counts file-write operations and cumulative
   bytes written.  Thresholds are configurable via environment variables.

3. Path allowlist
   File-operating tools may only access paths under the user's home directory
   by default.  Override with SANDBOX_ALLOWED_PATHS (colon-separated).

4. Subprocess environment sanitisation
   Any subprocess spawned by tools inherits a stripped environment that does
   NOT include API keys, session tokens, or other sensitive variables.

Configuration (env vars)
------------------------
  SANDBOX_TOOL_TIMEOUT    integer seconds  (default 60)
  SANDBOX_MAX_FILES       max file writes per session  (default 200)
  SANDBOX_MAX_BYTES       max bytes written per session  (default 500 MB)
  SANDBOX_ALLOWED_PATHS   colon-separated allowed path prefixes
"""
from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── configuration ─────────────────────────────────────────────────────────────

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (ValueError, TypeError):
        return default

TOOL_TIMEOUT_SECONDS: int = _env_int("SANDBOX_TOOL_TIMEOUT", 60)
MAX_FILES_PER_SESSION: int = _env_int("SANDBOX_MAX_FILES", 200)
MAX_BYTES_PER_SESSION: int = _env_int("SANDBOX_MAX_BYTES", 500 * 1024 * 1024)

def _allowed_paths() -> list[Path]:
    raw = os.getenv("SANDBOX_ALLOWED_PATHS", "")
    if raw:
        return [Path(p).expanduser().resolve() for p in raw.split(":") if p.strip()]
    return [Path.home().resolve()]


# ── sensitive env vars to strip from child processes ─────────────────────────

_STRIP_ENV_PREFIXES = (
    "OPENAI_", "GEMINI_", "ANTHROPIC_", "BLACKBOX_",
    "AUTOMOTO_", "FLASK_SECRET", "AWS_", "AZURE_", "GCP_",
)


def clean_env() -> dict[str, str]:
    """Return a copy of os.environ with sensitive keys removed."""
    return {
        k: v for k, v in os.environ.items()
        if not any(k.upper().startswith(p) for p in _STRIP_ENV_PREFIXES)
    }


# ── resource guard ────────────────────────────────────────────────────────────

_session_guards: dict[str, "ResourceGuard"] = {}
_guards_lock = threading.Lock()


class ResourceGuard:
    """Track file-write operations for a single session."""

    def __init__(self, session_id: str) -> None:
        self._id      = session_id
        self._files   = 0
        self._bytes   = 0
        self._lock    = threading.Lock()

    def record_write(self, byte_count: int = 0) -> None:
        with self._lock:
            self._files += 1
            self._bytes += byte_count
            if self._files > MAX_FILES_PER_SESSION:
                raise PermissionError(
                    f"Sandbox limit: session has written more than {MAX_FILES_PER_SESSION} files."
                )
            if self._bytes > MAX_BYTES_PER_SESSION:
                raise PermissionError(
                    f"Sandbox limit: session has written more than {MAX_BYTES_PER_SESSION // (1024*1024)} MB."
                )

    def stats(self) -> dict:
        with self._lock:
            return {
                "files_written": self._files,
                "bytes_written": self._bytes,
                "files_limit":   MAX_FILES_PER_SESSION,
                "bytes_limit":   MAX_BYTES_PER_SESSION,
            }


def get_guard(session_id: str) -> ResourceGuard:
    with _guards_lock:
        if session_id not in _session_guards:
            _session_guards[session_id] = ResourceGuard(session_id)
        return _session_guards[session_id]


def reset_guard(session_id: str) -> None:
    with _guards_lock:
        _session_guards.pop(session_id, None)


# ── path check ────────────────────────────────────────────────────────────────

def check_path(path: str | Path) -> Path:
    """
    Resolve *path* and verify it falls under an allowed prefix.
    Raises PermissionError if the path is outside the allowlist.
    """
    resolved = Path(path).expanduser().resolve()
    allowed  = _allowed_paths()
    if any(str(resolved).startswith(str(a)) for a in allowed):
        return resolved
    raise PermissionError(
        f"Sandbox: path '{resolved}' is outside the allowed directories: "
        + ", ".join(str(a) for a in allowed)
    )


# ── execution with timeout ────────────────────────────────────────────────────

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="sandbox-")


def execute_with_timeout(
    fn: Callable[..., Any],
    *args: Any,
    timeout: int | None = None,
    **kwargs: Any,
) -> Any:
    """
    Run *fn(*args, **kwargs)* in a sandboxed thread pool.
    Raises TimeoutError if execution exceeds *timeout* seconds.
    """
    t = timeout or TOOL_TIMEOUT_SECONDS
    future = _executor.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=t)
    except FuturesTimeout:
        future.cancel()
        raise TimeoutError(
            f"Tool execution timed out after {t}s"
        )


# ── sandbox status ────────────────────────────────────────────────────────────

def status() -> dict:
    return {
        "tool_timeout_s":        TOOL_TIMEOUT_SECONDS,
        "max_files_per_session": MAX_FILES_PER_SESSION,
        "max_bytes_per_session": MAX_BYTES_PER_SESSION,
        "allowed_paths":         [str(p) for p in _allowed_paths()],
        "active_sessions":       len(_session_guards),
    }
