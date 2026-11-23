"""V52 API acceptance: current plan, trusted local root and server-enforced bounds."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from automoto import sandbox, server

BASE = "/api/developer/studio"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v52"
    root.mkdir(parents=True)
    (root / "login.py").write_text("def verify_login(user):\n    return bool(user)\n", encoding="utf-8")
    http = TestClient(server.app)
    trust = http.post(BASE + "/trust", headers=AUTH,
                      json={"project": str(root), "trusted": True, "confirmed": True})
    assert trust.status_code == 200, trust.text
    plan_response = http.post(BASE + "/task-plan", headers=AUTH,
                              json={"project": str(root), "request": "Add a login page"})
    assert plan_response.status_code == 200, plan_response.text
    yield http, root, plan_response.json()


def request_payload(root, plan):
    return {
        "workspace": str(root), "client": "web",
        "message": plan["request"],
        "messages": [{"role": "user", "content": plan["request"]}],
        "coding": {
            "plan_id": plan["plan_id"], "request": plan["request"],
            "max_steps": 8, "max_operations": 20, "max_seconds": 300,
        },
        "max_steps": 50,
    }


def test_bounded_agent_rejects_stale_or_mismatched_plan(fixture):
    http, root, plan = fixture
    payload = request_payload(root, plan)
    changed = http.post("/api/agent", headers=AUTH, json={
        **payload, "coding": {**payload["coding"], "plan_id": "0" * 64},
    })
    assert changed.status_code == 409
    mismatched = http.post("/api/agent", headers=AUTH, json={
        **payload, "message": "Run an unrelated command",
    })
    assert mismatched.status_code == 422
    (root / "login.py").write_text("def verify_login(user):\n    return False\n", encoding="utf-8")
    stale = http.post("/api/agent", headers=AUTH, json=payload)
    assert stale.status_code == 409


def test_only_explicit_local_trusted_project_can_start(fixture, tmp_path):
    http, root, plan = fixture
    payload = request_payload(root, plan)
    assert http.post("/api/agent", json=payload).status_code == 403
    assert http.post("/api/agent", headers={**AUTH, "Origin": "https://evil.invalid"},
                     json=payload).status_code == 403
    assert http.post("/api/agent", headers=AUTH, json={
        **payload, "client": "mobile",
    }).status_code == 403
    assert http.post("/api/agent", headers=AUTH, json={
        **payload, "workspace": str(tmp_path),
    }).status_code in (400, 403, 422)
    http.post(BASE + "/trust", headers=AUTH,
              json={"project": str(root), "trusted": False, "confirmed": True})
    untrusted = http.post("/api/agent", headers=AUTH, json=payload)
    assert untrusted.status_code == 403


def test_server_passes_only_bounded_values_to_task_manager(fixture, monkeypatch):
    http, root, plan = fixture
    captured = []
    def stub(messages, **kwargs):
        captured.append(kwargs)
        return SimpleNamespace(id="fake123", status="queued")
    monkeypatch.setattr(server.TASKS, "start", stub)
    response = http.post("/api/agent", headers=AUTH, json=request_payload(root, plan))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["task_id"] == "fake123"
    assert data["coding_budget"]["max_steps"] == 8
    assert data["coding_budget"]["max_operations"] == 20
    assert captured[0]["max_steps"] == 8  # never the client's generic max_steps=50
    assert captured[0]["coding_budget"] is captured[0]["agent_kwargs"]["coding_budget"]
    assert captured[0]["coding_budget"].max_seconds == 300


def test_excessive_limits_are_rejected_before_task_creation(fixture):
    http, root, plan = fixture
    payload = request_payload(root, plan)
    for invalid in (
        {"max_steps": 99}, {"max_operations": 999},
        {"max_seconds": 3600}, {"max_seconds": 1},
    ):
        response = http.post("/api/agent", headers=AUTH, json={
            **payload, "coding": {**payload["coding"], **invalid},
        })
        assert response.status_code == 422


def test_legacy_general_agent_has_no_coding_plan_requirement():
    body = server.AgentIn(messages=[{"role": "user", "content": "Hello"}])
    assert body.coding is None
