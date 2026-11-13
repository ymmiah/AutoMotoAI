"""First admin on any host: one-time setup code, forced password change, env bootstrap and reset."""

import json
import re
import time

import pytest
from fastapi.testclient import TestClient

from automoto import accounts, hosted, server

ORIGIN = {"Origin": "http://testserver"}
PW = "correct-horse-77"
NEW = "purple-subway-train-99"
ENV_PW = "env-only-secret-99"


@pytest.fixture(autouse=True)
def hosted_mode(monkeypatch):
    monkeypatch.setenv("AUTOMOTO_MODE", "multiuser")
    monkeypatch.delenv("AUTOMOTO_ADMIN_USER", raising=False)
    monkeypatch.delenv("AUTOMOTO_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("AUTOMOTO_SETUP_CODE", raising=False)
    monkeypatch.delenv("AUTOMOTO_ADMIN_RESET", raising=False)
    hosted._AUTH_HITS.clear()
    yield
    hosted._AUTH_HITS.clear()


def _code_from(lines: list[str]) -> str:
    for line in lines:
        m = re.search(r"(?:Setup code|Reset code):\s*(\S+)", line)
        if m:
            return m.group(1)
    raise AssertionError(f"no setup code in log lines: {lines}")


def _client() -> TestClient:
    return TestClient(server.app)


def _login(c: TestClient, username: str, password: str):
    r = c.post("/api/auth/login", json={"username": username, "password": password}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r


def _csrf(c: TestClient) -> str:
    page = c.get("/")
    return re.search(r'name="automoto-csrf" content="([^"]+)"', page.text).group(1)


def _stored_setup() -> dict:
    with accounts._db() as con:
        row = con.execute("SELECT value FROM kv WHERE key=?", (accounts.SETUP_KV,)).fetchone()
    assert row, "setup code was not stored"
    return json.loads(row["value"])


# -- setup code lifecycle ----------------------------------------------------------------------
def test_setup_code_works_once_and_is_stored_as_a_hash():
    lines = accounts.startup_admin_access("/setup")
    text = "\n".join(lines)
    assert "No admin account yet" in text and "/setup" in text
    assert "admin/admin" not in text.lower()
    code = _code_from(lines)
    assert ENV_PW not in text and code not in _stored_setup()["hash"]
    assert _stored_setup()["hash"] == accounts.setup_digest(code)
    assert _stored_setup()["purpose"] == "create"
    page = _client().get("/setup")
    assert page.status_code == 200
    assert "setup code" in page.text.lower() and 'id="setupForm"' in page.text
    info = _client().get("/api/setup/info").json()
    assert info["available"] is True and info["mode"] == "create" and "hash" not in info
    # grouped or ungrouped, the same code
    bare = accounts.normalize_setup_code(code)
    c = _client()
    bad_pw = c.post("/api/setup", json={"code": code, "username": "ada", "password": "password12345"}, headers=ORIGIN)
    assert bad_pw.status_code == 400 and accounts.admin_count() == 0
    assert _stored_setup()["hash"] == accounts.setup_digest(code)  # a weak password does not use the code up
    ok = c.post("/api/setup", json={"code": bare, "username": "Ada", "password": NEW}, headers=ORIGIN)
    assert ok.status_code == 200, ok.text
    user = accounts.find_user("ada")
    assert user and user.is_admin and user.must_change_password is False
    again = c.post("/api/setup", json={"code": code, "username": "ada", "password": NEW}, headers=ORIGIN)
    assert again.status_code == 401
    assert accounts.admin_count() == 1
    assert accounts._load_setup() is None


def test_setup_code_expires_and_a_restart_replaces_it():
    first = accounts.startup_admin_access()
    code = _code_from(first)
    rec = _stored_setup()
    rec["expires"] = time.time() - 5
    with accounts._db() as con:
        con.execute("UPDATE kv SET value=? WHERE key=?", (json.dumps(rec), accounts.SETUP_KV))
    c = _client()
    expired = c.post("/api/setup", json={"code": code, "username": "ada", "password": NEW}, headers=ORIGIN)
    assert expired.status_code == 400 and "expired" in expired.json()["detail"]
    assert accounts.find_user("ada") is None
    second = accounts.startup_admin_access()
    fresh = _code_from(second)
    assert fresh != code
    old = c.post("/api/setup", json={"code": code, "username": "ada", "password": NEW}, headers=ORIGIN)
    assert old.status_code == 401
    ok = c.post("/api/setup", json={"code": fresh, "username": "ada", "password": NEW}, headers=ORIGIN)
    assert ok.status_code == 200


def test_wrong_setup_code_is_rate_limited(monkeypatch):
    monkeypatch.setattr(hosted, "SETUP_FAIL_LIMIT", 3)
    lines = accounts.startup_admin_access()
    code = _code_from(lines)
    c = _client()
    for _ in range(3):
        r = c.post("/api/setup", json={"code": "not-the-code-at-all", "username": "ada", "password": NEW}, headers=ORIGIN)
        assert r.status_code == 401
    blocked = c.post("/api/setup", json={"code": code, "username": "ada", "password": NEW}, headers=ORIGIN)
    assert blocked.status_code == 429
    assert accounts.admin_count() == 0


def test_setup_is_refused_once_any_admin_exists():
    accounts.create_user("owner", PW, role="admin")
    issued = accounts.issue_setup_code(purpose="create")
    c = _client()
    assert c.get("/api/setup/info").json()["available"] is False
    r = c.post("/api/setup", json={"code": issued.code, "username": "other", "password": NEW}, headers=ORIGIN)
    assert r.status_code == 403 and "admin already exists" in r.json()["detail"]
    assert accounts.find_user("other") is None
    assert accounts.admin_count() == 1


def test_owner_supplied_setup_code_is_not_logged(monkeypatch):
    secret = "owner-picked-setup-code"
    monkeypatch.setenv("AUTOMOTO_SETUP_CODE", secret)
    lines = accounts.startup_admin_access()
    text = "\n".join(lines)
    assert secret not in text and "not printed" in text
    assert _stored_setup()["hash"] == accounts.setup_digest(secret)
    ok = _client().post("/api/setup", json={"code": secret, "username": "ada", "password": NEW}, headers=ORIGIN)
    assert ok.status_code == 200


def test_local_mode_has_no_setup_page(monkeypatch):
    monkeypatch.delenv("AUTOMOTO_MODE")
    c = _client()
    assert c.get("/setup").status_code == 404
    assert c.post("/api/setup", json={"code": "x", "username": "a", "password": NEW}, headers=ORIGIN).status_code == 404


# -- forced password change --------------------------------------------------------------------
def _flagged(username: str = "ada") -> TestClient:
    accounts.create_user(username, PW, role="admin", must_change=True)
    c = _client()
    _login(c, username, PW)
    return c


def test_forced_change_blocks_apis_until_the_password_changes():
    c = _flagged()
    page = c.get("/")
    assert "Choose a new password" in page.text
    assert 'id="app"' not in page.text and 'id="pwForm"' in page.text
    assert c.get("/api/me").json()["user"]["must_change_password"] is True
    assert c.get("/api/status").status_code == 403
    assert "Choose a new password" in c.get("/api/status").json()["detail"]
    assert c.get("/api/auth/info").status_code == 200
    csrf = _csrf(c)
    same = c.post("/api/auth/password", json={"current": PW, "new": PW}, headers={"X-CSRF-Token": csrf, **ORIGIN})
    assert same.status_code == 400 and "different" in same.json()["detail"]
    common = c.post("/api/auth/password", json={"current": PW, "new": "password12345"},
                    headers={"X-CSRF-Token": csrf, **ORIGIN})
    assert common.status_code == 400 and "common" in common.json()["detail"]
    short = c.post("/api/auth/password", json={"current": PW, "new": "short-pw-1"},
                   headers={"X-CSRF-Token": csrf, **ORIGIN})
    assert short.status_code == 400
    assert c.get("/api/status").status_code == 403  # still locked
    ok = c.post("/api/auth/password", json={"current": PW, "new": NEW}, headers={"X-CSRF-Token": csrf, **ORIGIN})
    assert ok.status_code == 200 and ok.json()["user"]["must_change_password"] is False
    assert c.get("/api/status").status_code == 200
    home = c.get("/")
    assert "Choose a new password" not in home.text and 'id="app"' in home.text


def test_clearing_the_flag_revokes_other_sessions():
    accounts.create_user("ada", PW, role="admin", must_change=True)
    a, b = _client(), _client()
    _login(a, "ada", PW)
    _login(b, "ada", PW)
    csrf = _csrf(a)
    assert a.post("/api/auth/password", json={"current": PW, "new": NEW},
                  headers={"X-CSRF-Token": csrf, **ORIGIN}).status_code == 200
    assert b.get("/api/me").status_code == 401
    assert a.get("/api/me").status_code == 200


def test_env_bootstrap_flags_must_change_and_does_not_overwrite(monkeypatch):
    monkeypatch.setenv("AUTOMOTO_ADMIN_USER", "Owner")
    monkeypatch.setenv("AUTOMOTO_ADMIN_PASSWORD", ENV_PW)
    lines = accounts.startup_admin_access()
    text = "\n".join(lines)
    assert "Created the first admin 'owner'" in text
    assert ENV_PW not in text
    user = accounts.find_user("owner")
    assert user and user.is_admin and user.must_change_password is True
    assert accounts.bootstrap_admin_from_env() is None
    monkeypatch.setenv("AUTOMOTO_ADMIN_PASSWORD", NEW)
    assert accounts.bootstrap_admin_from_env() is None
    c = _client()
    assert c.post("/api/auth/login", json={"username": "owner", "password": NEW}, headers=ORIGIN).status_code == 401
    _login(c, "owner", ENV_PW)
    assert c.get("/api/status").status_code == 403
    csrf = _csrf(c)
    assert c.post("/api/auth/password", json={"current": ENV_PW, "new": NEW},
                  headers={"X-CSRF-Token": csrf, **ORIGIN}).status_code == 200
    assert accounts.find_user("owner").must_change_password is False
    monkeypatch.setenv("AUTOMOTO_ADMIN_PASSWORD", ENV_PW)
    again = "\n".join(accounts.startup_admin_access())
    assert "were not applied" in again and ENV_PW not in again
    assert accounts.find_user("owner").must_change_password is False
    assert _client().post("/api/auth/login", json={"username": "owner", "password": NEW}, headers=ORIGIN).status_code == 200


def test_admin_set_password_flags_must_change():
    boss = accounts.create_user("boss", PW, role="admin")
    pupil = accounts.create_user("pupil", PW)
    c = _client()
    _login(c, "boss", PW)
    csrf = _csrf(c)
    r = c.post(f"/api/admin/users/{pupil.id}/password", json={"password": "another-horse-88"},
               headers={"X-CSRF-Token": csrf, **ORIGIN})
    assert r.status_code == 200
    assert accounts.find_user("pupil").must_change_password is True
    pupil_c = _client()
    _login(pupil_c, "pupil", "another-horse-88")
    assert pupil_c.get("/api/status").status_code == 403
    assert accounts.find_user("boss").must_change_password is False


def test_cli_temp_password_and_reset_password(monkeypatch):
    from automoto import cli
    monkeypatch.setenv("PWVAR", PW)
    assert cli.main(["admin", "create", "yasin", "--temporary", "--password-env", "PWVAR"]) == 0
    assert accounts.find_user("yasin").must_change_password is True
    monkeypatch.setenv("PWVAR", "another-horse-88")
    assert cli.main(["admin", "reset-password", "yasin", "--password-env", "PWVAR"]) == 0
    assert accounts.find_user("yasin").must_change_password is True
    c = _client()
    assert c.post("/api/auth/login", json={"username": "yasin", "password": PW}, headers=ORIGIN).status_code == 401
    _login(c, "yasin", "another-horse-88")
    assert c.get("/api/status").status_code == 403


def test_admin_reset_env_prints_a_code_and_forces_a_change(monkeypatch):
    accounts.create_user("owner", PW, role="admin")
    monkeypatch.setenv("AUTOMOTO_ADMIN_RESET", "1")
    lines = accounts.startup_admin_access("http://127.0.0.1:8765/setup")
    text = "\n".join(lines)
    assert "AUTOMOTO_ADMIN_RESET=1" in text and "/setup" in text
    assert PW not in text
    code = _code_from(lines)
    assert _stored_setup()["purpose"] == "reset"
    assert _stored_setup()["username"] == "owner"
    c = _client()
    ok = c.post("/api/setup", json={"code": code, "username": "owner", "password": "reset-ticket-42"}, headers=ORIGIN)
    assert ok.status_code == 200 and ok.json()["must_change_password"] is True
    used = c.post("/api/setup", json={"code": code, "username": "owner", "password": NEW}, headers=ORIGIN)
    assert used.status_code == 401
    assert c.post("/api/auth/login", json={"username": "owner", "password": PW}, headers=ORIGIN).status_code == 401
    _login(c, "owner", "reset-ticket-42")
    assert c.get("/").status_code == 200 and "Choose a new password" in c.get("/").text
    assert c.get("/api/status").status_code == 403


def test_old_database_gains_the_password_flag(monkeypatch, tmp_path):
    import sqlite3
    db = tmp_path / "accounts.db"
    monkeypatch.setattr(accounts, "db_path", lambda: db)
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE users (
      id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, pw TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user',
      status TEXT NOT NULL DEFAULT 'active', created REAL NOT NULL, last_login REAL,
      quota_minutes REAL, unlimited INTEGER NOT NULL DEFAULT 0, request_cap INTEGER, token_cap INTEGER,
      usage_reset REAL NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0,
      note TEXT NOT NULL DEFAULT '')""")
    con.commit()
    con.close()
    accounts._MIGRATED.discard(str(db))
    user = accounts.create_user("ada", PW, role="admin")
    assert user.must_change_password is False
    with accounts._db() as con:
        cols = {r["name"] for r in con.execute("PRAGMA table_info(users)")}
    assert "must_change_password" in cols
