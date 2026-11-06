"""One request finishes the task. The user does not pick tools, online or offline."""

import pytest

from automoto import planner, sandbox, tools
from automoto.loop import Agent
from automoto.memory import Memory
from automoto.providers import REGISTRY


def scripted(*replies, log=None):
    seq = list(replies)

    def transport(spec, messages, model, key, *, tools, native, **_):
        if log is not None:
            log.append({"provider": spec.id, "messages": messages, "tool_names": [
                (s.get("function") or s).get("name") for s in (tools or [])]})
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return transport


def call(name, **args):
    return {"id": f"c_{name}", "name": name, "arguments": args}


def _owns_the_task(prompt: str) -> None:
    assert "The user writes one request. You finish it." in prompt
    assert "Do not ask the user to pick a tool" in prompt
    assert "Never show a tool menu" in prompt
    assert "Tools available:" not in prompt


@pytest.fixture
def cloud(monkeypatch):
    for p in REGISTRY.values():
        for k in p.env_keys:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("AUTOMOTO_OFFLINE", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")


def test_online_one_request_finishes_two_steps_without_a_tool_menu(cloud):
    log = []
    events = []
    transport = scripted(
        ("", [call("write_file", path="scratch/note.txt", content="done")]),
        ("", [call("read_file", path="scratch/note.txt")]),
        ("Saved note.txt. It says done.", []),
        log=log,
    )
    res = Agent(memory=Memory(), skills={}, transport=transport).run(
        "save a note that says done and read it back", on_event=events.append)
    assert res.stopped == "done" and res.text.startswith("Saved note.txt")
    assert res.provider == "nim"
    assert [e["name"] for e in events if e["type"] == "tool_call"] == ["write_file", "read_file"]
    labels = [e["label"] for e in events if e["type"] == "tool_call"]
    assert labels == ["Writing note.txt", "Reading note.txt"]
    assert all("_" not in label for label in labels)
    _owns_the_task(log[0]["messages"][0]["content"])
    # The model is offered tools. The user never had to name them.
    assert "write_file" in log[0]["tool_names"] and "read_file" in log[1]["tool_names"]
    assert (sandbox.root() / "scratch" / "note.txt").read_text() == "done"
    plan = next(e for e in events if e["type"] == "plan")
    assert plan["summary"].startswith("I'll take this from here")
    assert "write_file" not in plan["summary"]


def test_offline_one_request_uses_only_the_local_model(monkeypatch):
    for p in REGISTRY.values():
        for k in p.env_keys:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    monkeypatch.setenv("AUTOMOTO_OFFLINE", "1")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:9")
    log = []
    events = []
    transport = scripted(
        ("", [call("write_file", path="scratch/offline.txt", content="local")]),
        ("", [call("read_file", path="scratch/offline.txt")]),
        ("The note is saved.", []),
        log=log,
    )
    res = Agent(memory=Memory(), skills={}, transport=transport).run(
        "save a note and read it back", on_event=events.append)
    assert res.stopped == "done" and res.provider == "ollama"
    assert {entry["provider"] for entry in log} == {"ollama"}
    prompt = log[0]["messages"][0]["content"]
    _owns_the_task(prompt)
    assert "Decide the steps yourself" in prompt
    assert "Offline mode is on" in prompt
    assert [e["label"] for e in events if e["type"] == "tool_call"] == ["Writing offline.txt", "Reading offline.txt"]
    assert (sandbox.root() / "scratch" / "offline.txt").read_text() == "local"


def test_plan_summary_is_plain_language():
    plan = planner.plan("Make a Word report about exercise", tools.build())
    summary = plan.as_dict()["summary"]
    assert summary.startswith("I'll take this from here: ")
    assert "Word documents" in summary
    assert "office_" not in summary
