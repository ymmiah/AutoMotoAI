"""Research Studio V8: authenticated portable export/import and non-destructive staging."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from automoto import research_acceptance, research_portable, sandbox, server
from automoto.hosted import path_allowed
from test_research_acceptance import approved_comparison, copy_body

BASE = "/api/research/studio/portable"
H = {"X-AutoMoto-Token": server.SESSION_TOKEN}
PASSWORD = "unique-v8-portable-recovery-passphrase-2026"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "portable-home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "portable-user"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    with server._HITS_LOCK:
        server._HITS.clear()
    try:
        yield TestClient(server.app)
    finally:
        with server._HITS_LOCK:
            server._HITS.clear()


def source_backup(client):
    ref, sources = approved_comparison(client)
    backup = client.post("/api/research/studio/acceptance/snapshot", headers=H,
                         json=copy_body(ref))
    assert backup.status_code == 200, backup.text
    return backup.json(), sources


def encrypted_backup(client):
    local, sources = source_backup(client)
    sent = {
        "path": local["path"], "sha256": local["sha256"],
        "passphrase": PASSWORD, "acknowledgement": "ENCRYPT PORTABLE BACKUP",
        "confirm_user_will_store_separately": True,
    }
    response = client.post(BASE + "/create", headers=H, json=sent)
    assert response.status_code == 200, response.text
    info = response.json()
    return info, (sandbox.default_root() / info["path"]).read_bytes(), sources


def send(client, path, payload, password=PASSWORD, **fields):
    return client.post(BASE + path, headers=H,
        files={"capsule": ("research.amrc8", payload, "application/octet-stream")},
        data={"passphrase": password, **fields})


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def test_local_only_authenticated_and_hosted_default_deny(client):
    for method, route in (
        ("POST", "/create"), ("POST", "/inspect"), ("POST", "/stage"),
        ("GET", "/download"), ("GET", "/list"),
    ):
        assert not path_allowed(method, BASE + route)
    assert client.get(BASE + "/list").status_code == 403
    assert client.post(BASE + "/inspect", files={
        "capsule": ("research.amrc8", b"invalid", "application/octet-stream")},
        data={"passphrase": PASSWORD}).status_code == 403
    assert client.post(BASE + "/create", json={
        "path": "artifacts/research/recovery/snapshots/backup-" + "a" * 24 + ".recovery.json",
        "sha256": "b" * 64, "passphrase": PASSWORD,
        "acknowledgement": "ENCRYPT PORTABLE BACKUP",
        "confirm_user_will_store_separately": True}).status_code == 403


def test_encrypted_file_contains_no_plaintext_and_is_downloadable(client):
    created, capsule, sources = encrypted_backup(client)
    assert created["encrypted"] and created["originals_modified"] is False
    assert capsule.startswith(research_portable.MAGIC)
    assert PASSWORD.encode() not in capsule
    assert b"deployment exposure" not in capsule
    assert b"uploads/audit-1.txt" not in capsule
    listed = client.get(BASE + "/list", headers=H)
    assert listed.status_code == 200
    assert any(x["path"] == created["path"] for x in listed.json()["capsules"])
    downloaded = client.get(BASE + "/download", headers=H,
        params={"path": created["path"], "sha256": created["sha256"]})
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == capsule
    assert downloaded.headers.get("cache-control") == "no-store"
    assert downloaded.headers["content-type"].startswith("application/octet-stream")
    assert client.get(BASE + "/download", headers=H,
        params={"path": created["path"], "sha256": "0" * 64}).status_code == 409
    assert client.get(BASE + "/download", headers=H,
        params={"path": "artifacts/research/recovery/portable/../escape.amrc8",
                "sha256": created["sha256"]}).status_code == 403


def test_wrong_password_truncated_and_bit_flipped_ciphertexts_fail_closed(client):
    created, capsule, _ = encrypted_backup(client)
    assert send(client, "/inspect", capsule, password="totally-different-passphrase").status_code == 422
    assert send(client, "/inspect", capsule[:-5]).status_code == 422
    changed = bytearray(capsule)
    changed[-8] ^= 0x80
    assert send(client, "/inspect", bytes(changed)).status_code == 422
    assert send(client, "/inspect", b"made-up-header" + capsule).status_code == 422
    assert send(client, "/stage", capsule, acknowledgement="STAGE ENCRYPTED BACKUP",
                confirm_no_overwrite="false", expected_sha256=digest(capsule)).status_code == 422
    assert client.get(BASE + "/download", headers=H,
        params={"path": created["path"], "sha256": created["sha256"]}).status_code == 200


def test_new_workspace_can_authenticate_and_stage_without_replacing_documents(client, monkeypatch, tmp_path):
    created, capsule, sources = encrypted_backup(client)
    prior = sandbox.default_root()
    original_bytes = {(prior / x["path"]).as_posix(): (prior / x["path"]).read_bytes()
                      for x in sources}
    other = tmp_path / "independent-machine"
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(other))
    inspected = send(client, "/inspect", capsule)
    assert inspected.status_code == 200, inspected.text
    data = inspected.json()
    assert data["verified_against_encrypted_manifest"]
    assert data["trust_status"] == "quarantined_not_reinstated"
    assert data["file_count"] >= 4
    assert data["manual_review_required"]
    assert client.get(BASE + "/list", headers=H).json()["capsules"] == []
    stage = send(client, "/stage", capsule, expected_sha256=data["capsule_sha256"],
                 acknowledgement="STAGE ENCRYPTED BACKUP", confirm_no_overwrite="true")
    assert stage.status_code == 200, stage.text
    result = stage.json()
    assert result["restored_into_trusted_locations"] is False
    assert not result["original_files_modified"] and not result["published"]
    where = other / result["staging_path"]
    assert where.is_dir()
    manifest = json.loads((where / "staged-manifest.json").read_text())
    assert manifest["source_capsule_sha256"] == data["capsule_sha256"]
    assert not manifest["source_accuracy_verified"]
    for row in manifest["files"]:
        recovered = (where / row["member"]).read_bytes()
        assert digest(recovered) == row["sha256"]
    assert all(__import__("pathlib").Path(path).read_bytes() == body
               for path, body in original_bytes.items())
    assert not (other / "uploads").exists()
    assert not (other / "artifacts/research/comparisons").exists()


def test_inspect_and_stage_are_bound_to_same_selected_capsule_digest(client):
    _, payload, _ = encrypted_backup(client)
    expected = digest(payload)
    result = send(client, "/stage", payload, expected_sha256="f"*64,
                  acknowledgement="STAGE ENCRYPTED BACKUP",
                  confirm_no_overwrite="true")
    assert result.status_code == 409
    okay = send(client, "/stage", payload, expected_sha256=expected,
                acknowledgement="STAGE ENCRYPTED BACKUP",
                confirm_no_overwrite="true")
    assert okay.status_code == 200, okay.text


def test_user_approval_password_length_and_file_type_required(client):
    backup, _ = source_backup(client)
    base = {"path": backup["path"], "sha256": backup["sha256"],
            "passphrase": PASSWORD}
    assert client.post(BASE + "/create", headers=H, json=base).status_code == 422
    invalid = client.post(BASE + "/create", headers=H, json={
        **base, "passphrase": "short",
        "acknowledgement": "ENCRYPT PORTABLE BACKUP",
        "confirm_user_will_store_separately": True})
    assert invalid.status_code == 422
    assert send(client, "/inspect", b"invalid").status_code == 422
    no_file = client.post(BASE + "/inspect", headers=H,
                          data={"passphrase": PASSWORD})
    assert no_file.status_code in (415, 422)


def test_untrusted_archive_extra_member_rejected_after_valid_authenticated_decryption(client):
    _, capsule, _ = encrypted_backup(client)
    plain = research_portable._unseal(capsule, PASSWORD.encode())
    record_len = int.from_bytes(plain[:4], "big")
    original_record = plain[4:4 + record_len]
    original_zip = plain[4 + record_len:]
    new_zip = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original_zip)) as src:
        with zipfile.ZipFile(new_zip, "w", compression=zipfile.ZIP_STORED) as dest:
            for info in src.infolist():
                dest.writestr(info.filename, src.read(info))
            dest.writestr("../sneaky.txt", b"outside sandbox")
    record = json.loads(original_record)
    record["archive_sha256"] = digest(new_zip.getvalue())
    forged = research_portable._seal(research_portable._pack(
        json.dumps(record, separators=(",", ":")).encode(), new_zip.getvalue()
    ), PASSWORD.encode())
    assert send(client, "/inspect", forged).status_code == 422
    assert send(client, "/stage", forged, expected_sha256=digest(forged),
                acknowledgement="STAGE ENCRYPTED BACKUP",
                confirm_no_overwrite="true").status_code == 422
    assert not (sandbox.default_root() / "sneaky.txt").exists()


def test_portable_metadata_and_user_workspace_isolation(client, tmp_path, monkeypatch):
    created, _, _ = encrypted_backup(client)
    root = sandbox.default_root()
    file = root / created["path"]
    sidecar = file.with_suffix(".json")
    sidecar.write_bytes(sidecar.read_bytes() + b"bad")
    assert client.get(BASE + "/download", headers=H,
        params={"path": created["path"], "sha256": created["sha256"]}).status_code == 422
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "other-user"))
    assert client.get(BASE + "/list", headers=H).json()["capsules"] == []
    assert client.get(BASE + "/download", headers=H,
        params={"path": created["path"], "sha256": created["sha256"]}).status_code == 404


def test_import_size_limit_checks_before_decrypting(client, monkeypatch):
    monkeypatch.setattr(research_portable, "MAX_CAPSULE_BYTES", 32)
    assert send(client, "/inspect", b"A" * 65).status_code == 413
    assert send(client, "/inspect", b"A" * 24).status_code == 422
