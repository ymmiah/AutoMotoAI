"""V4 commercial studio: real local PDFs, exact money, private contacts, security."""
from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from automoto import sandbox, server
from automoto.hosted import path_allowed

API = "/api/spreadsheets/commercial"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "workspace"))
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def party(name="Example Ltd"):
    return {"name": name, "address": "15 Test Road\nBirmingham B1 1AA",
            "email": "info@example.test", "phone": "0121 555 0000",
            "registration": "GB123456789"}


def document(kind="invoice"):
    return {
        "kind": kind, "review_state": "draft", "number": "DRAFT-2026-001",
        "issue_date": "2026-11-07", "due_date": "2026-11-21",
        "currency": "GBP", "seller": party("Seller Test Ltd"),
        "customer": party("Customer Test Ltd"),
        "brand": {"display_name": "TEST STUDIO", "accent": "#183153", "template": "executive"},
        "lines": [
            {"description": "Website maintenance & support", "quantity": "2",
             "unit_price": "19.99", "discount_percent": "10"},
            {"description": "Monthly hosting", "quantity": "1",
             "unit_price": "5.00", "discount_percent": "0"},
        ],
        "discount_percent": "5", "tax_percent": "20", "tax_label": "VAT",
        "notes": "Thank you for reviewing this private draft.",
        "terms": "No bank transfer should be made on this draft.",
    }


def test_authentication_and_hosted_scopes(client):
    body = document()
    for path, method in [
        ("/list", "GET"), ("/preview", "POST"), ("/save", "POST"),
        ("/load", "GET"), ("/export", "POST"),
        ("/customer/save", "POST"), ("/customer/load", "GET"),
    ]:
        assert path_allowed(method, API + path), (method, path)
        if method == "GET":
            result = client.get(API + path, params={"path": "artifacts/spreadsheets/safe-abcdefabcdef.commercial.json"}) if path.endswith("/load") else client.get(API + path)
        else:
            result = client.post(API + path, json=body)
        assert result.status_code == 403, (path, result.status_code)
    assert not path_allowed("POST", API + "/pay")
    assert not path_allowed("POST", API + "/send")
    assert not path_allowed("DELETE", API + "/save")


def test_precise_rounding_with_line_and_order_discounts(client):
    response = client.post(API + "/preview", json=document(), headers=AUTH)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["lines"][0]["gross"] == "39.98"
    assert data["lines"][0]["discount"] == "4.00"
    assert data["lines"][0]["net"] == "35.98"
    assert data["subtotal"] == "44.98"
    assert data["line_discounts"] == "4.00"
    assert data["document_discount"] == "2.05"
    assert data["taxable"] == "38.93"
    assert data["tax"] == "7.79"
    assert data["total"] == "46.72"
    assert data["draft_only"] and not data["sent"] and not data["paid"] and not data["issued"]


@pytest.mark.parametrize("kind", ["invoice", "quotation"])
def test_branded_pdf_is_genuine_accessible_multipage_and_never_issued(client, kind):
    body = document(kind)
    body["review_state"] = "reviewed"
    body["brand"]["template"] = "minimal" if kind == "quotation" else "executive"
    body["lines"] = body["lines"] * 20  # exercise 40 lines / multiple pages
    body["notes"] = "Please check customer information and tax treatment. " * 12
    response = client.post(API + "/export", json=body, headers=AUTH)
    assert response.status_code == 200, response.text
    record = response.json()
    assert record["draft_only"] and not record["issued"] and not record["paid"] and not record["sent"]
    assert record["format"] == "pdf"
    path = sandbox.default_root() / record["path"]
    before = path.read_bytes()
    assert before.startswith(b"%PDF-")
    pages = PdfReader(str(path)).pages
    assert len(pages) >= 2
    page_texts = [page.extract_text() for page in pages]
    text = "\n".join(page_texts)
    assert "DRAFT" in text
    assert "TEST STUDIO" in text
    assert body["number"] in text
    assert "Website maintenance" in text
    assert "VAT (20%)" in text
    for page_text in page_texts:
        assert "DRAFT ONLY - NOT ISSUED" in page_text
    second = client.post(API + "/export", json=body, headers=AUTH)
    assert second.status_code == 200, second.text
    assert second.json()["path"] != record["path"], "Exports must create fresh files."
    assert path.read_bytes() == before


def test_quotation_dates_and_labels_are_not_invoices(client):
    body = document("quotation")
    result = client.post(API + "/export", headers=AUTH, json=body)
    assert result.status_code == 200, result.text
    text = "\n".join(page.extract_text() for page in PdfReader(
        str(sandbox.default_root() / result.json()["path"])).pages)
    assert "DRAFT QUOTATION" in text
    assert "Valid until" in text
    assert "PREPARED FOR" in text


def test_sanitises_untrusted_document_text_for_pdf(client):
    body = document()
    body["number"] = "='unsafe' && <script>alert(1)</script>"
    body["lines"][0]["description"] = "<b>Not bold</b> & <script>ignore()</script>"
    body["terms"] = "<img src='https://example.invalid/tracker'>"
    response = client.post(API + "/export", json=body, headers=AUTH)
    assert response.status_code == 200, response.text
    output = sandbox.default_root() / response.json()["path"]
    text = "\n".join(page.extract_text() for page in PdfReader(str(output)).pages)
    assert "Not bold" in text
    assert "script" in text
    assert "DRAFT ONLY - NOT ISSUED" in text


def test_documents_are_create_only_and_customer_contacts_are_private(client):
    source = document()
    saved = client.post(API + "/save", json=source, headers=AUTH)
    assert saved.status_code == 200, saved.text
    path = saved.json()["path"]
    assert path.endswith(".commercial.json")
    original = sandbox.default_root() / path
    old_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    found = client.get(API + "/list", headers=AUTH)
    assert found.status_code == 200
    assert any(item["path"] == path for item in found.json()["documents"])
    retrieved = client.get(API + "/load", params={"path": path}, headers=AUTH)
    assert retrieved.status_code == 200
    assert retrieved.json()["document"] == source
    edited = document()
    edited["lines"][0]["unit_price"] = "99.00"
    newer = client.post(API + "/save", json=edited, headers=AUTH)
    assert newer.status_code == 200
    assert newer.json()["path"] != path
    assert hashlib.sha256(original.read_bytes()).hexdigest() == old_hash

    contact = client.post(API + "/customer/save", json=party("New customer"), headers=AUTH)
    assert contact.status_code == 200, contact.text
    contact_path = contact.json()["path"]
    assert contact_path.endswith(".contact.json")
    loaded = client.get(API + "/customer/load", params={"path": contact_path}, headers=AUTH)
    assert loaded.status_code == 200
    assert loaded.json()["customer"]["name"] == "New customer"
    assert contact_path in [item["path"] for item in client.get(API + "/list", headers=AUTH).json()["customers"]]
    assert client.get(API + "/load", params={"path": contact_path}, headers=AUTH).status_code == 403
    assert client.get(API + "/customer/load", params={"path": path}, headers=AUTH).status_code == 403


@pytest.mark.parametrize("bad", [
    "../private", "../../secrets", "uploads/test.pdf", "artifacts/spreadsheets/foo.commercial.json",
    "artifacts/spreadsheets/../foo-abcdefabcdef.commercial.json",
])
def test_record_paths_are_confined(client, bad):
    assert client.get(API + "/load", params={"path": bad}, headers=AUTH).status_code in (403, 404)


@pytest.mark.parametrize("field,value", [
    ("tax_percent", "101"), ("tax_percent", "-2"), ("discount_percent", "100.001"),
    ("discount_percent", "=99"), ("due_date", "2026-01-01"),
    ("number", "\x00hello"), ("number", " "),
    ("kind", "credit_note"), ("review_state", "paid"),
])
def test_document_validation_rejects_invalid_input(client, field, value):
    body = document()
    body[field] = value
    response = client.post(API + "/preview", headers=AUTH, json=body)
    assert response.status_code == 422, (field, response.text)


def test_line_amount_and_brand_safety(client):
    for patch in [
        {"quantity": "0"}, {"unit_price": "9.999"},
        {"discount_percent": "110"}, {"description": "\x01evil"}, {"unit_price": "=1+1"},
    ]:
        body = document()
        body["lines"][0].update(patch)
        result = client.post(API + "/preview", headers=AUTH, json=body)
        assert result.status_code == 422, (patch, result.text)
    for accent in ("#FFFFFF", "#eeeeee", "blue", "#12345G"):
        body = document()
        body["brand"]["accent"] = accent
        assert client.post(API + "/preview", headers=AUTH, json=body).status_code == 422


def test_customer_email_and_extra_fields_rejected(client):
    body = document()
    body["customer"]["email"] = "not an email"
    assert client.post(API + "/preview", headers=AUTH, json=body).status_code == 422
    body = document()
    body["external_payment_id"] = "ATTACKER"
    assert client.post(API + "/save", headers=AUTH, json=body).status_code == 422


def test_no_background_email_or_payment_side_effects(client, monkeypatch):
    import urllib.request

    def forbidden(*args, **kwargs):
        raise AssertionError("Commercial preview must not call external services.")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    root = sandbox.default_root()
    before = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in root.rglob("*") if p.is_file()}
    result = client.post(API + "/preview", headers=AUTH, json=document())
    assert result.status_code == 200, result.text
    after = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in root.rglob("*") if p.is_file()}
    assert after == before
