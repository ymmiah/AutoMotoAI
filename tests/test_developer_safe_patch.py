"""V51 checked patch preview, apply and persistent undo regression tests."""
from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient
import pytest

from automoto import developer_safe_patch as patch, sandbox, server
from automoto.hosted import path_allowed
from automoto.studio_registry import studio_request

BASE = "/api/developer/studio/patch"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
ORIGINAL = "def add(a, b):\n    return a - b\n"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    repo = sandbox.default_root() / "v51"
    repo.mkdir(parents=True)
    (repo / "add.py").write_text(ORIGINAL, encoding="utf-8")
    (repo / ".env").write_text("password=SECRET", encoding="utf-8")
    (repo / ".npmrc").write_text("token=SECRET", encoding="utf-8")
    with patch.LOCK:
        patch.PREVIEWS.clear()
    http = TestClient(server.app)
    response = http.post("/api/developer/studio/trust", headers=AUTH,
                         json={"project": str(repo), "trusted": True, "confirmed": True})
    assert response.status_code == 200, response.text
    yield http, repo
    with patch.LOCK:
        patch.PREVIEWS.clear()


def payload(repo, **kwargs):
    value = {
        "project": str(repo), "path": "add.py",
        "expected_sha256": hashlib.sha256((repo / "add.py").read_bytes()).hexdigest(),
        "old_fragment": "return a - b", "new_fragment": "return a + b",
    }
    value.update(kwargs)
    return value


def test_preview_never_changes_and_apply_can_undo(client):
    http, repo = client
    response = http.post(BASE + "/preview", headers=AUTH, json=payload(repo))
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["source_modified"] is False
    assert "return a + b" in plan["diff"]
    assert len(plan["token"]) == 32
    assert (repo / "add.py").read_text() == ORIGINAL

    action = {"project": str(repo), "path": "add.py", "token": plan["token"], "confirmed": True}
    applied = http.post(BASE + "/apply", headers=AUTH, json=action)
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] is True and applied.json()["executed"] is False
    assert (repo / "add.py").read_text() == "def add(a, b):\n    return a + b\n"
    assert http.post(BASE + "/apply", headers=AUTH, json=action).status_code == 409

    undone = http.post(BASE + "/undo", headers=AUTH,
                       json={**action, "token": applied.json()["undo_id"]})
    assert undone.status_code == 200, undone.text
    assert undone.json()["undone"] is True
    assert (repo / "add.py").read_text() == ORIGINAL
    assert http.post(BASE + "/undo", headers=AUTH,
                     json={**action, "token": applied.json()["undo_id"]}).status_code == 404


def test_stale_preview_and_stale_undo_refuse_to_clobber(client):
    http, repo = client
    p = http.post(BASE + "/preview", headers=AUTH, json=payload(repo)).json()
    (repo / "add.py").write_text("def add(a, b):\n    return 123\n")
    action = {"project": str(repo), "path": "add.py", "token": p["token"], "confirmed": True}
    assert http.post(BASE + "/apply", headers=AUTH, json=action).status_code == 409
    assert "123" in (repo / "add.py").read_text()
    (repo / "add.py").write_text(ORIGINAL)
    p2 = http.post(BASE + "/preview", headers=AUTH, json=payload(repo)).json()
    a2 = http.post(BASE + "/apply", headers=AUTH,
                   json={**action, "token": p2["token"]}).json()
    (repo / "add.py").write_text("def add(a, b):\n    return 999\n")
    bad_undo = http.post(BASE + "/undo", headers=AUTH,
                         json={**action, "token": a2["undo_id"]})
    assert bad_undo.status_code == 409
    assert "999" in (repo / "add.py").read_text()


def test_blocks_ambiguous_invalid_oversized_and_protected_files(client):
    http, repo = client
    (repo / "add.py").write_text("def add(a,b):\n    return a - b\n    # return a - b\n")
    duplicate = http.post(BASE + "/preview", headers=AUTH, json=payload(repo))
    assert duplicate.status_code == 409
    (repo / "add.py").write_text(ORIGINAL)
    invalid = http.post(BASE + "/preview", headers=AUTH,
                        json=payload(repo, new_fragment="return ("))
    assert invalid.status_code == 422
    huge = http.post(BASE + "/preview", headers=AUTH,
                     json=payload(repo, new_fragment="\n".join(["pass"] * 95)))
    assert huge.status_code == 413
    for secret in (".env", ".npmrc"):
        response = http.post(BASE + "/preview", headers=AUTH,
                             json=payload(repo, path=secret))
        assert response.status_code == 403
    assert (repo / ".env").read_text() == "password=SECRET"


def test_auth_hosted_guard_and_agent_apply_is_refused(client):
    http, repo = client
    assert not path_allowed("POST", BASE + "/preview")
    assert not path_allowed("POST", BASE + "/apply")
    assert http.post(BASE + "/preview", json=payload(repo)).status_code == 403
    assert http.post(BASE + "/preview", headers={**AUTH, "Origin": "https://evil.invalid"},
                     json=payload(repo)).status_code == 403
    preview = http.post(BASE + "/preview", headers=AUTH, json=payload(repo)).json()
    action = patch.ActIn(project=str(repo), path="add.py", token=preview["token"], confirmed=True)
    with pytest.raises(Exception) as exc:
        patch.apply(studio_request("POST"), action)
    assert getattr(exc.value, "status_code", None) == 403
    assert (repo / "add.py").read_text() == ORIGINAL


def test_preview_requires_trust_and_blocks_symlinks(client, tmp_path):
    http, repo = client
    http.post("/api/developer/studio/trust", headers=AUTH,
              json={"project": str(repo), "trusted": False, "confirmed": True})
    assert http.post(BASE + "/preview", headers=AUTH, json=payload(repo)).status_code == 403
    http.post("/api/developer/studio/trust", headers=AUTH,
              json={"project": str(repo), "trusted": True, "confirmed": True})
    external = tmp_path / "external.py"
    external.write_text(ORIGINAL)
    try:
        (repo / "linked.py").symlink_to(external)
    except (NotImplementedError, OSError):
        pytest.skip("No symlink support on this host")
    response = http.post(BASE + "/preview", headers=AUTH,
                         json=payload(repo, path="linked.py"))
    assert response.status_code in (403, 404)
