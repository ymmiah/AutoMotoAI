"""Registry discovery, central safety, and planner selection."""

import logging

import pytest

from automoto import hosted, planner, tenancy, tools as tools_mod
from automoto import studio_registry as registry
from automoto.studio_registry import StudioSpec
from automoto.tenancy import Tenant
from automoto.tools import Tool


def _ping(ctx, name: str = "world") -> str:
    return "pong " + name


def test_dropped_in_studio_is_planned_and_filtered(tmp_path, monkeypatch, caplog):
    (tmp_path / "sample_studio_tools.py").write_text(
        "from automoto.studio_registry import StudioSpec\n"
        "from automoto.tools import Tool\n"
        "def ping(ctx, name='world'):\n    return 'pong ' + name\n"
        "def write(ctx, name='x'):\n    return 'wrote ' + name\n"
        "def online(ctx):\n    return 'web'\n"
        "def run(ctx):\n    return 'ran'\n"
        "STUDIO = StudioSpec(id='dummy', name='Dummy Studio', words=r'\\bflarble\\b', exts=('.flarble',),\n"
        " fuzzy=('flarble',), how='Call dummy_ping.', hosted_ok=False, approval='safe',\n"
        " online_only=('dummy_online',), host_exec=('dummy_exec',),\n"
        " labels={'dummy_ping': 'Pinging', 'dummy_write': 'Writing the dummy',\n"
        " 'dummy_online': 'Checking online', 'dummy_exec': 'Running the dummy'},\n"
        " tools=(Tool('dummy_ping', 'Ping.', {'type':'object','properties':{},'required':[]}, 'safe', ping),\n"
        " Tool('dummy_write', 'Write.', {'type':'object','properties':{'name':{'type':'string'}},'required':['name']}, 'safe', write),\n"
        " Tool('dummy_online', 'Online.', {'type':'object','properties':{},'required':[]}, 'safe', online),\n"
        " Tool('dummy_exec', 'Run.', {'type':'object','properties':{},'required':[]}, 'safe', run)))\n",
        encoding="utf-8")
    (tmp_path / "broken_studio_tools.py").write_text("raise RuntimeError('studio boom')\n", encoding="utf-8")
    monkeypatch.setenv("AUTOMOTO_STUDIO_PATH", str(tmp_path))
    registry.reset()
    with caplog.at_level(logging.ERROR, logger="automoto.studio_registry"):
        tools = tools_mod.build()
    assert any("broken_studio_tools.py" in r.getMessage() for r in caplog.records)
    assert "dummy_ping" in tools and tools["dummy_ping"].level == "safe"
    assert tools["dummy_write"].level == "risky"  # registry refuses a safe write
    assert tools["dummy_exec"].level == "risky"
    assert tools["dummy_ping"].group == "studio:dummy"
    assert "dummy" in planner.classify("please flarble the widget")
    plan = planner.plan("please flarble the widget", tools)
    assert "dummy" in plan.capabilities and "dummy_ping" in plan.tools
    assert planner.human_step("dummy_ping", {}) == "Pinging"

    monkeypatch.setenv("AUTOMOTO_OFFLINE", "1")
    registry.reset()
    offline = tools_mod.build()
    assert "dummy_online" not in offline and "dummy_ping" in offline

    desktop = tools_mod.build(local_apps=False)
    assert "dummy_exec" not in desktop and "dummy_ping" in desktop
    hosted_names = set(hosted.hosted_tools())
    assert "dummy_ping" not in hosted_names and "dummy_exec" not in hosted_names
    registry.reset()


def test_entry_point_and_broken_entry_point(monkeypatch, caplog):
    spec_ok = StudioSpec(id="plug", name="Plug", words=r"\bplugette\b", tools=(
        Tool("plug_ping", "Ping.", {"type": "object", "properties": {}, "required": []}, "safe", _ping),
    ), hosted_ok=True)

    class Good:
        name = "good"

        def load(self):
            return lambda: spec_ok

    class Bad:
        name = "bad"

        def load(self):
            raise RuntimeError("entry boom")

    monkeypatch.setattr(registry, "_entry_point_objects", lambda: [Good(), Bad()])
    registry.reset()
    with caplog.at_level(logging.ERROR, logger="automoto.studio_registry"):
        found = {s.id for s in registry.load_studios()}
    assert "plug" in found
    assert any("bad" in r.getMessage() for r in caplog.records)
    tools = tools_mod.build()
    assert "plug_ping" in tools
    assert "plug_ping" in hosted.hosted_tools()
    registry.reset()


@pytest.mark.parametrize("goal,files,cap", [
    ("write my thesis chapter with Harvard refs and export Word", [], "document"),
    ("make an invoice for Northwind and an email-ready PDF", [], "spreadsheet"),
    ("verify DOI 10.1000/xyz123 for this research question", [], "research"),
    ("make a promo GIF in my brand colours", [], "visual"),
    ("fix the bug in this repo file and show the diff", ["uploads/calc/calc.py"], "developer"),
    ("explain this", ["pkg/main.ts"], "developer"),
    ("summarise", ["uploads/chapter.docx"], "document"),
    ("totals", ["invoices.csv"], "spreadsheet"),
    ("open it", ["promo.gif"], "visual"),
])
def test_prompts_pick_the_studio(goal, files, cap):
    assert cap in planner.classify(goal, files)


def test_hosted_session_can_call_a_hosted_studio(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_MODE", "multiuser")
    tenant = Tenant(id="u1", username="u", role="user", home=tmp_path / "user")
    token = tenancy._CURRENT.set(tenant)
    try:
        from automoto.document_studio_tools import document_list
        from automoto.developer_studio_tools import developer_open
        from automoto.tools import ToolContext

        listed = document_list(ToolContext())
        assert "documents" in listed
        with pytest.raises(tools_mod.ToolFailed, match="hosted"):
            developer_open(ToolContext(), project=".")
    finally:
        tenancy._CURRENT.reset(token)


def test_package_studios_survive_a_reset():
    registry.reset()
    ids = {s.id for s in registry.load_studios()}
    assert {"document", "spreadsheet", "research", "visual", "developer"} <= ids
