"""V7 business workflow: authenticated snapshot reviews, role controls and audit."""
from __future__ import annotations

import hashlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from automoto import sandbox, server, business_workflows
from automoto.hosted import path_allowed

API = "/api/spreadsheets/workflows"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "workflows-home"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def seed(client):
    workbook = {"name": "Saved sales", "sheets": [
        {"name": "Data", "rows": [["Item", "Cost"], ["Example", 40]]}]}
    invoice = {
        "kind": "quotation", "review_state": "draft", "number": "Q-V7-01",
        "issue_date": "2026-11-07", "due_date": "2026-12-07",
        "seller": {"name": "Example Seller Ltd", "address": "Birmingham"},
        "customer": {"name": "Example Customer Ltd", "address": "London"},
        "brand": {"display_name": "Example Seller", "accent": "#183153"},
        "currency": "GBP",
        "lines": [{"description": "Service", "quantity": "1", "unit_price": "40.00"}],
    }
    finance = {"name": "Cash ledger", "currency": "GBP", "opening_balance": "0.00",
               "period_from": "2026-01-01", "period_to": "2026-12-31",
               "entries": []}
    responses = [
        client.post("/api/spreadsheets/save", headers=AUTH, json=workbook),
        client.post("/api/spreadsheets/commercial/save", headers=AUTH, json=invoice),
        client.post("/api/spreadsheets/finance/save", headers=AUTH, json=finance),
    ]
    for response in responses:
        assert response.status_code == 200, response.text
    files = {}
    for response, kind in zip(responses, ("sheet", "commercial", "finance")):
        path = response.json()["path"]
        files[kind] = {"path": path,
                       "sha256": hashlib.sha256((sandbox.default_root()/path).read_bytes()).hexdigest()}
    return files


def payload(files, primary="commercial", related="finance", purpose="cash_reconciliation_review"):
    return {
        "source_path": files[primary]["path"], "source_sha256": files[primary]["sha256"],
        "related_path": files[related]["path"], "related_sha256": files[related]["sha256"],
        "purpose": purpose,
        "note": "Check the relation between this quotation and the independently entered cash snapshot.",
        "confirm_review_only": True,
    }


def create(client, files, **overrides):
    body = {**payload(files), **overrides}
    return client.post(API + "/create", headers=AUTH, json=body)


def decide(client, record, action="approve", reason="Reviewed source evidence manually."):
    return client.post(API + "/decide", headers=AUTH, json={
        "workflow_id": record["id"], "expected_event_hash": record["last_event_hash"],
        "action": action, "reason": reason, "confirm_review_only": True,
    })


def test_authentication_and_hosted_route_policy(client):
    for endpoint in ("sources", "list", "detail", "verify"):
        assert path_allowed("GET", API + "/" + endpoint)
    for endpoint in ("create", "decide"):
        assert path_allowed("POST", API + "/" + endpoint)
    for endpoint in ("post", "pay", "issue", "email", "sync", "delete", "execute"):
        assert not path_allowed("POST", API + "/" + endpoint)
    assert client.get(API + "/sources").status_code == 403
    assert client.get(API + "/verify").status_code == 403
    assert client.post(API + "/create", json={
        "source_path": "artifacts/spreadsheets/x-000000000000.commercial.json",
        "related_path": "artifacts/spreadsheets/y-000000000000.finance.json",
        "source_sha256": "0"*64, "related_sha256": "0"*64,
        "purpose": "business_review", "note": "This is an unauthorised example.",
        "confirm_review_only": True
    }).status_code == 403
    assert not business_workflows._can_decide("user", "user", "user", "approve")
    assert not business_workflows._can_decide("user", "user", "user", "reject")
    assert not business_workflows._can_decide("other", "user", "owner", "cancel")
    assert business_workflows._can_decide("owner", "user", "owner", "cancel")
    assert business_workflows._can_decide("admin", "admin", "owner", "approve")


def test_sources_and_approval_are_review_only_and_hash_chained(client):
    files = seed(client)
    catalog = client.get(API + "/sources", headers=AUTH)
    assert catalog.status_code == 200, catalog.text
    found = {item["kind"]: item for item in catalog.json()["sources"]}
    assert set(found) == {"sheet", "commercial", "finance"}
    assert found["finance"]["sha256"] == files["finance"]["sha256"]
    before = {key: (sandbox.default_root()/item["path"]).read_bytes() for key,item in files.items()}
    request = create(client, files)
    assert request.status_code == 200, request.text
    record = request.json()
    assert record["status"] == "pending"
    assert not record["approved"] and len(record["events"]) == 1
    assert record["requires_explicit_decision"]
    assert record["requester"] == "local-owner"
    assert record["events"][0]["action"] == "requested"
    assert record["events"][0]["previous_hash"] == "0"*64
    assert len(record["last_event_hash"]) == 64
    assert client.get(API + "/verify", headers=AUTH).json()["event_count"] == 1

    decided = decide(client, record)
    assert decided.status_code == 200, decided.text
    output = decided.json()
    assert output["status"] == "approved"
    assert output["sources_modified"] is False
    assert output["financial_postings"] == 0
    assert output["sent"] is False and output["issued"] is False and output["paid"] is False
    loaded = client.get(API + "/detail", headers=AUTH, params={"workflow_id": record["id"]})
    assert loaded.status_code == 200
    assert loaded.json()["approved"]
    assert loaded.json()["events"][1]["action"] == "approved"
    assert loaded.json()["events"][1]["previous_hash"] == record["last_event_hash"]
    verification = client.get(API + "/verify", headers=AUTH).json()
    assert verification["valid"] and verification["event_count"] == 2
    assert verification["latest_event_hash"] == output["last_event_hash"]
    for key,item in files.items():
        assert (sandbox.default_root()/item["path"]).read_bytes() == before[key]
    listed = client.get(API + "/list", headers=AUTH)
    assert listed.status_code == 200
    assert listed.json()["permissions"]["role"] == "admin"
    assert listed.json()["workflows"][0]["status"] == "approved"


def test_reject_cancel_and_duplicate_decisions(client):
    files = seed(client)
    record = create(client, files).json()
    rejected = decide(client, record, action="reject", reason="Missing supporting evidence.")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert decide(client, record).status_code == 409
    other = create(client, files, purpose="business_review").json()
    cancelled = decide(client, other, action="cancel", reason="I need to revise the request.")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert decide(client, other, action="reject").status_code == 409
    assert client.get(API + "/verify", headers=AUTH).json()["event_count"] == 4


def test_stale_snapshot_cannot_be_approved_or_created(client):
    files = seed(client)
    request = create(client, files).json()
    invoice_file = sandbox.default_root()/files["commercial"]["path"]
    original = invoice_file.read_bytes()
    invoice_file.write_bytes(original+b" ")
    stale = decide(client, request)
    assert stale.status_code == 409, stale.text
    assert "changed" in stale.text
    assert client.get(API + "/detail", headers=AUTH,
                      params={"workflow_id": request["id"]}).json()["status"] == "pending"
    attempt = create(client, files)
    assert attempt.status_code == 409
    invoice_file.write_bytes(original)
    fresh = client.get(API + "/sources", headers=AUTH).json()["sources"]
    assert any(item["path"] == files["commercial"]["path"] for item in fresh)
    assert decide(client, request).status_code == 200


def test_bad_paths_self_links_cross_module_and_invalid_purpose(client):
    files = seed(client)
    assert create(client, files, related_path=files["commercial"]["path"],
                  related_sha256=files["commercial"]["sha256"]).status_code == 422
    assert create(client, files, related_path=files["sheet"]["path"],
                  related_sha256=files["sheet"]["sha256"]).status_code == 422  # cash review needs finance
    assert create(client, files, related_path="../../etc/passwd").status_code == 403
    assert create(client, files, source_path="uploads/source.csv").status_code == 403
    assert create(client, files, confirm_review_only=False).status_code == 422
    assert create(client, files, note="bad\x00actor").status_code == 422
    assert create(client, files, purpose="pay_customer").status_code == 422


def test_tampering_is_detected_and_blocks_new_decisions(client):
    files = seed(client)
    request = create(client, files).json()
    path = sandbox.default_root() / "artifacts/workflows/workflow-events-v7.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE events SET note=? WHERE workflow_id=?", ("Forged history", request["id"]))
    assert client.get(API + "/verify", headers=AUTH).status_code == 409
    assert client.get(API + "/list", headers=AUTH).status_code == 409
    assert decide(client, request).status_code == 409
    assert create(client, files).status_code == 409


def test_symlink_escape_rejected_before_source_read(client, tmp_path):
    files = seed(client)
    target = tmp_path / "external.json"
    target.write_text('{"schema":"finance-v5","data":{}}')
    symlink = sandbox.default_root() / "artifacts/spreadsheets" / \
        "fake-000000000000.finance.json"
    try:
        symlink.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable in this environment")
    request = create(client, files, related_path="artifacts/spreadsheets/"+symlink.name,
                     related_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    assert request.status_code == 404


def test_schema_invalid_source_rejected(client):
    files = seed(client)
    path = sandbox.default_root() / files["finance"]["path"]
    path.write_text('{"schema":"spreadsheet-v1","data":{}}')
    corrupt = create(client, files, related_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    assert corrupt.status_code == 422


def test_database_root_is_private_and_not_cross_tenant(client, tmp_path, monkeypatch):
    files = seed(client)
    create(client, files)
    root_a = sandbox.default_root()
    db_path = root_a / "artifacts/workflows/workflow-events-v7.sqlite3"
    assert db_path.is_file()
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "different-user-home"))
    result = client.get(API + "/list", headers=AUTH)
    assert result.status_code == 200
    assert result.json()["workflows"] == []
    assert not (sandbox.default_root() / files["finance"]["path"]).exists()
    assert db_path.is_file()
