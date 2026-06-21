"""
Structured audit logging with HMAC-SHA256 integrity chain.

Every audit entry is a JSON line written to logs/audit.jsonl.
Each entry includes an HMAC that covers its own content plus the
previous entry's HMAC, forming a tamper-evident chain.

Verify integrity offline:
    python -m src.core.audit --verify

Schema per line
---------------
{
  "ts":         ISO-8601 UTC timestamp,
  "session":    first 12 hex chars of SHA-256(session_token),
  "ip":         client IP (127.0.0.1 for loopback requests),
  "method":     HTTP verb,
  "path":       request path (no query string logged),
  "action":     tool name or endpoint label,
  "result":     "ok" | "error" | "denied",
  "status":     HTTP status code (int),
  "duration_ms": round-trip time in milliseconds (int),
  "extra":      optional dict of sanitised metadata,
  "hmac":       HMAC-SHA256 hex of (serialised_entry + prev_hmac)
}
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_AUDIT_KEY_ENV = "AUTOMOTO_AUDIT_KEY"
_LOCK = threading.Lock()

# ── log key ───────────────────────────────────────────────────────────────────

def _audit_key() -> bytes:
    """
    Return the HMAC signing key for the audit chain.
    Sourced (in order of preference):
      1. AUTOMOTO_AUDIT_KEY env var
      2. ~/.automotoai/audit.key  (auto-generated on first use, chmod 600)
      3. Fallback: machine fingerprint (warn in logs)
    """
    env_val = os.getenv(_AUDIT_KEY_ENV, "")
    if env_val:
        return env_val.encode()

    key_path = Path.home() / ".automotoai" / "audit.key"
    if key_path.exists():
        return key_path.read_bytes()

    # Generate and persist
    key = os.urandom(32)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    try:
        key_path.chmod(0o600)
    except (OSError, NotImplementedError):
        pass
    logger.info("Generated new audit HMAC key at %s", key_path)
    return key


# ── log file ──────────────────────────────────────────────────────────────────

_LOG_DIR: Path | None = None
_PREV_HMAC = "genesis"   # seed for chain

def _log_file() -> Path:
    global _LOG_DIR
    if _LOG_DIR is None:
        from src.core.config import app_config
        _LOG_DIR = app_config.log_dir
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR / "audit.jsonl"


# ── HMAC computation ──────────────────────────────────────────────────────────

def _compute_hmac(payload: str, prev_hmac: str) -> str:
    key   = _audit_key()
    data  = (payload + prev_hmac).encode()
    return _hmac.new(key, data, hashlib.sha256).hexdigest()


# ── session hashing ───────────────────────────────────────────────────────────

def _hash_session(token: str) -> str:
    if not token:
        return "anon"
    return hashlib.sha256(token.encode()).hexdigest()[:12]


# ── public API ────────────────────────────────────────────────────────────────

def log_action(
    *,
    session_token: str = "",
    ip: str = "127.0.0.1",
    method: str = "",
    path: str = "",
    action: str = "",
    result: str = "ok",
    status: int = 200,
    duration_ms: int = 0,
    extra: dict | None = None,
) -> None:
    """Append one tamper-evident audit entry to audit.jsonl."""
    global _PREV_HMAC
    try:
        entry: dict = {
            "ts":          datetime.now(timezone.utc).isoformat(),
            "session":     _hash_session(session_token),
            "ip":          ip,
            "method":      method,
            "path":        path,
            "action":      action,
            "result":      result,
            "status":      status,
            "duration_ms": duration_ms,
        }
        if extra:
            entry["extra"] = extra

        payload = json.dumps(entry, separators=(",", ":"), sort_keys=True)

        with _LOCK:
            mac = _compute_hmac(payload, _PREV_HMAC)
            _PREV_HMAC = mac
            entry["hmac"] = mac
            line = json.dumps(entry, separators=(",", ":")) + "\n"
            _log_file().open("a", encoding="utf-8").write(line)
    except Exception as exc:
        logger.error("Audit log write failed: %s", exc)


# ── Flask integration ─────────────────────────────────────────────────────────

def attach_to_flask(app) -> None:
    """Register before/after_request hooks on a Flask app instance."""
    import flask

    @app.before_request
    def _before():
        flask.g._t0           = time.monotonic()
        flask.g._session_tok  = ""

    @app.after_request
    def _after(response):
        try:
            elapsed_ms = int((time.monotonic() - getattr(flask.g, "_t0", time.monotonic())) * 1000)
            body = flask.request.get_json(silent=True) or {}
            tok  = (body.get("session_token") or flask.request.form.get("session_token") or "")
            result_str = "ok" if response.status_code < 400 else (
                "denied" if response.status_code in (401, 403) else "error"
            )
            log_action(
                session_token=tok or getattr(flask.g, "_session_tok", ""),
                ip=flask.request.remote_addr or "127.0.0.1",
                method=flask.request.method,
                path=flask.request.path,
                action=flask.request.endpoint or "",
                result=result_str,
                status=response.status_code,
                duration_ms=elapsed_ms,
            )
        except Exception as exc:
            logger.debug("Audit after_request error: %s", exc)
        return response


# ── integrity verification ────────────────────────────────────────────────────

def verify_log(log_path: Path | None = None) -> tuple[bool, str]:
    """
    Re-compute the HMAC chain for the audit log.
    Returns (ok, message).
    """
    path = log_path or _log_file()
    if not path.exists():
        return True, "No audit log found — nothing to verify."

    prev  = "genesis"
    count = 0
    try:
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                stored_mac = entry.pop("hmac", "")
                payload    = json.dumps(entry, separators=(",", ":"), sort_keys=True)
                expected   = _compute_hmac(payload, prev)
                if not _hmac.compare_digest(stored_mac, expected):
                    return False, f"Integrity violation at line {i}"
                prev  = stored_mac
                count += 1
    except Exception as exc:
        return False, f"Verification error: {exc}"

    return True, f"Audit log OK — {count} entries verified."


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    ok, msg = verify_log()
    print(("✓ " if ok else "✗ ") + msg)
    raise SystemExit(0 if ok else 1)
