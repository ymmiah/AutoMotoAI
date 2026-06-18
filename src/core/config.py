"""Application configuration loaded exclusively from environment variables."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


class AIConfig:
    openai_api_key: str = _env("OPENAI_API_KEY")
    gemini_api_key: str = _env("GEMINI_API_KEY")
    anthropic_api_key: str = _env("ANTHROPIC_API_KEY")
    blackbox_api_key: str = _env("BLACKBOX_API_KEY")
    default_provider: str = _env("DEFAULT_AI_PROVIDER", "openai").lower()
    temperature: float = float(_env("AI_TEMPERATURE", "0.3"))
    max_tokens: int = int(_env("AI_MAX_TOKENS", "1024"))
    blackbox_api_url: str = "https://api.blackbox.ai/v1/chat/completions"
    models: dict = {
        "openai": _env("OPENAI_MODEL", "gpt-4"),
        "gemini": _env("GEMINI_MODEL", "gemini-pro"),
        "claude": _env("CLAUDE_MODEL", "claude-3-5-sonnet-20241022"),
        "blackbox": _env("BLACKBOX_MODEL", "blackboxai"),
    }
    system_prompt: str = (
        "You are AutoMoto AI, an intelligent Windows desktop automation assistant. "
        "Help users control their desktop by translating natural language into specific, "
        "safe desktop actions. Always clarify what you are about to do. "
        "Never execute destructive or irreversible actions without explicit user confirmation."
    )


class AppConfig:
    name: str = "AutoMoto AI"
    version: str = "3.0.0"
    base_dir: Path = _BASE_DIR
    log_dir: Path = _BASE_DIR / "logs"
    screenshots_dir: Path = _BASE_DIR / "screenshots"
    log_level: str = _env("LOG_LEVEL", "INFO")


class ServerConfig:
    host: str = _env("WEB_HOST", "127.0.0.1")
    port: int = int(_env("WEB_PORT", "5000"))
    debug: bool = _env("FLASK_DEBUG", "false").lower() == "true"
    secret_key: str = _env("FLASK_SECRET_KEY") or secrets.token_hex(32)


ai_config = AIConfig()
app_config = AppConfig()
server_config = ServerConfig()

# Ensure runtime directories exist
app_config.log_dir.mkdir(parents=True, exist_ok=True)
app_config.screenshots_dir.mkdir(parents=True, exist_ok=True)
