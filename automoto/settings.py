"""GUI/runtime settings saved in ``~/.automoto/settings.json``.

Only non-secret preferences live here. **API keys are never accepted or stored** - BYOK keys
stay in the browser tab's sessionStorage.

Settings that change behaviour:
  * ``approval_mode`` - ask | auto | readonly (overrides ``AUTOMOTO_APPROVAL`` when set)
  * ``provider_order`` - list of provider ids; reorders auto-mode failover priority
UI-only: ``theme`` (dark | light | system), ``accent`` (#rrggbb), ``default_mode`` (agent | chat).
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from automoto import home

_LOCK = threading.Lock()
DEFAULTS: dict[str, Any] = {"theme": "dark", "accent": "#38f2a5", "default_mode": "agent",
                            "approval_mode": None, "provider_order": []}
SECRETISH = re.compile(r"(key|token|secret|password)", re.I)


class SettingsError(ValueError):
    pass


def path() -> Path:
    return home.home() / "settings.json"


def load() -> dict[str, Any]:
    p = path()
    data: dict[str, Any] = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    return {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}


def validate(patch: dict[str, Any]) -> dict[str, Any]:
    from automoto.providers import REGISTRY

    out: dict[str, Any] = {}
    for k, v in patch.items():
        if SECRETISH.search(k):
            raise SettingsError("API keys are never stored on the server - use the Keys panel (tab only)")
        if k not in DEFAULTS:
            raise SettingsError(f"unknown setting '{k}'")
        if k == "theme" and v not in ("dark", "light", "system"):
            raise SettingsError("theme must be dark, light or system")
        if k == "accent" and not (isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v)):
            raise SettingsError("accent must be a #rrggbb colour")
        if k == "default_mode" and v not in ("agent", "chat"):
            raise SettingsError("default_mode must be agent or chat")
        if k == "approval_mode" and v not in (None, "ask", "auto", "readonly"):
            raise SettingsError("approval_mode must be ask, auto or readonly")
        if k == "provider_order":
            if not isinstance(v, list) or any(p not in REGISTRY for p in v) or len(set(v)) != len(v):
                raise SettingsError("provider_order must be a list of distinct provider ids")
        out[k] = v
    return out


def update(patch: dict[str, Any]) -> dict[str, Any]:
    clean = validate(patch)
    with _LOCK:
        cur = load()
        cur.update(clean)
        p = path()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur, indent=2), encoding="utf-8")
        tmp.replace(p)
    return cur


def get(name: str) -> Any:
    return load().get(name)
