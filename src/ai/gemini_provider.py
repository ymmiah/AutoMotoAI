from __future__ import annotations

import logging

from src.ai.base import AIProvider, Message
from src.core.config import ai_config
from src.core.exceptions import AIProviderError

logger = logging.getLogger(__name__)


class GeminiProvider(AIProvider):

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def is_available(self) -> bool:
        return bool(ai_config.gemini_api_key)

    def chat(self, messages: list[Message], temperature: float = 0.3, max_tokens: int = 1024) -> str:
        try:
            import google.generativeai as genai
            genai.configure(api_key=ai_config.gemini_api_key)
            model = genai.GenerativeModel(ai_config.models["gemini"])
            parts = []
            for m in messages:
                prefix = {"system": "[System]", "user": "User", "assistant": "Assistant"}.get(m.role, m.role)
                parts.append(f"{prefix}: {m.content}")
            response = model.generate_content(
                "\n".join(parts),
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                ),
            )
            return response.text.strip()
        except Exception as exc:
            logger.error("Gemini request failed: %s", exc)
            raise AIProviderError(f"Gemini: {exc}") from exc
