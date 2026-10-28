import pytest


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path_factory):
    """Every test gets its own ~/.automoto so nothing touches the real one."""
    home = tmp_path_factory.mktemp("automoto_home")
    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(home))
    for k in ("AUTOMOTO_WORKSPACE", "AUTOMOTO_MEMORY_DB", "AUTOMOTO_APPROVAL", "AUTOMOTO_AUTO_APPROVE",
              "AUTOMOTO_BLOCK_TOOLS", "AUTOMOTO_TOOL_MODE", "AUTOMOTO_ENABLE_DESKTOP", "AUTOMOTO_ALLOW_SHELL", "AUTOMOTO_MAX_STEPS", "AUTOMOTO_NET_ALLOW_CIDRS", "AUTOMOTO_MCP_CONFIG"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AUTOMOTO_SANDBOX", "local")
    return home
