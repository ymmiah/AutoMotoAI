import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# AI Provider API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
BLACKBOX_API_KEY = os.getenv("BLACKBOX_API_KEY")

# Default AI Provider (openai, gemini, claude, or blackbox)
DEFAULT_AI_PROVIDER = os.getenv("DEFAULT_AI_PROVIDER", "openai").lower()

# System prompt for the AI agent
SYSTEM_PROMPT = """
You are AutoMoto AI, an intelligent Windows assistant.
Translate user inputs into desktop automation actions.
Always ask for confirmation before executing any task.
Give clear feedback on every step.
You can perform tasks like:
- Opening applications
- Creating files
- Managing windows
- Executing system commands
- Providing information and assistance
"""

# AI Model Configuration
AI_MODELS = {
    "openai": "gpt-4",
    "gemini": "gemini-pro",
    "claude": "claude-3-sonnet-20240229",
    "blackbox": "blackbox-ai"
}

# BLACKBOX AI API Configuration
BLACKBOX_API_URL = "https://api.blackbox.ai/v1/chat/completions"

# AI Generation Parameters
AI_TEMPERATURE = 0.3  # Lower = more deterministic
AI_MAX_TOKENS = 500   # Response length limit

# Application settings
APP_NAME = "AutoMoto AI"
VERSION = "2.1.0"
