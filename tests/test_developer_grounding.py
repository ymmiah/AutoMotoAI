"""V49 source-grounding checks: real lines, strict bounds and local-only safety."""
from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from automoto import sandbox, server

BASE = "/api/developer/studio/grounding"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "my-app"
    (root / "src").mkdir(parents=True)
    (root / "src" / "login.py").write_text(
        "from typing import Any\n"
        "def verify_login(username: str) -> bool:\n"
        "    return bool(username)\n", encoding="utf-8")
    (root / ".env").write_text("password=PRIVATE_MARKER", encoding="utf-8")
    (root / "src" / "config.py").write_text(
        "api_key = 'PRIVATE_MARKER'\n"
        "def connect_api():\n"
        "    return True\n", encoding="utf-8")
    return TestClient(server.app), root


def test_exact_source_and_lines(fixture):
    client, root = fixture
    response = client.post(BASE, headers=AUTH, json={
        "project": str(root), "question": "Where is verify_login defined?"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["verified"] and data["read_only"]
    assert data["sources"][0]["path"] == "src/login.py"
    assert data["sources"][0]["matched_line"] == 2
    assert "L2: def verify_login" in data["sources"][0]["excerpt"]
    assert len(data["sources"][0]["sha256"]) == 64


def test_no_guess_and_no_hidden_secrets(fixture):
    client, root = fixture
    no_match = client.post(BASE, headers=AUTH, json={
        "project": str(root), "question": "unfound_unique_identifier_xyz"})
    assert no_match.status_code == 200
    assert no_match.json()["sources"] == []
    assert not no_match.json()["verified"]
    response = client.post(BASE, headers=AUTH, json={
        "project": str(root), "question": "api_key password"})
    assert response.status_code == 200
    text = str(response.json())
    assert "PRIVATE_MARKER" not in text
    assert ".env" not in text
    assert "[redacted]" in text


def test_private_route_and_rejected_paths(fixture, tmp_path):
    client, root = fixture
    assert client.post(BASE, json={"project": str(root), "question": "login"}).status_code == 403
    assert client.post(BASE, headers={**AUTH, "Origin": "https://evil.example"},
                       json={"project": str(root), "question": "login"}).status_code == 403
    assert client.post(BASE, headers=AUTH, json={
        "project": str(tmp_path), "question": "login"}).status_code in (403, 422)
    outside = tmp_path / "external.py"
    outside.write_text("verify_login outside\n")
    try:
        (root / "src" / "linked.py").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Cannot create symlinks on this host")
    response = client.post(BASE, headers=AUTH, json={
        "project": str(root), "question": "outside"})
    assert response.status_code == 200
    assert all(s["path"] != "src/linked.py" for s in response.json()["sources"])


def test_no_project_modification(fixture):
    client, root = fixture
    file = root / "src" / "login.py"
    before = file.read_bytes()
    client.post(BASE, headers=AUTH, json={
        "project": str(root), "question": "verify_login"})
    assert file.read_bytes() == before
