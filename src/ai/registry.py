"""AI provider registry — selects and falls back across configured providers."""
from __future__ import annotations

import logging

from src.ai.base import AIProvider, Message
from src.ai.blackbox_provider import BlackboxProvider
from src.ai.claude_provider import ClaudeProvider
from src.ai.gemini_provider import GeminiProvider
from src.ai.openai_provider import OpenAIProvider
from src.core.config import ai_config
from src.core.exceptions import AIProviderError, NoProviderAvailableError

logger = logging.getLogger(__name__)

_PROVIDER_ORDER: list[AIProvider] = [
    OpenAIProvider(),
    GeminiProvider(),
    ClaudeProvider(),
    BlackboxProvider(),
]


class AIRegistry:
    """Manages provider selection and automatic fallback."""

    def __init__(self) -> None:
        self._providers: dict[str, AIProvider] = {
            p.name: p for p in _PROVIDER_ORDER if p.is_available
        }
        if self._providers:
            logger.info("Available AI providers: %s", list(self._providers))
        else:
            logger.warning("No AI providers configured — add at least one API key to .env")

    @property
    def available_providers(self) -> list[str]:
        return list(self._providers)

    @property
    def default_provider_name(self) -> str:
        if not self._providers:
            raise NoProviderAvailableError("No AI provider configured. Add an API key to .env")
        pref = ai_config.default_provider
        return pref if pref in self._providers else next(iter(self._providers))

    def chat(self, messages: list[Message], provider: str | None = None) -> str:
        if not self._providers:
            raise NoProviderAvailableError("No AI provider configured. Add an API key to .env")

        chosen = provider or self.default_provider_name
        order = [chosen] + [n for n in self._providers if n != chosen]

        last_exc: Exception = RuntimeError("No providers tried")
        for name in order:
            if name not in self._providers:
                continue
            try:
                if name != chosen:
                    logger.info("Falling back to provider '%s'", name)
                return self._providers[name].chat(
                    messages,
                    temperature=ai_config.temperature,
                    max_tokens=ai_config.max_tokens,
                )
            except AIProviderError as exc:
                logger.warning("Provider '%s' failed: %s", name, exc)
                last_exc = exc

        raise NoProviderAvailableError("All AI providers failed.") from last_exc


registry = AIRegistry()
