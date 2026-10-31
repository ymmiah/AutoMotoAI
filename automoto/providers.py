"""Provider registry for AutoMoto AI v4.

Every provider sits behind one interface: ``complete(spec, messages, model, key)``.
Messages use the OpenAI chat format; images are ``{"type": "image_url",
"image_url": {"url": "data:image/png;base64,..."}}`` content parts and are
converted per provider.

Vision flags are decided per provider *default vision model*, based on what those
models actually accept (checked against provider model catalogues in Oct 2026).
Every model id can be overridden from the environment, e.g. ``NIM_MODEL``.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from automoto import config


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    env_keys: tuple[str, ...]
    kind: str  # "openai_compat" | "anthropic"
    base_url: str | None
    text_model: str
    vision_model: str | None
    strong_model: str | None
    supports_vision: bool
    supports_tools: bool
    supports_streaming: bool
    free_tier: bool
    priority: int  # lower = tried earlier in auto mode
    speed: int  # 1 (slow) .. 5 (very fast) - used by the task heuristic
    strength: int  # 1 (basic) .. 5 (frontier) - used by the task heuristic
    model_env: str = ""
    vision_env: str = ""
    strong_env: str = ""
    agent_model: str | None = None  # model tried first for tool-calling agent steps
    agent_env: str = ""
    review_model: str | None = None  # stronger vision model for careful page/layout reviews
    review_env: str = ""
    signup_url: str = ""
    notes: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)
    # Ordered backup models per role ("text", "strong", "vision", "review", "agent"). Tried, in
    # order, after the (env-overridable) default when a model is missing for this key (404/410).
    fallbacks: dict[str, tuple[str, ...]] = field(default_factory=dict)
    local: bool = False  # runs on this computer (Ollama / llama.cpp): no key, works offline

    # -- resolved (env-overridable) values ---------------------------------
    def key(self, overrides: dict[str, str] | None = None) -> str | None:
        if self.local:
            from automoto import local_llm

            return "local" if local_llm.enabled(self.id) else None
        if overrides:
            k = config.real_key(overrides.get(self.id))
            if k:
                return k
        for name in self.env_keys:
            k = config.real_key(config.env(name))
            if k:
                return k
        return None

    def url(self) -> str | None:
        """Base URL for openai-compatible calls (local servers read theirs from the environment)."""
        if self.id == "ollama":
            from automoto import local_llm

            return local_llm.ollama_url() + "/v1"
        if self.id == "local":
            from automoto import local_llm

            return local_llm.local_server_url()
        return self.base_url

    def model_for(self, *, vision: bool = False, strong: bool = False) -> str:
        if self.id == "ollama":
            from automoto import local_llm

            return local_llm.ollama_model()
        if vision and self.supports_vision:
            return (config.env(self.vision_env) if self.vision_env else None) or self.vision_model or self.text_model
        if strong:
            s = (config.env(self.strong_env) if self.strong_env else None) or self.strong_model
            if s:
                return s
        return (config.env(self.model_env) if self.model_env else None) or self.text_model

    def all_models(self, role: str = "text") -> list[str]:
        """Every model for a role, in order: env override / default first, then the fallbacks.

        Roles: ``text`` (quick chat), ``strong`` (deep reasoning), ``vision`` (image attached),
        ``review`` (careful vision review), ``agent`` (tool-calling step), ``agent_vision``.
        Models currently marked unavailable are *not* filtered here - see :meth:`models`.
        """
        fb = self.fallbacks
        if role == "vision" or role == "agent_vision":
            if not self.supports_vision:
                return self.all_models("agent" if role == "agent_vision" else "text")
            order = [self.model_for(vision=True), *fb.get("vision", ())]
            if role == "agent_vision":
                order.append(self.model_for())
        elif role == "review":
            rm = (config.env(self.review_env) if self.review_env else None) or self.review_model
            order = [rm, *fb.get("review", ()), *self.all_models("vision")]
        elif role == "strong":
            order = [self.model_for(strong=True), self.model_for(), *fb.get("strong", ()), *self.all_models("text")]
        elif role == "agent":
            first = (config.env(self.agent_env) if self.agent_env else None) or self.agent_model
            order = [first, *fb.get("agent", ()), *self.all_models("text")]
        else:
            order = [self.model_for(), *fb.get("text", ())]
        return list(dict.fromkeys(m for m in order if m))

    def models(self, role: str = "text") -> list[str]:
        """Like :meth:`all_models` but without models that recently returned 404/410 for us."""
        return [m for m in self.all_models(role) if not is_unavailable(self.id, m)]

    def agent_models(self, *, vision: bool = False) -> list[str]:
        """Models to try, in order, for an agent (tool-calling) step."""
        return self.models("agent_vision" if vision else "agent")

    def public(self, overrides: dict[str, str] | None = None) -> dict[str, Any]:
        """Status dict that is safe to send to a UI (no key material)."""
        return {
            "id": self.id,
            "label": self.label,
            "configured": self.key(overrides) is not None,
            "env_keys": list(self.env_keys),
            "supports_vision": self.supports_vision,
            "supports_tools": self.supports_tools,
            "supports_streaming": self.supports_streaming,
            "free_tier": self.free_tier,
            "priority": self.priority,
            "text_model": self.model_for(),
            "vision_model": self.model_for(vision=True) if self.supports_vision else None,
            "strong_model": self.model_for(strong=True) if self.model_for(strong=True) != self.model_for() else None,
            "agent_model": self.all_models("agent")[0],
            "unavailable": [m for m in self.all_models("agent") + self.all_models("review") if is_unavailable(self.id, m)],
            "signup_url": self.signup_url,
            "notes": self.notes,
            "local": self.local,
        }


REGISTRY: dict[str, ProviderSpec] = {
    p.id: p
    for p in [
        ProviderSpec(
            id="nim",
            label="NVIDIA NIM",
            env_keys=("NVIDIA_API_KEY", "NIM_API_KEY"),
            kind="openai_compat",
            base_url="https://integrate.api.nvidia.com/v1",
            text_model="meta/llama-3.2-11b-vision-instruct",
            vision_model="meta/llama-3.2-11b-vision-instruct",
            strong_model=None,  # set NIM_STRONG_MODEL to opt in; free-tier availability varies
            supports_vision=True,
            supports_tools=True,
            supports_streaming=True,
            free_tier=True,
            priority=10,
            speed=3,
            strength=3,
            model_env="NIM_MODEL",
            vision_env="NIM_VISION_MODEL",
            strong_env="NIM_STRONG_MODEL",
            agent_model="nvidia/nemotron-3.5-super-vl-120b-a12b",
            agent_env="NIM_AGENT_MODEL",
            review_model="nvidia/nemotron-3.5-super-vl-120b-a12b",
            review_env="NIM_REVIEW_MODEL",
            signup_url="https://build.nvidia.com",
            notes="Free dev credits. Default Llama 3.2 11B Vision is verified live; it takes 1 image per request. "
                  "Which models a key may call varies, so 404s fall back through the lists below.",
            # From the public catalogue (GET https://integrate.api.nvidia.com/v1/models, Oct 2026);
            # widely available free chat models first. Unverified per key - 404s are skipped.
            fallbacks={
                "text": ("openai/gpt-oss-20b", "deepseek-ai/deepseek-v4.1-flash", "mistralai/mistral-large-2-instruct",
                         "nvidia/nemotron-3-super-120b-a12b", "nvidia/llama-3.1-nemotron-70b-instruct",
                         "google/gemma-3-12b-it"),
                "agent": ("nvidia/nemotron-3-super-120b-a12b", "openai/gpt-oss-20b", "deepseek-ai/deepseek-v4.1-flash",
                          "mistralai/mistral-large-2-instruct", "nvidia/llama-3.1-nemotron-70b-instruct"),
                "vision": ("meta/llama-3.2-90b-vision-instruct", "nvidia/nemotron-3.5-super-vl-120b-a12b",
                           "microsoft/phi-3-vision-128k-instruct"),
                "review": ("meta/llama-3.2-90b-vision-instruct",),
            },
        ),
        ProviderSpec(
            id="gemini",
            label="Google Gemini",
            env_keys=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            kind="openai_compat",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            text_model="gemini-flash-latest",
            vision_model="gemini-flash-latest",
            strong_model="gemini-pro-latest",
            supports_vision=True,
            supports_tools=True,
            supports_streaming=True,
            free_tier=True,
            priority=20,
            speed=4,
            strength=4,
            model_env="GEMINI_MODEL",
            vision_env="GEMINI_VISION_MODEL",
            strong_env="GEMINI_STRONG_MODEL",
            agent_env="GEMINI_AGENT_MODEL",
            signup_url="https://aistudio.google.com/apikey",
            notes="Free tier via AI Studio. Uses Google's OpenAI-compatible endpoint.",
            # Current ids from https://ai.google.dev/gemini-api/docs/models (Oct 2026). A busy (503)
            # or missing model moves to the next one; Flash-Lite is the lightest, most available.
            fallbacks={
                "text": ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"),
                "strong": ("gemini-3.8-flash",),
                "vision": ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"),
            },
        ),
        ProviderSpec(
            id="groq",
            label="Groq",
            env_keys=("GROQ_API_KEY",),
            kind="openai_compat",
            base_url="https://api.groq.com/openai/v1",
            text_model="openai/gpt-oss-20b",
            vision_model="qwen/qwen3.8-27b",
            strong_model="openai/gpt-oss-120b",
            supports_vision=True,
            supports_tools=True,
            supports_streaming=True,
            free_tier=True,
            priority=30,
            speed=5,
            strength=3,
            model_env="GROQ_MODEL",
            vision_env="GROQ_VISION_MODEL",
            strong_env="GROQ_STRONG_MODEL",
            agent_model="openai/gpt-oss-120b",
            agent_env="GROQ_AGENT_MODEL",
            signup_url="https://console.groq.com/keys",
            notes="Fastest free tier. Vision model is a Groq *preview* model.",
            # Ids from https://console.groq.com/docs/models (Oct 2026).
            fallbacks={
                "text": ("llama-3.3-70b-versatile", "qwen/qwen3-32b", "llama-3.1-8b-instant"),
                "strong": ("llama-3.3-70b-versatile", "moonshotai/kimi-k2-instruct"),
                "agent": ("llama-3.3-70b-versatile", "qwen/qwen3-32b"),
                "vision": ("meta-llama/llama-4-scout-17b-16e-instruct", "qwen/qwen3.6-27b"),
            },
        ),
        ProviderSpec(
            id="openrouter",
            label="OpenRouter (free)",
            env_keys=("OPENROUTER_API_KEY",),
            kind="openai_compat",
            base_url="https://openrouter.ai/api/v1",
            text_model="openrouter/free",
            vision_model="google/gemma-4-31b-it:free",
            strong_model="nvidia/nemotron-3-ultra-550b-a55b:free",
            supports_vision=True,
            supports_tools=False,
            supports_streaming=True,
            free_tier=True,
            priority=40,
            speed=2,
            strength=3,
            model_env="OPENROUTER_MODEL",
            vision_env="OPENROUTER_VISION_MODEL",
            strong_env="OPENROUTER_STRONG_MODEL",
            agent_env="OPENROUTER_AGENT_MODEL",
            signup_url="https://openrouter.ai/keys",
            notes="':free' models are rate-limited; 'openrouter/free' auto-picks a free model.",
            # ':free' ids from GET https://openrouter.ai/api/v1/models (Oct 2026).
            fallbacks={
                "text": ("nvidia/nemotron-3.5-lightning:free", "google/gemma-4-31b-it:free"),
                "strong": ("nvidia/nemotron-3.5-super-vl:free",),
                "vision": ("google/gemma-4-26b-a4b-it:free", "nvidia/nemotron-3.5-super-vl:free"),
            },
            extra_headers={"HTTP-Referer": "https://github.com/ymmiah/AutoMotoAI", "X-Title": "AutoMoto AI"},
        ),
        ProviderSpec(
            id="openai",
            label="OpenAI",
            env_keys=("OPENAI_API_KEY",),
            kind="openai_compat",
            base_url=None,
            text_model="gpt-5.4-mini",
            vision_model="gpt-5.4-mini",
            strong_model="gpt-5.5",
            supports_vision=True,
            supports_tools=True,
            supports_streaming=True,
            free_tier=False,
            priority=50,
            speed=4,
            strength=5,
            model_env="OPENAI_MODEL",
            vision_env="OPENAI_VISION_MODEL",
            strong_env="OPENAI_STRONG_MODEL",
            agent_env="OPENAI_AGENT_MODEL",
            signup_url="https://platform.openai.com/api-keys",
            notes="Paid. Used only if you add a key.",
        ),
        ProviderSpec(
            id="claude",
            label="Anthropic Claude",
            env_keys=("ANTHROPIC_API_KEY",),
            kind="anthropic",
            base_url=None,
            text_model="claude-haiku-4-5",
            vision_model="claude-haiku-4-5",
            strong_model="claude-sonnet-4-6",
            supports_vision=True,
            supports_tools=True,
            supports_streaming=True,
            free_tier=False,
            priority=60,
            speed=3,
            strength=5,
            model_env="CLAUDE_MODEL",
            vision_env="CLAUDE_VISION_MODEL",
            strong_env="CLAUDE_STRONG_MODEL",
            agent_env="CLAUDE_AGENT_MODEL",
            signup_url="https://console.anthropic.com/",
            notes="Paid. Used only if you add a key.",
        ),
        ProviderSpec(
            id="ollama",
            label="Ollama (on this computer)",
            env_keys=(),
            kind="openai_compat",
            base_url=None,
            text_model="qwen2.5:3b",
            vision_model=None,
            strong_model=None,
            supports_vision=False,
            supports_tools=True,
            supports_streaming=True,
            free_tier=True,
            priority=90,
            speed=2,
            strength=2,
            model_env="OLLAMA_MODEL",
            signup_url="https://ollama.com/download",
            notes="Free and private. Runs on your computer, works offline. Pick a model in Settings.",
            local=True,
        ),
        ProviderSpec(
            id="local",
            label="Local server (llama.cpp / LM Studio)",
            env_keys=(),
            kind="openai_compat",
            base_url=None,
            text_model="local-model",
            vision_model=None,
            strong_model=None,
            supports_vision=False,
            supports_tools=True,
            supports_streaming=True,
            free_tier=True,
            priority=95,
            speed=2,
            strength=2,
            model_env="LOCAL_LLM_MODEL",
            signup_url="https://github.com/ggml-org/llama.cpp",
            notes="Any OpenAI-compatible server on this computer. Set LOCAL_LLM_URL (and LOCAL_LLM_MODEL).",
            local=True,
        ),
    ]
}

# BLACKBOX was a v2/v3 provider. Its old endpoint is not a documented public
# chat API, so it is removed in v4 rather than shipped as a fake integration.


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ProviderError(Exception):
    """A provider call failed. ``retryable`` tells the router to try the next one."""

    def __init__(self, provider: str, message: str, *, status: int | None = None, retryable: bool = True,
                 retry_after: float | None = None, transient: bool | None = None):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after  # seconds, from a Retry-After header when the provider sent one
        # Busy/overloaded/timeout: worth retrying the *same* model after a short wait.
        self.transient = (status in TRANSIENT_STATUSES) if transient is None else transient
        self.attempts = 1


TRANSIENT_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


# ---------------------------------------------------------------------------
# Model availability: a model that returns 404/410 for this key is skipped for a while
# ---------------------------------------------------------------------------
UNAVAILABLE_TTL_S = 3600.0
_UNAVAILABLE: dict[tuple[str, str], float] = {}
_UNAVAILABLE_LOCK = threading.Lock()

_MODEL_MISSING = re.compile(
    r"(model|function)[^.;]{0,80}(not found|not exist|does not exist|unavailable|not available|"
    r"decommissioned|deprecated|no longer|retired)|"
    r"no such model|unknown model|invalid model|not a valid model|no endpoints found|"
    r"model_not_found|NotFoundError|Error code: 404|Error code: 410",
    re.I,
)


def mark_unavailable(provider: str, model: str, ttl: float | None = None) -> None:
    with _UNAVAILABLE_LOCK:
        _UNAVAILABLE[(provider, model)] = time.monotonic() + (UNAVAILABLE_TTL_S if ttl is None else ttl)


def is_unavailable(provider: str, model: str) -> bool:
    with _UNAVAILABLE_LOCK:
        until = _UNAVAILABLE.get((provider, model))
        if until is None:
            return False
        if until <= time.monotonic():
            _UNAVAILABLE.pop((provider, model), None)
            return False
        return True


def clear_unavailable(provider: str | None = None) -> None:
    with _UNAVAILABLE_LOCK:
        for k in [k for k in _UNAVAILABLE if provider is None or k[0] == provider]:
            _UNAVAILABLE.pop(k, None)


def clear_unavailable_model(provider: str, model: str) -> None:
    with _UNAVAILABLE_LOCK:
        _UNAVAILABLE.pop((provider, model), None)


def unavailable_models() -> list[tuple[str, str]]:
    return [k for k in list(_UNAVAILABLE) if is_unavailable(*k)]


def model_missing(exc: Exception) -> bool:
    """True when an error means "this model is not available to this key" (404/410 or the
    provider's words for it), as opposed to a bad key, a rate limit or a timeout."""
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    if status in (404, 410):
        return True
    if status in (401, 403, 429) or (isinstance(status, int) and status >= 500):
        return False
    return bool(_MODEL_MISSING.search(str(exc)))


def key_rejected(exc: Exception) -> bool:
    return (getattr(exc, "status", None) or getattr(exc, "status_code", None)) in (401, 403)


def has_images(messages: list[dict[str, Any]]) -> bool:
    for m in messages:
        c = m.get("content")
        if isinstance(c, list) and any(isinstance(p, dict) and p.get("type") == "image_url" for p in c):
            return True
    return False


def strip_images(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            text = "\n".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
            out.append({**m, "content": text})
        else:
            out.append(m)
    return out


def _retry_after(exc: Exception) -> float | None:
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if not headers:
        return None
    try:
        ms = headers.get("retry-after-ms")
        if ms:
            return max(0.0, float(ms) / 1000)
        v = headers.get("retry-after")
        if v:
            return max(0.0, float(v))
    except (TypeError, ValueError):  # an HTTP date: not worth parsing, fall back to our backoff
        return None
    return None


_TIMEOUTISH = re.compile(r"timeout|timed out|connection (error|reset|aborted|refused)|temporarily unavailable|overloaded", re.I)


def _classify(provider: str, exc: Exception) -> ProviderError:
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    # Bad request (400/422) is usually our payload, but a different provider may accept it,
    # so everything is retryable; the router decides how far to go.
    msg = str(exc).splitlines()[0][:240] if str(exc) else exc.__class__.__name__
    transient = status in TRANSIENT_STATUSES or (status is None and bool(
        _TIMEOUTISH.search(f"{exc.__class__.__name__} {msg}")))
    return ProviderError(provider, f"{exc.__class__.__name__}: {msg}", status=status, retryable=True,
                         retry_after=_retry_after(exc), transient=transient)


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------
def _timeout(spec: ProviderSpec, timeout: float) -> float:
    """A model on a laptop CPU is slow: give local AI much longer (LOCAL_AI_TIMEOUT, default 600 s)."""
    if not spec.local:
        return timeout
    try:
        return max(float(timeout or 0), float(config.env("LOCAL_AI_TIMEOUT", "600")))
    except ValueError:
        return 600.0


def _openai_compat(spec: ProviderSpec, messages, model, key, *, temperature, max_tokens, timeout) -> str:
    from openai import OpenAI

    client = OpenAI(
        api_key=key,
        base_url=spec.url(),
        timeout=_timeout(spec, timeout),
        max_retries=0,  # failover is the router's job
        default_headers=spec.extra_headers or None,
    )
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    choice = resp.choices[0] if resp.choices else None
    text = (choice.message.content or "").strip() if choice and choice.message else ""
    if spec.local:
        from automoto.local_llm import strip_thinking

        text = strip_thinking(text)
    if not text:
        raise ProviderError(spec.id, "empty response", retryable=True)
    return text


def _to_anthropic(messages):
    system_parts, out = [], []
    for m in messages:
        role, content = m.get("role"), m.get("content")
        if role == "system":
            system_parts.append(content if isinstance(content, str) else str(content))
            continue
        if isinstance(content, list):
            blocks = []
            for p in content:
                if p.get("type") == "text":
                    blocks.append({"type": "text", "text": p.get("text", "")})
                elif p.get("type") == "image_url":
                    url = p.get("image_url", {}).get("url", "")
                    if url.startswith("data:") and ";base64," in url:
                        media, data = url[5:].split(";base64,", 1)
                        blocks.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
                    else:
                        blocks.append({"type": "image", "source": {"type": "url", "url": url}})
            content = blocks
        out.append({"role": "assistant" if role == "assistant" else "user", "content": content})
    return "\n\n".join(system_parts), out


def _anthropic(spec: ProviderSpec, messages, model, key, *, temperature, max_tokens, timeout) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=0)
    system, msgs = _to_anthropic(messages)
    kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "temperature": temperature, "messages": msgs}
    if system:
        kwargs["system"] = system
    resp = client.messages.create(**kwargs)
    text = "".join(getattr(b, "text", "") for b in resp.content).strip()
    if not text:
        raise ProviderError(spec.id, "empty response", retryable=True)
    return text


TRANSPORTS: dict[str, Callable[..., str]] = {"openai_compat": _openai_compat, "anthropic": _anthropic}


def complete(spec: ProviderSpec, messages, model: str, key: str, *, temperature: float | None = None,
             max_tokens: int | None = None, timeout: float | None = None) -> str:
    """Single call to one provider. Raises ProviderError on any failure."""
    fn = TRANSPORTS[spec.kind]
    try:
        return fn(
            spec, messages, model, key,
            temperature=config.temperature() if temperature is None else temperature,
            max_tokens=config.max_tokens() if max_tokens is None else max_tokens,
            timeout=config.timeout_s() if timeout is None else timeout,
        )
    except ProviderError:
        raise
    except Exception as exc:  # SDK errors: rate limit, 5xx, auth, timeout, connection
        raise _classify(spec.id, exc) from None


# ---------------------------------------------------------------------------
# Agent turns (tool calling)
# ---------------------------------------------------------------------------
def _openai_turn(spec: ProviderSpec, messages, model, key, *, tools, native, temperature, max_tokens, timeout):
    from openai import OpenAI

    from automoto import toolcalls as tc

    client = OpenAI(api_key=key, base_url=spec.url(), timeout=_timeout(spec, timeout), max_retries=0,
                    default_headers=spec.extra_headers or None)
    kwargs: dict[str, Any] = {"model": model, "temperature": temperature, "max_tokens": max_tokens}
    if native and tools:
        kwargs["messages"] = tc.render_openai(messages, provider=spec.id)
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    else:
        kwargs["messages"] = tc.render_text(messages, tools)
    resp = client.chat.completions.create(**kwargs)
    choice = resp.choices[0] if resp.choices else None
    if not choice or not choice.message:
        raise ProviderError(spec.id, "empty response")
    text, calls = tc.parse_openai_message(choice.message)
    if spec.local and text:
        from automoto.local_llm import strip_thinking

        text = strip_thinking(text)
    for c in calls:
        c["provider"] = spec.id  # a provider-specific "extra" (Gemini signature) is only replayed to it
    return text, calls


def _anthropic_turn(spec: ProviderSpec, messages, model, key, *, tools, native, temperature, max_tokens, timeout):
    import anthropic

    from automoto import toolcalls as tc

    client = anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=0)
    if native and tools:
        system, msgs = tc.render_anthropic(messages, _to_anthropic)
    else:
        system, msgs = _to_anthropic(tc.render_text(messages, tools))
    kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "temperature": temperature, "messages": msgs}
    if system:
        kwargs["system"] = system
    if native and tools:
        kwargs["tools"] = tc.anthropic_tools(tools)
    resp = client.messages.create(**kwargs)
    text, calls = "", []
    for b in resp.content:
        if getattr(b, "type", "") == "text":
            text += b.text
        elif getattr(b, "type", "") == "tool_use":
            calls.append({"id": b.id, "name": b.name, "arguments": dict(b.input or {})})
    return text.strip(), calls


TURN_TRANSPORTS: dict[str, Callable[..., tuple[str, list]]] = {"openai_compat": _openai_turn, "anthropic": _anthropic_turn}


def complete_turn(spec: ProviderSpec, messages, model: str, key: str, *, tools: list[dict[str, Any]] | None,
                  native: bool, temperature: float | None = None, max_tokens: int | None = None,
                  timeout: float | None = None) -> tuple[str, list[dict[str, Any]]]:
    """One agent step on one provider -> (text, native_tool_calls). Raises ProviderError."""
    fn = TURN_TRANSPORTS[spec.kind]
    for attempt in (1, 2):  # reasoning models occasionally return nothing: retry the same model once
        try:
            text, calls = fn(spec, messages, model, key, tools=tools, native=native,
                             temperature=config.temperature() if temperature is None else temperature,
                             max_tokens=config.agent_max_tokens() if max_tokens is None else max_tokens,
                             timeout=config.timeout_s() if timeout is None else timeout)
        except ProviderError as exc:
            if attempt == 1 and "empty response" in str(exc):
                continue
            raise
        except Exception as exc:
            raise _classify(spec.id, exc) from None
        if text or calls:
            return text, calls
    raise ProviderError(spec.id, "empty response")
