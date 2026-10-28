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
    signup_url: str = ""
    notes: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)

    # -- resolved (env-overridable) values ---------------------------------
    def key(self, overrides: dict[str, str] | None = None) -> str | None:
        if overrides:
            k = config.real_key(overrides.get(self.id))
            if k:
                return k
        for name in self.env_keys:
            k = config.real_key(config.env(name))
            if k:
                return k
        return None

    def model_for(self, *, vision: bool = False, strong: bool = False) -> str:
        if vision and self.supports_vision:
            return (config.env(self.vision_env) if self.vision_env else None) or self.vision_model or self.text_model
        if strong:
            s = (config.env(self.strong_env) if self.strong_env else None) or self.strong_model
            if s:
                return s
        return (config.env(self.model_env) if self.model_env else None) or self.text_model

    def agent_models(self, *, vision: bool = False) -> list[str]:
        """Models to try, in order, for an agent (tool-calling) step."""
        first = (config.env(self.agent_env) if self.agent_env else None) or self.agent_model
        order = [self.model_for(vision=True)] if vision and self.supports_vision else []
        if not vision and first:
            order.append(first)
        order.append(self.model_for())
        return list(dict.fromkeys(m for m in order if m))

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
            "agent_model": self.agent_models()[0],
            "signup_url": self.signup_url,
            "notes": self.notes,
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
            signup_url="https://build.nvidia.com",
            notes="Free dev credits. Default Llama 3.2 11B Vision is verified live; it takes 1 image per request.",
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
    ]
}

# BLACKBOX was a v2/v3 provider. Its old endpoint is not a documented public
# chat API, so it is removed in v4 rather than shipped as a fake integration.


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ProviderError(Exception):
    """A provider call failed. ``retryable`` tells the router to try the next one."""

    def __init__(self, provider: str, message: str, *, status: int | None = None, retryable: bool = True):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.status = status
        self.retryable = retryable


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


def _classify(provider: str, exc: Exception) -> ProviderError:
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    # Bad request (400/422) is usually our payload, but a different provider may accept it,
    # so everything is retryable; the router decides how far to go.
    msg = str(exc).splitlines()[0][:240] if str(exc) else exc.__class__.__name__
    return ProviderError(provider, f"{exc.__class__.__name__}: {msg}", status=status, retryable=True)


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------
def _openai_compat(spec: ProviderSpec, messages, model, key, *, temperature, max_tokens, timeout) -> str:
    from openai import OpenAI

    client = OpenAI(
        api_key=key,
        base_url=spec.base_url,
        timeout=timeout,
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

    client = OpenAI(api_key=key, base_url=spec.base_url, timeout=timeout, max_retries=0,
                    default_headers=spec.extra_headers or None)
    kwargs: dict[str, Any] = {"model": model, "temperature": temperature, "max_tokens": max_tokens}
    if native and tools:
        kwargs["messages"] = tc.render_openai(messages)
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    else:
        kwargs["messages"] = tc.render_text(messages, tools)
    resp = client.chat.completions.create(**kwargs)
    choice = resp.choices[0] if resp.choices else None
    if not choice or not choice.message:
        raise ProviderError(spec.id, "empty response")
    return tc.parse_openai_message(choice.message)


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
    try:
        text, calls = fn(spec, messages, model, key, tools=tools, native=native,
                         temperature=config.temperature() if temperature is None else temperature,
                         max_tokens=config.max_tokens() if max_tokens is None else max_tokens,
                         timeout=config.timeout_s() if timeout is None else timeout)
    except ProviderError:
        raise
    except Exception as exc:
        raise _classify(spec.id, exc) from None
    if not text and not calls:
        raise ProviderError(spec.id, "empty response")
    return text, calls
