"""Offline agent behaviour with a scripted local model: no cloud leak, multi-step tools, no fake completion."""

import pytest

from automoto import sandbox
from automoto.loop import Agent
from automoto.memory import Memory
from automoto.providers import REGISTRY, ProviderError


@pytest.fixture(autouse=True)
def offline_local(monkeypatch):
    for p in REGISTRY.values():
        for k in p.env_keys:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AUTOMOTO_OFFLINE", "1")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:9")


def scripted(*replies, log=None):
    seq = list(replies)

    def transport(spec, messages, model, key, *, tools, native, **_):
        if log is not None:
            log.append({"provider": spec.id, "model": model, "messages": messages})
        r = seq.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    return transport


def call(name, **args):
    return {"id": f"c_{name}", "name": name, "arguments": args}


def test_offline_multi_step_stays_on_the_local_model_and_states_the_rules(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")
    log = []
    transport = scripted(
        ("", [call("write_file", path="scratch/note.txt", content="hello offline")]),
        ("", [call("read_file", path="scratch/note.txt")]),
        ("The note says hello offline.", []),
        log=log,
    )
    res = Agent(memory=Memory(), skills={}, transport=transport).run("save a note and read it back")
    assert res.stopped == "done" and res.text == "The note says hello offline."
    assert res.steps == 3
    assert {entry["provider"] for entry in log} == {"ollama"}
    assert all(entry["model"] == "qwen2.5:3b" for entry in log)
    guide = log[0]["messages"][0]["content"]
    assert "Local model operating rules" in guide
    assert "Offline mode is on" in guide
    assert "do not use or claim a web search" in guide
    assert (sandbox.root() / "scratch" / "note.txt").read_text() == "hello offline"


def test_offline_failure_does_not_fall_back_to_cloud(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    log = []

    def transport(spec, messages, model, key, *, tools, native, **_):
        log.append(spec.id)
        raise ProviderError("ollama", "model failed", status=400)

    res = Agent(memory=Memory(), skills={}, transport=transport).run("hi")
    assert res.stopped == "error"
    assert log and set(log) == {"ollama"}
    assert "gemini" not in res.text


def test_local_model_cannot_claim_the_work_is_done_before_a_tool_runs():
    log = []
    transport = scripted(
        ("I've created the report at out/report.docx.", []),
        ("", [call("write_file", path="scratch/report.txt", content="report")]),
        ("Saved.", []),
        log=log,
    )
    res = Agent(memory=Memory(), skills={}, transport=transport).run("write the report")
    assert res.text == "Saved." and res.stopped == "done"
    assert any(e["type"] == "nudge" and e["reason"] == "unverified" for e in res.events)
    # The agent keeps one history list, so every log entry sees the finished transcript.
    assert any("No tool has run" in (m.get("content") or "") for m in log[-1]["messages"])
    assert (sandbox.root() / "scratch" / "report.txt").read_text() == "report"


def test_cloud_runs_do_not_get_the_local_rules(monkeypatch):
    monkeypatch.delenv("AUTOMOTO_OFFLINE", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")
    log = []
    res = Agent(memory=Memory(), skills={}, transport=scripted(("hello", []), log=log)).run("hi")
    assert res.text == "hello"
    assert log[0]["provider"] == "nim"
    assert "Local model operating rules" not in log[0]["messages"][0]["content"]
