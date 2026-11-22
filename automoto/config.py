"""Runtime settings, read from the environment (and an optional local .env file).

Keys are BYOK: nothing is baked in. Keys never leave this machine except in the
request to the provider you chose.
"""

from __future__ import annotations

import os



def env_files() -> list[str]:
    """The .env files AutoMoto reads, first one wins for each key (real environment variables beat all):
    1. ``.env`` in the current folder (or a parent), 2. ``.env`` next to a source checkout,
    3. ``~/.automoto/.env`` (or ``$AUTOMOTO_DATA_DIR/.env``) - the place for pip / pipx installs."""
    try:
        from dotenv import find_dotenv
    except Exception:  # pragma: no cover
        return []
    out: list[str] = []
    for p in (find_dotenv(usecwd=True), find_dotenv()):
        if p and os.path.abspath(p) not in out:
            out.append(os.path.abspath(p))
    return out


def _data_env_file() -> str:
    base = os.getenv("AUTOMOTO_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".automoto")
    return os.path.abspath(os.path.join(os.path.expanduser(base), ".env"))


# Where each value read from a .env file came from: name -> (file, value). Real environment
# variables are never listed here. Used to keep project .env files from redirecting tokens.
ENV_SOURCES: dict[str, tuple[str, str]] = {}


def load_env_files() -> list[str]:
    try:  # python-dotenv is optional at import time (tests don't need it)
        from dotenv import load_dotenv
    except Exception:  # pragma: no cover
        return []
    loaded: list[str] = []

    def _load(p: str) -> bool:
        before = set(os.environ)
        ok = load_dotenv(p, override=False)
        for name in set(os.environ) - before:
            ENV_SOURCES[name] = (os.path.abspath(p), os.environ[name])
        return ok

    for p in env_files():
        if _load(p):
            loaded.append(p)
    data = _data_env_file()  # after the others, so AUTOMOTO_DATA_DIR from a local .env counts
    if data not in loaded and os.path.isfile(data) and _load(data):
        loaded.append(data)
    return loaded


def env_source(name: str) -> str | None:
    """The .env file a variable's current value came from, or None for a real environment variable."""
    src = ENV_SOURCES.get(name)
    if src and os.getenv(name) == src[1]:
        return src[0]
    return None


def env_trusted(name: str, default: str | None = None) -> str | None:
    """Like env(), but a value that came from a project/current-folder .env is ignored.

    Hosts and client IDs that decide where a token is sent may only come from a real environment
    variable or from AutoMoto's own ``~/.automoto/.env`` - never from a repository's .env."""
    src = env_source(name)
    if src is None or os.path.normcase(src) == os.path.normcase(_data_env_file()):
        return env(name, default)
    try:
        from dotenv import dotenv_values

        own = dotenv_values(_data_env_file()).get(name) if os.path.isfile(_data_env_file()) else None
    except Exception:  # pragma: no cover
        own = None
    return (own or "").strip() or default


LOADED_ENV_FILES = load_env_files()

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
