"""Agent loop tests with a scripted fake provider (no network, no keys)."""

import json

import pytest

from automoto import router, sandbox
from automoto.loop import Agent
from automoto.memory import Memory
from automoto.providers import REGISTRY, ProviderError


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    for p in REGISTRY.values():
        for k in p.env_keys:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AI_PROVIDER", "auto")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")


def scripted(*replies, log=None, fail=None):
    """Each reply is (text, calls) or an Exception. ``fail``: provider ids that always 429."""
    seq = list(replies)

    def t(spec, messages, model, key, *, tools, native, **_):
        if log is not None:
            log.append({"provider": spec.id, "model": model, "native": native, "messages": messages})
        if fail and spec.id in fail:
            raise ProviderError(spec.id, "429 rate limited", status=429)
        r = seq.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    return t


def call(name, **args):
    return {"id": f"c_{name}", "name": name, "arguments": args}


def agent(transport, **kw):
    return Agent(memory=Memory(), skills={}, transport=transport, **kw)


def test_native_tool_loop_runs_tools_and_feeds_results_back():
    log = []
    t = scripted(("", [call("write_file", path="scratch/a.txt", content="hi")]),
                 ("", [call("read_file", path="scratch/a.txt")]),
                 ("The file says hi.", []), log=log)
    res = agent(t).run("make a file")
    assert res.text == "The file says hi." and res.steps == 3 and res.stopped == "done"
    assert (sandbox.root() / "scratch" / "a.txt").read_text() == "hi"
    tool_msgs = [m for m in log[-1]["messages"] if m.get("role") == "tool"]
    assert [m["content"] for m in tool_msgs] == ["wrote 2 chars to scratch/a.txt", "hi"]
    assert all(entry["native"] for entry in log)


def test_text_fallback_parses_json_tool_blocks(monkeypatch):
    monkeypatch.setenv("AUTOMOTO_TOOL_MODE", "text")
    block = '```tool\n{"name": "list_dir", "arguments": {"path": "."}}\n```'
    log = []
    res = agent(scripted((block, []), ("done", []), log=log)).run("list files")
    assert res.text == "done"
    assert not log[0]["native"]
    assert any(e["type"] == "tool_result" and e["name"] == "list_dir" and e["ok"] for e in res.events)


def test_native_rejection_retries_same_model_in_text_mode():
    log = []
    t = scripted(ProviderError("nim", "400 tools not supported", status=400),
                 ('```tool\n{"name":"recall","arguments":{}}\n```', []), ("ok", []), log=log)
    res = agent(t).run("hi")
    assert res.text == "ok"
    assert [e["native"] for e in log[:2]] == [True, False] and log[0]["model"] == log[1]["model"]


def test_failover_mid_loop_keeps_history(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-q")
    log = []
    replies = [("", [call("remember", fact="likes tea")]),
               ProviderError("x", "429", status=429), ProviderError("x", "429", status=429),
               ("Noted.", [])]
    res = agent(scripted(*replies, log=log)).run("remember I like tea", prefer="nim")
    assert res.text == "Noted."
    providers = [e["provider"] for e in log]
    assert providers[0] == "nim" and providers[-1] == "groq"
    assert any(m.get("role") == "tool" for m in log[-1]["messages"])  # history survived the switch
    assert any(e["type"] == "model" and e["switched"] for e in res.events)


def test_max_steps_guard(monkeypatch):
    monkeypatch.setattr(router, "ask", lambda *a, **k: router.Answer("summary", "nim", "m", "chat"))
    forever = scripted(*[("", [call("recall", query="x")]) for _ in range(10)])
    res = agent(forever).run("loop", max_steps=3)
    assert res.stopped == "max_steps" and res.steps == 3 and res.text == "summary"


def test_risky_call_waits_for_approval_and_denial_is_reported():
    asked = []
    t = scripted(("", [call("run_shell", command="echo hi")]), ("ok, skipped", []))
    res = agent(t).run("run echo", approver=lambda c, d: asked.append((c["name"], d.level)) or False)
    assert asked == [("run_shell", "risky")]
    result = next(e for e in res.events if e["type"] == "tool_result")
    assert not result["ok"] and "denied" in result["output"]


def test_approved_shell_runs_in_workspace():
    t = scripted(("", [call("run_shell", command="echo cousin")]), ("done", []))
    res = agent(t).run("echo", approver=lambda c, d: True)
    out = next(e for e in res.events if e["type"] == "tool_result")
    assert out["ok"] and "cousin" in out["output"]


def test_blocked_call_never_reaches_approver():
    asked = []
    t = scripted(("", [call("read_file", path="../../etc/passwd")]), ("can't", []))
    res = agent(t).run("read passwd", approver=lambda c, d: asked.append(1) or True)
    assert not asked
    assert "blocked" in next(e for e in res.events if e["type"] == "tool_result")["output"]


def test_unknown_tool_is_reported_not_crashing():
    res = agent(scripted(("", [call("rm_everything")]), ("sorry", []))).run("x")
    assert res.text == "sorry"


def test_no_keys_gives_error_result(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY")
    res = agent(scripted()).run("hi")
    assert res.stopped == "error" and "No AI provider key" in res.text


def test_memory_and_skills_are_in_system_prompt(tmp_path):
    m = Memory()
    m.remember("Yasin studies at BCU")
    log = []
    from automoto import skills
    sk = skills.discover()
    Agent(memory=m, skills=sk, transport=scripted(("hi", []), log=log)).run("hello")
    system = log[0]["messages"][0]["content"]
    assert "Yasin studies at BCU" in system and "research-brief" in system


def test_render_roundtrip_formats():
    from automoto import providers, toolcalls

    hist = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
            {"role": "assistant", "content": "", "tool_calls": [call("list_dir", path=".")]},
            {"role": "tool", "tool_call_id": "c_list_dir", "name": "list_dir", "content": "a.txt"}]
    oa = toolcalls.render_openai(hist)
    assert oa[2]["tool_calls"][0]["function"]["arguments"] == json.dumps({"path": "."})
    assert oa[3] == {"role": "tool", "tool_call_id": "c_list_dir", "content": "a.txt"}
    system, an = toolcalls.render_anthropic(hist, providers._to_anthropic)
    assert system == "s" and an[1]["content"][0]["type"] == "tool_use" and an[2]["content"][0]["type"] == "tool_result"
    tx = toolcalls.render_text(hist, [{"type": "function", "function": {"name": "list_dir", "description": "d",
                                                                         "parameters": {"properties": {}}}}])
    assert "```tool" in tx[2]["content"] and tx[3]["role"] == "user" and "list_dir" in tx[0]["content"]


def test_bad_key_provider_is_skipped_for_rest_of_run(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-q")
    log = []

    def t(spec, messages, model, key, *, tools, native, **_):
        log.append(spec.id)
        if spec.id == "groq":
            raise ProviderError("groq", "401 invalid key", status=401)
        return ("", [call("recall")]) if len(log) < 4 else ("done", [])

    res = agent(t).run("x", prefer="groq")
    assert res.text == "done"
    assert log.count("groq") == 1  # one model tried, then skipped for the whole run
