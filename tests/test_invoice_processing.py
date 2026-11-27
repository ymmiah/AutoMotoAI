"""Phase 2 invoice processing: real generated fixtures, hard cases included.

Fixtures are built in-test with ReportLab/Pillow so the suite is deterministic
and needs no committed binary samples. Every fixture is a complete invoice
document, not a stub.
"""
from __future__ import annotations

import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from PIL import Image, ImageDraw
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as rl_canvas

from automoto import invoice_processing, sandbox, server
from automoto.hosted import path_allowed

API = "/api/invoices"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "workspace"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def _uploads(client_root) -> object:
    root = sandbox.default_root()
    folder = root / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _pdf_bytes(lines: list[str]) -> bytes:
    buffer = io.BytesIO()
    page = rl_canvas.Canvas(buffer, pagesize=A4)
    y = 800
    for text in lines:
        page.drawString(40, y, text)
        y -= 16
        if y < 60:
            page.showPage()
            y = 800
    page.save()
    return buffer.getvalue()


def _write(name: str, data: bytes) -> tuple[str, str]:
    folder = _uploads(None)
    path = folder / name
    path.write_bytes(data)
    return f"uploads/{name}", hashlib.sha256(data).hexdigest()


def _extract(client, name: str, data: bytes, **extra):
    path, sha = _write(name, data)
    body = {"path": path, "sha256": sha, **extra}
    return client.post(API + "/extract", headers=AUTH, json=body)


CLEAN = [
    "Acme Supplies Ltd",
    "Invoice No: INV-2026-001",
    "From: Acme Supplies Ltd",
    "Bill To: Beta Retail Ltd",
    "Invoice Date: 03 November 2026",
    "Due Date: 03 December 2026",
    "VAT No: GB123456789",
    "Widget A 2 x £19.99 £39.98",
    "Widget B 1 x £5.00 £5.00",
    "Subtotal: £44.98",
    "VAT 20%: £9.00",
    "VAT: £9.00",
    "Total: £53.98",
    "IBAN: GB29 NWBK 6016 1331 9268 19",
    "Sort Code: 60-16-13",
    "Payment Ref: INV-2026-001",
]


def test_authentication_and_hosted_scopes(client):
    bodies = {
        "/extract": {"path": "uploads/x.pdf", "sha256": "0" * 64},
        "/correct": {"id": "a" * 24, "field": "total", "value": "1.00",
                     "reason": "Correction reason here."},
        "/decide": {"id": "a" * 24, "action": "approve", "reason": "Decision reason here."},
        "/export": {"id": "a" * 24, "format": "json"},
    }
    for path, method in [("/list", "GET"), ("/detail", "GET"), ("/extract", "POST"),
                         ("/correct", "POST"), ("/decide", "POST"), ("/export", "POST")]:
        assert path_allowed(method, API + path), (method, path)
        if method == "GET":
            result = client.get(API + path, params={"id": "a" * 24}) \
                if path.endswith("/detail") else client.get(API + path)
        else:
            result = client.post(API + path, json=bodies[path])
        assert result.status_code == 403, (path, result.status_code)
    assert not path_allowed("POST", API + "/pay")
    assert not path_allowed("POST", API + "/send")
    assert not path_allowed("POST", API + "/post-to-erp")


def test_clean_invoice_extracts_with_evidence(client):
    result = _extract(client, "clean.pdf", _pdf_bytes(CLEAN))
    assert result.status_code == 200, result.text
    record = result.json()
    assert record["status"] == "ready", record["issues"]
    assert record["issues"] == []
    fields = record["fields"]
    assert fields["invoice_number"]["value"] == "INV-2026-001"
    assert fields["seller"]["value"] == "Acme Supplies Ltd"
    assert fields["buyer"]["value"] == "Beta Retail Ltd"
    assert fields["issue_date"]["value"] == "2026-11-03"
    assert fields["due_date"]["value"] == "2026-12-03"
    assert fields["currency"]["value"] == "GBP"
    assert fields["vat_number"]["value"] == "GB123456789"
    assert fields["vat_rate_percent"]["value"] == "20"
    assert fields["subtotal"]["value"] == "44.98"
    assert fields["tax_amount"]["value"] == "9.00"
    assert fields["total"]["value"] == "53.98"
    assert fields["bank"]["iban"]["value"] == "GB29NWBK60161331926819"
    assert fields["bank"]["sort_code"]["value"] == "60-16-13"
    # Every field carries its exact source location and confidence.
    total = fields["total"]
    assert total["confidence"] == 0.95
    assert total["source"]["page"] == 1
    assert "Total: £53.98" in total["source"]["text"]
    assert total["source"]["start"] >= 0
    assert len(record["lines"]) == 2
    assert record["lines"][0]["description"]["value"] == "Widget A"
    assert record["lines"][0]["quantity"]["value"] == "2"
    assert record["lines"][0]["line_total"]["value"] == "39.98"
    # The imported original was copied, never modified.
    root = sandbox.default_root()
    copy = root / record["source_copy"]
    assert copy.is_file()
    assert hashlib.sha256(copy.read_bytes()).hexdigest() == record["source_sha256"]


def test_multipage_invoice(client):
    lines = ["Acme Supplies Ltd", "Invoice No: INV-2026-060",
             "From: Acme Supplies Ltd", "Bill To: Beta Retail Ltd",
             "Invoice Date: 2026-11-03", "Due Date: 2026-12-03",
             "VAT No: GB123456789"]
    for i in range(1, 61):
        lines.append(f"Item {i:02d} 1 x £1.00 £1.00")
    lines += ["Subtotal: £60.00", "VAT 20%: £12.00", "VAT: £12.00", "Total: £72.00"]
    result = _extract(client, "multipage.pdf", _pdf_bytes(lines))
    assert result.status_code == 200, result.text
    record = result.json()
    assert record["status"] == "ready", record["issues"]
    assert len(record["lines"]) == 60
    assert record["fields"]["total"]["value"] == "72.00"
    # Evidence spans both pages.
    pages = {item["description"]["source"]["page"] for item in record["lines"]}
    assert pages == {1, 2}


def test_foreign_currency_decimal_comma_and_vat_policy(client):
    lines = ["Invoice No: INV-EU-77", "From: Berlin GmbH", "Bill To: Paris SARL",
             "Invoice Date: 03/11/2026", "Due Date: 03/12/2026",
             "Consulting 1 x €100,00 €100,00",
             "Subtotal: €100,00", "VAT 19%: €19,00", "VAT: €19,00",
             "Total: €119,00"]
    # Default policy (20/5/0) flags 19% as unrecognised, but arithmetic still checks.
    result = _extract(client, "eur.pdf", _pdf_bytes(lines))
    record = result.json()
    assert record["fields"]["currency"]["value"] == "EUR"
    assert record["fields"]["subtotal"]["value"] == "100.00"
    assert record["fields"]["total"]["value"] == "119.00"
    assert any(i["code"] == "vat_rate_unrecognised" for i in record["issues"])
    # With a configured 19% policy the same invoice is ready (new number, so
    # it is not a duplicate of the first extraction).
    lines2 = [line.replace("INV-EU-77", "INV-EU-78") for line in lines]
    result = _extract(client, "eur2.pdf", _pdf_bytes(lines2),
                      vat_policy={"standard": "20", "reduced": "5", "zero": "0",
                                  "german_standard": "19"})
    record = result.json()
    assert record["status"] == "ready", record["issues"]


def test_reduced_vat_five_percent(client):
    lines = ["Invoice No: INV-2026-005", "From: Acme Supplies Ltd",
             "Bill To: Beta Retail Ltd", "Invoice Date: 2026-11-03",
             "Due Date: 2026-12-03", "Heating repair 1 x £100.00 £100.00",
             "Subtotal: £100.00", "VAT 5%: £5.00", "VAT: £5.00", "Total: £105.00"]
    record = _extract(client, "vat5.pdf", _pdf_bytes(lines)).json()
    assert record["status"] == "ready", record["issues"]
    assert record["fields"]["vat_rate_percent"]["value"] == "5"


def test_mismatched_total_is_caught_and_correctable(client):
    bad = [line.replace("Total: £53.98", "Total: £99.99") for line in CLEAN]
    record = _extract(client, "mismatch.pdf", _pdf_bytes(bad)).json()
    assert record["status"] == "needs_review"
    assert any(i["code"] == "arithmetic_total" for i in record["issues"])
    # Approval is blocked while the error stands.
    blocked = client.post(API + "/decide", headers=AUTH, json={
        "id": record["id"], "action": "approve", "reason": "Looks fine to me."})
    assert blocked.status_code == 409
    # A manual correction is recorded, re-validated, and clears the error.
    fixed = client.post(API + "/correct", headers=AUTH, json={
        "id": record["id"], "field": "total", "value": "53.98",
        "reason": "Total on the paper invoice is 53.98; the scan read 99.99."})
    assert fixed.status_code == 200, fixed.text
    fixed = fixed.json()
    assert fixed["status"] == "ready", fixed["issues"]
    assert fixed["corrections"][0]["field"] == "total"
    assert fixed["corrections"][0]["previous"] == "99.99"
    assert fixed["corrections"][0]["new"] == "53.98"
    approved = client.post(API + "/decide", headers=AUTH, json={
        "id": record["id"], "action": "approve", "reason": "Corrected total verified."})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert "no payment" in approved.json()["effect"].lower()
    # A decided record cannot be corrected or decided again.
    assert client.post(API + "/correct", headers=AUTH, json={
        "id": record["id"], "field": "total", "value": "1.00",
        "reason": "Too late to change this."}).status_code == 409


def test_line_total_mismatch_is_caught(client):
    bad = [line.replace("Widget A 2 x £19.99 £39.98", "Widget A 2 x £19.99 £29.98")
           for line in CLEAN]
    record = _extract(client, "linemismatch.pdf", _pdf_bytes(bad)).json()
    assert any(i["code"] == "arithmetic_line_total" for i in record["issues"])
    assert record["status"] == "needs_review"


def test_duplicate_invoice_is_flagged(client):
    first = _extract(client, "dup-a.pdf", _pdf_bytes(CLEAN)).json()
    assert first["status"] == "ready"
    second = _extract(client, "dup-b.pdf", _pdf_bytes(CLEAN)).json()
    assert any(i["code"] == "duplicate_invoice" for i in second["issues"])
    assert second["status"] == "needs_review"


def test_missing_fields_are_never_invented(client):
    lines = ["Invoice No: INV-MISS-1", "Total: £10.00"]
    record = _extract(client, "missing.pdf", _pdf_bytes(lines)).json()
    assert record["status"] == "needs_review"
    codes = {i["code"] for i in record["issues"]}
    assert "missing_field" in codes
    assert record["fields"]["seller"]["value"] is None
    assert record["fields"]["seller"]["confidence"] == 0.0
    assert record["fields"]["issue_date"]["value"] is None
    # Currency is genuinely evidenced by the £ symbol, not invented.
    assert record["fields"]["currency"]["value"] == "GBP"
    assert record["fields"]["currency"]["confidence"] == 0.85


def test_non_invoice_document_and_corrupt_pdf(client):
    record = _extract(client, "letter.txt",
                      b"Hello world,\nThis is a letter about the weather.\nRegards,\nJo\n").json()
    assert record["status"] == "needs_review"
    assert record["fields"]["invoice_number"]["value"] is None
    assert record["lines"] == []
    assert any(i["code"] == "missing_field" for i in record["issues"])
    bad = _extract(client, "broken.pdf", b"%PDF-1.4 garbage not a real pdf")
    assert bad.status_code == 422


def test_scanned_image_needs_ocr_and_invents_nothing(client):
    image = Image.new("RGB", (900, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 20), "INVOICE INV-SCAN-1\nAcme Supplies Ltd\nTotal: £42.00", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    record = _extract(client, "scan.png", buffer.getvalue()).json()
    assert record["status"] == "needs_ocr"
    assert any(i["code"] == "needs_ocr" for i in record["issues"])
    assert record["fields"]["total"]["value"] is None
    assert record["fields"]["invoice_number"]["value"] is None
    assert record["lines"] == []
    # Deciding a needs-OCR record is refused.
    assert client.post(API + "/decide", headers=AUTH, json={
        "id": record["id"], "action": "approve",
        "reason": "Approve without reading it."}).status_code == 409


def test_review_queue_lists_needs_review_first(client):
    good = _extract(client, "q-good.pdf", _pdf_bytes(CLEAN)).json()
    bad = _extract(client, "q-bad.pdf", _pdf_bytes(
        [line.replace("Total: £53.98", "Total: £1.00") for line in CLEAN])).json()
    listing = client.get(API + "/list", headers=AUTH).json()
    assert listing["no_payment_actions"] is True
    queue = listing["review_queue"]
    assert {item["id"] for item in queue} == {bad["id"]}
    assert all(item["id"] != good["id"] for item in queue)


def test_exports_csv_xlsx_json_pdf(client):
    record = _extract(client, "exp.pdf", _pdf_bytes(CLEAN)).json()
    record_id = record["id"]
    exported = client.post(API + "/export", headers=AUTH,
                           json={"id": record_id, "format": "json"}).json()
    assert exported["format"] == "json"
    assert exported["paid"] is False and exported["sent"] is False
    root = sandbox.default_root()
    assert (root / exported["path"]).is_file()

    csv_result = client.post(API + "/export", headers=AUTH,
                             json={"id": record_id, "format": "csv"})
    assert csv_result.status_code == 200, csv_result.text
    csv_path = root / csv_result.json()["path"]
    assert "INV-2026-001" in csv_path.read_text(encoding="utf-8-sig")

    xlsx_result = client.post(API + "/export", headers=AUTH,
                              json={"id": record_id, "format": "xlsx"})
    assert xlsx_result.status_code == 200, xlsx_result.text
    book = load_workbook(str(root / xlsx_result.json()["path"]))
    assert book["Invoice"]["B2"].value == "Acme Supplies Ltd"
    assert "Evidence" in book.sheetnames and "Issues" in book.sheetnames

    pdf_result = client.post(API + "/export", headers=AUTH,
                             json={"id": record_id, "format": "pdf"})
    assert pdf_result.status_code == 200, pdf_result.text
    pdf_bytes = (root / pdf_result.json()["path"]).read_bytes()
    assert pdf_bytes.startswith(b"%PDF-")
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert "INV-2026-001" in (reader.pages[0].extract_text() or "")


def test_source_confinement_and_sha_checks(client):
    path, sha = _write("safe.pdf", _pdf_bytes(CLEAN))
    traversal = client.post(API + "/extract", headers=AUTH,
                            json={"path": "../secret.pdf", "sha256": sha})
    assert traversal.status_code == 403
    wrong_sha = client.post(API + "/extract", headers=AUTH,
                            json={"path": path, "sha256": "0" * 64})
    assert wrong_sha.status_code == 409
    missing = client.post(API + "/extract", headers=AUTH,
                          json={"path": "uploads/nope.pdf", "sha256": sha})
    assert missing.status_code == 404
    bad_ext = _write("note.exe", b"junk")
    assert client.post(API + "/extract", headers=AUTH,
                       json={"path": bad_ext[0], "sha256": bad_ext[1]}).status_code == 415


def test_xlsx_source_extracts(client):
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    for row in [["Invoice No:", "INV-XLSX-1"], ["From:", "Acme Supplies Ltd"],
                ["Bill To:", "Beta Retail Ltd"], ["Invoice Date:", "2026-11-03"],
                ["Due Date:", "2026-12-03"], ["Currency:", "GBP"],
                ["Widget A", "2", "19.99", "39.98"],
                ["Widget B", "1", "5.00", "5.00"],
                ["Subtotal:", "44.98"], ["VAT 20%:", "9.00"], ["VAT:", "9.00"],
                ["Total:", "53.98"]]:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    record = _extract(client, "sheet.xlsx", buffer.getvalue()).json()
    assert record["fields"]["invoice_number"]["value"] == "INV-XLSX-1"
    assert record["fields"]["total"]["value"] == "53.98"
    assert record["status"] == "ready", record["issues"]


def test_money_and_date_parsing_units():
    assert str(invoice_processing._parse_money("1,234.56")) == "1234.56"
    assert str(invoice_processing._parse_money("1.234,56")) == "1234.56"
    assert str(invoice_processing._parse_money("£1,234.56")) == "1234.56"
    assert str(invoice_processing._parse_money("100,00")) == "100.00"
    assert invoice_processing._parse_money("not money") is None
    assert invoice_processing._parse_date("03 November 2026") == "2026-11-03"
    assert invoice_processing._parse_date("2026-11-03") == "2026-11-03"
    assert invoice_processing._parse_date("03/11/2026") == "2026-11-03"
    assert invoice_processing._parse_date("tomorrow") is None
