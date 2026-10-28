"""Runtime settings, read from the environment (and an optional local .env file).

Keys are BYOK: nothing is baked in. Keys never leave this machine except in the
request to the provider you chose.
"""

from __future__ import annotations

import os

try:  # python-dotenv is optional at import time (tests don't need it)
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

PLACEHOLDER_PREFIXES = ("your_", "replace", "changeme", "xxx", "<")


def env(name: str, default: str | None = None) -> str | None:
    val = os.getenv(name)
    if val is None:
        return default
    val = val.strip()
    return val or default


def real_key(value: str | None) -> str | None:
    """Return the key if it looks real, else None (ignores .env.example placeholders)."""
    if not value:
        return None
    low = value.strip().lower()
    if any(low.startswith(p) for p in PLACEHOLDER_PREFIXES):
        return None
    return value.strip()


def ai_provider() -> str:
    # AI_PROVIDER is the v4 name; DEFAULT_AI_PROVIDER kept for v2/v3 .env files.
    return (env("AI_PROVIDER") or env("DEFAULT_AI_PROVIDER") or "auto").lower()


def temperature() -> float:
    try:
        return float(env("AI_TEMPERATURE", "0.4"))
    except ValueError:
        return 0.4


def max_tokens() -> int:
    try:
        return int(env("AI_MAX_TOKENS", "1500"))
    except ValueError:
        return 1500


def agent_max_tokens() -> int:
    """Agent steps can carry a whole document spec in one tool call, so they get a bigger budget."""
    try:
        return int(env("AI_AGENT_MAX_TOKENS", "") or max(max_tokens(), 8000))
    except ValueError:
        return 8000


def timeout_s() -> float:
    try:
        return float(env("AI_TIMEOUT", "45"))
    except ValueError:
        return 45.0


def desktop_enabled() -> bool:
    return (env("AUTOMOTO_ENABLE_DESKTOP", "1") or "1").lower() in ("1", "true", "yes", "on")


def mask(key: str | None) -> str:
    """Safe-to-log representation of a key: never the full value."""
    if not key:
        return "-"
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}…{key[-2:]}"
