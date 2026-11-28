import os

import pytest


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch):
    """Host Git config (signing, identity, default branch) must not change tests."""
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "0")
    monkeypatch.delenv("GIT_CONFIG_PARAMETERS", raising=False)
    for key in [k for k in os.environ
                if k.startswith("GIT_CONFIG_KEY_") or k.startswith("GIT_CONFIG_VALUE_")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "T")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "T")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@example.com")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path_factory):
    """Every test gets its own ~/.automoto so nothing touches the real one."""
    home = tmp_path_factory.mktemp("automoto_home")
    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(home))
    for k in ("AI_PROVIDER", "AI_TIMEOUT", "AUTOMOTO_WORKSPACE", "AUTOMOTO_MEMORY_DB", "AUTOMOTO_APPROVAL", "AUTOMOTO_AUTO_APPROVE",
              "AUTOMOTO_BLOCK_TOOLS", "AUTOMOTO_TOOL_MODE", "AUTOMOTO_ENABLE_DESKTOP", "AUTOMOTO_ALLOW_SHELL", "AUTOMOTO_MAX_STEPS", "AUTOMOTO_NET_ALLOW_CIDRS", "AUTOMOTO_MCP_CONFIG",
              "AUTOMOTO_MODE", "AUTOMOTO_SIGNUP", "AUTOMOTO_OFFLINE", "AUTOMOTO_OLLAMA", "OLLAMA_MODEL", "OLLAMA_HOST", "LOCAL_AI_CONTEXT", "LOCAL_AI_THINK", "LOCAL_LLM_URL", "LOCAL_LLM_MODEL", "AUTOMOTO_DEFAULT_QUOTA_MINUTES", "AUTOMOTO_ADMIN_USER", "AUTOMOTO_ADMIN_PASSWORD", "AUTOMOTO_SETUP_CODE", "AUTOMOTO_ADMIN_RESET",
              "AUTOMOTO_COOKIE_SECURE", "AUTOMOTO_ALLOW_HTTP_DEVICES", "AUTOMOTO_APP_ORIGINS", "AUTOMOTO_DEVICE_DAYS", "RENDER_EXTERNAL_HOSTNAME", "KOYEB_PUBLIC_DOMAIN", "SPACE_HOST"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AUTOMOTO_SANDBOX", "local")
    monkeypatch.setenv("AUTOMOTO_ALLOWED_HOSTS", "testserver")  # FastAPI TestClient's Host header
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "0")
    for k in ("AUTOMOTO_ALLOWED_ROOTS", "AUTOMOTO_ALLOWED_ORIGINS", "AUTOMOTO_LAUNCH_TOKEN", "AUTOMOTO_API_TOKEN",
              "GITHUB_TOKEN", "GH_TOKEN", "GITLAB_TOKEN", "GITLAB_URL", "VERCEL_TOKEN", "FIGMA_TOKEN", "NOTION_TOKEN",
              "ZOTERO_API_KEY", "ZOTERO_USER_ID", "GOOGLE_ACCESS_TOKEN", "MS_GRAPH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    return home


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    """No real backoff sleeps, and a fresh "model unavailable" cache, in every test."""
    from automoto import providers, router

    sleeps: list[float] = []
    monkeypatch.setattr(router, "_sleep", sleeps.append)
    from automoto import local_llm

    providers.clear_unavailable()
    local_llm.forget_installed()
    monkeypatch.delenv("AUTOMOTO_RETRIES", raising=False)
    monkeypatch.delenv("AUTOMOTO_RETRY_BUDGET_S", raising=False)
    yield sleeps
    providers.clear_unavailable()
