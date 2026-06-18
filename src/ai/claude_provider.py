from __future__ import annotations

import logging
from typing import Generator

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

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_tool_calling(self) -> bool:
        return True

    def _client_instance(self):
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=ai_config.anthropic_api_key)
            except ImportError as exc:
                raise AIProviderError("anthropic package not installed. Run: pip install anthropic") from exc
        return self._client

    def _split(self, messages: list[Message]):
        system = " ".join(m.content for m in messages if m.role == "system") or ai_config.system_prompt
        chat = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        return system, chat

    def chat(self, messages: list[Message], temperature: float = 0.3, max_tokens: int = 1024) -> str:
        try:
            system, chat = self._split(messages)
            resp = self._client_instance().messages.create(
                model=ai_config.models["claude"],
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=chat,
            )
            return resp.content[0].text.strip()
        except Exception as exc:
            logger.error("Claude chat failed: %s", exc)
            raise AIProviderError(f"Claude: {exc}") from exc

    def stream_chat(self, messages: list[Message], temperature: float = 0.3, max_tokens: int = 1024) -> Generator[str, None, None]:
        try:
            system, chat = self._split(messages)
            with self._client_instance().messages.stream(
                model=ai_config.models["claude"],
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=chat,
            ) as stream:
                for text in stream.text_stream:
                    yield text
        except Exception as exc:
            logger.error("Claude stream failed: %s", exc)
            raise AIProviderError(f"Claude stream: {exc}") from exc

    def chat_with_tools(
        self,
        raw_messages: list[dict],
        system: str,
        tool_schemas: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ):
        """Returns the raw Anthropic Message object (caller inspects .content)."""
        try:
            return self._client_instance().messages.create(
                model=ai_config.models["claude"],
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=raw_messages,
                tools=tool_schemas,
            )
        except Exception as exc:
            logger.error("Claude tool chat failed: %s", exc)
            raise AIProviderError(f"Claude tool_call: {exc}") from exc

    def continue_with_tool_results(
        self,
        raw_messages: list[dict],
        system: str,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> Generator[str, None, None]:
        try:
            with self._client_instance().messages.stream(
                model=ai_config.models["claude"],
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=raw_messages,
            ) as stream:
                for text in stream.text_stream:
                    yield text
        except Exception as exc:
            raise AIProviderError(f"Claude follow-up: {exc}") from exc
