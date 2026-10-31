"""One central assistant: research library, discovery, feeds, static inspection, the local page inspector,
workspace layout + artifacts, automatic memory, the server-setup helper and the central brand name."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import (automemory, brand, devbrowser, layout, local_llm, netguard, planner, policy, research,
                      sandbox, server, server_setup, tenancy, tools)
from automoto.loop import Agent
from automoto.memory import Memory
from automoto.providers import REGISTRY
from automoto.tools import ToolContext, ToolFailed


@pytest.fixture
def ws(monkeypatch, tmp_path):
    w = tmp_path / "ws"
    monkeypatch.setenv("AUTOMOTO_WORKDIR", str(w))
    from automoto import home

    layout.ensure(home.workspace())
    return sandbox.default_root()


CTX = ToolContext(memory=None, skills={})


# -- research library ---------------------------------------------------------------------------
def test_library_store_search_and_fts_injection(ws):
    research.store("https://docs.example/a", "Routing guide", "Use the router to map URLs to views. Routing is fast.",
                   library="demo", version="1")
    research.store("https://docs.example/a", "Routing guide v2", "Version two routing adds nested routes.",
                   library="demo", version="2")
    hits = research.search("routing")
    assert {h["version"] for h in hits} == {"1", "2"}
    assert research.search("routing", version="2")[0]["title"] == "Routing guide v2"
    for evil in ('" OR 1=1 --', "title:*", "NEAR(a b)", "'; DROP TABLE docs; --"):
        research.search(evil)  # quoted: never an FTS syntax error or injection
    with pytest.raises(ToolFailed):
        research.search("^*")
    assert research.library_path().is_relative_to(ws / "memory")


def test_discover_github_and_feed_parsing(monkeypatch):
    monkeypatch.setattr(research, "_json", lambda url: {"items": [{"full_name": "ex/repo", "html_url": "https://github.com/ex/repo",
                                                                    "description": "demo", "stargazers_count": 9}]})
    out = research.discover_search("github", "agents")
    assert out["results"][0]["title"] == "ex/repo"
    with pytest.raises(ToolFailed):
        research.discover_search("myspace", "x")

    class R:
        status = 200
        body = b"<rss><channel><item><title>Hello</title><link>https://e.x/1</link></item></channel></rss>"

    monkeypatch.setattr(netguard, "request", lambda url, **kw: R())
    assert research.read_feed("https://e.x/feed")["items"][0]["title"] == "Hello"
    R.body = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><rss><item><title>&e;</title></item></rss>'
    with pytest.raises(ToolFailed):
        research.read_feed("https://e.x/feed")  # defusedxml refuses entities (XXE)


def test_project_inspect_is_static_and_outside_is_risky(ws, tmp_path):
    (ws / "projects").mkdir(exist_ok=True)
    (ws / "projects" / "app.py").write_text("import requests\nrequests.get('https://x', verify=False)\nraise SystemExit(3)\n")
    out = json.loads(research.project_inspect(CTX, path="projects"))
    assert "tls-verification-off" in json.dumps(out)
    assert policy.classify("project_inspect", "safe", {"path": "projects"})[0] == "safe"
    assert policy.classify("project_inspect", "safe", {"path": str(tmp_path)})[0] in ("risky", "blocked")


def test_offline_mode_removes_online_research_tools():
    assert {"discover", "read_feed"} <= set(local_llm.ONLINE_TOOLS)


def test_research_tools_are_fenced_and_taint():
    from automoto import loop

    assert {"discover", "read_feed", "library_add", "page_inspect"} <= loop.TAINTING_TOOLS
    assert {"library_search", "project_inspect"} <= loop.UNTRUSTED_TOOLS


# -- local page inspector ------------------------------------------------------------------------
def test_page_inspect_default_deny_and_loopback_only(monkeypatch):
    monkeypatch.delenv("AUTOMOTO_BROWSER_ORIGINS", raising=False)
    with pytest.raises(ToolFailed, match="No approved origin"):
        devbrowser.authorise("http://127.0.0.1:3000/")
    monkeypatch.setenv("AUTOMOTO_BROWSER_ORIGINS", "http://127.0.0.1:3000")
    assert devbrowser.authorise("http://127.0.0.1:3000/page") == "http://127.0.0.1:3000"
    for bad in ("http://127.0.0.1:3001/", "http://example.com/", "http://user:pw@127.0.0.1:3000/", "file:///etc/passwd",
                "http://127.0.0.1.nip.io:3000/"):
        with pytest.raises(ToolFailed):
            devbrowser.authorise(bad)
    monkeypatch.setenv("AUTOMOTO_BROWSER_ORIGINS", "http://127.0.0.1:3000/some/path")
    with pytest.raises(ToolFailed, match="origins"):
        devbrowser.authorise("http://127.0.0.1:3000/")
    monkeypatch.setenv("AUTOMOTO_BROWSER_ORIGINS", "http://127.0.0.1:3000")
    monkeypatch.setattr(tenancy, "multiuser", lambda: True)
    with pytest.raises(ToolFailed, match="hosted"):
        devbrowser.authorise("http://127.0.0.1:3000/")


def test_page_inspect_is_risky_and_local_only():
    t = {x.name: x for x in devbrowser.TOOLS}["page_inspect"]
    assert t.level == "risky"
    assert "page_inspect" not in tools.build(local_apps=False) and "server_setup" not in tools.build(local_apps=False)
    assert "page_inspect" in tools.build() and "library_search" in tools.build(local_apps=False)


# -- layout + artifacts ----------------------------------------------------------------------------
def test_workspace_layout_and_artifact_policy(ws):
    for f in ("uploads", "artifacts", "projects", "memory", "skills", "logs", "scratch"):
        assert (ws / f).is_dir()
    assert (ws / "README.md").exists()
    d = layout.artifact_dir("Please make me a budget report for March")
    assert d.startswith("artifacts/") and d.endswith("budget-report-march")
    assert policy.classify("write_file", "risky", {"path": d + "/report.md"}) == ("safe", "new file in artifacts/")
    (ws / "artifacts" / "old.md").write_text("x")
    assert policy.classify("write_file", "risky", {"path": "artifacts/old.md"})[0] == "risky"  # overwrite asks
    assert policy.classify("edit_file", "risky", {"path": "artifacts/old.md"})[0] == "risky"
    assert policy.classify("write_file", "risky", {"path": "artifacts/../uploads/x.md"})[0] == "risky"
    assert policy.classify("office_create_docx", "risky", {"path": "artifacts/new.docx"})[0] == "safe"


def _scripted(*replies):
    seq = list(replies)

    def t(spec, messages, model, key, *, tools, native, **_):
        return seq.pop(0)
    return t


@pytest.fixture
def ai(monkeypatch):
    for p in REGISTRY.values():
        for k in p.env_keys:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AI_PROVIDER", "auto")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")


def test_run_lists_its_artifacts_and_logs(ws, ai):
    t = _scripted(("", [{"id": "c1", "name": "write_file", "arguments": {"path": "artifacts/2026-x/notes.md", "content": "hi"}}]),
                  ("Saved notes.md.", []))
    events = []
    res = Agent(memory=Memory(), skills={}, transport=t).run("write my notes", on_event=events.append)
    assert [f["path"] for f in res.artifacts] == ["artifacts/2026-x/notes.md"]
    ev = [e for e in events if e["type"] == "artifacts"]
    assert ev and ev[0]["files"][0]["name"] == "notes.md"
    assert [e["type"] for e in events].index("artifacts") < [e["type"] for e in events].index("final")
    assert "write my notes" in next((ws / "logs").glob("*.md")).read_text()
    plan_text = Agent(memory=Memory(), skills={}).system(planner.plan("write a report", tools.build(), skills={}))
    assert "artifacts/" in plan_text


# -- automatic memory ------------------------------------------------------------------------------
def test_extract_facts_and_never_secrets():
    got = [f["text"] for f in automemory.extract(
        "Hi, my name is Yasin. I prefer British English. I live in Birmingham. I don't like long emails.")]
    assert got == ["The user's name is Yasin", "Prefers British English", "Lives in / is from Birmingham",
                   "Dislikes long emails"]
    for secret in ("remember that my password is hunter2", "remember my api key is sk-abc", "my name is Bob, email bob@x.com",
                   "remember my card number 4111111111111111", "remember the token ghp_abcdef"):
        assert automemory.extract(secret) == [], secret
    assert automemory.extract("What is my name?") == []
    assert automemory.extract("I like this answer") == []
    assert automemory.extract("I am a bit tired") == []


def test_learn_dedups_replaces_keyed_facts_and_mirrors(ws):
    m = Memory()
    assert len(automemory.learn(m, "My name is Yasin. I like Python.")) == 2
    assert automemory.learn(m, "I like Python!") == []  # near-duplicate
    out = automemory.learn(m, "Call me Yas")
    assert out[0]["replaced"] == "The user's name is Yasin"
    texts = [f["text"] for f in m.facts()]
    assert "The user's name is Yas" in texts and "The user's name is Yasin" not in texts
    assert all("auto" in f["tags"] for f in m.facts())
    md = (ws / "memory" / "MEMORY.md").read_text()
    assert "## About you" in md and "Yas" in md


def test_auto_memory_setting_off(ws):
    from automoto import settings

    settings.update({"auto_memory": False})
    assert automemory.learn(Memory(), "My name is Yasin") == []
    with pytest.raises(settings.SettingsError):
        settings.update({"auto_memory": "yes"})


def test_agent_run_learns_and_emits_memory_event(ws, ai):
    events = []
    Agent(memory=Memory(), skills={}, transport=_scripted(("Hello Yasin!", []))).run(
        "my name is Yasin, say hi", on_event=events.append)
    mem = [e for e in events if e["type"] == "memory"]
    assert mem and mem[0]["facts"][0]["text"] == "The user's name is Yasin"
    ev2 = []
    Agent(memory=Memory(), skills={}, transport=_scripted(("ok", [])), client="routine").run(
        "my name is Bob", on_event=ev2.append)
    assert not [e for e in ev2 if e["type"] == "memory"]  # routines never teach memory


def test_memory_edit_endpoint(ws):
    c = TestClient(server.app)
    h = {"X-AutoMoto-Token": server.SESSION_TOKEN}
    fid = c.post("/api/memory", json={"text": "Likes tea"}, headers=h).json()["id"]
    assert c.put(f"/api/memory/{fid}", json={"text": "Likes green tea"}, headers=h).json() == {"ok": True}
    assert any(f["text"] == "Likes green tea" for f in c.get("/api/memory", headers=h).json()["facts"])
    assert c.put("/api/memory/99999", json={"text": "x"}, headers=h).status_code == 404
    assert c.put(f"/api/memory/{fid}", json={"text": ""}, headers=h).status_code == 422
    assert c.put(f"/api/memory/{fid}", json={"text": "x"}).status_code in (401, 403)


# -- server helper ----------------------------------------------------------------------------------
def test_server_setup_check_plan_write(ws):
    chk = json.loads(server_setup.server_setup(CTX, action="check"))
    assert {c["check"] for c in chk["checks"]} >= {"Python 3.10+", "Docker"}
    for target in server_setup.TARGETS:
        p = json.loads(server_setup.server_setup(CTX, action="plan", target=target))
        assert p["steps"] and "approval" in p["note"]
    out = json.loads(server_setup.server_setup(CTX, action="write", target="oracle", domain="ai.example.com"))
    folder = ws / out["folder"]
    assert folder.is_relative_to(ws / "artifacts" / "server-setup")
    names = {p.name for p in folder.iterdir()}
    assert {"compose.yaml", "Caddyfile", "cloud-init.yaml", ".env.template", "CHECKLIST.md"} <= names
    env = (folder / ".env.template").read_text()
    assert "<paste your key>" in env and "AUTOMOTO_MODE=multiuser" in env
    assert "ai.example.com" in (folder / "Caddyfile").read_text()
    again = json.loads(server_setup.server_setup(CTX, action="write", target="oracle"))
    assert again["folder"] != out["folder"]  # never overwrites
    with pytest.raises(ToolFailed):
        server_setup.server_setup(CTX, action="write", target="oracle", domain="x.com; rm -rf /")
    with pytest.raises(ToolFailed):
        server_setup.server_setup(CTX, action="plan", target="mars")
    assert policy.classify("server_setup", "safe", {"action": "write"})[0] == "safe"


def test_server_setup_never_runs_commands(monkeypatch, ws):
    import subprocess

    def boom(*a, **k):
        raise AssertionError("server_setup must not run commands")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    for action in ("plan", "write"):
        server_setup.server_setup(CTX, action=action, target="tunnel")


def test_planner_routes_prompts_to_the_right_tools():
    avail = tools.build()
    p = planner.plan("help me host automoto on oracle cloud so I can reach it from my phone", avail, skills={})
    assert "server" in p.capabilities and "server_setup" in p.tools
    p = planner.plan("save the fastapi docs to my library and search them for middleware", avail, skills={})
    assert "library" in p.capabilities and {"library_add", "library_search"} <= set(p.tools)
    p = planner.plan("what are developers saying on hacker news about rust", avail, skills={})
    assert "discover" in p.tools
    assert planner.human_step("server_setup", {}) == "Preparing your server setup"


# -- brand -------------------------------------------------------------------------------------------
def test_brand_is_central_and_overridable(monkeypatch):
    assert brand.name() == "AutoMoto AI"
    monkeypatch.setenv("AUTOMOTO_BRAND_NAME", "Nova <AI>")
    monkeypatch.setenv("AUTOMOTO_BRAND_SHORT", "Nova")
    assert brand.fill("<title>__BRAND__</title> __BRAND_SHORT__") == "<title>Nova &lt;AI&gt;</title> Nova"
    html = (Path(server.__file__).parent / "web" / "index.html").read_text()
    assert "__BRAND__" in html and 'name="automoto-brand"' in html
