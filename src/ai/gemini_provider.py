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

    def _configure(self):
        import google.generativeai as genai
        genai.configure(api_key=ai_config.gemini_api_key)
        return genai

    def _build_contents(self, messages: list[Message]) -> tuple[str, list[dict]]:
        """Return (system_instruction, contents) in the Gemini multi-turn format."""
        system_parts = [m.content for m in messages if m.role == "system"]
        system_instr = " ".join(system_parts) if system_parts else ""
        role_map = {"user": "user", "assistant": "model"}
        contents = [
            {"role": role_map.get(m.role, "user"), "parts": [{"text": m.content}]}
            for m in messages if m.role != "system"
        ]
        if not contents:
            contents = [{"role": "user", "parts": [{"text": "Hello"}]}]
        return system_instr, contents

    def _get_model(self, system_instr: str):
        genai = self._configure()
        kwargs: dict = {"model_name": ai_config.models["gemini"]}
        if system_instr:
            kwargs["system_instruction"] = system_instr
        return genai.GenerativeModel(**kwargs)

    def _gen_config(self, temperature: float, max_tokens: int):
        import google.generativeai as genai
        return genai.types.GenerationConfig(temperature=temperature, max_output_tokens=max_tokens)

    def chat(self, messages: list[Message], temperature: float = 0.3, max_tokens: int = 1024) -> str:
        try:
            system_instr, contents = self._build_contents(messages)
            model = self._get_model(system_instr)
            resp = model.generate_content(
                contents,
                generation_config=self._gen_config(temperature, max_tokens),
            )
            return resp.text.strip()
        except Exception as exc:
            logger.error("Gemini chat failed: %s", exc)
            raise AIProviderError(f"Gemini: {exc}") from exc

    def stream_chat(self, messages: list[Message], temperature: float = 0.3, max_tokens: int = 1024) -> Generator[str, None, None]:
        try:
            system_instr, contents = self._build_contents(messages)
            model = self._get_model(system_instr)
            stream = model.generate_content(
                contents,
                generation_config=self._gen_config(temperature, max_tokens),
                stream=True,
            )
            for chunk in stream:
                if chunk.text:
                    yield chunk.text
        except Exception as exc:
            logger.error("Gemini stream failed: %s", exc)
            raise AIProviderError(f"Gemini stream: {exc}") from exc
