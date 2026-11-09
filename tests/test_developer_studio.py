"""Developer Studio V1 — trust, private source viewing and non-mutation tests."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import developer_studio, sandbox, server
from automoto.hosted import path_allowed

BASE = "/api/developer/studio"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root()
    repo = root / "projects" / "example"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "main.py").write_bytes(b"print('safe')\n")
    (repo / ".env").write_text("SECRET=should-not-leak", encoding="utf-8")
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("[remote]\n", encoding="utf-8")
    yield TestClient(server.app), repo


def test_v1_routes_are_authenticated_and_not_hosted(client):
    http, repo = client
    assert not path_allowed("GET", BASE + "/roots")
    assert not path_allowed("GET", BASE + "/preview")
    assert http.get(BASE + "/roots").status_code == 403
    assert http.post(BASE + "/trust", json={"project": str(repo), "trusted": True,
                                           "confirmed": True}).status_code == 403
    assert http.get(BASE + "/roots", headers={**AUTH, "Origin": "https://evil.example"}).status_code == 403


def test_workspace_open_tree_preview_and_no_source_mutation(client):
    http, repo = client
    before = (repo / "src" / "main.py").read_bytes()
    opened = http.post(BASE + "/open", headers=AUTH, json={"project": str(repo)})
    assert opened.status_code == 200, opened.text
    assert opened.json()["read_only"] is True
    assert opened.json()["can_edit"] is False
    assert opened.json()["can_execute"] is False
    assert opened.json()["trusted"] is False

    listing = http.get(BASE + "/tree", headers=AUTH, params={"project": str(repo)})
    assert listing.status_code == 200, listing.text
    names = [item["name"] for item in listing.json()["items"]]
    assert "src" in names and ".git" not in names and ".env" not in names

    source = http.get(BASE + "/tree", headers=AUTH, params={"project": str(repo), "directory": "src"})
    assert source.status_code == 200
    assert source.json()["items"][0]["path"] == "src/main.py"
    preview = http.get(BASE + "/preview", headers=AUTH,
                       params={"project": str(repo), "path": "src/main.py"})
    assert preview.status_code == 200, preview.text
    assert preview.json()["text"] == "print('safe')\n"
    assert preview.json()["read_only"] is True
    assert (repo / "src" / "main.py").read_bytes() == before
    assert http.get(BASE + "/preview", headers=AUTH,
                    params={"project": str(repo), "path": ".env"}).status_code == 403


def test_trust_requires_explicit_confirmation_and_can_be_revoked(client):
    http, repo = client
    unsigned = http.post(BASE + "/trust", headers=AUTH,
                         json={"project": str(repo), "trusted": True})
    assert unsigned.status_code == 422
    enabled = http.post(BASE + "/trust", headers=AUTH,
                        json={"project": str(repo), "trusted": True, "confirmed": True})
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["trusted"] is True
    assert enabled.json()["read_only"] is True  # Trust does not grant V1 write access.
    roots = http.get(BASE + "/roots", headers=AUTH)
    assert any(p["trusted"] for p in roots.json()["recent"]) is False  # trust does not auto-open
    opened = http.post(BASE + "/open", headers=AUTH, json={"project": str(repo)})
    assert opened.json()["trusted"] is True
    assert any(p["trusted"] for p in http.get(BASE + "/roots", headers=AUTH).json()["recent"])
    revoked = http.post(BASE + "/trust", headers=AUTH,
                        json={"project": str(repo), "trusted": False, "confirmed": True})
    assert revoked.status_code == 200 and revoked.json()["trusted"] is False
    assert http.post(BASE + "/open", headers=AUTH, json={"project": str(repo)}).json()["trusted"] is False


def test_rejects_unapproved_roots_traversal_and_symlinks(client, tmp_path):
    http, repo = client
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "credentials.txt").write_text("private", encoding="utf-8")
    blocked = http.post(BASE + "/open", headers=AUTH, json={"project": str(outside)})
    assert blocked.status_code == 403
    for path in ("../private", "/etc/passwd", ".git/config", "src/../.env", "src\\main.py"):
        response = http.get(BASE + "/preview", headers=AUTH,
                            params={"project": str(repo), "path": path})
        assert response.status_code in (403, 422), (path, response.text)
    link = repo / "external"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Cannot create symlink on this host")
    entries = http.get(BASE + "/tree", headers=AUTH, params={"project": str(repo)})
    assert "external" not in [item["name"] for item in entries.json()["items"]]
    assert http.get(BASE + "/tree", headers=AUTH,
                    params={"project": str(repo), "directory": "external"}).status_code == 403


def test_external_root_requires_existing_settings_allowlist(client, tmp_path, monkeypatch):
    http, _ = client
    outside = tmp_path / "allowed"
    outside.mkdir()
    assert http.post(BASE + "/open", headers=AUTH, json={"project": str(outside)}).status_code == 403
    monkeypatch.setenv("AUTOMOTO_ALLOWED_ROOTS", str(outside))
    response = http.post(BASE + "/open", headers=AUTH, json={"project": str(outside)})
    assert response.status_code == 200, response.text
    assert response.json()["read_only"] is True


def test_large_binary_and_invalid_utf8_are_not_served(client):
    http, repo = client
    (repo / "binary.bin").write_bytes(b"hello\x00world")
    (repo / "large.txt").write_bytes(b"A" * (developer_studio.MAX_PREVIEW + 1))
    (repo / "bad.txt").write_bytes(b"\xff\xfe")
    for name, expected in (("binary.bin", 415), ("large.txt", 413), ("bad.txt", 415)):
        response = http.get(BASE + "/preview", headers=AUTH,
                            params={"project": str(repo), "path": name})
        assert response.status_code == expected, (name, response.text)


def test_state_symlink_fails_closed(client, tmp_path):
    http, repo = client
    state = developer_studio._state_path()
    state.parent.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "external-state.json"
    target.write_text('{"trusted": [], "recent": []}', encoding="utf-8")
    try:
        state.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Cannot create symlink on this host")
    response = http.post(BASE + "/trust", headers=AUTH,
                         json={"project": str(repo), "trusted": True, "confirmed": True})
    assert response.status_code == 403
    assert target.read_text(encoding="utf-8") == '{"trusted": [], "recent": []}'
