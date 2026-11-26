"""V55: bounded-agent test runs need one approval each, stop on time, and never overstate a pass."""
from __future__ import annotations

import json
import os
import shutil
import signal
import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient

from automoto import developer_agent_test as agent_test
from automoto import developer_run as run_mod
from automoto import sandbox, server
from automoto.developer_coding_budget import CodingBudget

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
PASSING = "def test_ok():\n    assert 1 + 1 == 2\n"
FAILING = "def test_ok():\n    assert True\n\n\ndef test_broken():\n    assert 1 == 2\n"

pytestmark = pytest.mark.skipif(
    __import__("importlib").util.find_spec("pytest") is None, reason="pytest not importable")


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    # The recipe runs "python3 -m pytest": make sure it is this interpreter, which has pytest.
    monkeypatch.setattr(run_mod, "_executable", lambda name, env: sys.executable
                        if name in ("python", "python3") else shutil.which(name, path=env.get("PATH", "")))
    root = sandbox.default_root() / "agent_v55"
    root.mkdir(parents=True)
    (root / "test_sample.py").write_text(PASSING)
    with TestClient(server.app) as client:
        t = client.post("/api/developer/studio/trust", headers=AUTH,
                        json={"project": str(root), "trusted": True, "confirmed": True})
        assert t.status_code == 200, t.text
        yield root, client
    run_mod.stop_all()
    with run_mod.LOCK:
        run_mod.RUNS.clear()


def _call(root, approver, *, arguments=None, budget=None, cancel=None):
    with sandbox.use_root(str(root)):
        agent = server._agent_factory(coding_budget=budget or CodingBudget(max_steps=4, max_operations=5,
                                                                          max_seconds=120),
                                      workspace=str(root))
        agent.coding_budget.start()
        agent._touched = []  # normally set by Agent._run; these tests drive one call directly
        agent._cancel = cancel
        events = []
        answer = agent._run_call({"id": "model-id", "name": "developer_agent_test",
                                  "arguments": arguments or {}}, 1, approver, events.append)
        return answer, events


def _evidence(answer) -> dict:
    return json.loads(answer["content"].split("\n", 1)[0])


def test_registry_offers_test_runs_but_no_shell(project):
    root, _ = project
    with sandbox.use_root(str(root)):
        bounded = server._agent_factory(coding_budget=CodingBudget(), workspace=str(root))
    tool = bounded.tools["developer_agent_test"]
    assert tool.level == "risky"
    assert set(tool.parameters["properties"]) == {"recipe"}  # no command text, ever
    for forbidden in ("run_shell", "run_command", "developer_run", "run_app", "write_file"):
        assert forbidden not in bounded.tools
    # Outside the bounded gateway the tool fails closed.
    with pytest.raises(Exception):
        tool.fn(None)


def test_approved_run_reports_a_real_pass(project, monkeypatch):
    root, _ = project
    monkeypatch.setenv("AUTOMOTO_APPROVAL", "auto")  # global auto-approval must not skip the card
    seen = []

    def approve(call, decision):
        assert decision.action == "ask"
        assert not run_mod.RUNS, "nothing runs before the approval"
        args = call["args"]
        assert args["prepared_by_server"] is True and args["test_run"] is True
        assert args["recipe"] == "python:pytest" and "pytest" in args["command"]
        assert args["os_sandbox"] is False and "not a sandbox" in args["isolation"]
        assert 10 <= args["time_limit_seconds"] <= agent_test.MAX_SECONDS
        seen.append(call["id"])
        return True

    answer, events = _call(root, approve)
    evidence = _evidence(answer)
    assert len(seen) == 1 and len(seen[0]) == 32  # server-unique approval id
    assert evidence["verdict"] == "passed" and evidence["passed"] is True
    assert evidence["counts"]["passed"] == 1 and evidence["counts"]["failed"] == 0
    assert evidence["exit_code"] == 0 and evidence["evidence"] == "observed_by_server"
    assert '<untrusted source="developer_agent_test output">' in answer["content"]
    # The run shows up in Review → Tests like a manual one.
    assert evidence["run_id"] in run_mod.RUNS


def test_failing_tests_are_failed_with_names(project):
    root, _ = project
    (root / "test_sample.py").write_text(FAILING)
    evidence = _evidence(_call(root, lambda c, d: True)[0])
    assert evidence["verdict"] == "failed" and evidence["passed"] is False
    assert evidence["counts"]["failed"] == 1 and evidence["counts"]["passed"] == 1
    assert any("test_broken" in name for name in evidence["failures"])


def test_denied_run_starts_nothing(project):
    root, _ = project
    answer, _ = _call(root, lambda c, d: False)
    assert "DENIED" in answer["content"]
    assert not run_mod.RUNS


def test_untrusted_project_and_missing_tests_are_refused_before_asking(project):
    root, client = project
    asked = []
    (root / "test_sample.py").unlink()
    answer, _ = _call(root, lambda c, d: asked.append(c) or True)
    assert "REFUSED" in answer["content"] and "not run" in answer["content"]
    client.post("/api/developer/studio/trust", headers=AUTH,
                json={"project": str(root), "trusted": False, "confirmed": True})
    (root / "test_sample.py").write_text(PASSING)
    answer, _ = _call(root, lambda c, d: asked.append(c) or True)
    assert "REFUSED" in answer["content"]
    assert not asked and not run_mod.RUNS


def test_unknown_recipe_is_refused(project):
    root, _ = project
    answer, _ = _call(root, lambda c, d: True, arguments={"recipe": "node:test"})
    assert "REFUSED" in answer["content"] and "python:pytest" in answer["content"]
    assert not run_mod.RUNS


def test_command_that_disappears_during_approval_does_not_run(project):
    root, _ = project

    def approve(call, decision):
        (root / "test_sample.py").unlink()  # the recipe is no longer detected
        return True

    answer, _ = _call(root, approve)
    assert "Tests were not run" in answer["content"]
    assert not run_mod.RUNS


def test_too_little_time_left_is_refused(project):
    root, _ = project
    budget = CodingBudget(max_steps=2, max_operations=2, max_seconds=30)
    budget.start()
    budget._started -= 20  # 10 s left, minus the 5 s reporting margin: below the minimum
    answer, _ = _call(root, lambda c, d: True, budget=budget)
    assert "REFUSED" in answer["content"] and "Not enough time" in answer["content"]


@pytest.mark.skipif(os.name == "nt", reason="process-group check uses POSIX signals")
def test_time_limit_kills_the_whole_process_group(project, monkeypatch):
    root, _ = project
    monkeypatch.setattr(agent_test, "MIN_SECONDS", 1)
    monkeypatch.setattr(agent_test, "MAX_SECONDS", 2)
    pidfile = root / "child.pid"
    (root / "test_sample.py").write_text(
        "import subprocess, sys, time\n"
        "def test_hangs():\n"
        "    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"    open({str(pidfile)!r}, 'w').write(str(child.pid))\n"
        "    time.sleep(120)\n")
    started = time.monotonic()
    evidence = _evidence(_call(root, lambda c, d: True)[0])
    assert time.monotonic() - started < 30
    assert evidence["verdict"] == "timed_out" and evidence["timed_out"] is True and not evidence["passed"]
    child = int(pidfile.read_text())
    for _ in range(50):  # the grandchild must be gone too, not only pytest
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(child, signal.SIGKILL)
        pytest.fail("a child process outlived the time limit")


def test_stop_cancels_a_running_test(project):
    root, _ = project
    (root / "test_sample.py").write_text("import time\ndef test_slow():\n    time.sleep(120)\n")
    cancel = threading.Event()
    threading.Timer(1.5, cancel.set).start()
    started = time.monotonic()
    evidence = _evidence(_call(root, lambda c, d: True, cancel=cancel)[0])
    assert time.monotonic() - started < 30
    assert evidence["verdict"] == "cancelled" and evidence["cancelled"] is True and not evidence["passed"]


def test_output_is_redacted(project):
    root, _ = project
    token = "ghp_" + "Mn8Bv7Cx6Za5Sd4Fg3Hj2Kl1Qw9Er8Ty7Ui6"
    (root / "test_sample.py").write_text(f"def test_leak():\n    print({token!r})\n    assert False\n")
    answer, events = _call(root, lambda c, d: True)
    assert token not in answer["content"]
    assert all(token not in json.dumps(e) for e in events)


@pytest.mark.parametrize("status,code,summary,expected", [
    ("passed", 0, {"recognised": True, "passed": 3, "failed": 0, "total": 3}, "passed"),
    ("passed", 0, {"recognised": False}, "passed_exit_code_only"),
    ("passed", 0, {"recognised": True, "passed": 0, "failed": 0, "total": 0}, "no_tests"),
    ("failed", 5, {"recognised": True, "passed": 0, "failed": 0, "total": 0}, "no_tests"),
    ("passed", 0, {"recognised": True, "passed": 2, "failed": 1, "total": 3}, "failed"),
    ("failed", 1, {"recognised": False}, "failed"),
    ("timed_out", None, {"recognised": True, "passed": 9}, "timed_out"),
    ("stopped", None, {"recognised": True, "passed": 9}, "cancelled"),
])
def test_verdict_never_overstates(status, code, summary, expected):
    assert agent_test.verdict(status, code, summary) == expected
