"""The v4 "Cousin" router: one ``ask()`` call, many AIs, automatic failover.

Order of attempts
-----------------
1. ``prefer`` (per call) or ``AI_PROVIDER`` from the environment, if it has a key.
2. The provider recommended for the task (``recommend_provider``).
3. Every other configured provider by ``priority``.

Providers without a key are never tried. When the request needs vision (an image
is attached, or ``need_vision=True``) providers with ``supports_vision=False``
are skipped. Any failure (rate limit, 5xx, auth, timeout, empty reply, bad
model id) moves on to the next provider; the result lists everything tried.
"""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from automoto import config
from automoto import providers as _prov
from automoto.providers import REGISTRY, ProviderError, ProviderSpec, complete, has_images

log = logging.getLogger("automoto.router")
log.addHandler(logging.NullHandler())

# ---------------------------------------------------------------------------
# Task heuristic
# ---------------------------------------------------------------------------
VISION_HINTS = re.compile(
    r"\b(screenshot|screen ?shot|on my screen|what'?s on (my|the) screen|image|photo|picture|pic|ocr|"
    r"read (this|the) (text|receipt|doc)|diagram|chart|ui|ux|design|mockup|logo|figma|camera|scan)\b",
    re.I,
)
CODE_HINTS = re.compile(
    r"\b(code|coding|bug|debug|stack ?trace|traceback|refactor|function|class|api|regex|sql|python|"
    r"javascript|typescript|rust|java|c\+\+|dockerfile|kubernetes|unit test|algorithm|architecture|"
    r"prove|reason|analy[sz]e|plan|essay|report|security review|threat model)\b",
    re.I,
)


def classify_task(task_hint: str | None, *, has_image: bool = False) -> str:
    """Return ``"vision"``, ``"code"`` (deep/long reasoning) or ``"chat"`` (quick)."""
    hint = task_hint or ""
    if has_image or VISION_HINTS.search(hint):
        return "vision"
    if CODE_HINTS.search(hint) or len(hint) > 600:
        return "code"
    return "chat"


def _rank(spec: ProviderSpec, task: str) -> tuple:
    if task == "vision":
        return (-spec.strength, spec.priority)
    if task == "code":
        return (-spec.strength, -spec.speed, spec.priority)
    return (-spec.speed, spec.priority)  # quick chat: fastest first


def recommend_provider(task_hint: str = "", *, has_image: bool = False,
                       keys: dict[str, str] | None = None, only_configured: bool = True) -> str | None:
    """Best provider id for a task hint (among configured providers by default)."""
    task = classify_task(task_hint, has_image=has_image)
    pool = [p for p in REGISTRY.values() if not only_configured or p.key(keys)]
    if task == "vision":
        pool = [p for p in pool if p.supports_vision]
    if not pool:
        return None
    return sorted(pool, key=lambda p: _rank(p, task))[0].id


# ---------------------------------------------------------------------------
# Retries: a busy model (429/5xx/timeout) gets a couple more tries before failover
# ---------------------------------------------------------------------------
MAX_WAIT_S = 8.0  # longest single wait; a longer Retry-After means "fail over now"
_sleep = time.sleep  # tests replace this


def retry_count() -> int:
    try:
        return max(0, min(5, int(config.env("AUTOMOTO_RETRIES", "2") or 2)))
    except ValueError:
        return 2


def retry_budget_s() -> float:
    try:
        return max(0.0, float(config.env("AUTOMOTO_RETRY_BUDGET_S", "20") or 20))
    except ValueError:
        return 20.0


def backoff_delay(attempt: int, retry_after: float | None = None) -> float:
    """Wait before retry ``attempt`` (1, 2, ...): Retry-After if given, else exponential + jitter."""
    if retry_after is not None:
        return min(max(retry_after, 0.0), MAX_WAIT_S)
    base = 0.75 * (2 ** (attempt - 1))
    return min(base + random.uniform(0, base / 2), MAX_WAIT_S)  # nosec B311 - jitter, not security


class _Budget:
    def __init__(self) -> None:
        self.left = retry_budget_s()


def _call(fn: Callable[[], Any], budget: _Budget) -> Any:
    """Run one provider call, retrying the same model on transient errors (with backoff)."""
    tries = retry_count()
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except ProviderError as exc:
            exc.attempts = attempt
            if not getattr(exc, "transient", False) or attempt > tries:
                raise
            if exc.retry_after is not None and exc.retry_after > MAX_WAIT_S:
                raise  # the provider asked for a long pause: switch model/provider instead
            wait = backoff_delay(attempt, exc.retry_after)
            if wait > budget.left:
                raise
            budget.left -= wait
            log.info("%s busy (%s); retry %d in %.1fs", exc.provider, exc.status or "timeout", attempt, wait)
            _sleep(wait)


# ---------------------------------------------------------------------------
# ask()
# ---------------------------------------------------------------------------
class NoProviderError(RuntimeError):
    """No provider with a key (or none that supports vision) is available."""


FREE_BACKUP_HINT = ("Add a free backup key so one provider can't stop you: Gemini "
                    "(https://aistudio.google.com/apikey -> GEMINI_API_KEY) or Groq "
                    "(https://console.groq.com/keys -> GROQ_API_KEY).")


def explain_failures(tried: list[dict[str, Any]]) -> list[str]:
    """Plain-language lines (one per provider) plus what to do. Never contains key material."""
    by: dict[str, list[dict[str, Any]]] = {}
    for t in tried:
        if not t.get("ok"):
            by.setdefault(t["provider"], []).append(t)
    lines: list[str] = []
    for pid, ts in by.items():
        spec = REGISTRY.get(pid)
        label = spec.label if spec else pid
        signup = spec.signup_url if spec else ""
        env = (spec.env_keys[0] if spec.env_keys else "a local model") if spec else "the API key"
        missing = list(dict.fromkeys(t["model"] for t in ts if t.get("missing")))
        busy = [t for t in ts if t.get("transient")]
        if any(t.get("status") in (401, 403) for t in ts):
            bad = next(t for t in ts if t.get("status") in (401, 403))
            lines.append(f"{label}: the key was rejected ({bad['status']}) on model {bad['model']} - it is wrong, "
                         f"expired or has no access. Make a new key{' at ' + signup if signup else ''} and put it "
                         f"in {env}.")
            continue
        if busy:
            codes = "/".join(sorted({str(t.get("status") or "timeout") for t in busy}))
            n = max(t.get("attempts", 1) for t in busy) - 1
            models = ", ".join(dict.fromkeys(t["model"] for t in busy))
            what = "rate limit" if codes == "429" else "provider busy / overloaded"
            again = (f"retried {n} time{'s' if n != 1 else ''} with backoff" if n else "not retried")
            lines.append(f"{label}: {codes} = {what} (not your key) on {models} - {again}, then moved on. "
                         "Try again in a minute.")
        if missing:
            env_hint = spec.model_env if spec and spec.model_env else "the model setting"
            lines.append(f"{label}: model not available to this key (404) - tried {', '.join(missing)}. "
                         f"Run `automoto doctor` (or Settings -> Test keys) to see which models answer, then set "
                         f"{env_hint} to one of them.")
        if not busy and not missing:
            last = ts[-1]
            lines.append(f"{label}: {last.get('error', 'failed')} (model {last['model']}).")
    if _offline():
        if any(REGISTRY.get(t["provider"]) and REGISTRY[t["provider"]].local for t in tried):
            lines.append("Small local models sometimes stumble: try again, split the task into smaller steps, or pick "
                         "a bigger model in Settings > Offline AI.")
        return lines
    configured_free = {p.id for p in REGISTRY.values() if p.free_tier and p.key() and not p.local}
    if not ({"gemini", "groq"} & configured_free):
        lines.append(FREE_BACKUP_HINT)
    return lines


class AllProvidersFailed(RuntimeError):
    def __init__(self, tried: list[dict[str, Any]]):
        self.tried = tried
        self.hints = explain_failures(tried)
        detail = "; ".join(f"{t['provider']}/{t.get('model', '?')}: {t.get('error', '?')}" for t in tried if not t.get("ok"))
        super().__init__("All AI providers failed.\n" + "\n".join(f"- {h}" for h in self.hints)
                         + (f"\n(details: {detail})" if detail else ""))


@dataclass
class Answer:
    text: str
    provider: str
    model: str
    task: str
    tried: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "provider": self.provider, "model": self.model,
                "task": self.task, "tried": self.tried}


def _order_index(pid: str) -> int:
    """Position in the user's saved provider order (Settings page); unknown = after."""
    try:
        from automoto import settings

        order = settings.get("provider_order") or []
    except Exception:
        order = []
    return order.index(pid) if pid in order else len(order) + 100


def _no_provider_message() -> str:
    from automoto import local_llm

    if local_llm.offline():
        return ("Offline mode is on, but no AI is set up on this computer yet. Install Ollama and pick a model "
                "in Settings > Offline AI (see docs/OFFLINE.md), or turn Offline mode off.")
    return ("No AI provider key found. Add at least one key (e.g. NVIDIA_API_KEY, GEMINI_API_KEY, "
            "GROQ_API_KEY or OPENROUTER_API_KEY) to .env - see .env.example - or use a free offline "
            "model with Ollama (docs/OFFLINE.md).")


def plan_order(*, need_vision: bool, prefer: str | None, task: str,
               keys: dict[str, str] | None = None) -> list[ProviderSpec]:
    configured = [p for p in REGISTRY.values() if p.key(keys)]
    from automoto import local_llm

    if local_llm.offline():  # Offline mode: only AI that runs on this computer
        configured = [p for p in configured if p.local]
    if need_vision:
        configured = [p for p in configured if p.supports_vision]
    by_priority = sorted(configured, key=lambda p: (_order_index(p.id), p.priority))
    order: list[ProviderSpec] = []

    pref = (prefer or config.ai_provider() or "auto").lower()
    if pref != "auto" and pref in REGISTRY and REGISTRY[pref] in configured:
        order.append(REGISTRY[pref])

    custom = any(_order_index(p.id) < 100 for p in configured)
    rec_pool = sorted(configured, key=lambda p: _rank(p, task))
    if rec_pool and rec_pool[0] not in order and not custom:  # a saved provider order wins over the heuristic
        order.append(rec_pool[0])
    order += [p for p in by_priority if p not in order]
    return order


def ask(messages: list[dict[str, Any]] | str, *, need_vision: bool = False, prefer: str | None = None,
        task_hint: str | None = None, keys: dict[str, str] | None = None, system: str | None = None,
        transport: Callable[..., str] = complete, careful: bool = False, **gen: Any) -> Answer:
    """Send ``messages`` to the best available AI, failing over until one answers.

    ``keys`` lets a client pass per-request BYOK keys ({provider_id: key}); they are
    used for this call only and never logged.
    """
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    msgs = list(messages)
    if system and not any(m.get("role") == "system" for m in msgs):
        msgs.insert(0, {"role": "system", "content": system})

    image = has_images(msgs)
    need_vision = need_vision or image
    if task_hint is None:
        last_user = next((m for m in reversed(msgs) if m.get("role") == "user"), {})
        c = last_user.get("content", "")
        task_hint = c if isinstance(c, str) else " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    task = "vision" if need_vision else classify_task(task_hint)

    order = plan_order(need_vision=need_vision, prefer=prefer, task=task, keys=keys)
    if not order:
        if need_vision and any(p.key(keys) for p in REGISTRY.values()):
            raise NoProviderError("This needs a vision-capable AI, but none of your configured providers support images.")
        raise NoProviderError(_no_provider_message())

    tried: list[dict[str, Any]] = []
    budget = _Budget()
    for spec in order:
        # Within one provider: the (env-overridable) model for the task first, then that
        # provider's ordered fallbacks; a model that is missing for this key (404/410) is
        # remembered for an hour so later requests go straight to one that works.
        if careful and need_vision:  # e.g. office_review: a stronger vision model first
            role = "review"
        elif need_vision:
            role = "vision"
        else:
            role = "strong" if task == "code" else "text"
        models = spec.models(role)
        if not models:
            tried.append({"provider": spec.id, "model": ", ".join(spec.all_models(role)[:4]), "ok": False,
                          "status": 404, "missing": True, "ms": 0,
                          "error": "every model returned 404 in the last hour - skipped"})
            continue
        for model in models:
            t0 = time.monotonic()
            try:
                text = _call(lambda: transport(spec, msgs, model, spec.key(keys), **gen), budget)
            except ProviderError as exc:
                missing = _prov.model_missing(exc)
                if missing:
                    _prov.mark_unavailable(spec.id, model)
                tried.append({"provider": spec.id, "model": model, "ok": False, "status": exc.status,
                              "missing": missing, "transient": bool(getattr(exc, "transient", False)),
                              "attempts": getattr(exc, "attempts", 1), "error": str(exc).split(": ", 1)[-1][:200],
                              "ms": int((time.monotonic() - t0) * 1000)})
                log.warning("provider %s/%s failed (%s); trying next", spec.id, model, exc.status or "error")
                if _prov.key_rejected(exc) or exc.status == 429:
                    break  # bad key / rate-limited key: this provider's other models won't help
                continue  # missing or busy (5xx/timeout) model: try this provider's next model
            except Exception as exc:  # defensive: a transport bug must not stop failover
                tried.append({"provider": spec.id, "model": model, "ok": False, "status": None,
                              "error": f"{exc.__class__.__name__}: {str(exc)[:160]}",
                              "ms": int((time.monotonic() - t0) * 1000)})
                continue
            tried.append({"provider": spec.id, "model": model, "ok": True,
                          "ms": int((time.monotonic() - t0) * 1000)})
            return Answer(text=text, provider=spec.id, model=model, task=task, tried=tried)
    raise AllProvidersFailed(tried)


def _offline() -> bool:
    from automoto import local_llm

    return local_llm.offline()


def status(keys: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "mode": config.ai_provider(),
        "offline": _offline(),
        "providers": [p.public(keys) for p in sorted(REGISTRY.values(), key=lambda p: p.priority)],
    }


# ---------------------------------------------------------------------------
# ask_turn(): one agent step with tools, same failover rules as ask()
# ---------------------------------------------------------------------------
def tool_mode() -> str:
    m = (config.env("AUTOMOTO_TOOL_MODE", "auto") or "auto").lower()
    return m if m in ("auto", "native", "text") else "auto"


def ask_turn(messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, known: set[str],
             need_vision: bool = False, prefer: str | None = None, keys: dict[str, str] | None = None,
             transport: Callable[..., tuple[str, list]] | None = None, task_hint: str | None = None,
             exclude: set[str] | None = None, **gen: Any):
    """Ask the best available AI for the next agent step.

    Uses native tool calling when the provider supports it (``supports_tools``), else the
    JSON-in-text protocol. If a native call is rejected (400/404/422) the same model is
    retried in text mode before moving on. Any other failure fails over to the next
    provider - so a rate limit halfway through a task just switches AI and carries on.
    """
    from automoto import providers as prov
    from automoto import toolcalls as tc

    transport = transport or prov.complete_turn
    need_vision = need_vision or has_images(messages)
    if task_hint is None:
        last_user = next((m for m in reversed(messages) if m.get("role") == "user"), {})
        c = last_user.get("content", "")
        task_hint = c if isinstance(c, str) else " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    task = "vision" if need_vision else classify_task(task_hint)
    order = plan_order(need_vision=need_vision, prefer=prefer, task=task, keys=keys)
    if exclude and any(p.id not in exclude for p in order):
        order = [p for p in order if p.id not in exclude]
    if not order:
        if need_vision and any(p.key(keys) for p in REGISTRY.values()):
            raise NoProviderError("This needs a vision-capable AI, but none of your configured providers support images.")
        raise NoProviderError(_no_provider_message())
    mode_cfg = tool_mode()
    tried: list[dict[str, Any]] = []
    budget = _Budget()
    for spec in order:
        native_first = spec.supports_tools and mode_cfg != "text"
        models = spec.agent_models(vision=need_vision)
        if not models:
            tried.append({"provider": spec.id, "model": ", ".join(spec.all_models("agent")[:4]), "ok": False,
                          "status": 404, "missing": True, "ms": 0,
                          "error": "every model returned 404 in the last hour - skipped"})
            continue
        for model in models:
            if tried and tried[-1]["provider"] == spec.id and tried[-1].get("status") in (401, 403, 429):
                break  # bad or rate-limited key: don't try this provider's other models
            modes = [True, False] if native_first and mode_cfg == "auto" else [native_first]
            for native in modes:
                t0 = time.monotonic()
                try:
                    text, calls = _call(lambda: transport(spec, messages, model, spec.key(keys), tools=tools,
                                                          native=native, **gen), budget)
                except ProviderError as exc:
                    retry_text = native and exc.status in (400, 404, 422) and False in modes and exc.status != 410
                    # A native 404 may just mean "no tool calling here": retry as text first and
                    # only call the model missing when that fails too (or there is no text retry).
                    missing = _prov.model_missing(exc) and not retry_text
                    if missing:
                        _prov.mark_unavailable(spec.id, model)
                    tried.append({"provider": spec.id, "model": model, "ok": False, "status": exc.status,
                                  "mode": "native" if native else "text", "missing": missing,
                                  "transient": bool(getattr(exc, "transient", False)),
                                  "attempts": getattr(exc, "attempts", 1),
                                  "error": str(exc).split(": ", 1)[-1][:200], "ms": int((time.monotonic() - t0) * 1000)})
                    if retry_text:
                        continue  # retry this model without native tools
                    break  # next model / provider
                except Exception as exc:  # defensive
                    tried.append({"provider": spec.id, "model": model, "ok": False, "status": None,
                                  "error": f"{exc.__class__.__name__}: {str(exc)[:160]}",
                                  "ms": int((time.monotonic() - t0) * 1000)})
                    break
                if not native:
                    text, calls = tc.parse_text_calls(text, known)
                else:
                    calls = [c for c in calls if c.get("name")]
                    if not calls and text:  # some models answer natively but in text form
                        text, calls = tc.parse_text_calls(text, known)
                tried.append({"provider": spec.id, "model": model, "ok": True, "mode": "native" if native else "text",
                              "ms": int((time.monotonic() - t0) * 1000)})
                return tc.Turn(text=text, tool_calls=calls, provider=spec.id, model=model,
                               mode="native" if native else "text", tried=tried)
    raise AllProvidersFailed(tried)
