"""V53 proves bounded agents can mutate code only through reviewed V51 patches.

These are offline tests: no provider, network, shell, Git or API keys are needed.
"""
from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from automoto import developer_agent_patch as bridge
from automoto import developer_safe_patch as patch
from automoto import sandbox, server
from automoto.developer_coding_budget import CodingBudget
from automoto.tools import ToolContext, ToolFailed

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
OLD = "def calculate(a, b):\n    return a - b\n"
NEW = "def calculate(a, b):\n    return a + b\n"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v53"
    root.mkdir(parents=True)
    (root / "calc.py").write_text(OLD, encoding="utf-8")
    (root / ".env").write_text("PASSWORD=never-read-this", encoding="utf-8")
    with patch.LOCK:
        patch.PREVIEWS.clear()
    with TestClient(server.app) as http:
        trust = http.post("/api/developer/studio/trust", headers=AUTH,
            json={"project": str(root), "trusted": True, "confirmed": True})
        assert trust.status_code == 200, trust.text
        yield http, root
    with patch.LOCK:
        patch.PREVIEWS.clear()


def _run(root, *, old="return a - b", new="return a + b", path="calc.py", sha=None, approve=None):
    with sandbox.use_root(str(root)):
        budget = CodingBudget(max_steps=4, max_operations=8, max_seconds=90)
        agent = server._agent_factory(
            desktop=False, client="web", workspace=str(root), coding_budget=budget,
        )
        agent._touched = []
        budget.start()
        call = {"id": "patch-call-1", "name": "developer_agent_patch",
                "arguments": {
                    "path": path,
                    "expected_sha256": sha or hashlib.sha256((root / "calc.py").read_bytes()).hexdigest(),
                    "old_fragment": old, "new_fragment": new,
                }}
        events = []
        result = agent._run_call(call, 1, approve or (lambda *_: False), events.append)
        return agent, result, events


def test_bounded_registry_has_no_alternate_code_write_or_execution(workspace):
    _, root = workspace
    with sandbox.use_root(str(root)):
        bounded = server._agent_factory(coding_budget=CodingBudget(), workspace=str(root))
        tools = bounded.tools
        assert "developer_agent_patch" in tools
        assert tools["developer_agent_patch"].level == "risky"
        for dangerous in ("developer_save", "write_file", "edit_file", "run_shell",
                          "developer_run", "more_tools", "run_app", "run_app_script",
                          "service_api", "open_url", "routine", "developer_trust"):
            assert dangerous not in tools, dangerous
        assert set(tools) <= {
            "read_file", "list_dir", "search_files", "project_inspect",
            "developer_open", "developer_read", "developer_search", "developer_sources",
            "developer_symbols", "developer_languages", "developer_lsp",
            "developer_diff", "developer_agent_patch",
        }
        with pytest.raises(ToolFailed):
            tools["developer_agent_patch"].fn(ToolContext(), path="calc.py")
        assert "developer_save" in server._agent_factory(workspace=str(root)).tools


def test_reviewed_diff_is_exact_and_patch_is_undoable(workspace, monkeypatch):
    http, root = workspace
    monkeypatch.setenv("AUTOMOTO_APPROVAL", "auto")
    snapshots = []

    def approve(call, decision):
        assert decision.action == "ask"
        evidence = call["args"]
        snapshots.append(evidence)
        assert evidence["prepared_by_server"]
        assert evidence["path"] == "calc.py"
        assert evidence["original_sha256"] == hashlib.sha256(OLD.encode()).hexdigest()
        assert "-    return a - b" in evidence["preview_diff"]
        assert "+    return a + b" in evidence["preview_diff"]
        assert "token" not in evidence
        assert (root / "calc.py").read_text() == OLD, "approval came before write"
        return True

    _, response, events = _run(root, approve=approve)
    assert json.loads(response["content"])["applied"] is True
    assert (root / "calc.py").read_text() == NEW
    assert len(snapshots) == 1
    assert any(e["type"] == "approval" and e["approved"] for e in events)
    # Same V51 private undo record is produced and can be restored via its UI API.
    applied = json.loads(response["content"])
    undo = http.post("/api/developer/studio/patch/undo", headers=AUTH, json={
        "project": str(root), "path": "calc.py", "token": applied["undo_id"], "confirmed": True,
    })
    assert undo.status_code == 200, undo.text
    assert (root / "calc.py").read_text() == OLD


def test_rejected_patch_does_not_write_even_with_auto_approval(workspace, monkeypatch):
    _, root = workspace
    monkeypatch.setenv("AUTOMOTO_APPROVAL", "auto")
    seen = []
    _, result, events = _run(root, approve=lambda call, decision: seen.append(call) or False)
    assert len(seen) == 1
    assert (root / "calc.py").read_text() == OLD
    assert "DENIED" in result["content"]
    assert any(e["type"] == "approval" and e["approved"] is False for e in events)


def test_disk_changes_during_approval_abort_without_clobber(workspace):
    _, root = workspace
    edited = "def calculate(a, b):\n    return 999\n"
    def change_during_review(call, decision):
        (root / "calc.py").write_text(edited, encoding="utf-8")
        return True
    _, result, events = _run(root, approve=change_during_review)
    assert "Source changed since preview" in result["content"]
    assert (root / "calc.py").read_text() == edited
    assert any(e["type"] == "tool_result" and not e["ok"] for e in events)


def test_invalid_python_patch_is_rejected_before_approval(workspace):
    _, root = workspace
    asked = []
    _, result, _ = _run(root, new="return (", approve=lambda *x: asked.append(x) or True)
    assert not asked
    assert "valid Python syntax" in result["content"]
    assert (root / "calc.py").read_text() == OLD


def test_protected_path_and_duplicate_snippet_are_rejected(workspace):
    _, root = workspace
    asked = []
    _, blocked, _ = _run(root, path=".env", approve=lambda *x: asked.append(x) or True)
    assert not asked
    assert "blocked" in blocked["content"].lower() or "protected" in blocked["content"].lower()
    (root / "calc.py").write_text(OLD + "# return a - b\n", encoding="utf-8")
    _, duplicate, _ = _run(root, approve=lambda *x: asked.append(x) or True)
    assert "exactly one" in duplicate["content"]
    assert not asked


def test_model_cannot_call_a_legacy_write_tool(workspace):
    _, root = workspace
    with sandbox.use_root(str(root)):
        agent = server._agent_factory(coding_budget=CodingBudget(), workspace=str(root))
        events = []
        result = agent._run_call(
            {"name": "write_file", "id": "legacy", "arguments": {
                "path": "calc.py", "content": "danger",
            }}, 1, lambda *_: pytest.fail("Legacy writes must never ask for approval"),
            events.append,
        )
        assert "unknown tool" in result["content"]
        assert (root / "calc.py").read_text() == OLD



def test_provider_tool_ids_cannot_reuse_a_previous_approval(workspace):
    _, root = workspace
    with sandbox.use_root(str(root)):
        agent = server._agent_factory(coding_budget=CodingBudget(), workspace=str(root))
        agent._touched = []
        # Both calls deliberately reuse the same provider-generated tool_call id.
        original_sha = hashlib.sha256(OLD.encode("utf-8")).hexdigest()
        def proposed():
            return {"id": "reused-id", "name": "developer_agent_patch", "arguments": {
                "path": "calc.py", "expected_sha256": original_sha,
                "old_fragment": "return a - b", "new_fragment": "return a + b",
            }}
        ids = []
        def decline(call, decision):
            ids.append(call["id"])
            return False
        first = agent._run_call(proposed(), 1, decline, lambda _: None)
        second = agent._run_call(proposed(), 2, decline, lambda _: None)
        assert ids[0] != ids[1]
        assert all(len(i) == 32 for i in ids)
        assert "DENIED" in first["content"] and "DENIED" in second["content"]
        assert (root / "calc.py").read_text() == OLD
