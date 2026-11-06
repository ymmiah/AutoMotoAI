"""Offline AI against a stand-in Ollama server (same endpoints and error shapes as the real one).

Regression tests for "the offline model doesn't load":
* a chosen / default model that isn't downloaded must fall back to one that is, not fail with 404;
* a 404 must not hide the local model for an hour (it may be downloaded a minute later);
* every request sets a context window big enough for the agent's prompt (Ollama's default cuts it off);
* models without tool calling (Gemma 3) go straight to the text protocol.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from automoto import local_llm, providers, router, settings
from automoto.providers import REGISTRY

TOOLS = [{"type": "function", "function": {"name": "remember", "description": "Save a note",
                                            "parameters": {"type": "object", "properties": {"text": {"type": "string"}}}}}]


class FakeOllama:
    def __init__(self, models):
        self.models = dict(models)  # name -> {"tools": bool, "thinking": bool}
        self.chats: list[dict] = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/version":
                    return self._send(200, {"version": "0.12.0"})
                if self.path == "/api/tags":
                    return self._send(200, {"models": [{"name": n, "size": 2 << 30} for n in fake.models]})
                self._send(404, {"error": "not found"})

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                model = data.get("model")
                if self.path == "/api/pull":
                    fake.models[model] = {"tools": True}
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"status":"success"}\n')
                    return
                if model not in fake.models:
                    return self._send(404, {"error": f"model '{model}' not found"})
                m = fake.models[model]
                if self.path == "/api/show":
                    caps = ["completion"] + (["tools"] if m.get("tools") else []) + (["thinking"] if m.get("thinking") else [])
                    return self._send(200, {"capabilities": caps, "model_info": {"llama.context_length": 32768}})
                if self.path == "/api/chat":
                    fake.chats.append(data)
                    content = data["messages"][-1].get("content") or ""
                    if data.get("tools") and not m.get("tools"):
                        return self._send(400, {"error": f"registry.ollama.ai/library/{model} does not support tools"})
                    if data.get("tools") and content == "save it":
                        return self._send(200, {"message": {"role": "assistant", "content": "", "tool_calls": [
                            {"function": {"name": "remember", "arguments": {"text": "hi"}}}]}})
                    if "prefix save" in content:
                        return self._send(200, {"message": {"role": "assistant", "content": "", "tool_calls": [
                            {"function": {"name": "functions.remember", "arguments": {"text": "hi"}}}]}})
                    if "loose save" in content:
                        return self._send(200, {"message": {"role": "assistant", "content":
                            'Saving now.\n{"name": "remember", "arguments": {"text": "hi"}}'}})
                    return self._send(200, {"message": {"role": "assistant", "content": f"<think>x</think>Hello from {model}"}})
                self._send(404, {"error": "not found"})

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()


@pytest.fixture
def ollama(monkeypatch):
    for p in REGISTRY.values():
        for k in p.env_keys:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.setattr(local_llm, "_hardware_cached", lambda: {"ram_gb": 16.0, "gpu": None, "cpus": 4,
                                                                "os": "Linux", "arch": "x86_64"})
    fakes = []

    def make(models):
        f = FakeOllama(models)
        fakes.append(f)
        monkeypatch.setenv("OLLAMA_HOST", f.url)
        local_llm.forget_installed()
        local_llm._INFO_CACHE.clear()
        providers.clear_unavailable()
        return f

    yield make
    for f in fakes:
        f.close()
    local_llm.forget_installed()
    local_llm._INFO_CACHE.clear()
    providers.clear_unavailable()


def turn(text="hi"):
    return router.ask_turn([{"role": "user", "content": text}], TOOLS, known={"remember"})


def test_offline_uses_a_downloaded_model_when_none_was_chosen(ollama):
    fake = ollama({"llama3.2:3b": {"tools": True}})
    settings.update({"offline": True})  # default would be qwen2.5:3b, which isn't downloaded
    t = turn()
    assert (t.provider, t.model, t.text) == ("ollama", "llama3.2:3b", "Hello from llama3.2:3b")
    assert local_llm.status()["model"] == "llama3.2:3b"  # Settings shows what really runs
    assert all(c["model"] == "llama3.2:3b" for c in fake.chats)


def test_env_model_is_a_lock(ollama, monkeypatch):
    ollama({"llama3.2:3b": {"tools": True}})
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:7b")
    assert local_llm.active_model() == "qwen2.5:7b"


def test_a_missing_model_is_usable_right_after_download(ollama):
    ollama({})
    settings.update({"offline": True, "local_model": "qwen2.5:3b"})
    with pytest.raises(router.AllProvidersFailed) as e:
        turn()
    assert any("not downloaded on this computer" in h for h in e.value.hints)
    assert local_llm.pull("qwen2.5:3b", wait=True)["state"] == "done"
    assert turn().model == "qwen2.5:3b"  # not "skipped: 404 in the last hour"


def test_local_404s_are_forgotten_quickly(ollama):
    providers.mark_unavailable("ollama", "x:1b")
    providers.mark_unavailable("gemini", "x")
    left = {k: v for k, v in providers._UNAVAILABLE.items()}
    assert left[("ollama", "x:1b")] - left[("gemini", "x")] < -3000  # 30 s vs an hour


def test_every_request_sets_a_big_enough_context_and_turns_thinking_down(ollama, monkeypatch):
    fake = ollama({"qwen3.5:4b": {"tools": True, "thinking": True}})
    settings.update({"local_model": "qwen3.5:4b"})
    t = turn()
    assert t.text == "Hello from qwen3.5:4b"  # <think> stripped
    body = fake.chats[-1]
    assert body["options"]["num_ctx"] == 8192 and body["think"] is False and body["tools"]
    assert body["options"]["temperature"] == 0.2  # tool turns stay deterministic
    monkeypatch.setenv("LOCAL_AI_CONTEXT", "65536")
    assert local_llm.context_size("qwen3.5:4b") == 32768  # never above what the model was trained for


def test_native_tool_calls_come_back(ollama):
    ollama({"qwen2.5:3b": {"tools": True}})
    settings.update({"local_model": "qwen2.5:3b"})
    t = turn("save it")
    assert t.mode == "native" and t.tool_calls[0]["name"] == "remember" and t.tool_calls[0]["arguments"] == {"text": "hi"}


def test_prefixed_and_loose_tool_calls_still_run(ollama):
    ollama({"qwen2.5:3b": {"tools": True}})
    settings.update({"local_model": "qwen2.5:3b"})
    prefixed = turn("prefix save")
    assert prefixed.tool_calls[0]["name"] == "remember" and prefixed.tool_calls[0]["arguments"] == {"text": "hi"}
    loose = turn("loose save")
    assert loose.tool_calls[0]["name"] == "remember" and loose.tool_calls[0]["arguments"] == {"text": "hi"}
    assert "remember" not in loose.text


def test_missing_choice_is_replaced_out_loud(ollama):
    ollama({"qwen2.5:0.5b": {"tools": True}})
    settings.update({"offline": True, "local_model": "qwen3.5:4b"})
    panel = local_llm.status()
    assert panel["model"] == "qwen2.5:0.5b"
    assert panel["substitution"]["weaker"] is True
    assert "weaker" in panel["substitution"]["message"]
    assert panel["tier"] == "limited"


def test_models_without_tools_skip_the_failing_native_call(ollama):
    fake = ollama({"gemma3:4b": {"tools": False}})
    settings.update({"local_model": "gemma3:4b"})
    t = turn()
    assert t.mode == "text" and t.text == "Hello from gemma3:4b"
    assert len(fake.chats) == 1 and "tools" not in fake.chats[0]  # no wasted 400


def test_messages_are_converted_for_ollama():
    msgs = providers._ollama_messages([
        {"role": "user", "content": [{"type": "text", "text": "look"},
                                     {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}]},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "remember", "arguments": '{"text": "a"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "saved"},
    ])
    assert msgs[0] == {"role": "user", "content": "look", "images": ["QUJD"]}
    assert msgs[1]["tool_calls"] == [{"function": {"name": "remember", "arguments": {"text": "a"}}}]
    assert msgs[1]["content"] == "" and msgs[2]["tool_name"] == "remember"


def test_ollama_not_running_says_what_to_do(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:9")
    monkeypatch.setattr(local_llm, "ollama_binary", lambda: None)
    with pytest.raises(providers.ProviderError, match="ollama.com/download") as e:
        providers.complete(REGISTRY["ollama"], [{"role": "user", "content": "hi"}], "qwen2.5:3b", "local")
    assert e.value.transient is False  # no pointless backoff retries


def test_test_button_uses_the_chat_settings(ollama):
    fake = ollama({"qwen2.5:3b": {"tools": True}})
    r = local_llm.test_ollama("qwen2.5:3b")
    assert r["ok"] and r["reply"] == "Hello from qwen2.5:3b" and r["context"] == 8192
    assert fake.chats[-1]["options"]["num_ctx"] == 8192
