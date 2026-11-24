"""V42 debugger and profiling host: DAP sessions, crash recovery, watch limits, profiling, crash explainer."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from automoto import developer_debug as debug
from automoto import sandbox, server

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
URL = "/api/developer/studio/debug"
REAL_PY = os.environ.get("AUTOMOTO_V42_REAL_TOOL_TESTS") == "1"
REAL_GDB = os.environ.get("AUTOMOTO_V42_REAL_GDB") == "1"
FAKE = Path(__file__).parent / "fixtures" / "v42_fake_dap.py"
PROG = '''def add(a, b):
    total = a + b
    return total


values = [1, 2]
print("V42_RESULT", add(*values))
'''


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    root = sandbox.default_root() / "v42-debug"
    root.mkdir(parents=True)
    (root / "prog.py").write_text(PROG)
    (root / "test_prog.py").write_text("def test_x():\n    pass\n")
    (root / "notes.txt").write_text("hello")
    client = TestClient(server.app)
    yield client, root
    debug.shutdown()


def trust(client, root):
    result = client.post("/api/developer/studio/trust", headers=AUTH,
                         json={"project": str(root), "trusted": True, "confirmed": True})
    assert result.status_code == 200, result.text


def detect(client, root):
    response = client.get(URL + "/detect", params={"project": str(root)}, headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()


def wait_for(client, sid, predicate, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(URL + "/state", params={"session_id": sid}, headers=AUTH).json()
        if predicate(data):
            return data
        time.sleep(0.2)
    raise AssertionError(f"timed out; last state {data}")


@pytest.fixture
def fake_adapter(monkeypatch):
    monkeypatch.setitem(debug.DEBUGGERS, "fakedap", {
        "kind": "python", "label": "Fake adapter", "names": (), "args": [str(FAKE.resolve())],
        "install": {"windows": "n/a", "macos": "n/a", "linux": "n/a"}, "ci_verified_hosts": []})
    real = debug._locate
    monkeypatch.setattr(debug, "_locate", lambda spec: sys.executable if spec["label"] == "Fake adapter" else real(spec))


def start_body(root, data, debugger, target="prog.py", breakpoints=None):
    tool = next(d for d in data["debuggers"] if d["name"] == debugger)
    item = next(t for t in data["targets"] if t["path"] == target)
    return {"project": str(root), "debugger": debugger, "target": target,
            "expected_target_sha256": item["sha256"], "expected_executable": tool["executable"],
            "expected_sha256": tool["sha256"], "breakpoints": breakpoints or [],
            "confirmed": True, "accept_unsandboxed_execution": True}


def test_detect_lists_targets_and_never_starts(project):
    client, root = project
    data = detect(client, root)
    paths = [t["path"] for t in data["targets"]]
    assert "prog.py" in paths and "test_prog.py" not in paths and "notes.txt" not in paths
    assert data["program_started"] is False
    assert {d["name"] for d in data["debuggers"]} >= {"debugpy", "gdb", "lldb-dap"}
    assert ".NET (netcoredbg)" in data["not_supported_yet"]


def test_missing_debuggers_reported_with_install_hints(project, monkeypatch):
    client, root = project
    monkeypatch.setattr(debug.shutil, "which", lambda name: None)
    monkeypatch.setattr(debug, "LLDB_CANDIDATES", ())
    for item in detect(client, root)["debuggers"]:
        assert item["status"] == "unavailable" and item["install_hint"]


def test_start_requires_trust_pins_and_valid_target(project, fake_adapter):
    client, root = project
    data = detect(client, root)
    body = start_body(root, data, "fakedap")
    assert client.post(URL + "/start", json=body, headers=AUTH).status_code == 403
    trust(client, root)
    assert client.post(URL + "/start", json={**body, "expected_sha256": "0" * 64}, headers=AUTH).status_code == 409
    assert client.post(URL + "/start", json={**body, "expected_target_sha256": "0" * 64}, headers=AUTH).status_code == 409
    assert client.post(URL + "/start", json={**body, "target": "notes.txt"}, headers=AUTH).status_code == 422
    assert client.post(URL + "/start", json={**body, "debugger": "kubectl"}, headers=AUTH).status_code == 422
    assert client.post(URL + "/start", json={**body, "target": "../outside.py"}, headers=AUTH).status_code in (403, 422)
    body.pop("accept_unsandboxed_execution")
    assert client.post(URL + "/start", json=body, headers=AUTH).status_code == 422


def test_fake_session_stack_variables_watch_crash_and_restart(project, fake_adapter):
    client, root = project
    trust(client, root)
    data = detect(client, root)
    body = start_body(root, data, "fakedap", breakpoints=[{"path": "prog.py", "line": 3}])
    started = client.post(URL + "/start", json=body, headers=AUTH)
    assert started.status_code == 200, started.text
    sid = started.json()["session_id"]
    state = wait_for(client, sid, lambda d: d["status"] == "stopped" and d["frames"] and not d["stop"]["inspecting"])
    assert state["frames"][0]["name"] == "add" and state["frames"][0]["line"] == 3
    assert state["breakpoints"]["prog.py"][0]["verified"] is True
    values = {v["name"]: v for v in state["variables"]}
    assert values["total"]["value"] == "3"
    assert len(values["secret_blob"]["value"]) <= debug.MAX_VALUE + 1
    watched = client.post(URL + "/watch", json={"session_id": sid, "expressions": ["a", "user.name", "items[0]"]},
                          headers=AUTH).json()
    assert watched["watches"][0]["value"] == "1"
    for bad in ("__import__('os').system('x')", "a + b", "f()", "a; b", "a=1"):
        assert client.post(URL + "/watch", json={"session_id": sid, "expressions": [bad]}, headers=AUTH).status_code == 422
    # The fake adapter crashes on continue: the session must say so and offer Restart.
    client.post(URL + "/control", json={"session_id": sid, "action": "continue"}, headers=AUTH)
    crashed = wait_for(client, sid, lambda d: d["status"] == "adapter_crashed")
    assert crashed["restart_available"] is True and crashed["debugger_running"] is False
    assert "Restart" in crashed["error"]
    again = client.post(URL + "/restart", json={"session_id": sid, "confirmed": True}, headers=AUTH)
    assert again.status_code == 200, again.text
    new = again.json()
    assert new["restarts"] == 1 and new["breakpoints"]["prog.py"][0]["line"] == 3
    restarted = wait_for(client, new["session_id"], lambda d: d["status"] == "stopped" and d["frames"])
    assert restarted["watches"][0]["expression"] == "a"
    stopped = client.post(URL + "/stop", json={"session_id": new["session_id"]}, headers=AUTH).json()
    assert stopped["status"] == "stopped_by_user" and stopped["debugger_running"] is False


def test_restart_refuses_changed_program(project, fake_adapter):
    client, root = project
    trust(client, root)
    data = detect(client, root)
    sid = client.post(URL + "/start", json=start_body(root, data, "fakedap"), headers=AUTH).json()["session_id"]
    wait_for(client, sid, lambda d: d["status"] == "stopped")
    client.post(URL + "/stop", json={"session_id": sid}, headers=AUTH)
    (root / "prog.py").write_text(PROG + "\nprint('changed')\n")
    assert client.post(URL + "/restart", json={"session_id": sid, "confirmed": True}, headers=AUTH).status_code == 409


def test_unknown_session(project):
    client, _ = project
    assert client.get(URL + "/state", params={"session_id": "x" * 24}, headers=AUTH).status_code == 404


@pytest.mark.parametrize("text,exit_code,expect", [
    ('Traceback (most recent call last):\n  File "{root}/prog.py", line 2, in <module>\n    1/0\nZeroDivisionError: division by zero\n',
     1, ("ZeroDivisionError: division by zero", "prog.py", 2)),
    ("thread 'main' panicked at src/main.rs:3:5:\nindex out of bounds\n", 101, ("panicked", "main.rs", 3)),
    ("panic: runtime error: invalid memory address\n\ngoroutine 1 [running]:\nmain.main()\n\t/app/main.go:12 +0x1d\n", 2,
     ("panic: runtime error", "main.go", 12)),
    ("Segmentation fault (core dumped)\n", -11, ("SIGSEGV", None, None)),
    ("", 3221225477, ("access violation", None, None)),
])
def test_crash_explainer(project, text, exit_code, expect):
    client, root = project
    body = {"project": str(root), "text": (text.replace("{root}", str(root)) or " "), "exit_code": exit_code}
    data = client.post(URL + "/crash", json=body, headers=AUTH).json()
    needle, path, line = expect
    assert needle in data["summary"] + str(data["signal"]) + str(data["error"])
    if path:
        assert data["frames"] and data["frames"][0]["path"].endswith(path) and data["frames"][0]["line"] == line
    assert data["program_started"] is False and data["text_stored"] is False


def test_crash_explainer_marks_project_frames(project):
    client, root = project
    text = f'Traceback (most recent call last):\n  File "{root / "prog.py"}", line 7, in <module>\n  File "/usr/lib/python3/x.py", line 9, in f\nValueError: bad\n'
    data = client.post(URL + "/crash", json={"project": str(root), "text": text}, headers=AUTH).json()
    assert data["first_project_frame"]["path"] == "prog.py" and data["first_project_frame"]["in_project"] is True
    assert any("stop point" in tip for tip in data["tips"])


def test_profile_finds_slow_function(project):
    client, root = project
    (root / "slow.py").write_text("def slow():\n    return sum(i * i for i in range(300000))\n\nfor _ in range(3):\n    slow()\nprint('done')\n")
    data = detect(client, root)
    tool = next(d for d in data["debuggers"] if d["name"] == "debugpy")
    if tool["status"] != "installed_not_executed":
        pytest.skip("python not on PATH")
    target = next(t for t in data["targets"] if t["path"] == "slow.py")
    body = {"project": str(root), "target": "slow.py", "expected_target_sha256": target["sha256"],
            "expected_executable": tool["executable"], "expected_sha256": tool["sha256"],
            "confirmed": True, "accept_unsandboxed_execution": True}
    assert client.post(URL + "/profile", json=body, headers=AUTH).status_code == 403
    trust(client, root)
    result = client.post(URL + "/profile", json=body, headers=AUTH)
    assert result.status_code == 200, result.text
    out = result.json()
    assert out["status"] == "completed" and "done" in out["program_output"]
    assert any(r["function"] == "slow" and r["path"] == "slow.py" for r in out["slowest_in_project"])


def test_requires_session_token(project):
    client, root = project
    assert client.get(URL + "/detect", params={"project": str(root)}).status_code in (401, 403)


@pytest.mark.skipif(not REAL_PY, reason="real debugpy session runs in the V42 CI job")
def test_real_debugpy_breakpoint_step_variables_exit(project):
    client, root = project
    trust(client, root)
    data = detect(client, root)
    body = start_body(root, data, "debugpy", breakpoints=[{"path": "prog.py", "line": 3}])
    started = client.post(URL + "/start", json=body, headers=AUTH)
    assert started.status_code == 200, started.text
    sid = started.json()["session_id"]
    assert started.json()["status"] in ("running", "stopped"), started.json()
    state = wait_for(client, sid, lambda d: d["status"] == "stopped" and d["frames"] and not d["stop"]["inspecting"])
    assert state["frames"][0]["name"] == "add" and state["frames"][0]["line"] == 3
    assert state["frames"][0]["path"] == "prog.py"
    assert {v["name"]: v["value"] for v in state["variables"]}["total"] == "3"
    watched = client.post(URL + "/watch", json={"session_id": sid, "expressions": ["a", "b"]}, headers=AUTH).json()
    assert [w["value"] for w in watched["watches"]] == ["1", "2"]
    client.post(URL + "/control", json={"session_id": sid, "action": "continue"}, headers=AUTH)
    done = wait_for(client, sid, lambda d: d["status"] == "exited")
    assert "V42_RESULT 3" in done["output"]
    assert done["exit_code"] == 0


@pytest.mark.skipif(not REAL_PY, reason="real debugpy session runs in the V42 CI job")
def test_real_debugpy_uncaught_exception_and_adapter_crash_recovery(project):
    client, root = project
    (root / "boom.py").write_text("import time\n\ndef divide(n):\n    return 10 / n\n\nprint(divide(0))\n")
    trust(client, root)
    data = detect(client, root)
    sid = client.post(URL + "/start", json=start_body(root, data, "debugpy", "boom.py"), headers=AUTH).json()["session_id"]
    state = wait_for(client, sid, lambda d: d["status"] == "stopped" and d["frames"] and not d["stop"]["inspecting"])
    assert state["stop"]["reason"] == "exception"
    assert state["frames"][0]["line"] == 4
    session = debug.SESSIONS[sid]
    pids = set(session.debuggee_pids)
    session.proc.kill()  # the debugger itself crashes
    crashed = wait_for(client, sid, lambda d: d["status"] == "adapter_crashed")
    assert crashed["restart_available"] is True
    if os.name != "nt":
        time.sleep(1)
        for pid in pids:
            with pytest.raises(OSError):
                os.kill(pid, 0)
    again = client.post(URL + "/restart", json={"session_id": sid, "confirmed": True}, headers=AUTH).json()
    wait_for(client, again["session_id"], lambda d: d["status"] == "stopped")
    client.post(URL + "/stop", json={"session_id": again["session_id"]}, headers=AUTH)


@pytest.mark.skipif(not REAL_GDB, reason="real GDB DAP session runs on the Linux V42 CI job")
def test_real_gdb_native_breakpoint(project):
    client, root = project
    (root / "fixture.c").write_text('#include <stdio.h>\n\nint add(int a, int b) {\n    int total = a + b;\n    return total;\n}\n\nint main(void) {\n    printf("V42_RESULT %d\\n", add(1, 2));\n    return 0;\n}\n')
    subprocess.run(["gcc", "-g", "-O0", "-o", "fixture", "fixture.c"], cwd=root, check=True)
    trust(client, root)
    data = detect(client, root)
    assert any(t["path"] == "fixture" and t["kind"] == "native" for t in data["targets"])
    body = start_body(root, data, "gdb", "fixture", [{"path": "fixture.c", "line": 5}])
    started = client.post(URL + "/start", json=body, headers=AUTH)
    assert started.status_code == 200, started.text
    sid = started.json()["session_id"]
    state = wait_for(client, sid, lambda d: d["status"] == "stopped" and d["frames"] and not d["stop"]["inspecting"])
    assert state["frames"][0]["name"].startswith("add") and state["frames"][0]["line"] == 5
    assert {v["name"]: v["value"] for v in state["variables"]}.get("total") == "3"
    client.post(URL + "/control", json={"session_id": sid, "action": "continue"}, headers=AUTH)
    done = wait_for(client, sid, lambda d: d["status"] == "exited")
    assert done["exit_code"] in (0, None)
