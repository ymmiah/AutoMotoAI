"""Regression checks for the new local-runtime controls and optional providers.

No local models, cloud keys, or downloads are required for this test module.
"""

import pytest
from fastapi.testclient import TestClient

from automoto import local_llm, server
from automoto.providers import REGISTRY


def test_gemma_is_available_as_local_model():
    names = {model.name for model in local_llm.CATALOG}
    assert {"gemma3:1b", "gemma3:4b"} <= names
    assert all(local_llm.valid_model_name(name) for name in names)


def test_optional_cloud_providers_are_key_gated(monkeypatch):
    for ident in ("zai", "kimi"):
        spec = REGISTRY[ident]
        for key in spec.env_keys:
            monkeypatch.delenv(key, raising=False)
        assert not spec.local
        assert spec.key() is None
        assert spec.url().startswith("https://")
        assert spec.supports_tools
    monkeypatch.setenv("ZAI_API_KEY", "test-zai")
    monkeypatch.setenv("MOONSHOT_API_KEY", "test-moonshot")
    assert REGISTRY["zai"].key() == "test-zai"
    assert REGISTRY["kimi"].key() == "test-moonshot"


def test_start_ollama_reuses_a_running_service(monkeypatch):
    monkeypatch.setattr(local_llm, "ollama_url", lambda: "http://127.0.0.1:11434")
    monkeypatch.setattr(local_llm, "ollama_status", lambda: {"running": True, "models": []})
    result = local_llm.start_ollama()
    assert result["started"] and result["already_running"]


def test_start_ollama_reports_a_missing_runtime(monkeypatch):
    monkeypatch.setattr(local_llm, "ollama_url", lambda: "http://127.0.0.1:11434")
    monkeypatch.setattr(local_llm, "ollama_status", lambda: {"running": False})
    monkeypatch.setattr(local_llm.shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="not installed"):
        local_llm.start_ollama()


def test_start_ollama_blocks_remote_runtime(monkeypatch):
    monkeypatch.setattr(local_llm, "ollama_url", lambda: "http://192.168.1.25:11434")
    with pytest.raises(ValueError, match="only"):
        local_llm.start_ollama()


def test_test_ollama_refuses_absent_models_and_invalid_names(monkeypatch):
    monkeypatch.setattr(local_llm, "ollama_status", lambda: {
        "running": True, "models": [{"name": "qwen2.5:3b"}],
    })
    with pytest.raises(ValueError, match="not downloaded"):
        local_llm.test_ollama("gemma3:4b")
    with pytest.raises(ValueError, match="Invalid"):
        local_llm.test_ollama("../../../etc/passwd")


def test_runtime_endpoints_require_authorisation():
    client = TestClient(server.app)
    assert client.post("/api/local/start").status_code in (401, 403)
    assert client.post("/api/local/test", json={"model": "qwen2.5:3b"}).status_code in (401, 403)
