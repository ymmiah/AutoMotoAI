"""V2 formula engine acceptance: bounded local execution, safety and compatibility."""
from __future__ import annotations

import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from automoto import sandbox, server, spreadsheet_formulas
from automoto.hosted import path_allowed

API = "/api/spreadsheets"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "workspace"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def make_book(rows, *, mode="formulas"):
    return {"name": "Calculated 2026", "calculation_mode": mode,
            "sheets": [{"name": "Costs", "rows": rows}]}


def calculate(client, rows, *, mode="formulas"):
    return client.post(API + "/calculate", headers=AUTH,
                       json=make_book(rows, mode=mode))


def by_cell(result):
    return {item["cell"]: item for item in result["results"]}


def test_requires_auth_and_hosted_allowlist(client):
    assert client.post(API + "/calculate", json=make_book([[1, "=A1+2"]])).status_code == 403
    assert path_allowed("POST", API + "/calculate")
    assert not path_allowed("DELETE", API + "/calculate")


def test_arithmetic_precedence_references_and_dependencies(client):
    result = calculate(client, [
        [5, 3, "=A1+B1*2", "=C1/2"],
        ["=SUM(A1:B1)", "=IF(C1>10,99,7)", "=A1^2", "=-A1"],
    ])
    assert result.status_code == 200, result.text
    values = by_cell(result.json())
    assert values["C1"]["value"] == "11"
    assert values["D1"]["value"] == "5.5"
    assert values["A2"]["value"] == "8"
    assert values["B2"]["value"] == "99"
    assert values["C2"]["value"] == "25"
    assert values["D2"]["value"] == "-5"
    assert values["C1"]["dependencies"] == ["A1", "B1"]
    assert result.json()["errors"] == []


def test_aggregates_blank_and_text_values(client):
    result = calculate(client, [
        [2, "ignored", None, 8],
        ["=SUM(A1:D1)", "=AVERAGE(A1:D1)", "=MIN(A1:D1)", "=MAX(A1:D1)"],
        ["=COUNT(A1:D1)", "=COUNTA(A1:D1)", "=IF(A1=2,\"yes\",\"no\")", "=A1>1"],
    ])
    assert result.status_code == 200, result.text
    v = by_cell(result.json())
    assert [v[x]["value"] for x in ("A2", "B2", "C2", "D2")] == ["10", "5", "2", "8"]
    assert [v[x]["value"] for x in ("A3", "B3", "C3", "D3")] == ["2", "3", "yes", True]


def test_if_only_evaluates_selected_branch(client):
    result = calculate(client, [["=IF(1=1,42,1/0)", "=IF(FALSE,1/0,8)"]])
    assert result.status_code == 200, result.text
    assert by_cell(result.json())["A1"]["value"] == "42"
    assert by_cell(result.json())["B1"]["value"] == "8"
    assert result.json()["errors"] == []


def test_cycle_invalid_ref_and_divide_by_zero_are_visible_errors(client):
    result = calculate(client, [["=B1", "=A1", "=1/0", "=Z99", "=SUM(A1:A2)"]])
    assert result.status_code == 200, result.text
    v = by_cell(result.json())
    assert v["A1"]["error"] == "#CYCLE!"
    assert v["B1"]["error"] == "#CYCLE!"
    assert v["C1"]["error"] == "#DIV/0!"
    assert v["D1"]["error"] == "#REF!"
    assert v["E1"]["error"] == "#CYCLE!"
    assert len(result.json()["errors"]) == 5


def test_injection_and_unsupported_features_never_evaluate(client):
    hostile = [
        '=__import__("os").system("id")', '=WEBSERVICE("https://attacker.invalid")',
        "=[1]Sheet1!A1", "=SUM(A1;B1)", '=HYPERLINK("https://example.invalid","click")',
        "=A1:A1000", "=1+abc",
    ]
    root = sandbox.default_root()
    before = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    result = calculate(client, [hostile])
    assert result.status_code == 200, result.text
    assert len(result.json()["errors"]) == len(hostile)
    assert all(row["error"] in ("#NAME?", "#PARSE!", "#REF!", "#VALUE!")
               for row in result.json()["results"])
    # Errors and formula previews never create or modify files.
    after = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    assert after == before


def test_formula_limit_and_overlong_formulas(client):
    overlong = "=" + "1+" * 160 + "1"
    response = calculate(client, [[overlong]])
    assert response.status_code == 422
    rows = [["=1"] * 16 for _ in range(32)]
    response = calculate(client, rows)
    assert response.status_code == 422
    assert "500" in response.text


def test_legacy_literal_mode_preserves_v1_semantics_and_manual_opt_in(client):
    old = {"name": "Legacy", "sheets": [{"name": "Sheet1", "rows": [[7, "=A1*2"]]}]}
    saved = client.post(API + "/save", json=old, headers=AUTH)
    assert saved.status_code == 200, saved.text
    loaded = client.get(API + "/load", headers=AUTH, params={"path": saved.json()["path"]})
    assert loaded.json()["workbook"] == old
    report = client.post(API + "/calculate", headers=AUTH, json=old).json()
    assert report["mode"] == "literal" and report["results"] == []
    opt_in = {**old, "calculation_mode": "formulas"}
    report = client.post(API + "/calculate", headers=AUTH, json=opt_in).json()
    assert by_cell(report)["B1"]["value"] == "14"
    reloaded = client.get(API + "/load", headers=AUTH, params={"path": saved.json()["path"]})
    assert reloaded.json()["workbook"] == old


def test_xlsx_export_safe_intentional_formula_and_csv_calculated_values(client):
    book = make_book([["Product", "Price", "Qty", "Line"],
                      ["Service", 19.99, 2, "=B2*C2"],
                      ["Total", None, None, "=SUM(D2:D2)"]])
    export = client.post(API + "/export", headers=AUTH, json={**book, "format": "xlsx"})
    assert export.status_code == 200, export.text
    result = export.json()
    assert result["formulas_evaluated"] is True
    assert result["needs_spreadsheet_recalculation"] is True
    original = sandbox.default_root() / result["path"]
    wb = load_workbook(original, data_only=False, keep_links=False)
    assert wb.active["D2"].value == "=B2*C2"
    assert wb.active["D2"].data_type == "f"
    assert wb.active["D3"].data_type == "f"
    assert not wb._external_links
    wb.close()
    trimmed = make_book([["Value", "Times two"], [5, "=A2*2"]])
    csv_export = client.post(API + "/export", headers=AUTH, json={**trimmed, "format": "csv"})
    assert csv_export.status_code == 200, csv_export.text
    output = (sandbox.default_root() / csv_export.json()["path"]).read_text(encoding="utf-8-sig")
    assert "5,10" in output
    assert "=A2*2" not in output


def test_export_with_errors_rejected_without_creating_files(client):
    book = make_book([[2, "=1/0"]])
    for ext in ("xlsx", "csv"):
        response = client.post(API + "/export", headers=AUTH, json={**book, "format": ext})
        assert response.status_code == 422, response.text
        assert "formula errors" in response.text.lower()
    folder = sandbox.default_root() / "artifacts" / "spreadsheets"
    assert not folder.exists() or not list(folder.iterdir())


def test_offline_no_external_side_effects_and_unchanged_source(client, monkeypatch):
    book = make_book([[3, "=A1+4", "=IF(1,5,0)"]])
    root = sandbox.default_root()
    before = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    def disallow(*args, **kwargs):
        raise AssertionError("Formula evaluation must never use external services")
    monkeypatch.setattr("urllib.request.urlopen", disallow)
    answer = client.post(API + "/calculate", headers=AUTH, json=book)
    assert answer.status_code == 200, answer.text
    after = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    assert before == after


def test_parser_budget_and_safe_unsupported_sheet_refs(client):
    result = calculate(client, [["=SUM(A1:A100)", "=IF(2>1,3,4)", "=Other!A1"]])
    assert result.status_code == 200
    assert by_cell(result.json())["C1"]["error"] == "#PARSE!"
    assert by_cell(result.json())["A1"]["error"] == "#CYCLE!"
    assert by_cell(result.json())["B1"]["value"] == "3"
