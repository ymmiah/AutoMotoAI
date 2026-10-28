"""API + agent tests (mocked AI)."""

import pytest
from fastapi.testclient import TestClient

from automoto import agent, desktop, router, server
from automoto.providers import REGISTRY


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    for p in REGISTRY.values():
        for k in p.env_keys:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AUTOMOTO_WORKDIR", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")


@pytest.fixture
def client():
    return TestClient(server.app)


H = {"X-AutoMoto-Token": server.SESSION_TOKEN}


def test_index_injects_token(client):
    r = client.get("/")
    assert r.status_code == 200 and server.SESSION_TOKEN in r.text and "4.0.0" in r.text


def test_api_requires_token(client):
    assert client.get("/api/status").status_code == 403
    assert client.get("/api/status", headers=H).json()["version"] == "4.0.0"


def test_chat_returns_provider_and_actions(client, monkeypatch):
    reply = 'Sure!\n```actions\n[{"tool":"create_folder","args":{"path":"demo"},"why":"make it"}]\n```'
    monkeypatch.setattr(server, "ask", lambda *a, **k: router.Answer(reply, "gemini", "m", "chat", [{"provider": "gemini", "ok": True}]))
    r = client.post("/api/chat", headers=H, json={"messages": [{"role": "user", "content": "make a folder"}]})
    body = r.json()
    assert body["provider"] == "gemini" and body["text"] == "Sure!"
    assert body["actions"][0]["tool"] == "create_folder" and body["actions"][0]["risk"] == "confirm"


def test_actions_need_confirmation(client, tmp_path):
    a = {"tool": "create_folder", "args": {"path": "x"}}
    assert client.post("/api/actions/execute", headers=H, json={"action": a}).json()["needs_confirmation"]
    assert not (tmp_path / "x").exists()
    assert client.post("/api/actions/execute", headers=H, json={"action": a, "confirmed": True}).json()["ok"]
    assert (tmp_path / "x").is_dir()


def test_shell_off_by_default():
    res = desktop.execute({"tool": "run_command", "args": {"command": "echo hi"}}, confirmed=True)
    assert not res["ok"] and "disabled" in res["error"]


def test_create_file_never_overwrites(tmp_path):
    assert desktop.execute({"tool": "create_file", "args": {"path": "a.txt", "content": "1"}}, confirmed=True)["ok"]
    assert not desktop.execute({"tool": "create_file", "args": {"path": "a.txt", "content": "2"}}, confirmed=True)["ok"]
    assert (tmp_path / "a.txt").read_text() == "1"


def test_split_actions_drops_unknown_tools():
    text, acts = agent.split_actions('ok\n```actions\n[{"tool":"rm_rf","args":{}},{"tool":"open_url","args":{"url":"x.com"}}]\n```')
    assert text == "ok" and [a["tool"] for a in acts] == ["open_url"]


def test_mobile_prompt_has_no_desktop_tools():
    assert "open_app" not in agent.system_prompt(client="mobile")


def test_split_actions_accepts_unfenced_block():
    text, acts = agent.split_actions('Done.\nactions [{"tool": "open_url", "args": {"url": "ymmiah.com"}, "why": "x"}]')
    assert text == "Done." and acts[0]["tool"] == "open_url"
