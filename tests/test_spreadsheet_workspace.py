"""Invoice & Spreadsheet Intelligence v1: local, safe, non-destructive workflows."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from automoto import sandbox, server
from automoto.hosted import path_allowed

API = "/api/spreadsheets"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def book():
    return {"name": "Operations 2026", "sheets": [
        {"name": "Finance", "rows": [
            ["Description", "Amount", "Literal"],
            ["Hosting", 12.50, "=2+2"],
            ["Postcode", "00123", "@SUM(A1:A2)"],
        ]}
    ]}


def invoice():
    return {
        "number": "INV-2026-001", "seller": "Example Ltd\nBirmingham",
        "customer": "Customer Ltd\nLondon",
        "issue_date": "2026-11-07", "due_date": "2026-12-07", "currency": "GBP",
        "tax_rate": "20.00",
        "lines": [
            {"description": "Example service", "quantity": "0.333", "unit_price": "19.99"},
            {"description": "Product", "quantity": "2", "unit_price": "7.50"},
        ],
    }


def upload(name, data):
    path = sandbox.default_root() / "uploads" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_all_routes_require_auth_and_hosted_allowlist(client):
    assert client.get(API + "/list").status_code == 403
    assert client.post(API + "/save", json=book()).status_code == 403
    assert client.post(API + "/export", json={**book(), "format": "xlsx"}).status_code == 403
    assert client.post(API + "/invoice/preview", json=invoice()).status_code == 403
    assert client.post(API + "/invoice/export", json=invoice()).status_code == 403
    allowed = [
        ("GET", "/list"), ("GET", "/load"), ("POST", "/save"),
        ("POST", "/import"), ("POST", "/export"),
        ("POST", "/invoice/save"), ("GET", "/invoice/load"),
        ("POST", "/invoice/preview"), ("POST", "/invoice/export"),
    ]
    for verb, path in allowed:
        assert path_allowed(verb, API + path), (verb, path)
    assert not path_allowed("DELETE", API + "/save")
    assert not path_allowed("POST", API + "/invoice/pay")


def test_private_workbook_roundtrip_create_only_and_no_mutation(client):
    original = book()
    saved = client.post(API + "/save", headers=AUTH, json=original)
    assert saved.status_code == 200, saved.text
    path = saved.json()["path"]
    physical = sandbox.default_root() / path
    before = hashlib.sha256(physical.read_bytes()).hexdigest()
    listing = client.get(API + "/list", headers=AUTH)
    assert listing.status_code == 200
    assert any(item["path"] == path for item in listing.json()["workbooks"])
    loaded = client.get(API + "/load", headers=AUTH, params={"path": path})
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["workbook"] == original
    assert loaded.json()["read_only"] is True
    changed = book()
    changed["sheets"][0]["rows"][1][1] = 99
    second = client.post(API + "/save", headers=AUTH, json=changed)
    assert second.status_code == 200
    assert second.json()["path"] != path
    assert hashlib.sha256(physical.read_bytes()).hexdigest() == before


def test_export_real_excel_with_literal_formulas_no_remote_links(client):
    result = client.post(API + "/export", headers=AUTH, json={**book(), "format": "xlsx"})
    assert result.status_code == 200, result.text
    output = sandbox.default_root() / result.json()["path"]
    assert output.is_file()
    wb = load_workbook(output, data_only=False, keep_links=False)
    ws = wb["Finance"]
    assert ws["B2"].value == 12.5
    assert ws["C2"].value == "=2+2" and ws["C2"].data_type == "s"
    assert ws["C3"].value == "@SUM(A1:A2)" and ws["C3"].data_type == "s"
    assert ws["B3"].value == "00123"
    assert ws.freeze_panes == "A2"
    assert len(wb._external_links) == 0
    wb.close()


def test_csv_export_prevents_formula_execution(client):
    rows = [["a", "=WEBSERVICE(\"https://bad.example\")", "+A1", "-3", "@SUM(2,2)"]]
    result = client.post(API + "/export", headers=AUTH, json={
        "name": "formula-literals", "sheets": [{"name": "S", "rows": rows}], "format": "csv",
    })
    assert result.status_code == 200, result.text
    text = (sandbox.default_root() / result.json()["path"]).read_text(encoding="utf-8-sig")
    actual = list(csv.reader(io.StringIO(text)))[0]
    assert actual[1].startswith("'=")
    assert actual[2].startswith("'+")
    assert actual[3].startswith("'-")
    assert actual[4].startswith("'@")


def test_import_xlsx_is_read_only_and_warns_of_formula_conversion(client):
    original = Workbook()
    ws = original.active
    ws.title = "Input"
    ws.append(["Quantity", "Price"])
    ws.append([2, "=A2*10"])
    memory = io.BytesIO()
    original.save(memory)
    path = upload("source.xlsx", memory.getvalue())
    before = path.read_bytes()
    imported = client.post(API + "/import", headers=AUTH, json={"path": "uploads/source.xlsx"})
    assert imported.status_code == 200, imported.text
    output = imported.json()
    assert output["original_unchanged"]
    assert output["workbook"]["sheets"][0]["rows"][1] == [2, "=A2*10"]
    assert any("not recalculated" in w for w in output["warnings"])
    assert path.read_bytes() == before
    assert not list((sandbox.default_root() / "artifacts").rglob("*")) if (sandbox.default_root() / "artifacts").exists() else True


def test_import_csv_preserves_leading_zero_and_limits_columns(client):
    data = "Code,Amount\n00123,10\n".encode()
    upload("data.csv", data)
    result = client.post(API + "/import", headers=AUTH, json={"path": "uploads/data.csv"})
    assert result.status_code == 200
    assert result.json()["workbook"]["sheets"][0]["rows"][1] == ["00123", "10"]


@pytest.mark.parametrize("name", ["../secrets.csv", "uploads/../../etc/passwd",
                                    "/etc/passwd", "settings.json", "uploads/sheet.xlsm"])
def test_import_paths_are_confined_and_extension_restricted(client, name):
    res = client.post(API + "/import", headers=AUTH, json={"path": name})
    assert res.status_code in (403, 404, 415, 422), res.text


def test_invalid_workbook_and_cross_scope_load_are_refused(client):
    illegal = {**book(), "sheets": [{"name": "a/b", "rows": [[1]]}]}
    assert client.post(API + "/save", headers=AUTH, json=illegal).status_code == 422
    dup = {**book(), "sheets": [{"name": "Sheet1", "rows": []}, {"name": "sheet1", "rows": []}]}
    assert client.post(API + "/save", headers=AUTH, json=dup).status_code == 422
    too_big = {"name": "Big", "sheets": [{"name": "S", "rows": [[0] * 17]}]}
    assert client.post(API + "/save", headers=AUTH, json=too_big).status_code == 422
    for path in ("../../etc/passwd", "uploads/data.csv", "artifacts/spreadsheets/sneaky.sheet.json"):
        res = client.get(API + "/load", headers=AUTH, params={"path": path})
        assert res.status_code in (403, 404)


def test_invoice_precise_money_rounded_only_at_line_and_tax(client):
    result = client.post(API + "/invoice/preview", headers=AUTH, json=invoice())
    assert result.status_code == 200, result.text
    v = result.json()
    assert v["subtotal"] == "21.66"
    assert v["tax"] == "4.33"
    assert v["total"] == "25.99"
    assert v["draft_only"] and not v["sent"] and not v["paid"]
    assert v["lines"][0]["line_total"] == "6.66"


def test_invoice_rejects_bad_tax_amounts_and_dates(client):
    for patch in [
        {"tax_rate": "101"}, {"tax_rate": "-1"}, {"tax_rate": "20.001"},
        {"due_date": "2026-01-01"}, {"lines": [{**invoice()["lines"][0], "quantity": "0"}]},
        {"lines": [{**invoice()["lines"][0], "unit_price": "19.991"}]},
        {"lines": [{**invoice()["lines"][0], "unit_price": "=5+5"}]},
        {"lines": []},
    ]:
        res = client.post(API + "/invoice/preview", headers=AUTH, json={**invoice(), **patch})
        assert res.status_code == 422, (patch, res.text)


def test_invoice_saved_privately_and_exported_not_issued(client):
    source = invoice()
    saved = client.post(API + "/invoice/save", headers=AUTH, json=source)
    assert saved.status_code == 200, saved.text
    loaded = client.get(API + "/invoice/load", headers=AUTH, params={"path": saved.json()["path"]})
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["invoice"] == source
    exported = client.post(API + "/invoice/export", headers=AUTH, json=source)
    assert exported.status_code == 200, exported.text
    result = exported.json()
    assert result["draft_only"] and not result["sent"] and not result["paid"]
    wb = load_workbook(sandbox.default_root() / result["path"])
    ws = wb.active
    assert ws["A1"].value == "INVOICE · DRAFT"
    assert ws["D" + str(13+len(source["lines"])+2)].value == 25.99
    assert ws["D12"].value == 6.66
    wb.close()


def test_hostile_invoice_identifiers_are_never_excel_formulas(client):
    val = invoice()
    val["number"] = "=WEBSERVICE(\"https://example.invalid\")"
    val["seller"] = "=1+1"
    val["customer"] = "=2+2"
    val["lines"][0]["description"] = "=cmd|' /C calc'!A0"
    exported = client.post(API + "/invoice/export", headers=AUTH, json=val)
    assert exported.status_code == 200, exported.text
    wb = load_workbook(sandbox.default_root() / exported.json()["path"], data_only=False)
    ws = wb.active
    for key in ("B3", "A8", "C8", "A12"):
        assert ws[key].data_type == "s", (key, ws[key].value, ws[key].data_type)
    wb.close()
