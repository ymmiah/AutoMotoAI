"""Abstract base class that every AI provider must implement."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generator


@dataclass
class Message:
    role: str   # "system" | "user" | "assistant"
    content: str


class AIProvider(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        """Short provider identifier, e.g. 'openai'."""

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """True when the provider has a configured API key."""

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> str:
        """Send a message list and return the full assistant reply."""

    def stream_chat(
        self,
        messages: list[Message],
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> Generator[str, None, None]:
        """
        Stream the reply token by token.
        Default implementation yields the full chat() response as one chunk.
        Override in providers that support native streaming.
        """
        yield self.chat(messages, temperature, max_tokens)

    @property
    def supports_streaming(self) -> bool:
        return False

    @property
    def supports_tool_calling(self) -> bool:
        return False
