from __future__ import annotations

import logging

from src.ai.base import AIProvider, Message
from src.core.config import ai_config
from src.core.exceptions import AIProviderError

logger = logging.getLogger(__name__)


class ClaudeProvider(AIProvider):
    _client = None

    @property
    def name(self) -> str:
        return "claude"

    @property
    def is_available(self) -> bool:
        return bool(ai_config.anthropic_api_key)

    def _client_instance(self):
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=ai_config.anthropic_api_key)
            except ImportError as exc:
                raise AIProviderError("anthropic package not installed. Run: pip install anthropic") from exc
        return self._client

    def chat(self, messages: list[Message], temperature: float = 0.3, max_tokens: int = 1024) -> str:
        try:
            client = self._client_instance()
            system_parts = [m.content for m in messages if m.role == "system"]
            chat_msgs = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
            system = " ".join(system_parts) if system_parts else ai_config.system_prompt
            response = client.messages.create(
                model=ai_config.models["claude"],
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=chat_msgs,
            )
            return response.content[0].text.strip()
        except Exception as exc:
            logger.error("Claude request failed: %s", exc)
            raise AIProviderError(f"Claude: {exc}") from exc
