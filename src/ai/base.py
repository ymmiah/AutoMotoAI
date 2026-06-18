"""Abstract base class that every AI provider must implement."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


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
        """Send a message list and return the assistant reply."""
