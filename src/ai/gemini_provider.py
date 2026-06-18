from __future__ import annotations

import logging
from typing import Generator

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

    @property
    def supports_streaming(self) -> bool:
        return True

    def _build_prompt(self, messages: list[Message]) -> str:
        label = {"system": "[System]", "user": "User", "assistant": "Assistant"}
        return "\n".join(f"{label.get(m.role, m.role)}: {m.content}" for m in messages)

    def _get_model(self):
        import google.generativeai as genai
        genai.configure(api_key=ai_config.gemini_api_key)
        return genai.GenerativeModel(ai_config.models["gemini"])

    def _gen_config(self, temperature: float, max_tokens: int):
        import google.generativeai as genai
        return genai.types.GenerationConfig(temperature=temperature, max_output_tokens=max_tokens)

    def chat(self, messages: list[Message], temperature: float = 0.3, max_tokens: int = 1024) -> str:
        try:
            model = self._get_model()
            resp = model.generate_content(
                self._build_prompt(messages),
                generation_config=self._gen_config(temperature, max_tokens),
            )
            return resp.text.strip()
        except Exception as exc:
            logger.error("Gemini chat failed: %s", exc)
            raise AIProviderError(f"Gemini: {exc}") from exc

    def stream_chat(self, messages: list[Message], temperature: float = 0.3, max_tokens: int = 1024) -> Generator[str, None, None]:
        try:
            model = self._get_model()
            stream = model.generate_content(
                self._build_prompt(messages),
                generation_config=self._gen_config(temperature, max_tokens),
                stream=True,
            )
            for chunk in stream:
                if chunk.text:
                    yield chunk.text
        except Exception as exc:
            logger.error("Gemini stream failed: %s", exc)
            raise AIProviderError(f"Gemini stream: {exc}") from exc
