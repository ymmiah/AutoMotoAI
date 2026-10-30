"""v5.6 one account everywhere: app sign-in with revocable device tokens, the app window session,
My devices / Admin revocation, CORS for the app origins and HTTPS-only tokens."""

import re
import time

import pytest
from fastapi.testclient import TestClient

from automoto import accounts, hosted, server
from automoto.providers import REGISTRY

PW = "correct-horse-77"
HTTPS = "https://testserver"
APP = "http://tauri.localhost"  # Tauri 2's page origin on Windows


@pytest.fixture(autouse=True)
def hosted_env(monkeypatch):
    for p in REGISTRY.values():
        for k in p.env_keys:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    monkeypatch.setenv("AUTOMOTO_MODE", "multiuser")
    hosted._AUTH_HITS.clear()
    accounts._LAUNCH_CODES.clear()
    yield


def app_client():
    """A native app: HTTPS, no cookies needed, no Origin header (requests made by the Rust shell)."""
    return TestClient(server.app, base_url=HTTPS)


def device_login(username="alice", password=PW, name="Yasin's laptop", platform="windows", c=None, **kw):
    c = c or app_client()
    return c.post("/api/auth/device/login", json={"username": username, "password": password,
                                                  "device_name": name, "platform": platform}, **kw)


def bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


def open_window(tok):
    """What the app does: ask for a one-time link, then open it in its window (a cookie session)."""
    c = app_client()
    r = c.post("/api/auth/device/launch", headers=bearer(tok))
    assert r.status_code == 200, r.text
    path = r.json()["path"]
    assert path.startswith("/?device_launch=")
    w = TestClient(server.app, base_url=HTTPS)
    page = w.get(path)
    assert page.status_code == 200 and 'http-equiv="refresh"' in page.text
    ck = page.headers["set-cookie"].lower()
    assert "httponly" in ck and "samesite=strict" in ck and "secure" in ck
    home = w.get("/")
    m = re.search(r'name="automoto-csrf" content="([^"]+)"', home.text)
    assert m, "the window is not signed in"
    return w, m.group(1), path


def test_app_sign_in_gives_a_hashed_revocable_device_token():
    accounts.create_user("alice", PW)
    r = device_login(name="Yasin's laptop\n<script>")
    assert r.status_code == 200, r.text
    d = r.json()
    tok = d["token"]
    assert tok.startswith("amd_") and len(tok) > 40 and d["user"]["username"] == "alice"
    assert d["device"]["name"] == "Yasin's laptop script" and d["device"]["platform"] == "windows"  # cleaned
    assert tok.encode() not in accounts.db_path().read_bytes()  # only the hash is stored
    me = app_client().get("/api/me", headers=bearer(tok))
    assert me.status_code == 200 and me.json()["user"]["username"] == "alice"
    assert app_client().get("/api/me", headers=bearer(tok + "x")).status_code == 401
    assert app_client().get("/api/me", headers=bearer("amd_nope")).status_code == 401
    # wrong password: same vague error as the browser sign-in
    bad = device_login(password="nope-nope-nope")
    assert bad.status_code == 401 and bad.json()["detail"] == "wrong username or password"


def test_device_tokens_need_https_except_on_this_computer(monkeypatch):
    accounts.create_user("alice", PW)
    plain = TestClient(server.app)  # http://testserver - a network host over plain HTTP
    r = device_login(c=plain)
    assert r.status_code == 403 and "HTTPS" in r.json()["detail"]
    tok = device_login().json()["token"]
    assert plain.get("/api/me", headers=bearer(tok)).status_code == 403  # never accepted in clear text
    assert plain.post("/api/auth/device/launch", headers=bearer(tok)).status_code == 403
    assert plain.get("/?device_launch=whatever").status_code == 403
    local = TestClient(server.app, base_url="http://127.0.0.1:8765")  # the same computer: fine
    assert device_login(c=local).status_code == 200
    monkeypatch.setenv("AUTOMOTO_ALLOW_HTTP_DEVICES", "1")  # home-network testing only (documented)
    assert device_login(c=plain).status_code == 200


def test_device_window_session_and_one_time_launch_codes():
    accounts.create_user("alice", PW)
    tok = device_login().json()["token"]
    w, csrf, path = open_window(tok)
    # the window works like a normal signed-in page (cookie + CSRF)
    r = w.post("/api/conversations", json={"title": "From the window"},
               headers={"X-CSRF-Token": csrf, "Origin": HTTPS})
    assert r.status_code == 200, r.text
    # a launch code works once
    again = TestClient(server.app, base_url=HTTPS)
    again.get(path)
    assert 'name="automoto-csrf"' not in again.get("/").text
    # and only for 60 seconds
    code = accounts.device_launch_code(accounts.list_devices()[0]["id"], accounts.find_user("alice").id, ttl=-1)
    late = TestClient(server.app, base_url=HTTPS)
    late.get("/?device_launch=" + code)
    assert 'name="automoto-csrf"' not in late.get("/").text
    # opening a new window ends the device's previous window session
    w2, _, _ = open_window(tok)
    assert 'name="automoto-csrf"' not in w.get("/").text
    assert 'name="automoto-csrf"' in w2.get("/").text


def test_same_account_sees_the_same_chats_and_files_on_every_device():
    accounts.create_user("alice", PW)
    accounts.create_user("bob", PW)
    pc = device_login(name="Windows PC").json()["token"]
    phone = device_login(name="Phone", platform="android").json()["token"]
    bob = device_login("bob", name="Bob PC").json()["token"]
    c = app_client()
    made = c.post("/api/conversations", json={"title": "Essay plan"}, headers=bearer(pc))
    assert made.status_code == 200, made.text
    cid = made.json()["id"]
    up = c.post("/api/files/upload", headers=bearer(pc), json={"name": "notes.txt", "data": "aGVsbG8gZnJvbSB0aGUgUEM="})
    assert up.status_code == 200, up.text
    seen = c.get("/api/conversations", headers=bearer(phone)).json()
    assert cid in [x["id"] for x in seen["conversations"]]
    files = str(c.get("/api/files?dir=uploads", headers=bearer(phone)).json())
    assert "notes.txt" in files
    dl = c.get("/api/files/download?path=uploads/notes.txt", headers=bearer(phone))
    assert dl.status_code == 200 and dl.content == b"hello from the PC"
    w, _, _ = open_window(phone)  # and in the phone's window
    assert cid in [x["id"] for x in w.get("/api/conversations").json()["conversations"]]
    # another account sees none of it
    assert cid not in str(c.get("/api/conversations", headers=bearer(bob)).json())
    assert "notes.txt" not in str(c.get("/api/files?dir=uploads", headers=bearer(bob)).json())
    assert c.get(f"/api/conversations/{cid}", headers=bearer(bob)).status_code == 404


def test_my_devices_lists_and_revokes_apps_and_browser_sessions():
    accounts.create_user("alice", PW)
    a = device_login(name="Laptop").json()
    b = device_login(name="Desktop").json()
    w, csrf, _ = open_window(a["token"])
    lst = w.get("/api/devices").json()
    names = {d["name"]: d for d in lst["devices"]}
    assert {"Laptop", "Desktop"} <= set(names) and lst["current"] == a["device"]["id"]
    browser = TestClient(server.app, base_url=HTTPS)
    browser.post("/api/auth/login", json={"username": "alice", "password": PW}, headers={"Origin": HTTPS})
    lst = w.get("/api/devices").json()["devices"]
    web = [d for d in lst if d["kind"] == "browser"]
    assert len(web) == 1 and not any(d["kind"] == "browser" and d["name"] == "Laptop" for d in lst)
    # revoke the other app: its token stops working at once
    h = {"X-CSRF-Token": csrf, "Origin": HTTPS}
    assert w.delete(f"/api/devices/{b['device']['id']}", headers=h).status_code == 200
    assert app_client().get("/api/me", headers=bearer(b["token"])).status_code == 401
    # revoke the browser session
    assert w.delete(f"/api/devices/{web[0]['id']}", headers=h).status_code == 200
    assert browser.get("/api/me").status_code == 401
    # the app signs itself out: token and window session go
    assert app_client().post("/api/auth/device/logout", headers=bearer(a["token"])).status_code == 200
    assert app_client().get("/api/me", headers=bearer(a["token"])).status_code == 401
    assert w.get("/api/me").status_code == 401
    assert w.delete("/api/devices/0123456789abcdef", headers=h).status_code in (401, 404)


def test_users_cannot_revoke_other_peoples_devices_but_admins_can():
    accounts.create_user("boss", PW, role="admin")
    accounts.create_user("alice", PW)
    accounts.create_user("bob", PW)
    al = device_login(name="Alice PC").json()
    bob = device_login("bob").json()
    c = app_client()
    assert c.delete(f"/api/devices/{al['device']['id']}", headers=bearer(bob["token"])).status_code == 404
    assert c.get("/api/me", headers=bearer(al["token"])).status_code == 200
    assert c.get("/api/admin/devices", headers=bearer(bob["token"])).status_code == 403
    boss = device_login("boss").json()["token"]
    all_ = c.get("/api/admin/devices", headers=bearer(boss)).json()["devices"]
    assert {d["user"] for d in all_} == {"alice", "bob", "boss"}
    only = c.get("/api/admin/devices?user=alice", headers=bearer(boss)).json()["devices"]
    assert [d["name"] for d in only] == ["Alice PC"]
    assert c.delete(f"/api/admin/devices/{al['device']['id']}", headers=bearer(boss)).status_code == 200
    assert c.get("/api/me", headers=bearer(al["token"])).status_code == 401
    assert any(a["action"] == "revoke_device" and a["actor"] == "boss" for a in accounts.audit_log())


def test_password_change_suspension_and_deletion_sign_apps_out():
    boss = accounts.create_user("boss", PW, role="admin")
    al = accounts.create_user("alice", PW)
    t1 = device_login().json()["token"]
    accounts.update_user(al.id, "boss", status="suspended")
    assert app_client().get("/api/me", headers=bearer(t1)).status_code == 401
    assert device_login().status_code == 401  # "suspended"
    accounts.update_user(al.id, "boss", status="active")
    assert app_client().get("/api/me", headers=bearer(t1)).status_code == 200  # back when unsuspended
    accounts.set_password(al.id, "another-horse-88", "alice")
    assert app_client().get("/api/me", headers=bearer(t1)).status_code == 401
    t2 = device_login(password="another-horse-88").json()["token"]
    accounts.delete_user(al.id, boss.username)
    assert app_client().get("/api/me", headers=bearer(t2)).status_code == 401
    assert accounts.list_devices() == []


def test_device_tokens_expire_and_old_devices_drop_off(monkeypatch):
    accounts.create_user("alice", PW)
    tok = device_login().json()["token"]
    with accounts._db() as con:
        con.execute("UPDATE devices SET expires=?", (time.time() - 1,))
    assert app_client().get("/api/me", headers=bearer(tok)).status_code == 401
    for i in range(accounts.MAX_DEVICES + 3):
        assert device_login(name=f"pc{i}").status_code == 200
        hosted._AUTH_HITS.clear()
    assert len(accounts.list_devices()) == accounts.MAX_DEVICES


def test_cors_only_for_app_origins_and_sign_in_paths():
    accounts.create_user("alice", PW)
    c = app_client()
    pre = c.options("/api/auth/device/login", headers={"Origin": APP, "Access-Control-Request-Method": "POST",
                                                        "Access-Control-Request-Headers": "content-type"})
    assert pre.status_code == 204 and pre.headers["access-control-allow-origin"] == APP
    assert "access-control-allow-credentials" not in pre.headers  # no cookies cross-origin
    r = device_login(headers={"Origin": APP})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == APP
    tok = r.json()["token"]
    for origin in ("tauri://localhost", "https://tauri.localhost"):
        assert c.get("/api/me", headers={"Origin": origin, **bearer(tok)}).status_code == 200
    # an app origin may not reach anything else, and other sites may not sign in at all
    assert c.get("/api/conversations", headers={"Origin": APP, **bearer(tok)}).status_code == 403
    assert device_login(headers={"Origin": "https://evil.example"}).status_code == 403
    evil = c.options("/api/auth/device/login", headers={"Origin": "https://evil.example",
                                                         "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in evil.headers
    assert c.options("/api/conversations", headers={"Origin": APP}).status_code in (403, 404, 405)


def test_device_routes_do_not_exist_in_local_mode(monkeypatch):
    monkeypatch.delenv("AUTOMOTO_MODE")
    c = TestClient(server.app)
    for path in ("/api/auth/device/login", "/api/auth/device/launch"):
        assert c.post(path, json={}).status_code == 404
    assert c.get("/api/devices").status_code == 404


def test_old_database_gets_the_device_column(tmp_path, monkeypatch):
    import sqlite3

    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(tmp_path))
    con = sqlite3.connect(str(tmp_path / "accounts.db"))
    con.execute("CREATE TABLE sessions (token TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf TEXT NOT NULL, "
                "created REAL NOT NULL, expires REAL NOT NULL, ip TEXT NOT NULL DEFAULT '')")
    con.commit()
    con.close()
    accounts._MIGRATED.clear()
    u = accounts.create_user("alice", PW)
    tok, _ = accounts.new_session(u, "1.2.3.4")
    assert accounts.session_user(tok)[0].username == "alice"


def test_local_launch_from_the_app_uses_a_page_not_a_redirect(monkeypatch):
    """The desktop app's local mode: a 303 started from the app's own page would not carry the
    SameSite=Strict cookie on WebKit, so `app=1` (or a cross-site start) gets a refresh page."""
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    plain = TestClient(server.app)
    assert plain.get("/?launch=" + server.new_launch_token(), follow_redirects=False).status_code == 303
    app = TestClient(server.app)
    r = app.get("/?launch=" + server.new_launch_token() + "&app=1", follow_redirects=False)
    assert r.status_code == 200 and 'http-equiv="refresh"' in r.text
    assert "automoto_session" in r.headers.get("set-cookie", "")
    assert app.get("/api/status").status_code == 200
    cross = TestClient(server.app)
    r = cross.get("/?launch=" + server.new_launch_token(), headers={"Sec-Fetch-Site": "cross-site"},
                  follow_redirects=False)
    assert r.status_code == 200 and cross.get("/api/status").status_code == 200
    used = TestClient(server.app)
    assert used.get("/?launch=bogus&app=1", follow_redirects=False).status_code == 403
