"""V5 real financial analysis and report tests; deliberately no auto-posted invoice data."""
from __future__ import annotations

import csv
import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from automoto import sandbox, server
from automoto.hosted import path_allowed

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
API = "/api/spreadsheets/finance"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "finance-workspace"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def entry(entry_id, date, kind, amount, status="actual", category="Other", description="Example cash item", reference=""):
    return {
        "entry_id": entry_id, "transaction_date": date, "kind": kind, "status": status,
        "category": category, "description": description, "reference": reference,
        "amount": amount,
    }


def book():
    return {
        "name": "Example cash activity", "currency": "GBP", "opening_balance": "100.00",
        "period_from": "2026-01-01", "period_to": "2026-03-31",
        "entries": [
            entry("before", "2025-12-22", "revenue", "20.00", category="Sales"),
            entry("receipt", "2026-01-12", "revenue", "100.12", category="Services"),
            entry("cost", "2026-01-14", "expense", "20.07", category="Software"),
            entry("capital", "2026-02-10", "capital_in", "50.00", category="Capital"),
            entry("drawing", "2026-02-11", "capital_out", "10.00", category="Capital"),
            entry("later", "2026-03-13", "expense", "5.01", category="Rent"),
            entry("planned", "2026-02-22", "revenue", "1000.00", status="planned", category="Sales"),
            entry("plannedcost", "2026-03-04", "expense", "3.00", status="planned", category="Rent"),
            entry("after", "2026-04-10", "revenue", "999.00", category="Sales"),
        ],
    }


def analyse(client, value=None):
    return client.post(API + "/analyse", headers=AUTH, json=value or book())


def test_unauthenticated_and_hosted_allowlist(client):
    assert path_allowed("GET", API + "/list")
    assert path_allowed("GET", API + "/load")
    for action in ("analyse", "save", "export"):
        assert path_allowed("POST", API + "/" + action)
        assert client.post(API + "/" + action, json={}).status_code == 403
    assert client.get(API + "/list").status_code == 403
    assert client.get(API + "/load", params={"path": "artifacts/spreadsheets/f-abcdefabcdef.finance.json"}).status_code == 403
    for action in ("transfer", "pay", "post-invoice", "delete", "connect-bank"):
        assert not path_allowed("POST", API + "/" + action)


def test_cash_basis_actual_only_and_owner_capital_excluded_from_surplus(client):
    response = analyse(client)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["opening_cash"] == "120.00"
    assert report["revenue"] == "100.12"
    assert report["expenses"] == "25.08"
    assert report["operating_surplus"] == "75.04"
    assert report["operating_margin_percent"] == "74.95"
    assert report["capital_in"] == "50.00"
    assert report["capital_out"] == "10.00"
    assert report["net_cash_movement"] == "115.04"
    assert report["closing_cash"] == "235.04"
    assert report["planned_revenue"] == "1000.00"
    assert report["planned_expenses"] == "3.00"
    assert report["entry_counts"] == {"actual": 5, "planned": 2}
    assert report["invoices_included"] is False
    assert report["bank_connected"] is False
    assert len(report["months"]) == 3
    assert report["months"][0]["cash_balance"] == "200.05"
    assert report["months"][1]["cash_balance"] == "240.05"
    assert report["months"][2]["cash_balance"] == "235.04"
    assert report["categories"] == [
        {"category": "Rent", "revenue": "0.00", "expenses": "5.01"},
        {"category": "Services", "revenue": "100.12", "expenses": "0.00"},
        {"category": "Software", "revenue": "0.00", "expenses": "20.07"},
    ]


def test_zero_revenue_margin_is_null_and_loss_is_negative(client):
    value = book()
    value["entries"] = [entry("rent", "2026-01-02", "expense", "150.00")]
    response = analyse(client, value)
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["operating_margin_percent"] is None
    assert summary["operating_surplus"] == "-150.00"
    assert summary["closing_cash"] == "-50.00", "negative closing cash must be shown, not clipped"
    csv_export = client.post(API + "/export", headers=AUTH,
                             json={**value, "format": "csv"})
    assert csv_export.status_code == 200, csv_export.text
    output = (sandbox.default_root() / csv_export.json()["path"]).read_text(encoding="utf-8-sig")
    rows = list(csv.reader(io.StringIO(output)))
    assert ["Operating cash surplus (not statutory profit)", "-150.00"] in rows
    assert ["Closing cash", "-50.00"] in rows



def test_planned_only_cannot_be_mistaken_for_real_revenue(client):
    value = book()
    value["entries"] = [
        entry("estimate", "2026-01-01", "revenue", "55000.00", status="planned"),
        entry("draftcost", "2026-02-01", "expense", "100.00", status="planned"),
    ]
    summary = analyse(client, value).json()
    assert summary["revenue"] == "0.00"
    assert summary["expenses"] == "0.00"
    assert summary["closing_cash"] == "100.00"
    assert summary["planned_revenue"] == "55000.00"
    assert summary["planned_expenses"] == "100.00"


def test_private_immutable_snapshots_and_isolation(client):
    saved = client.post(API + "/save", headers=AUTH, json=book())
    assert saved.status_code == 200, saved.text
    first = saved.json()["path"]
    assert first.endswith(".finance.json")
    disk = sandbox.default_root() / first
    initial = hashlib.sha256(disk.read_bytes()).hexdigest()
    assert saved.json()["immutable_snapshot"]
    collection = client.get(API + "/list", headers=AUTH).json()["snapshots"]
    assert any(entry["path"] == first for entry in collection)
    loaded = client.get(API + "/load", headers=AUTH, params={"path": first})
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["book"] == book()
    assert loaded.json()["read_only"]
    changed = book()
    changed["entries"][1]["amount"] = "88.00"
    newer = client.post(API + "/save", headers=AUTH, json=changed)
    assert newer.status_code == 200
    assert newer.json()["path"] != first
    assert hashlib.sha256(disk.read_bytes()).hexdigest() == initial
    for value in ("../../secrets", "uploads/data.csv", "artifacts/spreadsheets/../finance",
                  "artifacts/spreadsheets/invoice-1234.commercial.json",
                  "artifacts/spreadsheets/f-abcdefabcdef.finance.json/"):
        assert client.get(API + "/load", headers=AUTH, params={"path": value}).status_code == 403


def test_manual_report_does_not_automatically_read_draft_invoices(client):
    draft = {
        "kind": "quotation", "number": "DRAFT-Q-01", "issue_date": "2026-11-07",
        "due_date": "2026-12-07", "currency": "GBP", "review_state": "reviewed",
        "seller": {"name": "Example seller", "address": "UK"},
        "customer": {"name": "Example buyer", "address": "UK"},
        "brand": {"display_name": "Example", "accent": "#183153"},
        "lines": [{"description": "Future work", "quantity": "1", "unit_price": "500000.00"}]
    }
    commercial = client.post("/api/spreadsheets/commercial/save", headers=AUTH, json=draft)
    assert commercial.status_code == 200, commercial.text
    value = book()
    value["entries"] = []
    report = analyse(client, value)
    assert report.status_code == 200
    assert report.json()["revenue"] == "0.00"
    assert report.json()["invoices_included"] is False


def test_real_csv_and_pdf_export_and_formula_injection_escaping(client):
    value = book()
    value["entries"][1]["description"] = '=HYPERLINK("https://invalid.example","click")'
    value["entries"][1]["reference"] = "+WEBSERVICE(1)"
    csv_response = client.post(API + "/export", headers=AUTH, json={**value, "format": "csv"})
    assert csv_response.status_code == 200, csv_response.text
    csv_path = sandbox.default_root() / csv_response.json()["path"]
    content = csv_path.read_text(encoding="utf-8-sig")
    rows = list(csv.reader(io.StringIO(content)))
    assert any(cell.startswith("'=HYPERLINK") for row in rows for cell in row)
    assert any(cell.startswith("'+WEBSERVICE") for row in rows for cell in row)
    assert not any("999.00" in row for row in rows if row and row[0] == "2026-04-10")
    assert "Cash closing" in content or "Closing cash" in content
    pdf_response = client.post(API + "/export", headers=AUTH, json={**value, "format": "pdf"})
    assert pdf_response.status_code == 200, pdf_response.text
    pdf_path = sandbox.default_root() / pdf_response.json()["path"]
    assert pdf_path.read_bytes().startswith(b"%PDF-")
    pages = PdfReader(str(pdf_path)).pages
    text = "\n".join(page.extract_text() for page in pages)
    assert "FINANCIAL INTELLIGENCE" in text
    assert "235.04" in text
    assert "UNVERIFIED" in text
    assert "NOT AN AUDITED" in text
    assert "HYPERLINK" in text
    assert pdf_response.json()["verified"] is False


@pytest.mark.parametrize("field,value", [
    ("opening_balance", "-1"), ("opening_balance", "10.999"),
    ("currency", "BTC"), ("period_to", "2025-01-01"),
    ("period_to", "2034-12-31"), ("name", "=WEBSERVICE()"),
])
def test_financial_request_validation(client, field, value):
    item = book()
    item[field] = value
    response = analyse(client, item)
    # Report name is user content, escaped in exports; formula-like plain names are permitted.
    if field == "name":
        assert response.status_code == 200
    else:
        assert response.status_code == 422, (field, response.text)


@pytest.mark.parametrize("field,value", [
    ("status", "paid"), ("kind", "refund"), ("amount", "0"),
    ("amount", "-20"), ("amount", "0.001"), ("amount", "=2+2"),
    ("category", "Random"), ("entry_id", "../unsafe"), ("description", "\x00bad"),
])
def test_invalid_transaction_rejected(client, field, value):
    item = book()
    item["entries"][0][field] = value
    response = analyse(client, item)
    assert response.status_code == 422, (field, response.text)


def test_duplicate_ids_and_transaction_cap(client):
    item = book()
    item["entries"][1]["entry_id"] = item["entries"][0]["entry_id"]
    assert analyse(client, item).status_code == 422
    item = book()
    item["entries"] = [entry(f"line-{i}", "2026-01-01", "revenue", "1.00") for i in range(501)]
    assert analyse(client, item).status_code == 422


def test_read_only_analysis_has_no_filesystem_or_network_side_effects(client, monkeypatch):
    import urllib.request
    def deny(*args, **kwargs):
        raise AssertionError("Financial analysis cannot call any external service")
    monkeypatch.setattr(urllib.request, "urlopen", deny)
    root = sandbox.default_root()
    before = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in root.rglob("*") if p.is_file()}
    assert analyse(client).status_code == 200
    after = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in root.rglob("*") if p.is_file()}
    assert before == after
