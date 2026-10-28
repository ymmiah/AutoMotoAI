"""Memory, skills, routines/scheduler, background tasks, MCP client and v5 API."""

import json
import sys
import textwrap
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from automoto import mcp, routines, skills, tasks
from automoto.memory import Memory


# -- memory ------------------------------------------------------------------------
def test_memory_remember_recall_forget():
    m = Memory()
    a = m.remember("Yasin's GitHub handle is ymmiah", "profile")
    assert m.remember("yasin's github handle is YMMIAH")["duplicate"]
    m.remember("GhostWires is an OSINT tool")
    assert [f["id"] for f in m.recall("github handle")] == [a["id"]]
    assert len(m.facts()) == 2
    assert m.forget(a["id"]) and not m.forget(a["id"])
    m.log("cli", "did a thing")
    block = m.prompt_block()
    assert "GhostWires" in block and "did a thing" in block and "ymmiah" not in block


def test_memory_persists_across_instances():
    Memory().remember("persist me")
    assert Memory().recall("persist")[0]["text"] == "persist me"


# -- skills ------------------------------------------------------------------------
def test_skills_discover_and_user_override(tmp_path):
    (tmp_path / "research-brief").mkdir()
    (tmp_path / "research-brief" / "SKILL.md").write_text("---\nname: research-brief\ndescription: mine\n---\nStep 1")
    (tmp_path / "plain").mkdir()
    (tmp_path / "plain" / "SKILL.md").write_text("# Plain skill\nDo it.")
    sk = skills.discover(tmp_path)
    assert sk["research-brief"].description == "mine" and not sk["research-brief"].bundled
    assert sk["plain"].description == "Plain skill" and "project-scaffold" in sk
    from automoto import tools
    ok, out = tools.call(tools.build()["load_skill"], tools.ToolContext(skills=sk), {"name": "research-brief"})
    assert ok and "Step 1" in out and "description" not in out


# -- routines ----------------------------------------------------------------------
def test_schedule_parsing():
    assert routines.parse_interval("every 30m") == 1800
    assert routines.parse_interval("every 2 hours") == 7200
    assert routines.parse_interval("0 8 * * *") is None
    with pytest.raises(routines.ScheduleError):
        routines.validate("every banana")
    with pytest.raises(routines.ScheduleError):
        routines.validate("61 * * * *")
    mon_8am = datetime(2026, 10, 26, 8, 0)  # a Monday
    assert routines.cron_matches("0 8 * * 1-5", mon_8am)
    assert not routines.cron_matches("0 8 * * 0,6", mon_8am)
    assert routines.cron_matches("*/15 * * * *", datetime(2026, 1, 1, 3, 45))
    assert routines.cron_matches("0 8 * * 7", datetime(2026, 10, 25, 8, 0))  # 7 = Sunday


def test_routine_due_logic():
    r = routines.Routine("r", "every 1h", "p")
    now = time.time()
    assert r.is_due(now)
    r.last_run = now - 100
    assert not r.is_due(now)
    r.last_run = now - 3700
    assert r.is_due(now)
    c = routines.Routine("c", "* * * * *", "p")
    assert c.is_due(now)
    c.last_run = now
    assert not c.is_due(now)


def test_store_and_scheduler_runs_due_routines(tmp_path):
    store = routines.RoutineStore(tmp_path / "r.json")
    store.add("news digest", "every 1h", "summarise news")
    assert list(store.load()) == ["news-digest"]
    ran = []
    sch = routines.Scheduler(lambda p: ran.append(p) or {"text": "ok", "stopped": "done"}, store)
    assert sch.run_due() == ["news-digest"]
    for _ in range(100):
        if store.load()["news-digest"].last_status == "done":
            break
        time.sleep(0.02)
    assert ran == ["summarise news"] and store.load()["news-digest"].last_result == "ok"
    assert sch.run_due() == []  # not due again for an hour
    assert store.remove("news-digest") and not store.load()


# -- background tasks --------------------------------------------------------------
class FakeAgent:
    def __init__(self, **_):
        pass

    def run(self, messages, *, approver, on_event, cancel=None, **_):
        from automoto import policy
        from automoto.loop import AgentResult
        on_event({"type": "tool_call", "name": "run_shell"})
        ok = approver({"id": "c1", "name": "run_shell", "args": {"command": "ls"}},
                      policy.Decision("ask", "risky", "shell"))
        on_event({"type": "final", "text": f"approved={ok}"})
        return AgentResult(f"approved={ok}", 1)


def test_task_waits_for_approval_then_finishes():
    tm = tasks.TaskManager(FakeAgent)
    t = tm.start([{"role": "user", "content": "go"}], keys={"nim": "secret-key"})
    for _ in range(200):
        if t.status == "waiting_approval":
            break
        time.sleep(0.01)
    assert t.status == "waiting_approval" and t.pending["name"] == "run_shell"
    assert not tm.approve(t.id, "wrong-id", True)
    assert tm.approve(t.id, "c1", True)
    tm.wait(t.id, 5)
    assert t.status == "done" and t.result["text"] == "approved=True"
    assert "secret-key" not in json.dumps(t.summary()) + json.dumps(t.events)


def test_auto_deny_tasks_for_routines():
    tm = tasks.TaskManager(FakeAgent)
    t = tm.start([{"role": "user", "content": "go"}], auto_deny=True)
    tm.wait(t.id, 5)
    assert t.result["text"] == "approved=False"


def test_cancel_unblocks_waiting_task():
    tm = tasks.TaskManager(FakeAgent)
    t = tm.start([{"role": "user", "content": "go"}])
    for _ in range(200):
        if t.status == "waiting_approval":
            break
        time.sleep(0.01)
    tm.cancel(t.id)
    tm.wait(t.id, 5)
    assert t.result["text"] == "approved=False"


# -- MCP ---------------------------------------------------------------------------
FAKE_MCP = textwrap.dedent('''
    import json, sys
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg:
            continue
        m = msg["method"]
        if m == "initialize":
            res = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake"}}
        elif m == "tools/list":
            res = {"tools": [{"name": "add", "description": "add numbers",
                              "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                                              "required": ["a", "b"]}}]}
        elif m == "tools/call":
            a = msg["params"]["arguments"]
            res = {"content": [{"type": "text", "text": str(a["a"] + a["b"])}]}
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": res}), flush=True)
''')


def test_mcp_stdio_client(tmp_path):
    script = tmp_path / "fake_mcp.py"
    script.write_text(FAKE_MCP)
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"servers": {"calc": {"command": sys.executable, "args": [str(script)]}}}))
    try:
        tl, errors = mcp.connect_all(cfg)
        assert not errors and [t.name for t in tl] == ["mcp__calc__add"] and tl[0].level == "risky"
        from automoto import tools
        ok, out = tools.call(tl[0], tools.ToolContext(), {"a": 2, "b": 3})
        assert ok and out == "5"
    finally:
        mcp.close_all()


def test_mcp_bad_server_reports_error(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"servers": {"nope": {"command": "definitely-not-a-real-binary-xyz"}}}))
    tl, errors = mcp.connect_all(cfg)
    assert tl == [] and errors and errors[0].startswith("nope:")


# -- v5 API ------------------------------------------------------------------------
def test_agent_api_task_flow(monkeypatch):
    from automoto import server
    monkeypatch.setattr(server, "TASKS", tasks.TaskManager(FakeAgent))
    c = TestClient(server.app)
    H = {"X-AutoMoto-Token": server.SESSION_TOKEN}
    assert c.post("/api/agent", json={"messages": [{"role": "user", "content": "x"}]}).status_code == 403
    tid = c.post("/api/agent", headers=H, json={"messages": [{"role": "user", "content": "x"}],
                                                "keys": {"nim": "byok-secret"}}).json()["task_id"]
    for _ in range(200):
        st = c.get(f"/api/tasks/{tid}", headers=H).json()
        if st["status"] == "waiting_approval":
            break
        time.sleep(0.01)
    assert st["pending"]["id"] == "c1"
    assert c.post(f"/api/tasks/{tid}/approve", headers=H, json={"call_id": "c1", "approve": False}).json()["ok"]
    server.TASKS.wait(tid, 5)
    st = c.get(f"/api/tasks/{tid}?since=0", headers=H).json()
    assert st["status"] == "done" and st["result"]["text"] == "approved=False" and st["next"] == len(st["events"])
    assert "byok-secret" not in json.dumps(c.get("/api/tasks", headers=H).json())


def test_memory_routines_info_api():
    from automoto import server
    c = TestClient(server.app)
    H = {"X-AutoMoto-Token": server.SESSION_TOKEN}
    fid = c.post("/api/memory", headers=H, json={"text": "likes dark mode"}).json()["id"]
    assert c.get("/api/memory", headers=H).json()["facts"][0]["text"] == "likes dark mode"
    assert c.delete(f"/api/memory/{fid}", headers=H).json()["ok"]
    assert c.post("/api/routines", headers=H, json={"name": "x", "schedule": "nope", "prompt": "p"}).status_code == 400
    assert c.post("/api/routines", headers=H, json={"name": "x", "schedule": "every 1d", "prompt": "p"}).status_code == 200
    assert c.get("/api/routines", headers=H).json()["routines"][0]["name"] == "x"
    assert c.delete("/api/routines/x", headers=H).json()["ok"]
    info = c.get("/api/agent/info", headers=H).json()
    names = {t["name"]: t["level"] for t in info["tools"]}
    assert names["run_shell"] == "risky" and names["read_file"] == "safe"
    assert any(s["name"] == "research-brief" for s in info["skills"])
