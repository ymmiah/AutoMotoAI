from __future__ import annotations

import logging

import requests

from src.ai.base import AIProvider, Message
from src.core.config import ai_config
from src.core.exceptions import AIProviderError

logger = logging.getLogger(__name__)


class BlackboxProvider(AIProvider):

    @property
    def name(self) -> str:
        return "blackbox"

    @property
    def is_available(self) -> bool:
        return bool(ai_config.blackbox_api_key)

    def chat(self, messages: list[Message], temperature: float = 0.3, max_tokens: int = 1024) -> str:
        try:
            headers = {
                "Authorization": f"Bearer {ai_config.blackbox_api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": ai_config.models["blackbox"],
                "messages": [{"role": m.role, "content": m.content} for m in messages],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            resp = requests.post(
                ai_config.blackbox_api_url,
                headers=headers,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except requests.HTTPError as exc:
            logger.error("Blackbox HTTP error: %s", exc)
            raise AIProviderError(f"Blackbox HTTP {exc.response.status_code}: {exc}") from exc
        except Exception as exc:
            logger.error("Blackbox request failed: %s", exc)
            raise AIProviderError(f"Blackbox: {exc}") from exc
