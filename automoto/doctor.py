"""``automoto doctor``: which of my configured models actually answer?

For every provider that has a key, send a tiny request (one output token) to each model
AutoMoto might use - the defaults, your env overrides and the built-in fallbacks - and
report which respond. Models that return 404/410 are marked unavailable (the router then
skips them for an hour); models that answer are cleared. Keys are never returned or logged.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from automoto import providers as prov
from automoto.providers import REGISTRY, ProviderError, ProviderSpec

ROLES = ("text", "agent", "vision", "review", "strong")
PING = [{"role": "user", "content": "Reply with: ok"}]


def _role_env(spec: ProviderSpec, role: str) -> str:
    return {"text": spec.model_env, "agent": spec.agent_env, "vision": spec.vision_env,
            "review": spec.review_env, "strong": spec.strong_env}.get(role, "")


def probe(spec: ProviderSpec, model: str, key: str, *, transport: Callable[..., str] = prov.complete,
          timeout: float = 25.0) -> dict[str, Any]:
    """One 1-token request. ``state``: ok | missing (404/410) | key (401/403) | busy (429) | error."""
    t0 = time.monotonic()
    state, status, error = "ok", None, ""
    try:
        transport(spec, PING, model, key, temperature=0, max_tokens=1, timeout=timeout)
    except ProviderError as exc:
        status, error = exc.status, str(exc).split(": ", 1)[-1][:160]
        if "empty response" in str(exc):
            state = "ok"  # it answered; one token was simply not enough for visible text
        elif prov.key_rejected(exc):
            state = "key"
        elif prov.model_missing(exc):
            state = "missing"
        elif status == 429:
            state = "busy"
        else:
            state = "error"
    except Exception as exc:  # defensive
        state, error = "error", f"{exc.__class__.__name__}: {str(exc)[:120]}"
    return {"model": model, "state": state, "ok": state in ("ok", "busy"), "status": status,
            "error": error, "ms": int((time.monotonic() - t0) * 1000)}


def check_provider(spec: ProviderSpec, key: str, *, transport: Callable[..., str] = prov.complete,
                   timeout: float = 25.0, workers: int = 4) -> dict[str, Any]:
    roles: dict[str, list[str]] = {}
    for role in ROLES:
        if role in ("vision", "review") and not spec.supports_vision:
            continue
        for m in spec.all_models(role):
            roles.setdefault(m, []).append(role)
    models = list(roles)
    results: list[dict[str, Any]] = []
    # First model alone: a rejected key fails every model, so don't spam the provider.
    first = probe(spec, models[0], key, transport=transport, timeout=timeout)
    results.append(first)
    if first["state"] != "key" and len(models) > 1:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            results += list(pool.map(lambda m: probe(spec, m, key, transport=transport, timeout=timeout), models[1:]))
    for r in results:
        r["roles"] = roles[r["model"]]
        if r["state"] == "missing":
            prov.mark_unavailable(spec.id, r["model"])
        elif r["ok"]:
            prov.clear_unavailable_model(spec.id, r["model"])
    ok = {r["model"] for r in results if r["ok"]}
    suggest: dict[str, str] = {}
    for role in ROLES:
        env = _role_env(spec, role)
        cands = [m for m in spec.all_models(role) if m in roles]
        if not env or not cands or cands[0] in ok:
            continue
        good = next((m for m in cands if m in ok), None)
        if good:
            suggest[env] = good
    key_ok = None if first["state"] == "error" else first["state"] != "key"
    return {"id": spec.id, "label": spec.label, "key_ok": key_ok, "signup_url": spec.signup_url,
            "env_key": spec.env_keys[0] if spec.env_keys else "", "models": results, "working": [r["model"] for r in results if r["ok"]],
            "suggest": suggest}


def run(keys: dict[str, str] | None = None, *, only: str | None = None,
        transport: Callable[..., str] = prov.complete, timeout: float = 25.0) -> dict[str, Any]:
    out = []
    for spec in sorted(REGISTRY.values(), key=lambda p: p.priority):
        if only and spec.id != only:
            continue
        key = spec.key(keys)
        if not key:
            continue
        out.append(check_provider(spec, key, transport=transport, timeout=timeout))
    hints = []
    for p in out:
        if p["key_ok"] is False:
            hints.append(f"{p['label']}: key rejected - make a new one at {p['signup_url']} and put it in {p['env_key']}.")
        elif not p["working"]:
            hints.append(f"{p['label']}: no model answered. Check the key's access at {p['signup_url']}.")
        for env, m in p["suggest"].items():
            hints.append(f"{p['label']}: set {env}={m}")
    if not any(p["working"] for p in out if p["id"] in ("gemini", "groq")):
        from automoto.router import FREE_BACKUP_HINT

        hints.append(FREE_BACKUP_HINT)
    return {"providers": out, "hints": hints, "configured": len(out)}
