"""The task planner: one smart assistant that picks the few tools and skills a task needs."""

import pytest

from automoto import planner, skills as skills_mod, tools as tools_mod
from automoto.loop import Agent
from automoto.memory import Memory
from automoto.providers import REGISTRY

TOOLS = tools_mod.build()


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    for p in REGISTRY.values():
        for k in p.env_keys:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AI_PROVIDER", "auto")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")


@pytest.mark.parametrize("goal,files,cap", [
    ("summarise my slides", ["uploads/deck.pptx"], "slides"),
    ("", ["uploads/My Report.docx"], "word"),
    ("can u make a presntation abt dogs", [], "slides"),
    ("make me a spredsheet for my budget", [], "sheet"),
    ("analyse this", ["data/sales.csv"], "data"),
    ("check my plugin", ["hello-banner.zip"], "archive"),
    ("fix the wordpress plugin in hello.zip", [], "wordpress"),
    ("my python script crashes with a traceback", [], "code"),
    ("what's the latest news on AI?", [], "web"),
    ("resize this photo", ["a.png"], "image"),
    ("every morning at 8 send me the headlines", [], "routines"),
    ("remember that I like tea", [], "memory"),
    ("run rm -rf /", [], "terminal"),
])
def test_classify(goal, files, cap):
    assert cap in planner.classify(goal, files)


def test_plan_is_small_and_always_has_the_core():
    p = planner.plan("summarise uploads/deck.pptx", TOOLS, skills=skills_mod.discover())
    assert p.capabilities[0] == "slides" and "office_create_pptx" in p.tools
    assert set(planner.ALWAYS) <= set(p.tools) and len(p.tools) <= 16
    assert "powerpoint-decks" in p.skills
    assert not any(TOOLS[n].hidden for n in p.tools)  # merged tools are never offered
    chat = planner.plan("write a poem about the sea", TOOLS)
    assert chat.capabilities == [] and len(chat.tools) <= 12


def test_prompt_block_injects_skill_with_merged_names():
    sk = skills_mod.discover()
    p = planner.plan("make a word report about bees", TOOLS, skills=sk)
    block = planner.prompt_block(p, sk)
    assert "## This task" in block and "word-documents" in block and len(block) <= 3600
    assert "office_render" not in block and "office_read" not in block


def test_mcp_tools_join_by_keyword_or_server_name():
    fake = dict(TOOLS)
    fake["mcp__linear__list_issues"] = tools_mod.Tool("mcp__linear__list_issues", "Linear issues", {"type": "object",
                                                       "properties": {}}, "risky", lambda ctx: "x", "mcp:linear")
    assert "mcp__linear__list_issues" in planner.plan("show my linear issues", fake).tools
    assert "mcp__linear__list_issues" in planner.plan("list my github issues", fake).tools  # connectors capability
    assert "mcp__linear__list_issues" not in planner.plan("write a poem", fake).tools


def test_human_step_labels():
    assert planner.human_step("read_file", {"path": "uploads/deck.pptx"}) == "Reading your slides"
    assert planner.human_step("office_create_xlsx", {"path": "x.xlsx"}) == "Building your spreadsheet"
    assert planner.human_step("mcp__github__list_issues", {}) == "Using github (list issues)"
    assert "secret" not in planner.human_step("service_api", {"service": "github", "body": {"token": "secret"}})


def test_ideas():
    d = planner.default_ideas()
    assert len(d) == 8 and all(i["title"] and i["prompt"] for i in d)
    ideas = planner.ideas_for(["uploads/deck.pptx"])
    assert ideas and "uploads/deck.pptx" in ideas[0]["prompt"] and ideas[0]["capability"] == "slides"


def test_merged_tools_still_run_when_called():
    ctx = tools_mod.ToolContext(memory=Memory(), skills={})
    ok, out = tools_mod.call(TOOLS["office_create_docx"], ctx, {"path": "a.docx", "spec": {"blocks": [
        {"type": "heading", "text": "Hello"}]}})
    assert ok, out
    for name in ("office_read", "read_file"):
        ok, out = tools_mod.call(TOOLS[name], ctx, {"path": "a.docx"})
        assert ok and "Hello" in out, (name, out)
    assert TOOLS["office_read"].hidden and not TOOLS["read_file"].hidden
    assert len(tools_mod.offered(TOOLS)) < len(TOOLS)


def _scripted(*replies, log):
    seq = list(replies)

    def t(spec, messages, model, key, *, tools, native, **_):
        log.append([s["function"]["name"] for s in tools])
        return seq.pop(0)
    return t


def test_loop_offers_the_plan_and_more_tools_expands_it():
    log = []
    t = _scripted(("", [{"id": "1", "name": "more_tools", "arguments": {"need": "spreadsheet"}}]),
                  ("ok", []), log=log)
    events = []
    res = Agent(memory=Memory(), skills={}, transport=t).run("write a haiku", on_event=events.append)
    assert res.text == "ok"
    assert "office_create_xlsx" not in log[0] and "office_create_xlsx" in log[1]
    plans = [e for e in events if e["type"] == "plan"]
    assert len(plans) == 2 and "sheet" in plans[1]["capabilities"]
    call = next(e for e in events if e["type"] == "tool_call")
    assert call["label"] == "Getting more tools"


def test_planner_off_offers_everything(monkeypatch):
    monkeypatch.setenv("AUTOMOTO_PLANNER", "off")
    log = []
    Agent(memory=Memory(), skills={}, transport=_scripted(("ok", []), log=log)).run("hi")
    assert len(log[0]) == len(tools_mod.offered(Agent(memory=Memory(), skills={}).tools))
