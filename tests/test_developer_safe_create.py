"""V54: no-clobber creation and guarded undo; no providers or commands required."""
from __future__ import annotations

import hashlib
import os

import pytest
from fastapi.testclient import TestClient

from automoto import developer_safe_create as create
from automoto import developer_safe_patch as patch
from automoto import sandbox, server
from automoto.hosted import path_allowed
from automoto.studio_registry import studio_request

BASE = "/api/developer/studio/create"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
CODE = "def answer():\n    return 42\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v54"
    root.mkdir(parents=True)
    (root / "src").mkdir()
    with create.LOCK:
        create.PREVIEWS.clear()
    with TestClient(server.app) as client:
        response = client.post("/api/developer/studio/trust", headers=AUTH,
                               json={"project": str(root), "trusted": True, "confirmed": True})
        assert response.status_code == 200, response.text
        yield client, root, tmp_path
    with create.LOCK:
        create.PREVIEWS.clear()


def payload(root, path="src/new_module.py", text=CODE):
    return {"project": str(root), "path": path, "text": text}


def preview(client, root, path="src/new_module.py", text=CODE):
    return client.post(BASE + "/preview", headers=AUTH, json=payload(root, path, text))


def confirmed(root, token, path="src/new_module.py"):
    return {"project": str(root), "path": path, "token": token, "confirmed": True}


def test_preview_then_create_and_guarded_undo(env):
    client, root, _ = env
    result = preview(client, root)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["creation"] and data["prepared_by_server"]
    assert data["file_exists"] is False and data["source_modified"] is False
    assert data["preview_diff"].startswith("--- /dev/null")
    assert data["after_sha256"] == hashlib.sha256(CODE.encode()).hexdigest()
    assert not (root / "src" / "new_module.py").exists()

    response = client.post(BASE + "/apply", headers=AUTH,
                           json=confirmed(root, data["token"]))
    assert response.status_code == 200, response.text
    applied = response.json()
    assert applied["created"] and not applied["executed"] and not applied["shared"]
    assert (root / "src" / "new_module.py").read_text() == CODE
    assert client.post(BASE + "/apply", headers=AUTH,
                       json=confirmed(root, data["token"])).status_code == 409
    undo = client.post(BASE + "/undo", headers=AUTH,
                       json=confirmed(root, applied["undo_id"]))
    assert undo.status_code == 200, undo.text
    assert not (root / "src" / "new_module.py").exists()
    assert client.post(BASE + "/undo", headers=AUTH,
                       json=confirmed(root, applied["undo_id"])).status_code == 404


def test_creation_never_overwrites_existing_file_even_if_appears_after_preview(env):
    client, root, _ = env
    planned = preview(client, root).json()
    destination = root / "src" / "new_module.py"
    destination.write_text("existing user's work\n")
    result = client.post(BASE + "/apply", headers=AUTH,
                         json=confirmed(root, planned["token"]))
    assert result.status_code == 409
    assert destination.read_text() == "existing user's work\n"
    assert preview(client, root).status_code == 409


def test_undo_never_removes_later_edits_or_file_replacement(env):
    client, root, _ = env
    p = preview(client, root).json()
    created = client.post(BASE + "/apply", headers=AUTH,
                          json=confirmed(root, p["token"])).json()
    destination = root / "src" / "new_module.py"
    destination.write_text("user changed this after approval\n")
    result = client.post(BASE + "/undo", headers=AUTH,
                         json=confirmed(root, created["undo_id"]))
    assert result.status_code == 409
    assert destination.read_text() == "user changed this after approval\n"
    destination.unlink()
    destination.write_text(CODE)
    again = client.post(BASE + "/undo", headers=AUTH,
                        json=confirmed(root, created["undo_id"]))
    assert again.status_code == 409, "same content with a replacement inode cannot be removed"
    assert destination.read_text() == CODE


def test_preview_rejects_protected_paths_syntax_oversize_missing_parent(env):
    client, root, _ = env
    for name in (".env", ".npmrc", ".git/hooks/pre-commit", "../outside.py",
                 "src/secret.pem", "src/secret.key", "node_modules/evil.js",
                 "src/config.ini", "src/file.exe", "src/.hidden.py"):
        assert preview(client, root, name).status_code in (403, 404, 409, 422), name
    assert preview(client, root, "missing/new_module.py").status_code == 404
    assert preview(client, root, text="def broken(:\n").status_code == 422
    assert preview(client, root, text="x\n" * 121).status_code == 413
    assert preview(client, root, text="\x00").status_code == 415
    assert preview(client, root, text="x" * (create.MAX_NEW_BYTES+1)).status_code == 422


def test_rejects_links_and_modified_parent_directory(env):
    client, root, tmp_path = env
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Host disallows symlinks")
    assert preview(client, root, "linked/escape.py").status_code == 403
    planned = preview(client, root).json()
    (root / "src").rename(root / "src2")
    (root / "src").mkdir()
    attempt = client.post(BASE + "/apply", headers=AUTH,
                          json=confirmed(root, planned["token"]))
    assert attempt.status_code == 409
    assert not (root / "src" / "new_module.py").exists()
    assert not (root / "src2" / "new_module.py").exists()


def test_only_local_human_can_apply_or_undo(env):
    client, root, _ = env
    p = preview(client, root).json()
    assert not path_allowed("POST", BASE + "/preview")
    assert not path_allowed("POST", BASE + "/apply")
    assert client.post(BASE + "/preview", json=payload(root)).status_code == 403
    assert client.post(BASE + "/apply", headers={**AUTH, "Origin": "https://evil.invalid"},
                       json=confirmed(root, p["token"])).status_code == 403
    with pytest.raises(Exception) as exc:
        create.apply(studio_request("POST"),
                     create.ActIn(**confirmed(root, p["token"])))
    assert getattr(exc.value, "status_code", None) == 403
    assert not (root / "src" / "new_module.py").exists()


def test_undo_record_survives_preview_cache_reset(env):
    client, root, _ = env
    p = preview(client, root).json()
    result = client.post(BASE + "/apply", headers=AUTH,
                         json=confirmed(root, p["token"])).json()
    with create.LOCK:
        create.PREVIEWS.clear()  # restart-like: the in-memory preview cache is gone
    undone = client.post(BASE + "/undo", headers=AUTH,
                         json=confirmed(root, result["undo_id"]))
    assert undone.status_code == 200
    assert not (root / "src" / "new_module.py").exists()
