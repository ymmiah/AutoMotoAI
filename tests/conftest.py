import pytest


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path_factory):
    """Every test gets its own ~/.automoto so nothing touches the real one."""
    home = tmp_path_factory.mktemp("automoto_home")
    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(home))
    for k in ("AI_PROVIDER", "AI_TIMEOUT", "AUTOMOTO_WORKSPACE", "AUTOMOTO_MEMORY_DB", "AUTOMOTO_APPROVAL", "AUTOMOTO_AUTO_APPROVE",
              "AUTOMOTO_BLOCK_TOOLS", "AUTOMOTO_TOOL_MODE", "AUTOMOTO_ENABLE_DESKTOP", "AUTOMOTO_ALLOW_SHELL", "AUTOMOTO_MAX_STEPS", "AUTOMOTO_NET_ALLOW_CIDRS", "AUTOMOTO_MCP_CONFIG",
              "AUTOMOTO_MODE", "AUTOMOTO_SIGNUP", "AUTOMOTO_DEFAULT_QUOTA_MINUTES", "AUTOMOTO_ADMIN_USER", "AUTOMOTO_ADMIN_PASSWORD",
              "AUTOMOTO_COOKIE_SECURE", "RENDER_EXTERNAL_HOSTNAME", "KOYEB_PUBLIC_DOMAIN", "SPACE_HOST"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AUTOMOTO_SANDBOX", "local")
    monkeypatch.setenv("AUTOMOTO_ALLOWED_HOSTS", "testserver")  # FastAPI TestClient's Host header
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "0")
    for k in ("AUTOMOTO_ALLOWED_ROOTS", "AUTOMOTO_ALLOWED_ORIGINS", "AUTOMOTO_LAUNCH_TOKEN", "AUTOMOTO_API_TOKEN",
              "GITHUB_TOKEN", "GH_TOKEN", "GITLAB_TOKEN", "GITLAB_URL", "VERCEL_TOKEN", "FIGMA_TOKEN", "NOTION_TOKEN",
              "ZOTERO_API_KEY", "ZOTERO_USER_ID", "GOOGLE_ACCESS_TOKEN", "MS_GRAPH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    return home
