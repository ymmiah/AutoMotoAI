"""Developer Studio review checkpoints: Keep or Undo one coding task's changes."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from automoto import sandbox, server
from automoto.hosted import path_allowed

BASE = "/api/developer/studio"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    repo = sandbox.default_root() / "projects" / "web"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "Counter.tsx").write_text("const n = 1;\nexport default n;\n", encoding="utf-8")
    (repo / "README.md").write_text("# web\n", encoding="utf-8")
    (repo / "node_modules" / "x").mkdir(parents=True)
    (repo / "node_modules" / "x" / "i.js").write_text("ignored", encoding="utf-8")
    (repo / ".env").write_text("SECRET=1", encoding="utf-8")
    http = TestClient(server.app)
    yield http, repo


def _trust(http, repo):
    r = http.post(BASE + "/trust", headers=AUTH, json={"project": str(repo), "trusted": True, "confirmed": True})
    assert r.status_code == 200, r.text


def test_review_routes_are_local_only_and_need_trust(client):
    http, repo = client
    assert not path_allowed("POST", BASE + "/review/start")
    assert not path_allowed("GET", BASE + "/review/toolchains")
    assert http.post(BASE + "/review/start", json={"project": str(repo)}).status_code == 403
    assert http.post(BASE + "/review/start", headers=AUTH, json={"project": str(repo)}).status_code == 403


def test_changes_diff_and_undo_restore_everything(client):
    http, repo = client
    _trust(http, repo)
    start = http.post(BASE + "/review/start", headers=AUTH, json={"project": str(repo)})
    assert start.status_code == 200, start.text
    cp = start.json()["checkpoint"]
    assert start.json()["complete"] is True
    (repo / "src" / "Counter.tsx").write_text("const n = 2;\nexport default n;\n", encoding="utf-8")
    (repo / "src" / "Counter.test.tsx").write_text("test\n", encoding="utf-8")
    (repo / "README.md").unlink()
    (repo / "node_modules" / "x" / "i.js").write_text("changed", encoding="utf-8")
    (repo / ".env").write_text("SECRET=2", encoding="utf-8")
    got = http.get(BASE + "/review/changes", headers=AUTH, params={"project": str(repo), "checkpoint": cp}).json()
    kinds = {c["path"]: c["change"] for c in got["changes"]}
    assert kinds == {"src/Counter.tsx": "modified", "src/Counter.test.tsx": "added", "README.md": "deleted"}
    counter = next(c for c in got["changes"] if c["path"] == "src/Counter.tsx")
    assert counter["added"] == 1 and counter["removed"] == 1 and "+const n = 2;" in counter["diff"]
    assert http.post(BASE + "/review/undo", headers=AUTH, json={"project": str(repo), "checkpoint": cp}).status_code == 422
    undone = http.post(BASE + "/review/undo", headers=AUTH, json={"project": str(repo), "checkpoint": cp, "confirmed": True})
    assert undone.status_code == 200, undone.text
    assert (repo / "src" / "Counter.tsx").read_text(encoding="utf-8") == "const n = 1;\nexport default n;\n"
    assert (repo / "README.md").read_text(encoding="utf-8") == "# web\n"
    assert not (repo / "src" / "Counter.test.tsx").exists()
    # Excluded folders and secrets are never touched.
    assert (repo / "node_modules" / "x" / "i.js").read_text(encoding="utf-8") == "changed"
    assert (repo / ".env").read_text(encoding="utf-8") == "SECRET=2"
    again = http.get(BASE + "/review/changes", headers=AUTH, params={"project": str(repo), "checkpoint": cp})
    assert again.status_code == 404


def test_keep_discards_checkpoint_and_leaves_files(client):
    http, repo = client
    _trust(http, repo)
    cp = http.post(BASE + "/review/start", headers=AUTH, json={"project": str(repo)}).json()["checkpoint"]
    (repo / "src" / "Counter.tsx").write_text("kept\n", encoding="utf-8")
    assert http.post(BASE + "/review/keep", headers=AUTH, json={"project": str(repo), "checkpoint": cp}).status_code == 200
    assert (repo / "src" / "Counter.tsx").read_text(encoding="utf-8") == "kept\n"
    assert http.post(BASE + "/review/undo", headers=AUTH,
                     json={"project": str(repo), "checkpoint": cp, "confirmed": True}).status_code == 404


def test_checkpoint_ids_are_validated(client):
    http, repo = client
    _trust(http, repo)
    bad = http.get(BASE + "/review/changes", headers=AUTH, params={"project": str(repo), "checkpoint": "../../etc/passwd00"})
    assert bad.status_code == 422


def test_toolchains_reports_path_availability_without_running(client):
    http, _ = client
    data = http.get(BASE + "/review/toolchains", headers=AUTH).json()
    assert "typescript" in data["toolchains"] and "installed" in data["toolchains"]["python"]
    assert "not run" in data["verification"]
