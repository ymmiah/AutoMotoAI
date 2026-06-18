from __future__ import annotations

import logging

from src.ai.base import AIProvider, Message
from src.core.config import ai_config
from src.core.exceptions import AIProviderError

logger = logging.getLogger(__name__)


class OpenAIProvider(AIProvider):
    _client = None

    @property
    def name(self) -> str:
        return "openai"

    @property
    def is_available(self) -> bool:
        return bool(ai_config.openai_api_key)

    def _client_instance(self):
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=ai_config.openai_api_key)
            except ImportError as exc:
                raise AIProviderError("openai package not installed. Run: pip install openai") from exc
        return self._client

    def chat(self, messages: list[Message], temperature: float = 0.3, max_tokens: int = 1024) -> str:
        try:
            client = self._client_instance()
            response = client.chat.completions.create(
                model=ai_config.models["openai"],
                messages=[{"role": m.role, "content": m.content} for m in messages],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.error("OpenAI request failed: %s", exc)
            raise AIProviderError(f"OpenAI: {exc}") from exc
