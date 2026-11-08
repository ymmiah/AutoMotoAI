"""V8 offline release assurance, private archive integrity and copy-only recovery."""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient

from automoto import sandbox, server, spreadsheet_release
from automoto.hosted import path_allowed

API = "/api/spreadsheets/release"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "release-workspace"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def seed(client):
    workbook = {"name": "V8 sheet", "sheets": [
        {"name": "Sales", "rows": [["Item", "Price"], ["Example", 24.5]]}]}
    commercial = {
        "kind": "quotation", "number": "Q-V8-001", "issue_date": "2026-11-07",
        "due_date": "2026-11-29", "currency": "GBP", "review_state": "draft",
        "seller": {"name": "Seller Ltd", "address": "Birmingham"},
        "customer": {"name": "Customer Ltd", "address": "London"},
        "brand": {"display_name": "Seller Studio", "accent": "#183153"},
        "lines": [{"description": "Local review service", "quantity": "1",
                   "unit_price": "24.50"}],
    }
    finance = {
        "name": "November cash", "currency": "GBP", "opening_balance": "10.00",
        "period_from": "2026-01-01", "period_to": "2026-12-31",
        "entries": [{"entry_id": "cash-01", "transaction_date": "2026-11-07",
                     "kind": "revenue", "status": "planned", "category": "Sales",
                     "description": "Forecast only", "reference": "", "amount": "24.50"}],
    }
    contact = {"name": "Customer Ltd", "address": "London"}
    invoice = {
        "number": "V8-INV-01", "seller": "Seller Ltd, Birmingham",
        "customer": "Customer Ltd, London", "issue_date": "2026-11-07",
        "due_date": "2026-11-21", "currency": "GBP", "tax_rate": "0",
        "lines": [{"description": "Draft service", "quantity": "1", "unit_price": "24.50"}],
    }
    paths = {}
    for name, endpoint, body in (
        ("sheet", "/api/spreadsheets/save", workbook),
        ("commercial", "/api/spreadsheets/commercial/save", commercial),
        ("finance", "/api/spreadsheets/finance/save", finance),
        ("contact", "/api/spreadsheets/commercial/customer/save", contact),
        ("invoice", "/api/spreadsheets/invoice/save", invoice),
    ):
        response = client.post(endpoint, json=body, headers=AUTH)
        assert response.status_code == 200, response.text
        paths[name] = response.json()["path"]
    return paths


def recovered_source_hashes(files):
    root = sandbox.default_root()
    return {kind: hashlib.sha256((root / path).read_bytes()).hexdigest()
            for kind, path in files.items()}


def make_workflow(client, files):
    hashes = recovered_source_hashes(files)
    response = client.post("/api/spreadsheets/workflows/create", headers=AUTH, json={
        "source_path": files["commercial"], "source_sha256": hashes["commercial"],
        "related_path": files["finance"], "related_sha256": hashes["finance"],
        "purpose": "cash_reconciliation_review",
        "note": "Audit this private quotation against the manual cash snapshot.",
        "confirm_review_only": True,
    })
    assert response.status_code == 200, response.text
    return response.json()


def create(client):
    response = client.post(API + "/create", headers=AUTH, json={})
    assert response.status_code == 200, response.text
    return response.json()


def body(record):
    return {"path": record["path"], "sha256": record["sha256"]}


def test_authenticated_readiness_routes_and_no_publication(client):
    for name in ("readiness", "list"):
        assert path_allowed("GET", API + "/" + name)
        assert client.get(API + "/" + name).status_code == 403
    for name in ("create", "verify", "restore"):
        assert path_allowed("POST", API + "/" + name)
        assert client.post(API + "/" + name, headers=None, json={}).status_code in (403, 422)
    for action in ("publish", "delete", "overwrite", "sync-cloud", "send", "pay", "store-submit"):
        assert not path_allowed("POST", API + "/" + action)
    readiness = client.get(API + "/readiness", headers=AUTH)
    assert readiness.status_code == 200, readiness.text
    data = readiness.json()
    assert data["release_ready"] is False
    assert data["store_publication_authorised"] is False
    assert data["development_complete"] is False
    assert data["checks"]["backup_available"] == "missing"
    assert data["checks"]["accessibility_manual"] == "pending"


def test_backup_verification_restores_new_copies_only_with_workflow_evidence(client):
    files = seed(client)
    review = make_workflow(client, files)
    root = sandbox.default_root()
    original_bytes = {key: (root / path).read_bytes() for key, path in files.items()}
    active_db = root / "artifacts/workflows/workflow-events-v7.sqlite3"
    db_before = active_db.read_bytes()

    archive = create(client)
    assert archive["records"] == 5
    assert archive["workflow_history_included"] is True
    assert archive["source_files_changed"] is False
    assert not archive["encrypted"]
    source = root / archive["path"]
    assert source.is_file()
    with zipfile.ZipFile(source) as zip_file:
        names = zip_file.namelist()
        assert "manifest.json" in names
        assert "workflow-audit.sqlite3" in names
        assert len([s for s in names if s.startswith("records/")]) == 5
    verification = client.post(API + "/verify", headers=AUTH, json=body(archive))
    assert verification.status_code == 200, verification.text
    assert verification.json()["valid"] is True

    rejected = client.post(API + "/restore", headers=AUTH, json={
        **body(archive), "acknowledgement": "RESTORE COPIES", "confirm_no_overwrite": False,
    })
    assert rejected.status_code == 422
    restored = client.post(API + "/restore", headers=AUTH, json={
        **body(archive), "acknowledgement": "RESTORE COPIES", "confirm_no_overwrite": True,
    })
    assert restored.status_code == 200, restored.text
    result = restored.json()
    assert result["records"] == 5
    assert result["original_records_overwritten"] is False
    assert result["live_workflow_history_replaced"] is False
    assert result["financial_postings"] == 0
    assert result["invoices_issued"] is False
    assert result["store_publication_authorised"] is False
    assert (root / result["archived_workflow_evidence"]).read_bytes() != b""
    assert result["archived_workflow_evidence"] != "artifacts/workflows/workflow-events-v7.sqlite3"
    assert active_db.read_bytes() == db_before
    assert client.get("/api/spreadsheets/workflows/detail", headers=AUTH,
                      params={"workflow_id": review["id"]}).status_code == 200

    for kind, relative in files.items():
        assert (root / relative).read_bytes() == original_bytes[kind]
    for entry in result["restored"]:
        assert entry["original"] in files.values()
        restored_file = root / entry["recovered"]
        assert restored_file.is_file()
        assert restored_file.read_bytes() == (root / entry["original"]).read_bytes()
        assert entry["original"] != entry["recovered"]
    assert client.get(API + "/readiness", headers=AUTH).json()["release_ready"] is False


def test_archive_creation_and_inspection_make_no_unapproved_network_calls(client, monkeypatch):
    import urllib.request
    seed(client)

    def blocked(*args, **kwargs):
        raise AssertionError("V8 recovery must not call external services")

    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    first = create(client)
    response = client.post(API + "/verify", headers=AUTH, json=body(first))
    assert response.status_code == 200, response.text
    listing = client.get(API + "/list", headers=AUTH)
    assert listing.status_code == 200
    assert listing.json()["backups"][0]["sha256"] == first["sha256"]
    assert listing.json()["encrypted"] is False
    assert listing.json()["records_unchanged"]


def test_modification_invalidates_expected_archive_digest(client):
    seed(client)
    archive = create(client)
    filename = sandbox.default_root() / archive["path"]
    filename.write_bytes(filename.read_bytes() + b"MODIFIED")
    response = client.post(API + "/verify", headers=AUTH, json=body(archive))
    assert response.status_code == 409, response.text
    fresh = hashlib.sha256(filename.read_bytes()).hexdigest()
    changed = client.post(API + "/verify", headers=AUTH,
                          json={**body(archive), "sha256": fresh})
    # Extra ZIP trailer isn't necessarily unsafe; original trusted digest prevents
    # an unnoticed switch. The user must not trust attacker-supplied replacement hash.
    assert changed.status_code in (200, 422)


def test_unsafe_zip_entries_rejected_even_with_attacker_matching_digest(client):
    folder = spreadsheet_release._directory(create=True)
    source = folder / ("recovery-" + "a" * 24 + ".zip")
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps({
            "schema": "automoto-recovery-v8", "created_at": "2026-11-08T12:00:00Z",
            "records": [], "workflow": None,
        }))
        archive.writestr("../../escape.json", "{}")
    response = client.post(API + "/verify", json={
        "path": "artifacts/recovery/" + source.name,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }, headers=AUTH)
    assert response.status_code == 422


def test_duplicate_zip_entries_rejected(client):
    folder = spreadsheet_release._directory(create=True)
    source = folder / ("recovery-" + "b" * 24 + ".zip")
    manifest = json.dumps({"schema": "automoto-recovery-v8",
                           "created_at": "2026-11-08", "records": [], "workflow": None})
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("manifest.json", manifest)
        with pytest.warns(UserWarning):
            archive.writestr("manifest.json", manifest)
    response = client.post(API + "/verify", headers=AUTH, json={
        "path": "artifacts/recovery/" + source.name,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    })
    assert response.status_code == 422


def test_zip_bomb_size_limit_before_decompression(client):
    folder = spreadsheet_release._directory(create=True)
    source = folder / ("recovery-" + "c" * 24 + ".zip")
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", "x" * (spreadsheet_release.MAX_RAW + 1))
    response = client.post(API + "/verify", headers=AUTH, json={
        "path": "artifacts/recovery/" + source.name,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    })
    assert response.status_code == 422


def test_corrupt_active_workflow_audit_blocks_backup(client):
    files = seed(client)
    review = make_workflow(client, files)
    database = sandbox.default_root() / "artifacts/workflows/workflow-events-v7.sqlite3"
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE events SET note=? WHERE workflow_id=?",
                     ("Changed audit event", review["id"]))
    response = client.post(API + "/create", headers=AUTH, json={})
    assert response.status_code == 409, response.text
    readiness = client.get(API + "/readiness", headers=AUTH)
    assert readiness.status_code == 200
    assert readiness.json()["checks"]["workflow_audit"] == "failed"


def test_invalid_legacy_record_blocks_backup_without_modifying_source(client):
    files = seed(client)
    root = sandbox.default_root()
    commercial = root / files["commercial"]
    before = commercial.read_bytes()
    data = json.loads(before)
    data["data"]["currency"] = "NOT_A_CURRENCY"
    commercial.write_text(json.dumps(data), encoding="utf-8")
    tampered = commercial.read_bytes()
    result = client.post(API + "/create", headers=AUTH, json={})
    assert result.status_code == 422, result.text
    assert commercial.read_bytes() == tampered


def test_symlink_records_and_backup_paths_are_not_followed(client, tmp_path):
    seed(client)
    root = sandbox.default_root()
    victim = tmp_path / "outside.sheet.json"
    victim.write_text('{"schema":"spreadsheet-v1","data":{}}', encoding="utf-8")
    link = root / "artifacts/spreadsheets/bad-aaaaaaaaaaaa.sheet.json"
    try:
        link.symlink_to(victim)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are not supported.")
    response = client.post(API + "/create", headers=AUTH, json={})
    assert response.status_code == 403
    link.unlink()
    archived = create(client)
    alias = root / "artifacts/recovery/recovery-ffffffffffffffffffffffff.zip"
    alias.symlink_to(root / archived["path"])
    result = client.post(API + "/verify", headers=AUTH, json={
        "path": "artifacts/recovery/" + alias.name,
        "sha256": archived["sha256"],
    })
    assert result.status_code == 403


def test_workspace_isolation_for_recovery_bundles(client, monkeypatch, tmp_path):
    seed(client)
    first = create(client)
    original = sandbox.default_root() / first["path"]
    assert original.is_file()
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "separate-workspace"))
    other = client.get(API + "/list", headers=AUTH)
    assert other.status_code == 200
    assert other.json()["backups"] == []
    assert client.post(API + "/verify", headers=AUTH, json=body(first)).status_code == 403
    assert original.is_file()
