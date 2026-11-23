"""V54: agent-side no-clobber new file creation must be individually approved."""
from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from automoto import developer_safe_create as create
from automoto import sandbox, server
from automoto.developer_coding_budget import CodingBudget

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
CONTENT = "def say_hello():\n    return 'hello'\n"


@pytest.fixture
def root_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "agent_v54"
    root.mkdir(parents=True)
    (root / "src").mkdir()
    with create.LOCK:
        create.PREVIEWS.clear()
    with TestClient(server.app) as client:
        t = client.post("/api/developer/studio/trust", headers=AUTH,
                        json={"project": str(root), "trusted": True, "confirmed": True})
        assert t.status_code == 200, t.text
        yield root, client
    with create.LOCK:
        create.PREVIEWS.clear()


def _run(root, approver, *, path="src/hello.py", text=CONTENT):
    with sandbox.use_root(str(root)):
        agent = server._agent_factory(
            coding_budget=CodingBudget(max_steps=4, max_operations=5, max_seconds=90),
            workspace=str(root),
        )
        agent._touched = []  # normally set by Agent._run; this test drives one call directly
        events = []
        answer = agent._run_call(
            {"id": "model-provided-id", "name": "developer_agent_create",
             "arguments": {"path": path, "text": text}},
            1, approver, events.append,
        )
        return answer, events


def test_registry_restricts_writes_to_existing_patch_and_new_create(root_env):
    root, _ = root_env
    with sandbox.use_root(str(root)):
        bounded = server._agent_factory(coding_budget=CodingBudget(), workspace=str(root))
        assert "developer_agent_create" in bounded.tools
        assert bounded.tools["developer_agent_create"].level == "risky"
        for forbidden in ("write_file", "edit_file", "developer_save", "run_shell",
                          "developer_run", "run_app", "more_tools", "open_url",
                          "routine", "developer_trust"):
            assert forbidden not in bounded.tools
        assert all(t.level == "safe" or t.name in
                   ("developer_agent_patch", "developer_agent_create")
                   for t in bounded.tools.values())


def test_reviewed_creation_then_undo(root_env, monkeypatch):
    root, client = root_env
    monkeypatch.setenv("AUTOMOTO_APPROVAL", "auto")
    approved = []
    new_file = root / "src" / "hello.py"

    def confirm(call, decision):
        assert decision.action == "ask"
        assert not new_file.exists(), "Create never writes before a confirmed review"
        args = call["args"]
        assert args["prepared_by_server"] is True and args["creation"] is True
        assert args["path"] == "src/hello.py"
        assert args["file_exists"] is False
        assert args["preview_diff"].startswith("--- /dev/null")
        assert "+def say_hello():" in args["preview_diff"]
        assert args["after_sha256"] == hashlib.sha256(CONTENT.encode()).hexdigest()
        assert "token" not in args and "text" not in args
        approved.append(call["id"])
        return True

    answer, events = _run(root, confirm)
    applied = json.loads(answer["content"])
    assert applied["created"] is True and applied["executed"] is False
    assert new_file.read_text() == CONTENT
    assert len(approved) == 1 and len(approved[0]) == 32
    assert any(e.get("type") == "approval" and e.get("approved") for e in events)
    undo = client.post("/api/developer/studio/create/undo", headers=AUTH, json={
        "project": str(root), "path": "src/hello.py",
        "token": applied["undo_id"], "confirmed": True,
    })
    assert undo.status_code == 200, undo.text
    assert not new_file.exists()


def test_denied_creation_and_forged_autoapproval_do_not_create(root_env, monkeypatch):
    root, _ = root_env
    monkeypatch.setenv("AUTOMOTO_APPROVAL", "auto")
    seen = []
    result, _ = _run(root, lambda call, decision: seen.append(call) or False)
    assert seen and "DENIED" in result["content"]
    assert not (root / "src" / "hello.py").exists()


def test_existing_file_created_during_approval_is_not_replaced(root_env):
    root, _ = root_env
    target = root / "src" / "hello.py"
    def race(call, decision):
        target.write_text("my original work\n")
        return True
    response, events = _run(root, race)
    assert "already exists" in response["content"].lower()
    assert target.read_text() == "my original work\n"
    assert any(e["type"] == "tool_result" and not e.get("ok") for e in events)


def test_invalid_code_and_hidden_file_fail_before_approval(root_env):
    root, _ = root_env
    requests = []
    a, _ = _run(root, lambda *args: requests.append(args) or True, text="def bad(:\n")
    b, _ = _run(root, lambda *args: requests.append(args) or True, path=".env")
    c, _ = _run(root, lambda *args: requests.append(args) or True, path="unknown/module.py")
    assert "invalid Python syntax" in a["content"]
    assert "restricted" in b["content"].lower()
    assert "folder must already exist" in c["content"].lower()
    assert not requests


def test_legacy_direct_write_stays_unknown(root_env):
    root, _ = root_env
    with sandbox.use_root(str(root)):
        agent = server._agent_factory(coding_budget=CodingBudget(), workspace=str(root))
        result = agent._run_call(
            {"name": "write_file", "id": "wrong-tool",
             "arguments": {"path": "src/hello.py", "content": "unsafe"}},
            1, lambda *_: pytest.fail("No approval prompt for a removed tool"),
            lambda _: None,
        )
        assert "unknown tool" in result["content"]
        assert not (root / "src" / "hello.py").exists()
