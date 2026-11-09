"""Developer Studio V3: trusted, non-clobber, private recovery regressions."""
from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from automoto import sandbox, server
from automoto.hosted import path_allowed

BASE = "/api/developer/studio"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root()
    project = root / "v3-project"
    (project / "src").mkdir(parents=True)
    source = project / "src" / "main.py"
    source.write_bytes(b"print('before')\n")
    return TestClient(server.app), project, source


def trust(client, project):
    result = client.post(BASE + "/trust", headers=AUTH,
                         json={"project": str(project), "trusted": True, "confirmed": True})
    assert result.status_code == 200, result.text


def opened(client, project, path="src/main.py"):
    result = client.get(BASE + "/file", headers=AUTH, params={"project": str(project), "path": path})
    assert result.status_code == 200, result.text
    return result.json()


def working(project, before, text="print('unsaved')\n", **kwargs):
    return {
        "project": str(project), "path": "src/main.py", "text": text,
        "encoding": before["encoding"], "newline": before["newline"],
        "expected_sha256": before["sha256"], "confirmed": True, **kwargs
    }


def operation(client, project, action, path="src/main.py", **kwargs):
    return client.post(BASE + "/operation", headers=AUTH, json={
        "project": str(project), "action": action, "path": path, "confirmed": True, **kwargs
    })


def test_v3_auth_and_hosted_default_deny(context):
    client, project, source = context
    assert not path_allowed("POST", BASE + "/operation")
    assert not path_allowed("POST", BASE + "/snapshot")
    assert not path_allowed("GET", BASE + "/recovery")
    assert client.post(BASE + "/operation", json={
        "project": str(project), "action": "create", "path": "src/new.py", "confirmed": True
    }).status_code == 403
    assert client.post(BASE + "/snapshot", json=working(project, opened(client, project))).status_code == 403


def test_create_trust_explicit_confirm_and_no_overwrite(context):
    client, project, source = context
    old = source.read_bytes()
    assert operation(client, project, "create", path="src/new.py").status_code == 403
    trust(client, project)
    missing = client.post(BASE + "/operation", headers=AUTH, json={
        "project": str(project), "action": "create", "path": "src/new.py"
    })
    assert missing.status_code == 422
    made = operation(client, project, "create", path="src/new.py")
    assert made.status_code == 200, made.text
    assert (project / "src" / "new.py").read_bytes() == b""
    assert operation(client, project, "create", path="src/new.py").status_code == 409
    assert operation(client, project, "create").status_code == 409
    assert source.read_bytes() == old


def test_rename_preserves_bytes_and_refuses_existing_dest(context):
    client, project, source = context
    trust(client, project)
    original = source.read_bytes()
    precondition = hashlib.sha256(original).hexdigest()
    (project / "src" / "taken.py").write_bytes(b"taken")
    conflict = operation(client, project, "rename", destination="src/taken.py",
                         expected_sha256=precondition)
    assert conflict.status_code == 409 and source.read_bytes() == original
    source.write_bytes(b"print('external')\n")
    stale = operation(client, project, "rename", destination="src/changed.py",
                      expected_sha256=precondition)
    assert stale.status_code == 409
    precondition = hashlib.sha256(source.read_bytes()).hexdigest()
    moved = operation(client, project, "rename", destination="src/renamed.py",
                      expected_sha256=precondition)
    if moved.status_code == 403 and "filesystem" in moved.text:
        pytest.skip("Host filesystem does not support safe hardlink rename")
    assert moved.status_code == 200, moved.text
    assert not source.exists()
    assert (project / "src" / "renamed.py").read_bytes() == b"print('external')\n"


def test_soft_delete_is_recoverable_and_never_clobbers(context):
    client, project, source = context
    trust(client, project)
    original = source.read_bytes()
    sha = hashlib.sha256(original).hexdigest()
    archived = operation(client, project, "trash", expected_sha256=sha)
    assert archived.status_code == 200, archived.text
    assert not source.exists()
    uid = archived.json()["archive_id"]
    target = {"project": str(project), "path": "src/main.py", "snapshot_id": uid}
    source.write_bytes(b"occupied\n")
    conflict = client.post(BASE + "/restore-trash", headers=AUTH, json=target)
    assert conflict.status_code == 409 and source.read_bytes() == b"occupied\n"
    source.unlink()
    restored = client.post(BASE + "/restore-trash", headers=AUTH, json=target)
    assert restored.status_code == 200, restored.text
    assert source.read_bytes() == original
    assert restored.json()["sha256"] == sha
    assert client.post(BASE + "/restore-trash", headers=AUTH, json=target).status_code == 404


def test_private_recovery_does_not_modify_source_and_requires_trust(context):
    client, project, source = context
    trust(client, project)
    before = opened(client, project)
    original = source.read_bytes()
    body = working(project, before)
    saved = client.post(BASE + "/snapshot", headers=AUTH, json=body)
    assert saved.status_code == 200, saved.text
    uid = saved.json()["snapshot_id"]
    assert source.read_bytes() == original
    listed = client.get(BASE + "/snapshots", headers=AUTH,
                        params={"project": str(project), "path": "src/main.py"})
    assert listed.status_code == 200 and len(listed.json()["items"]) == 1
    recovery = client.get(BASE + "/recovery", headers=AUTH,
                          params={"project": str(project), "path": "src/main.py", "snapshot_id": uid})
    assert recovery.status_code == 200, recovery.text
    assert recovery.json()["text"] == body["text"]
    assert recovery.json()["restored_to_disk"] is False
    source.write_bytes(b"print('external')\n")
    assert client.post(BASE + "/snapshot", headers=AUTH, json=body).status_code == 409
    assert source.read_bytes() == b"print('external')\n"
    revoke = client.post(BASE + "/trust", headers=AUTH,
                         json={"project": str(project), "trusted": False, "confirmed": True})
    assert revoke.status_code == 200
    assert client.get(BASE + "/recovery", headers=AUTH, params={
        "project": str(project), "path": "src/main.py", "snapshot_id": uid
    }).status_code == 403


def test_recovery_retention_and_discard(context):
    client, project, source = context
    trust(client, project)
    before = opened(client, project)
    snapshots = []
    for count in range(5):
        result = client.post(BASE + "/snapshot", headers=AUTH,
                             json=working(project, before, text=f"print({count})\n"))
        assert result.status_code == 200, result.text
        snapshots.append(result.json()["snapshot_id"])
    listed = client.get(BASE + "/snapshots", headers=AUTH, params={
        "project": str(project), "path": "src/main.py"
    })
    assert len(listed.json()["items"]) == 3
    assert snapshots[0] not in [x["snapshot_id"] for x in listed.json()["items"]]
    discard = client.post(BASE + "/discard-snapshot", headers=AUTH, json={
        "project": str(project), "path": "src/main.py", "snapshot_id": snapshots[-1]
    })
    assert discard.status_code == 200
    assert client.get(BASE + "/recovery", headers=AUTH, params={
        "project": str(project), "path": "src/main.py", "snapshot_id": snapshots[-1]
    }).status_code == 404


def test_diff_is_inert_and_fails_on_stale_source(context):
    client, project, source = context
    trust(client, project)
    before = opened(client, project)
    response = client.post(BASE + "/diff", headers=AUTH, json=working(project, before))
    assert response.status_code == 200, response.text
    assert response.json()["changed"] and "-print('before')" in response.json()["diff"]
    assert "+print('unsaved')" in response.json()["diff"]
    assert source.read_bytes() == b"print('before')\n"
    source.write_bytes(b"unrelated\n")
    assert client.post(BASE + "/diff", headers=AUTH,
                       json=working(project, before)).status_code == 409


def test_forbidden_paths_unapproved_roots_and_symlinks(context, tmp_path):
    client, project, source = context
    trust(client, project)
    before = opened(client, project)
    for candidate in ("../escape.py", ".env", ".git/evil", "src/../bad.py", "src\\bad.py"):
        assert operation(client, project, "create", path=candidate).status_code in (403, 409, 422)
    outside = tmp_path / "outside"
    outside.mkdir()
    assert operation(client, outside, "create", path="new.py").status_code == 403
    linked = project / "src" / "linked.py"
    try:
        linked.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("No symlink support")
    assert operation(client, project, "trash", path="src/linked.py",
                     expected_sha256=before["sha256"]).status_code == 403
