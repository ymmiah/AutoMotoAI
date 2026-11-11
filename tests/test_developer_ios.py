"""iPhone studio actions: registry, wizard, draft listing, and a fake Apple."""

from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from automoto import developer_ios, hosted, planner, sandbox, server, studio_registry
from automoto import tools as tools_mod
from automoto.developer_ios_studio_tools import ios_create, ios_publish
from automoto.tools import ToolContext

BASE = "/api/developer/studio/ios"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
CTX = ToolContext()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOMOTO_IOS_TOOLCHAIN", "fake")
    monkeypatch.setenv("AUTOMOTO_IOS_ALLOW_TEST_DOUBLE", "1")
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.delenv("AUTOMOTO_OFFLINE", raising=False)
    monkeypatch.delenv("AUTOMOTO_DESKTOP_PACKAGE", raising=False)
    sandbox.default_root().mkdir(parents=True, exist_ok=True)
    yield TestClient(server.app)
    for name in developer_ios.SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)


def _pem(tmp_path: Path) -> Path:
    key = ec.generate_private_key(ec.SECP256R1())
    blob = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    folder = tmp_path / "data" / "secrets"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "asc.p8"
    path.write_bytes(blob)
    path.chmod(0o600)
    return path


def _apple(bundle_ok=True):
    calls = []

    def http(method, url, headers, body):
        calls.append((method, url, headers, body))
        host = url.split("/")[2]
        if method != "PUT" and host != "api.appstoreconnect.apple.com":
            raise AssertionError(host)
        if method == "PUT":
            assert host.endswith(".apple.com")
            assert "Authorization" not in headers
            return 200, {}, {}
        if url.endswith("/v1/apps?filter[bundleId]=app.local.tap-counter") or "filter[bundleId]=" in url:
            if not bundle_ok:
                return 200, {}, {"data": []}
            return 200, {}, {"data": [{"id": "app_1", "type": "apps"}]}
        if url.endswith("/v1/buildUploads") and method == "POST":
            return 201, {}, {"data": {"id": "up_1", "type": "buildUploads"}}
        if url.endswith("/v1/buildUploadFiles") and method == "POST":
            size = json.loads(body)["data"]["attributes"]["fileSize"]
            return 201, {}, {"data": {"id": "file_1", "type": "buildUploadFiles", "attributes": {
                "uploadOperations": [{
                    "url": "https://uploads.apple.com/part", "offset": 0, "length": size,
                    "requestHeaders": [{"name": "Content-Type", "value": "application/octet-stream"}],
                }],
            }}}
        if "/v1/buildUploadFiles/" in url and method == "PATCH":
            return 200, {}, {"data": {"id": "file_1"}}
        if url.endswith("/v1/appStoreVersions"):
            return 201, {}, {"data": {"id": "ver_1", "type": "appStoreVersions"}}
        if url.endswith("/v1/appStoreVersionLocalizations"):
            sent = json.loads(body)["data"]["attributes"]
            assert sent["description"] == "Counts taps."
            return 201, {}, {"data": {"id": "loc_1"}}
        if url.endswith("/v1/reviewSubmissions") and method == "POST":
            return 201, {}, {"data": {"id": "rev_1", "type": "reviewSubmissions"}}
        if url.endswith("/v1/reviewSubmissionItems"):
            return 201, {}, {"data": {"id": "item_1"}}
        if url.endswith("/v1/reviewSubmissions/rev_1") and method == "PATCH":
            assert json.loads(body)["data"]["attributes"]["submitted"] is True
            return 200, {}, {"data": {"id": "rev_1", "attributes": {"submitted": True}}}
        raise AssertionError(method + " " + url)

    return calls, http


def test_registry_picks_up_ios_actions_and_hides_them_when_it_should(monkeypatch):
    monkeypatch.delenv("AUTOMOTO_OFFLINE", raising=False)
    studio_registry.reset()
    ids = {spec.id for spec in studio_registry.load_studios()}
    assert "developer-ios" in ids
    tools = tools_mod.build()
    assert tools["ios_wizard"].level == "safe"
    assert tools["ios_create"].level == "risky"
    assert tools["ios_publish"].level == "risky"
    assert tools["ios_listing"].level == "risky"
    assert "developer-ios" in planner.classify("please make an iphone app that counts taps")
    assert planner.human_step("ios_build", {}) == "Building the iPhone app"
    hosted_names = set(hosted.hosted_tools())
    assert "ios_wizard" not in hosted_names and "ios_publish" not in hosted_names
    monkeypatch.setenv("AUTOMOTO_OFFLINE", "1")
    studio_registry.reset()
    offline = tools_mod.build()
    assert "ios_publish" not in offline and "ios_create" in offline
    quiet = tools_mod.build(local_apps=False)
    assert "ios_build" not in quiet and "ios_wizard" in quiet
    studio_registry.reset()


def test_msix_and_windows_without_wsl_say_why(monkeypatch):
    monkeypatch.setattr(developer_ios.platform, "system", lambda: "Windows")
    monkeypatch.delenv("AUTOMOTO_IOS_TOOLCHAIN", raising=False)
    monkeypatch.setenv("AUTOMOTO_DESKTOP_PACKAGE", "msix")
    monkeypatch.setattr(developer_ios.shutil, "which", lambda name: None)
    message = developer_ios.deployment_message()
    assert message["code"] == "msix" and "Microsoft Store" in message["message"]
    monkeypatch.setenv("AUTOMOTO_DESKTOP_PACKAGE", "")
    message = developer_ios.deployment_message()
    assert message["code"] == "wsl" and "WSL" in message["message"]


def test_wizard_create_listing_and_refuse_until_the_button(client, tmp_path, caplog):
    wizard = client.get(BASE + "/wizard", headers=AUTH)
    assert wizard.status_code == 200, wizard.text
    assert any("Xcode" in step["text"] for step in wizard.json()["steps"])
    assert client.get(BASE + "/wizard").status_code == 403

    created = json.loads(ios_create(CTX, prompt="tap counter for kids"))
    project = created["project"]
    assert "tap-counter" in project
    assert "Package.swift" in created["files"]
    assert "struct " not in created["summary"]
    source = Path(project, "Sources").rglob("*.swift")
    assert any(path.is_file() for path in source)

    key = _pem(tmp_path)
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    stored = client.post(BASE + "/secrets", headers=AUTH, json={
        "name": "AUTOMOTO_ASC_KEY_PATH", "value": str(key),
    })
    assert stored.status_code == 200, stored.text
    assert "BEGIN" not in stored.text
    assert client.post(BASE + "/secrets", headers=AUTH, json={
        "name": "AUTOMOTO_ASC_KEY_ID", "value": "KEYID123",
    }).status_code == 200
    assert client.post(BASE + "/secrets", headers=AUTH, json={
        "name": "AUTOMOTO_ASC_ISSUER_ID", "value": "issuer-1",
    }).status_code == 200
    leaked = client.post(BASE + "/secrets", headers=AUTH, json={
        "name": "AUTOMOTO_ASC_KEY_ID", "value": "-----BEGIN PRIVATE KEY-----\nnope",
    })
    assert leaked.status_code == 409
    env_text = (tmp_path / "data" / ".env").read_text(encoding="utf-8")
    assert "KEYID123" in env_text and "BEGIN PRIVATE KEY" not in env_text

    listing = client.post(BASE + "/listing", headers=AUTH, json={
        "project": project, "name": "Tap Counter", "description": "Counts taps.",
        "privacy": "The person said the app stores nothing.",
    })
    assert listing.status_code == 200, listing.text
    sha = listing.json()["listing_sha256"]
    assert listing.json()["listing"]["screenshots_acknowledged"] is False
    shown = client.get(BASE + "/listing", headers=AUTH, params={"project": project})
    assert shown.status_code == 200 and shown.json()["listing_sha256"] == sha
    with pytest.raises(tools_mod.ToolFailed, match="Send to Apple"):
        ios_publish(CTX, project, sha)


def test_button_then_fake_apple_and_a_changed_page_cancels_it(client, tmp_path, caplog, monkeypatch):
    created = json.loads(ios_create(CTX, prompt="tap counter"))
    project = created["project"]
    key = _pem(tmp_path)
    for name, value in (
        ("AUTOMOTO_ASC_KEY_PATH", str(key)),
        ("AUTOMOTO_ASC_KEY_ID", "KEYID123"),
        ("AUTOMOTO_ASC_ISSUER_ID", "issuer-1"),
    ):
        assert client.post(BASE + "/secrets", headers=AUTH, json={"name": name, "value": value}).status_code == 200
    listing = client.post(BASE + "/listing", headers=AUTH, json={
        "project": project, "name": "Tap Counter", "description": "Counts taps.",
        "privacy": "Stores nothing, as the person wrote.",
    })
    sha = listing.json()["listing_sha256"]
    early = client.post(BASE + "/submit", headers=AUTH, json={"project": project, "listing_sha256": sha})
    assert early.status_code == 409

    agent = studio_registry.studio_request("POST")
    with pytest.raises(Exception):
        developer_ios.approve_listing(agent, developer_ios.ApproveIn.model_validate({
            "project": project, "confirmed": True, "screenshots_acknowledged": True, "listing_sha256": sha,
        }))

    calls, http = _apple()
    monkeypatch.setattr(developer_ios, "_HTTP", http)
    approved = client.post(BASE + "/approve", headers={**AUTH, "X-Automoto-Ios-Approval": "1"}, json={
        "project": project, "confirmed": True, "screenshots_acknowledged": True, "listing_sha256": sha,
    })
    assert approved.status_code == 200, approved.text
    caplog.clear()
    with caplog.at_level("DEBUG"):
        sent = client.post(BASE + "/submit", headers=AUTH, json={"project": project, "listing_sha256": sha})
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert body["submitted"] is True and body["apple_signature"] is False and body["test_double"] is True
    methods = [(method, url.split("api.appstoreconnect.apple.com")[-1] if "appstoreconnect" in url else url)
               for method, url, _headers, _body in calls]
    assert methods[0][0] == "GET"
    assert ("PATCH", "/v1/reviewSubmissions/rev_1") in [(m, u if u.startswith("/") else u) for m, u in methods]
    assert any(url.startswith("https://uploads.apple.com/") for _m, url, _h, _b in calls)
    pem = key.read_text(encoding="utf-8")
    assert pem not in caplog.text and pem not in sent.text
    again = client.post(BASE + "/submit", headers=AUTH, json={"project": project, "listing_sha256": sha})
    assert again.status_code == 409

    changed = client.post(BASE + "/listing", headers=AUTH, json={
        "project": project, "name": "Tap Counter", "description": "Counts taps differently.",
        "privacy": "Stores nothing, as the person wrote.",
    })
    assert changed.json()["listing_sha256"] != sha


def test_missing_app_record_stops_before_upload(client, tmp_path, monkeypatch):
    created = json.loads(ios_create(CTX, prompt="tap counter"))
    project = created["project"]
    key = _pem(tmp_path)
    for name, value in (
        ("AUTOMOTO_ASC_KEY_PATH", str(key)),
        ("AUTOMOTO_ASC_KEY_ID", "KEYID123"),
        ("AUTOMOTO_ASC_ISSUER_ID", "issuer-1"),
    ):
        client.post(BASE + "/secrets", headers=AUTH, json={"name": name, "value": value})
    listing = client.post(BASE + "/listing", headers=AUTH, json={
        "project": project, "name": "Tap Counter", "description": "Counts taps.",
        "privacy": "Nothing stored.",
    })
    sha = listing.json()["listing_sha256"]
    client.post(BASE + "/approve", headers={**AUTH, "X-Automoto-Ios-Approval": "1"}, json={
        "project": project, "confirmed": True, "screenshots_acknowledged": True, "listing_sha256": sha,
    })
    calls, http = _apple(bundle_ok=False)
    monkeypatch.setattr(developer_ios, "_HTTP", http)
    sent = client.post(BASE + "/submit", headers=AUTH, json={"project": project, "listing_sha256": sha})
    assert sent.status_code == 200, sent.text
    assert sent.json()["stopped"] is True and sent.json()["submitted"] is False
    assert [method for method, *_rest in calls] == ["GET"]


def test_zip_project_and_unpublished_artifact_and_bad_anisette(client, tmp_path, monkeypatch):
    archive = sandbox.default_root() / "incoming.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Hello/Package.swift", "// swift-tools-version: 6.0\n")
        zf.writestr("../escape.txt", "nope")
    bad = client.post(BASE + "/create", headers=AUTH, json={"zip_path": "incoming.zip", "prompt": ""})
    assert bad.status_code == 409
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Hello/Package.swift", "// swift-tools-version: 6.0\n")
        zf.writestr("Hello/.env", "SECRET=1")
    assert client.post(BASE + "/create", headers=AUTH, json={"zip_path": "incoming.zip"}).status_code == 409
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Hello/Package.swift", "// swift-tools-version: 6.0\n")
    good = client.post(BASE + "/create", headers=AUTH, json={"zip_path": "incoming.zip", "prompt": "hello phone"})
    assert good.status_code == 200, good.text
    assert (Path(good.json()["project"]) / "Hello" / "Package.swift").is_file()

    with pytest.raises(Exception, match="not published"):
        developer_ios.fetch_artifact("darwin-tools-aarch64", tmp_path / "tool.tar.gz")

    monkeypatch.setenv("AUTOMOTO_ANISETTE_URL", "https://mac-ani.jkcoxson.com")
    with pytest.raises(Exception, match="not used"):
        developer_ios.anisette_url()
    monkeypatch.setenv("AUTOMOTO_ANISETTE_URL", "https://ani.example.com")
    with pytest.raises(Exception, match="this computer"):
        developer_ios.anisette_url()

    argv = developer_ios.sign_argv("automoto-ios", "app.ipa", "cert.pem", "key.p8", windows=True)
    assert argv[:2] == ["wsl", "-e"]
    joined = " ".join(argv)
    assert "BEGIN" not in joined and "key.p8" in joined


def test_token_aud_and_checksum_mismatch(tmp_path, monkeypatch):
    key = _pem(tmp_path)
    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOMOTO_ASC_KEY_PATH", str(key))
    monkeypatch.setenv("AUTOMOTO_ASC_KEY_ID", "KEYID123")
    monkeypatch.setenv("AUTOMOTO_ASC_ISSUER_ID", "issuer-1")
    token = developer_ios.apple_token()
    import base64
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload))
    assert claims["aud"] == "appstoreconnect-v1" and claims["iss"] == "issuer-1"
    assert key.read_text(encoding="utf-8") not in token

    monkeypatch.setenv("AUTOMOTO_IOS_ARTIFACT_BASE", "https://github.com/ymmiah/AutoMotoAI/releases/download/ios-sdk-support")
    lock = developer_ios._lockfile()
    lock["artifacts"]["darwin-tools-aarch64"]["sha256"] = "a" * 64

    def opener(url):
        assert url.startswith("https://github.com/ymmiah/AutoMotoAI/")
        assert "xtool-org" not in url
        return b"not-the-file"
    monkeypatch.setattr(developer_ios, "_lockfile", lambda: lock)
    with pytest.raises(Exception, match="checksum"):
        developer_ios.fetch_artifact("darwin-tools-aarch64", tmp_path / "tool.tar.gz", opener=opener)


def test_publish_without_the_button_is_a_tool_error(client):
    created = json.loads(ios_create(CTX, prompt="tap counter"))
    listing = client.post(BASE + "/listing", headers=AUTH, json={
        "project": created["project"], "name": "Tap", "description": "Counts.", "privacy": "Nothing.",
    })
    with pytest.raises(tools_mod.ToolFailed, match="Send to Apple"):
        ios_publish(CTX, created["project"], listing.json()["listing_sha256"])
