"""Offline / local AI: Ollama + llama.cpp providers, model picker, Offline mode. No network needed."""

import pytest
from fastapi.testclient import TestClient

from automoto import local_llm, planner, router, server, settings, tools
from automoto.providers import REGISTRY

DEAD = "127.0.0.1:9"  # nothing listens here: "Ollama isn't running"


@pytest.fixture(autouse=True)
def no_cloud_keys(monkeypatch):
    for p in REGISTRY.values():
        for k in p.env_keys:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OLLAMA_HOST", DEAD)


def hw(ram, vram=None, kind=None):
    return {"ram_gb": ram, "gpu": ({"name": "GPU", "vram_gb": vram, "kind": kind or "nvidia"} if (vram or kind) else None)}


@pytest.mark.parametrize("h,best", [
    (hw(2), "qwen2.5:0.5b"), (hw(4), "qwen2.5:1.5b"), (hw(7.6), "qwen2.5:3b"), (hw(15.5), "qwen2.5:3b"),
    (hw(32), "qwen2.5:7b"), (hw(16, 4), "qwen2.5:3b"), (hw(16, 8), "qwen2.5:7b"), (hw(32, 12), "qwen3:14b"),
    (hw(16, None, "apple"), "qwen2.5:7b"), (hw(8, None, "apple"), "qwen2.5:3b"),
])
def test_recommend_fits_the_computer(h, best):
    r = local_llm.recommend(h)
    assert r["best"] == best
    assert any(m["name"] == best and m["recommended"] for m in r["models"])
    assert all(m["tools"] for m in r["models"])  # only models that can use tools
    assert "GB" in r["why"]


def test_small_computer_is_not_offered_big_models():
    names = {m["name"] for m in local_llm.recommend(hw(4))["models"]}
    assert "qwen2.5:7b" not in names and "qwen2.5:1.5b" in names


def test_hardware_detects_ram():
    h = local_llm.hardware()
    assert h["ram_gb"] is None or h["ram_gb"] > 0.5


def test_local_providers_off_until_turned_on(monkeypatch):
    assert REGISTRY["ollama"].key() is None and REGISTRY["local"].key() is None
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2:3b")
    o = REGISTRY["ollama"]
    assert o.key() == "local" and o.model_for() == "llama3.2:3b" and o.all_models("agent")[0] == "llama3.2:3b"
    assert o.url() == "http://127.0.0.1:9/v1" and o.public()["local"] is True


def test_settings_model_turns_ollama_on():
    settings.update({"local_model": "qwen2.5:3b"})
    assert REGISTRY["ollama"].key() == "local" and REGISTRY["ollama"].model_for() == "qwen2.5:3b"


def test_local_urls_must_stay_on_this_computer_or_lan(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://8.8.8.8:11434")
    assert local_llm.ollama_url() == local_llm.DEFAULT_OLLAMA
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")
    assert local_llm.ollama_url() == "http://127.0.0.1:11434"
    monkeypatch.setenv("LOCAL_LLM_URL", "https://api.example.com/v1")
    assert local_llm.local_server_url() is None and REGISTRY["local"].key() is None
    monkeypatch.setenv("LOCAL_LLM_URL", "http://192.168.1.20:8080")
    assert local_llm.local_server_url() == "http://192.168.1.20:8080/v1" and REGISTRY["local"].key() == "local"


def test_offline_mode_uses_only_local_ai(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
    assert [p.id for p in router.plan_order(need_vision=False, prefer=None, task="general")][0] == "gemini"
    monkeypatch.setenv("AUTOMOTO_OFFLINE", "1")
    assert [p.id for p in router.plan_order(need_vision=False, prefer="gemini", task="general")] == ["ollama"]
    seen = []

    def fake(spec, messages, model, key, **_):
        seen.append((spec.id, model))
        return "local answer", []

    turn = router.ask_turn([{"role": "user", "content": "hi"}], [], known=set(), transport=fake)
    assert turn.provider == "ollama"
    assert seen == [("ollama", "qwen2.5:3b")]


def test_offline_without_local_model_explains_what_to_do(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    settings.update({"offline": True})
    assert local_llm.offline() and REGISTRY["ollama"].key() == "local"  # offline turns Ollama on
    monkeypatch.setenv("AUTOMOTO_OLLAMA", "0")
    monkeypatch.setattr(local_llm, "enabled", lambda pid: False)
    with pytest.raises(router.NoProviderError, match="Offline mode is on"):
        router.ask_turn([{"role": "user", "content": "hi"}], [], known=set(), transport=lambda *a, **k: ("x", []))


def test_offline_mode_removes_internet_tools(monkeypatch):
    on = tools.build()
    assert {"web_search", "fetch_url", "download_file"} <= set(on)
    monkeypatch.setenv("AUTOMOTO_OFFLINE", "true")
    off = tools.build(extra=[tools.Tool("mcp__notion__search", "x", {"type": "object", "properties": {}}, "risky",
                                        lambda ctx, **k: "", "mcp:notion")])
    assert not (local_llm.ONLINE_TOOLS & set(off)) and "mcp__notion__search" not in off
    assert {"read_file", "write_file", "run_python"} & set(off)
    p = planner.plan("search the web for the latest news about solar panels", off)
    assert not {"web_search", "fetch_url"} & set(p.tools)
    assert "Offline mode" in planner.prompt_block(p)


def test_settings_validation():
    with pytest.raises(settings.SettingsError):
        settings.update({"offline": "yes"})
    with pytest.raises(settings.SettingsError):
        settings.update({"local_model": "qwen; rm -rf /"})
    assert settings.update({"offline": True, "local_model": "hf.co/bartowski/Qwen2.5-3B-GGUF:Q4_K_M"})["offline"] is True


def test_strip_thinking():
    assert local_llm.strip_thinking("<think>hmm\nok</think>\n\nHello!") == "Hello!"
    assert local_llm.strip_thinking("plain") == "plain"


def test_pull_reports_when_ollama_is_not_running():
    with pytest.raises(ValueError):
        local_llm.pull("../etc/passwd")
    st = local_llm.pull("qwen2.5:0.5b", wait=True)
    assert st["state"] == "error" and "Ollama isn't running" in st["error"]
    assert local_llm.ollama_status()["running"] is False


def test_api_local_panel_is_local_only():
    c = TestClient(server.app)
    H = {"X-AutoMoto-Token": server.SESSION_TOKEN}
    d = c.get("/api/local", headers=H).json()
    assert d["recommend"]["best"] and d["ollama"]["running"] is False and d["offline"] is False
    assert c.post("/api/local/pull", headers=H, json={"model": "bad name!"}).status_code == 400
    assert c.get("/api/local").status_code in (401, 403)
