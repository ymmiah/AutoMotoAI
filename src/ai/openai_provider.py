from __future__ import annotations

import json
import logging
from typing import Generator

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

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_tool_calling(self) -> bool:
        return True

    def _client_instance(self):
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=ai_config.openai_api_key)
            except ImportError as exc:
                raise AIProviderError("openai package not installed. Run: pip install openai") from exc
        return self._client

    def _fmt(self, messages: list[Message]) -> list[dict]:
        return [{"role": m.role, "content": m.content} for m in messages]

    def chat(self, messages: list[Message], temperature: float = 0.3, max_tokens: int = 1024) -> str:
        try:
            resp = self._client_instance().chat.completions.create(
                model=ai_config.models["openai"],
                messages=self._fmt(messages),
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()
        except Exception as exc:
            logger.error("OpenAI chat failed: %s", exc)
            raise AIProviderError(f"OpenAI: {exc}") from exc

    def stream_chat(self, messages: list[Message], temperature: float = 0.3, max_tokens: int = 1024) -> Generator[str, None, None]:
        try:
            stream = self._client_instance().chat.completions.create(
                model=ai_config.models["openai"],
                messages=self._fmt(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as exc:
            logger.error("OpenAI stream failed: %s", exc)
            raise AIProviderError(f"OpenAI stream: {exc}") from exc

    def chat_with_tools(
        self,
        messages: list[Message],
        tool_schemas: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> tuple[str, list]:
        """
        Returns (text, tool_calls) where tool_calls is the raw OpenAI list.
        Streams the text portion and accumulates tool call deltas.
        """
        try:
            stream = self._client_instance().chat.completions.create(
                model=ai_config.models["openai"],
                messages=self._fmt(messages),
                tools=tool_schemas,
                tool_choice="auto",
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            text = ""
            tc_acc: dict[int, dict] = {}
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    text += delta.content
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tc_acc:
                            tc_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc.id:
                            tc_acc[idx]["id"] += tc.id
                        if tc.function and tc.function.name:
                            tc_acc[idx]["name"] += tc.function.name
                        if tc.function and tc.function.arguments:
                            tc_acc[idx]["arguments"] += tc.function.arguments
            return text, list(tc_acc.values())
        except Exception as exc:
            logger.error("OpenAI tool chat failed: %s", exc)
            raise AIProviderError(f"OpenAI tool_call: {exc}") from exc

    def continue_with_tool_results(
        self,
        raw_messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> Generator[str, None, None]:
        """Stream the follow-up after tool results have been appended to raw_messages."""
        try:
            stream = self._client_instance().chat.completions.create(
                model=ai_config.models["openai"],
                messages=raw_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as exc:
            raise AIProviderError(f"OpenAI follow-up: {exc}") from exc
