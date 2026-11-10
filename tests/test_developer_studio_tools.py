"""Developer Studio tools keep hash checks, trust, and the hosted execution ban."""

import hashlib
import json

from automoto import developer_adapters, hosted, sandbox, tools as tools_mod
from automoto.developer_studio_tools import developer_diff, developer_read, developer_run, developer_save, developer_search, developer_trust
from automoto.tools import ToolContext

CTX = ToolContext()
SOURCE = "def average(values):\n    return sum(values) / (len(values) - 1)\n"
FIXED = "def average(values):\n    return sum(values) / len(values)\n"


def _project() -> str:
    folder = sandbox.default_root() / "uploads" / "calc"
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / "calc.py"
    if not file.exists():
        file.write_text(SOURCE, encoding="utf-8")
    return "uploads/calc"


def test_registered_levels_hosted_and_local_apps():
    tools = tools_mod.build()
    assert tools["developer_read"].level == "safe"
    assert tools["developer_diff"].level == "safe"
    assert tools["developer_save"].level == "risky"
    assert tools["developer_trust"].level == "risky"
    assert tools["developer_run"].level == "risky"
    assert "developer_run" in tools
    hosted_names = hosted.hosted_tools()
    assert "developer_run" not in hosted_names and "developer_read" not in hosted_names
    quiet = tools_mod.build(local_apps=False)
    assert "developer_run" not in quiet and "developer_read" in quiet


def test_diff_does_not_write_and_save_checks_the_hash():
    project = _project()
    developer_trust(CTX, project)
    opened = json.loads(developer_read(CTX, project, "calc.py"))
    file = sandbox.default_root() / "uploads" / "calc" / "calc.py"
    before = file.read_bytes()
    diff = json.loads(developer_diff(CTX, project, "calc.py", FIXED, opened["sha256"], opened["encoding"], opened["newline"]))
    assert diff["saved_to_disk"] is False and "len(values)" in diff["diff"]
    assert file.read_bytes() == before
    saved = developer_save(CTX, project, "calc.py", FIXED, opened["sha256"], opened["encoding"], opened["newline"])
    assert "true" in saved.lower() or "sha256" in saved
    assert "/ len(values)" in file.read_text(encoding="utf-8")
    assert hashlib.sha256(before).hexdigest() == opened["sha256"]


def test_search_calls_the_studio():
    project = _project()
    out = developer_search(CTX, project, "average")
    assert "calc.py" in out


def test_run_calls_the_adapter_and_not_on_hosted_tools(monkeypatch):
    seen = {}

    def fake(request, body):
        seen["id"] = body.id
        seen["risk"] = body.accept_execution_and_write_risk
        return {"ran": False, "reason": "test double"}

    monkeypatch.setattr(developer_adapters, "run", fake)
    out = developer_run(CTX, _project(), "pytest-local")
    assert seen["id"] == "pytest-local" and seen["risk"] is True and "test double" in out
