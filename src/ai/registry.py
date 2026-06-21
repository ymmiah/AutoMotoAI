"""
AI provider registry with:
  - Automatic fallback chain
  - Native streaming (OpenAI, Gemini, Claude)
  - Agentic tool-calling loop (OpenAI + Claude with native tool support)
  - Structured-text fallback for providers without native tool calling
"""
from __future__ import annotations

import json
import logging
from typing import Generator

from src.ai.base import AIProvider, Message
from src.ai.blackbox_provider import BlackboxProvider
from src.ai.claude_provider import ClaudeProvider
from src.ai.gemini_provider import GeminiProvider
from src.ai.openai_provider import OpenAIProvider
from src.core.config import ai_config
from src.core.exceptions import AIProviderError, NoProviderAvailableError

logger = logging.getLogger(__name__)

_PROVIDER_ORDER: list[AIProvider] = [
    OpenAIProvider(),
    GeminiProvider(),
    ClaudeProvider(),
    BlackboxProvider(),
]


# ── Event type constants ───────────────────────────────────────────────────────
EVT_TOKEN       = "token"        # ("token",  str)
EVT_TOOL_CALL   = "tool_call"    # ("tool_call",  {"name":…, "args":…, "id":…})
EVT_TOOL_RESULT = "tool_result"  # ("tool_result", {"name":…, "result":…, "success":…})
EVT_ERROR       = "error"        # ("error", str)
EVT_DONE        = "done"         # ("done",  None)


class AIRegistry:
    """Manages provider selection, streaming, fallback, and the agentic tool loop."""

    def __init__(self) -> None:
        self._providers: dict[str, AIProvider] = {
            p.name: p for p in _PROVIDER_ORDER if p.is_available
        }
        if self._providers:
            logger.info("Available AI providers: %s", list(self._providers))
        else:
            logger.warning("No AI providers configured — add at least one API key to .env")

    # ── basic queries ──────────────────────────────────────────────────────────
    @property
    def available_providers(self) -> list[str]:
        return list(self._providers)

    @property
    def default_provider_name(self) -> str:
        if not self._providers:
            raise NoProviderAvailableError("No AI provider configured. Add an API key to .env")
        pref = ai_config.default_provider
        return pref if pref in self._providers else next(iter(self._providers))

    # ── plain chat (non-streaming) ─────────────────────────────────────────────
    def chat(self, messages: list[Message], provider: str | None = None) -> str:
        if not self._providers:
            raise NoProviderAvailableError("No AI provider configured.")
        chosen = provider or self.default_provider_name
        order = [chosen] + [n for n in self._providers if n != chosen]
        last: Exception = RuntimeError("No providers tried")
        for name in order:
            if name not in self._providers:
                continue
            try:
                if name != chosen:
                    logger.info("Falling back to '%s'", name)
                return self._providers[name].chat(
                    messages, ai_config.temperature, ai_config.max_tokens
                )
            except AIProviderError as exc:
                logger.warning("Provider '%s' failed: %s", name, exc)
                last = exc
        raise NoProviderAvailableError("All AI providers failed.") from last

    # ── streaming chat (no tools) ──────────────────────────────────────────────
    def stream_chat(
        self, messages: list[Message], provider: str | None = None
    ) -> Generator[str, None, None]:
        if not self._providers:
            raise NoProviderAvailableError("No AI provider configured.")
        chosen = provider or self.default_provider_name
        order = [chosen] + [n for n in self._providers if n != chosen]
        for name in order:
            prov = self._providers.get(name)
            if not prov:
                continue
            try:
                yield from prov.stream_chat(
                    messages, ai_config.temperature, ai_config.max_tokens
                )
                return
            except AIProviderError as exc:
                logger.warning("Stream provider '%s' failed: %s", name, exc)
        raise NoProviderAvailableError("All AI providers failed during streaming.")

    # ── agentic streaming with tool calling ────────────────────────────────────
    def stream_chat_with_tools(
        self,
        messages: list[Message],
        provider: str | None = None,
        max_rounds: int = 6,
    ) -> Generator[tuple, None, None]:
        """
        Yields tuples:
          (EVT_TOKEN,       str)
          (EVT_TOOL_CALL,   {"name", "args", "id"})
          (EVT_TOOL_RESULT, {"name", "result", "success"})
          (EVT_ERROR,       str)
          (EVT_DONE,        None)
        """
        from src.ai.tools import tool_registry
        if not self._providers:
            yield (EVT_ERROR, "No AI provider configured.")
            yield (EVT_DONE, None)
            return

        chosen = provider or self.default_provider_name
        prov = self._providers.get(chosen) or next(iter(self._providers.values()))

        try:
            if prov.name == "openai" and prov.supports_tool_calling:
                yield from self._openai_loop(messages, prov, tool_registry, max_rounds)
            elif prov.name == "claude" and prov.supports_tool_calling:
                yield from self._claude_loop(messages, prov, tool_registry, max_rounds)
            else:
                # Providers without native tool calling: stream plain and parse
                yield from self._plain_stream_with_hints(messages, prov)
        except Exception as exc:
            logger.error("stream_chat_with_tools failed: %s", exc)
            yield (EVT_ERROR, str(exc))
        finally:
            yield (EVT_DONE, None)

    # ── OpenAI agentic loop ────────────────────────────────────────────────────
    def _openai_loop(self, messages, provider, tool_registry, max_rounds):
        from src.ai.tools import ToolCallRequest
        raw = [{"role": m.role, "content": m.content} for m in messages]
        schemas = tool_registry.to_openai_schema()

        for _ in range(max_rounds):
            text, tc_list = provider.chat_with_tools(
                [Message(r["role"], r["content"]) for r in raw],
                schemas,
                ai_config.temperature,
                ai_config.max_tokens,
            )
            if text:
                yield (EVT_TOKEN, text)

            if not tc_list:
                return   # No tool calls → conversation complete

            # Record assistant turn with tool calls
            raw.append({
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for tc in tc_list
                ],
            })

            for tc in tc_list:
                try:
                    args = json.loads(tc["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                req = ToolCallRequest(tc["id"], tc["name"], args)
                yield (EVT_TOOL_CALL, {"name": req.name, "args": req.arguments, "id": req.id})
                res = tool_registry.execute(req)
                yield (EVT_TOOL_RESULT, {"name": res.name, "result": res.result, "success": res.success})
                raw.append({"role": "tool", "tool_call_id": tc["id"], "content": res.result})

            # Stream follow-up
            for token in provider.continue_with_tool_results(raw, ai_config.temperature, ai_config.max_tokens):
                yield (EVT_TOKEN, token)
            return   # follow-up handled, done

        yield (EVT_ERROR, f"Reached maximum tool rounds ({max_rounds})")

    # ── Claude agentic loop ────────────────────────────────────────────────────
    def _claude_loop(self, messages, provider, tool_registry, max_rounds):
        from src.ai.tools import ToolCallRequest
        system = " ".join(m.content for m in messages if m.role == "system") or ai_config.system_prompt
        raw = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        schemas = tool_registry.to_claude_schema()

        for _ in range(max_rounds):
            resp = provider.chat_with_tools(raw, system, schemas, ai_config.temperature, ai_config.max_tokens)

            text_blocks = [b for b in resp.content if b.type == "text"]
            tool_uses   = [b for b in resp.content if b.type == "tool_use"]

            for tb in text_blocks:
                if tb.text:
                    yield (EVT_TOKEN, tb.text)

            if not tool_uses:
                return

            raw.append({"role": "assistant", "content": resp.content})

            tool_results = []
            for tu in tool_uses:
                req = ToolCallRequest(tu.id, tu.name, tu.input)
                yield (EVT_TOOL_CALL, {"name": req.name, "args": req.arguments, "id": req.id})
                res = tool_registry.execute(req)
                yield (EVT_TOOL_RESULT, {"name": res.name, "result": res.result, "success": res.success})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": res.result,
                    "is_error": not res.success,
                })
            raw.append({"role": "user", "content": tool_results})

            for token in provider.continue_with_tool_results(raw, system, ai_config.temperature, ai_config.max_tokens):
                yield (EVT_TOKEN, token)
            return

        yield (EVT_ERROR, f"Reached maximum tool rounds ({max_rounds})")

    # ── Plain streaming with structured-action hints ──────────────────────────
    def _plain_stream_with_hints(self, messages, provider):
        """
        For providers without native tool calling: inject a hint in the system
        prompt about how to express actions, then stream normally.
        The chat panel parses <action>…</action> tags for execution.
        """
        hint = Message(
            "system",
            "When you want to perform a desktop action, embed it as JSON in "
            "<action>{\"tool\": \"open_application\", \"args\": {\"app_name\": \"notepad\"}}</action>. "
            "Supported tools: open_application, take_screenshot, create_file, create_directory, "
            "list_directory, get_system_info, list_processes, type_text, press_key, run_hotkey, "
            "open_in_file_manager."
        )
        augmented = [hint] + list(messages)
        try:
            yield from ((EVT_TOKEN, tok) for tok in provider.stream_chat(
                augmented, ai_config.temperature, ai_config.max_tokens
            ))
        except AIProviderError as exc:
            yield (EVT_ERROR, str(exc))


