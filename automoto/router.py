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
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from automoto import config
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
# ask()
# ---------------------------------------------------------------------------
class NoProviderError(RuntimeError):
    """No provider with a key (or none that supports vision) is available."""


class AllProvidersFailed(RuntimeError):
    def __init__(self, tried: list[dict[str, Any]]):
        self.tried = tried
        detail = "; ".join(f"{t['provider']}: {t.get('error', '?')}" for t in tried)
        super().__init__(f"All AI providers failed ({detail})")


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


def plan_order(*, need_vision: bool, prefer: str | None, task: str,
               keys: dict[str, str] | None = None) -> list[ProviderSpec]:
    configured = [p for p in REGISTRY.values() if p.key(keys)]
    if need_vision:
        configured = [p for p in configured if p.supports_vision]
    by_priority = sorted(configured, key=lambda p: p.priority)
    order: list[ProviderSpec] = []

    pref = (prefer or config.ai_provider() or "auto").lower()
    if pref != "auto" and pref in REGISTRY and REGISTRY[pref] in configured:
        order.append(REGISTRY[pref])

    rec_pool = sorted(configured, key=lambda p: _rank(p, task))
    if rec_pool and rec_pool[0] not in order:
        order.append(rec_pool[0])
    order += [p for p in by_priority if p not in order]
    return order


def ask(messages: list[dict[str, Any]] | str, *, need_vision: bool = False, prefer: str | None = None,
        task_hint: str | None = None, keys: dict[str, str] | None = None, system: str | None = None,
        transport: Callable[..., str] = complete, **gen: Any) -> Answer:
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
        raise NoProviderError(
            "No AI provider key found. Add at least one key (e.g. NVIDIA_API_KEY, GEMINI_API_KEY, "
            "GROQ_API_KEY or OPENROUTER_API_KEY) to .env - see .env.example."
        )

    tried: list[dict[str, Any]] = []
    for spec in order:
        # Within one provider: try the task-specific model first, then its default
        # (e.g. a "strong" model that this key can't access) before moving on.
        models = [spec.model_for(vision=need_vision, strong=(task == "code"))]
        if not need_vision and models[0] != spec.model_for():
            models.append(spec.model_for())
        for model in models:
            t0 = time.monotonic()
            try:
                text = transport(spec, msgs, model, spec.key(keys), **gen)
            except ProviderError as exc:
                tried.append({"provider": spec.id, "model": model, "ok": False, "status": exc.status,
                              "error": str(exc).split(": ", 1)[-1][:200],
                              "ms": int((time.monotonic() - t0) * 1000)})
                log.warning("provider %s/%s failed (%s); trying next", spec.id, model, exc.status or "error")
                continue
            except Exception as exc:  # defensive: a transport bug must not stop failover
                tried.append({"provider": spec.id, "model": model, "ok": False, "status": None,
                              "error": f"{exc.__class__.__name__}: {str(exc)[:160]}",
                              "ms": int((time.monotonic() - t0) * 1000)})
                continue
            tried.append({"provider": spec.id, "model": model, "ok": True,
                          "ms": int((time.monotonic() - t0) * 1000)})
            return Answer(text=text, provider=spec.id, model=model, task=task, tried=tried)
    raise AllProvidersFailed(tried)


def status(keys: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "mode": config.ai_provider(),
        "providers": [p.public(keys) for p in sorted(REGISTRY.values(), key=lambda p: p.priority)],
    }
