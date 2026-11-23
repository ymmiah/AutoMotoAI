"""V52 unit tests: no hidden execution, finite tool/model budgets, honest stopping."""
from __future__ import annotations

import time

import pytest

from automoto import policy, sandbox
from automoto.developer_coding_budget import CodingBudget
from automoto.loop import Agent
from automoto.memory import Memory


def _call(name, **arguments):
    return {"id": "call_" + name, "name": name, "arguments": arguments}


def _transport(*answers):
    answers = list(answers)
    def fn(*_args, **_kwargs):
        return answers.pop(0)
    return fn


def _agent(*answers, budget):
    return Agent(memory=Memory(), skills={}, transport=_transport(*answers),
                 coding_budget=budget)


@pytest.fixture(autouse=True)
def provider(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "v52-mocked-key")
    monkeypatch.setenv("AI_PROVIDER", "auto")
    monkeypatch.setattr(policy, "mode", lambda: "auto")


def test_bounded_configuration_validation_and_progress():
    with pytest.raises(ValueError):
        CodingBudget(max_steps=13)
    with pytest.raises(ValueError):
        CodingBudget(max_operations=31)
    with pytest.raises(ValueError):
        CodingBudget(max_seconds=601)
    budget = CodingBudget(max_steps=4, max_operations=2, max_seconds=30)
    budget.start()
    assert budget.snapshot()["operations_used"] == 0
    assert budget.consume_operation() is None
    assert budget.consume_operation() is None
    assert budget.consume_operation() == "operations"
    assert budget.snapshot()["limit_reason"] == "operations"


def test_global_auto_setting_cannot_approve_a_write(tmp_path):
    target = sandbox.root() / "scratch" / "v52_no_auto.txt"
    target.unlink(missing_ok=True)
    budget = CodingBudget(max_steps=3, max_operations=3, max_seconds=90)
    asked = []
    a = _agent(("", [_call("write_file", path="scratch/v52_no_auto.txt", content="unsafe")]),
               ("Denied.", []), budget=budget)
    result = a.run("Make a file", approver=lambda call, decision: asked.append((call, decision)) or False)
    assert result.stopped == "done"
    assert not target.exists()
    assert len(asked) == 1
    assert asked[0][1].action == policy.ASK
    assert any(e.get("type") == "approval" and not e["approved"] for e in result.events)


def test_model_step_budget_stops_without_unapproved_final_model_call(monkeypatch):
    budget = CodingBudget(max_steps=2, max_operations=5, max_seconds=90)
    a = _agent(("", [_call("list_dir", path=".")]),
               ("", [_call("list_dir", path=".")]), budget=budget)
    result = a.run("Inspect project", max_steps=50)
    assert result.stopped == "limited"
    assert result.steps == 2
    assert any(e["type"] == "coding_limit" and e["reason"] == "steps" for e in result.events)
    assert budget.snapshot()["operations_used"] == 2


def test_operation_cap_prevents_later_tool_calls(tmp_path):
    target = sandbox.root() / "scratch" / "v52_op_block.txt"
    target.unlink(missing_ok=True)
    budget = CodingBudget(max_steps=4, max_operations=1, max_seconds=90)
    a = _agent(("", [_call("list_dir", path="."),
                       _call("write_file", path="scratch/v52_op_block.txt", content="x")]),
               budget=budget)
    result = a.run("Inspect then change", approver=lambda *_: True)
    assert result.stopped == "limited"
    assert not target.exists()
    assert budget.snapshot()["operations_used"] == 1
    assert any(e["type"] == "coding_limit" and e["reason"] == "operations" for e in result.events)


def test_expired_budget_invalidates_late_approval():
    budget = CodingBudget(max_steps=3, max_operations=3, max_seconds=30)
    target = sandbox.root() / "scratch" / "v52_expired.txt"
    target.unlink(missing_ok=True)
    def expire(*_):
        budget._started = time.monotonic() - 1000
        return True
    a = _agent(("", [_call("write_file", path="scratch/v52_expired.txt", content="bad")]),
               ("Done.", []), budget=budget)
    result = a.run("Edit", approver=expire)
    assert not target.exists()
    assert result.stopped == "limited"
    assert budget.snapshot()["limit_reason"] == "time"
