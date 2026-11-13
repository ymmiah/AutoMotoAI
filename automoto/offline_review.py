"""Studio reviews use the built-in llama.cpp engine when Offline is selected.

Ollama stays available for people who already run it and have not turned Offline on.
"""

from __future__ import annotations

import json
from typing import Any

from automoto import local_llm


def using_builtin() -> bool:
    return local_llm.offline()


def builtin_model() -> str:
    """The selected GGUF id, after checking a model file is on disk."""
    from automoto import gguf_runtime, settings

    if not gguf_runtime.ready():
        raise ValueError(
            "Offline is on. Choose a downloaded model in Settings → Offline AI. "
            "Studio reviews use the built-in engine on this PC, not Ollama."
        )
    return settings.get("gguf_model") or "builtin"


def complete_json(messages: list[dict[str, Any]], *, timeout: float = 110,
                  max_tokens: int = 1500) -> dict[str, Any]:
    """One JSON object from the warm built-in engine."""
    from automoto import gguf_runtime

    text = gguf_runtime.complete(messages, json_mode=True, max_tokens=max_tokens,
                                 timeout=timeout, temperature=0)
    data = json.loads(local_llm.strip_thinking(text) or "{}")
    if not isinstance(data, dict):
        raise ValueError("The built-in model did not return a JSON object.")
    return data
