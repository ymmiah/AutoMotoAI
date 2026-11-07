"""V3 spreadsheet editing/Excel fidelity: real OOXML output and safe import."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from automoto import sandbox, server

API = "/api/spreadsheets"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "v3-test-home"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def v3_book():
    return {
        "name": "Formatted operations",
        "calculation_mode": "literal",
        "sheets": [{
            "name": "Sales",
            "rows": [["Status", "Price"], ["Open", 12.5], ["Closed", 5]],
            "cell_styles": {
                "B2": {"bold": True, "italic": False, "align": "right",
                       "fill": "#DCE8F2", "color": "#203040", "number_format": "gbp"},
                "A100": {"bold": False, "italic": True, "align": "center",
                         "fill": "#FFFFFF", "color": "#1E293B", "number_format": "general"},
            },
            "freeze": "both",
            "filter_enabled": True,
            "column_widths": {"B": 25},
            "validations": [
                {"column": "A", "kind": "list", "options": ["Open", "Closed"],
                 "min_value": None, "max_value": None},
                {"column": "B", "kind": "decimal", "options": [],
                 "min_value": 0, "max_value": 1000},
            ],
        }],
    }


def test_v3_private_drafts_preserve_style_and_validation(client):
    original = v3_book()
    saved = client.post(API + "/save", headers=AUTH, json=original)
    assert saved.status_code == 200, saved.text
    imported = client.get(API + "/load", headers=AUTH, params={"path": saved.json()["path"]})
    assert imported.status_code == 200, imported.text
    assert imported.json()["workbook"] == original
    assert imported.json()["read_only"] is True


def test_real_xlsx_styles_freezes_filters_widths_and_validators(client):
    result = client.post(API + "/export", headers=AUTH, json={**v3_book(), "format": "xlsx"})
    assert result.status_code == 200, result.text
    wb = load_workbook(sandbox.default_root() / result.json()["path"], data_only=False, keep_links=False)
    ws = wb["Sales"]
    assert ws["B2"].value == 12.5
    assert ws["B2"].font.bold
    assert ws["B2"].alignment.horizontal == "right"
    assert ws["B2"].font.color.rgb[-6:] == "203040"
    assert ws["B2"].fill.fgColor.rgb[-6:] == "DCE8F2"
    assert "£" in ws["B2"].number_format
    assert ws["A100"].font.italic
    assert ws.freeze_panes == "B2"
    assert ws.auto_filter.ref == "A1:B3"
    assert ws.column_dimensions["B"].width == 25
    rules = list(ws.data_validations.dataValidation)
    assert len(rules) == 2
    assert {rule.type for rule in rules} == {"list", "decimal"}
    assert any(rule.type == "list" and "Open,Closed" in rule.formula1 for rule in rules)
    assert not wb._external_links
    wb.close()


def test_import_xlsx_extracts_styles_safely_and_warns_about_lost_features(client):
    data = client.post(API + "/export", headers=AUTH, json={**v3_book(), "format": "xlsx"})
    assert data.status_code == 200, data.text
    source = (sandbox.default_root() / data.json()["path"]).read_bytes()
    upload = sandbox.default_root() / "uploads" / "style-source.xlsx"
    upload.parent.mkdir(parents=True, exist_ok=True)
    upload.write_bytes(source)
    response = client.post(API + "/import", headers=AUTH, json={"path": "uploads/style-source.xlsx"})
    assert response.status_code == 200, response.text
    imported = response.json()
    sheet = imported["workbook"]["sheets"][0]
    assert sheet["rows"][1][1] == 12.5
    assert sheet["cell_styles"]["B2"]["bold"] is True
    assert sheet["cell_styles"]["B2"]["number_format"] == "gbp"
    assert imported["workbook"].get("calculation_mode") is None
    assert imported["original_unchanged"] is True
    assert any("not preserved" in warning for warning in imported["warnings"])
    assert upload.read_bytes() == source


@pytest.mark.parametrize("key,value", [
    ("freeze", "outside"),
    ("column_widths", {"A": 80000}),
    ("column_widths", {"ZZ": 20}),
    ("cell_styles", {"Q2": {"bold": True}}),
    ("cell_styles", {"A101": {"bold": True}}),
    ("cell_styles", {"A2": {"fill": "#G00000"}}),
    ("validations", [{"column": "A", "kind": "list", "options": ["=WEBSERVICE(1)"]}]),
    ("validations", [{"column": "A", "kind": "list", "options": ["hello,there"]}]),
    ("validations", [{"column": "A", "kind": "decimal", "min_value": 100, "max_value": 5}]),
])
def test_rejects_unsafe_or_invalid_metadata(client, key, value):
    book = v3_book()
    book["sheets"][0][key] = value
    answer = client.post(API + "/save", headers=AUTH, json=book)
    assert answer.status_code == 422, (key, answer.status_code, answer.text)


def test_validation_rejects_incorrect_values_or_formula_escape(client):
    book = v3_book()
    for value in ("Unapproved", "=IF(1,1,0)"):
        book["sheets"][0]["rows"][1][0] = value
        response = client.post(API + "/save", json=book, headers=AUTH)
        assert response.status_code == 422
    book = v3_book()
    for value in (True, 3.45, "oops", -1):
        book["sheets"][0]["rows"][1][1] = value
        if value == 3.45:
            book["sheets"][0]["validations"][1]["kind"] = "whole"
        response = client.post(API + "/save", json=book, headers=AUTH)
        assert response.status_code == 422, response.text


def test_filter_and_freeze_can_be_disabled_without_legacy_regressions(client):
    book = v3_book()
    sheet = book["sheets"][0]
    sheet["freeze"] = "none"
    sheet["filter_enabled"] = False
    exported = client.post(API + "/export", headers=AUTH, json={**book, "format": "xlsx"})
    assert exported.status_code == 200, exported.text
    wb = load_workbook(sandbox.default_root() / exported.json()["path"])
    ws = wb["Sales"]
    assert ws.freeze_panes is None
    assert ws.auto_filter.ref is None
    wb.close()


def test_legacy_sheet_remains_without_metadata(client):
    old = {"name": "V1-old", "sheets": [{"name": "Sheet1", "rows": [["label"], ["=1+1"]]}]}
    saved = client.post(API + "/save", json=old, headers=AUTH)
    assert saved.status_code == 200, saved.text
    loaded = client.get(API + "/load", headers=AUTH, params={"path": saved.json()["path"]})
    assert loaded.status_code == 200
    assert loaded.json()["workbook"] == old
