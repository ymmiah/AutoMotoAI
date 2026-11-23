"""Developer Studio V50: task previews never modify, execute or share projects."""
from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from automoto import sandbox, server
from automoto.hosted import path_allowed

BASE = "/api/developer/studio/task-plan"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "sample"
    root.mkdir(parents=True)
    (root / "login.py").write_text(
        "def verify_login(username):\n"
        "    return bool(username)\n", encoding="utf-8")
    (root / "test_login.py").write_text(
        "def test_verify_login():\n"
        "    assert True\n", encoding="utf-8")
    (root / ".env").write_text("password=NEVER_SEND", encoding="utf-8")
    return TestClient(server.app), root


def _preview(client, root, request):
    return client.post(BASE, headers=AUTH, json={"project": str(root), "request": request})


def test_login_plan_has_safe_steps_and_real_source_hints(fixture):
    client, root = fixture
    response = _preview(client, root, "Add a login page for existing users")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["category"] == "authentication"
    assert data["read_only"] and not data["execution_started"] and not data["source_modified"]
    assert data["approval_required"] and not data["plan_id"].startswith("0" * 64)
    assert 4 <= len(data["steps"]) <= 6
    assert [step["id"] for step in data["steps"]][-2:] == ["tests", "review"]
    assert all(step["status"] == "proposed" for step in data["steps"])
    assert data["source_verified"]
    assert any(item["path"] == "login.py" for item in data["evidence"])
    assert all(len(item["sha256"]) == 64 for item in data["evidence"])
    assert ".env" not in str(data)
    assert "NEVER_SEND" not in str(data)


def test_deterministic_plan_and_absent_source_are_not_misrepresented(fixture):
    client, root = fixture
    p = "Build a galactic_widget_never_existed controller"
    first = _preview(client, root, p).json()
    second = _preview(client, root, p).json()
    assert first["plan_id"] == second["plan_id"]
    assert first["category"] == "feature"
    assert not first["source_verified"]
    assert first["evidence"] == []
    assert first["steps"][0]["status"] == "proposed"


def test_debug_plan_and_no_mutation(fixture):
    client, root = fixture
    before = (root / "login.py").read_bytes()
    response = _preview(client, root, "Fix the login error in verify_login")
    assert response.status_code == 200
    data = response.json()
    assert data["category"] == "authentication"  # login safety takes priority
    assert any(step["id"] == "security" for step in data["steps"])
    assert (root / "login.py").read_bytes() == before


def test_local_only_auth_and_approval_boundary(fixture, tmp_path):
    client, root = fixture
    assert not path_allowed("POST", BASE)
    payload = {"project": str(root), "request": "Add a login page"}
    assert client.post(BASE, json=payload).status_code == 403
    assert client.post(BASE, headers={**AUTH, "Origin": "https://evil.invalid"},
                       json=payload).status_code == 403
    assert client.post(BASE, headers=AUTH,
                       json={**payload, "project": str(tmp_path)}).status_code in (403, 422)
    assert client.post(BASE, headers=AUTH,
                       json={**payload, "confirmed": True}).status_code == 422


def test_no_symlinked_content_in_plan(fixture, tmp_path):
    client, root = fixture
    external = tmp_path / "outside.py"
    external.write_text("def galactic_widget_never_existed(): pass\n", encoding="utf-8")
    try:
        (root / "linked.py").symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation unavailable on this host")
    response = _preview(client, root, "Implement galactic_widget_never_existed")
    assert response.status_code == 200
    assert not response.json()["source_verified"]
