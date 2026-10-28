"""Hosted (multi-user) mode: accounts, CSRF, quotas, admin controls and isolation (v5.5)."""

import re
import time

import pytest
from fastapi.testclient import TestClient

from automoto import accounts, hosted, router, sandbox, server, tenancy
from automoto.providers import REGISTRY
from automoto.toolcalls import Turn

ORIGIN = {"Origin": "http://testserver"}
PW = "correct-horse-77"


@pytest.fixture(autouse=True)
def hosted_env(monkeypatch):
    for p in REGISTRY.values():
        for k in p.env_keys:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    monkeypatch.setenv("AUTOMOTO_MODE", "multiuser")
    monkeypatch.setenv("AUTOMOTO_SIGNUP", "open")
    for k in ("AUTOMOTO_DEFAULT_QUOTA_MINUTES", "AUTOMOTO_DEFAULT_REQUEST_CAP", "AUTOMOTO_QUOTA_RESET_HOUR",
              "AUTOMOTO_ADMIN_USER", "AUTOMOTO_ADMIN_PASSWORD", "AUTOMOTO_HOSTED_MAX_UPLOAD_MB"):
        monkeypatch.delenv(k, raising=False)
    hosted._AUTH_HITS.clear()
    server.TASKS.tasks.clear()
    yield
    server.TASKS.tasks.clear()


class Session:
    """A browser: cookie jar + the CSRF token from the page."""

    def __init__(self, username: str, password: str = PW, *, role: str = "user", create: bool = True):
        if create:
            self.user = accounts.create_user(username, password, role=role)
        self.c = TestClient(server.app)
        r = self.c.post("/api/auth/login", json={"username": username, "password": password}, headers=ORIGIN)
        assert r.status_code == 200, r.text
        page = self.c.get("/")
        self.csrf = re.search(r'name="automoto-csrf" content="([^"]+)"', page.text).group(1)

    def h(self):
        return {"X-CSRF-Token": self.csrf, **ORIGIN}

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json if json is not None else {}, headers=self.h(), **kw)

    def patch(self, url, json):
        return self.c.patch(url, json=json, headers=self.h())

    def put(self, url, json):
        return self.c.put(url, json=json, headers=self.h())

    def delete(self, url):
        return self.c.delete(url, headers=self.h())


def fake_turns(monkeypatch, turns, delay=0.0):
    it = iter(turns)

    def ask_turn(history, schemas, **kw):
        if delay:
            time.sleep(delay)
        try:
            return next(it)
        except StopIteration:
            return Turn("done", provider="gemini", model="m")
    monkeypatch.setattr(router, "ask_turn", ask_turn)


def wait(tid, owner=None):
    t = server.TASKS.wait(tid, timeout=20)
    assert t and t.status in ("done", "error", "cancelled"), t and t.status
    return t


# -- passwords, sign-up, sign-in ---------------------------------------------------------------
def test_password_hash_is_scrypt_salted_and_verifies():
    h1, h2 = accounts.hash_password(PW), accounts.hash_password(PW)
    assert h1.startswith("scrypt$") and h1 != h2 and PW not in h1
    assert accounts.verify_password(PW, h1) and not accounts.verify_password(PW + "x", h1)
    assert not accounts.verify_password(PW, "garbage")
    for bad in ("short", "aaaaaaaaaaaa", "alice-is-my-password"):
        with pytest.raises(accounts.AccountError):
            accounts.check_password_rules(bad, "alice")


def test_signup_modes_and_invites(monkeypatch):
    c = TestClient(server.app)
    accounts.create_user("boss", PW, role="admin")
    accounts.set_settings("boss", signup="closed")
    assert c.post("/api/auth/signup", json={"username": "x1x", "password": PW}, headers=ORIGIN).status_code == 400
    accounts.set_settings("boss", signup="invite")
    r = c.post("/api/auth/signup", json={"username": "x1x", "password": PW}, headers=ORIGIN)
    assert r.status_code == 400 and "invite" in r.json()["detail"]
    code = accounts.create_invite("boss", uses=1)
    assert c.post("/api/auth/signup", json={"username": "x1x", "password": PW, "invite": "am-wrong"},
                  headers=ORIGIN).status_code == 400
    r = c.post("/api/auth/signup", json={"username": "x1x", "password": PW, "invite": code}, headers=ORIGIN)
    assert r.status_code == 200 and accounts.find_user("x1x").role == "user"
    r = TestClient(server.app).post("/api/auth/signup", json={"username": "x2x", "password": PW, "invite": code},
                                    headers=ORIGIN)
    assert r.status_code == 400 and "used up" in r.json()["detail"]  # one use only
    assert TestClient(server.app).post("/api/auth/signup", json={"username": "x3x", "password": PW},
                                       headers=ORIGIN).status_code == 429  # 5 sign-ups per hour per IP
    hosted._AUTH_HITS.clear()
    # a failed sign-up (taken name) gives the invite use back
    code2 = accounts.create_invite("boss", uses=1)
    assert TestClient(server.app).post("/api/auth/signup", json={"username": "x1x", "password": PW, "invite": code2},
                                       headers=ORIGIN).status_code == 400
    assert accounts.list_invites()[0]["uses_left"] == 1


def test_login_cookie_flags_and_vague_errors():
    accounts.create_user("alice", PW)
    c = TestClient(server.app)
    r = c.post("/api/auth/login", json={"username": "alice", "password": PW}, headers=ORIGIN)
    ck = r.headers["set-cookie"].lower()
    assert r.status_code == 200 and "httponly" in ck and "samesite=strict" in ck and "automoto_user=" in ck
    assert accounts.db_path().is_file()
    # the token is stored hashed only
    tok = c.cookies.get(hosted.COOKIE)
    assert tok and tok.encode() not in accounts.db_path().read_bytes()
    bad = TestClient(server.app).post("/api/auth/login", json={"username": "alice", "password": "nope-nope-nope"},
                                      headers=ORIGIN)
    nouser = TestClient(server.app).post("/api/auth/login", json={"username": "nobody", "password": "nope-nope-nope"},
                                         headers=ORIGIN)
    assert bad.status_code == nouser.status_code == 401 and bad.json() == nouser.json()
    # login must come from our own page (no login CSRF)
    assert TestClient(server.app).post("/api/auth/login", json={"username": "alice", "password": PW}).status_code == 403
    assert TestClient(server.app).post("/api/auth/login", json={"username": "alice", "password": PW},
                                       headers={"Origin": "https://evil.example"}).status_code == 403


def test_lockout_after_failed_logins_and_rate_limit():
    accounts.create_user("bob", PW)
    for _ in range(accounts.LOCK_AFTER):
        with pytest.raises(accounts.AccountError, match="wrong"):
            accounts.authenticate("bob", "wrong-password-1")
    with pytest.raises(accounts.AccountError, match="try again"):
        accounts.authenticate("bob", PW)  # locked even with the right password
    assert any(a["action"] == "lockout" for a in accounts.audit_log())
    c = TestClient(server.app)
    codes = [c.post("/api/auth/login", json={"username": "zed", "password": "x" * 12}, headers=ORIGIN).status_code
             for _ in range(12)]
    assert 429 in codes  # per-username limit (10 / 15 min)


def test_suspended_user_is_signed_out_and_cannot_sign_in():
    admin = Session("boss", role="admin")
    s = Session("carol")
    assert s.get("/api/me").status_code == 200
    r = admin.patch(f"/api/admin/users/{s.user.id}", {"status": "suspended"})
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    assert s.get("/api/me").status_code == 401
    with pytest.raises(accounts.AccountError, match="suspended"):
        accounts.authenticate("carol", PW)


# -- CSRF, route allow-list, local mode --------------------------------------------------------
def test_csrf_and_origin_are_required_for_changes():
    s = Session("dave")
    ok = s.post("/api/conversations", {"title": "t", "mode": "agent"})
    assert ok.status_code == 200
    assert s.c.post("/api/conversations", json={"title": "t"}).status_code == 403  # no CSRF header
    assert s.c.post("/api/conversations", json={"title": "t"},
                    headers={"X-CSRF-Token": "wrong", **ORIGIN}).status_code == 403
    assert s.c.post("/api/conversations", json={"title": "t"},
                    headers={"X-CSRF-Token": s.csrf, "Origin": "https://evil.example"}).status_code == 403
    assert s.get("/api/conversations").status_code == 200  # reads need only the cookie


def test_hosted_mode_closes_every_non_allowlisted_route():
    s = Session("erin")
    for method, path in [("POST", "/api/actions/execute"), ("POST", "/api/screen/explain"), ("GET", "/api/apps"),
                         ("GET", "/api/routines"), ("POST", "/api/routines"), ("PUT", "/api/settings"),
                         ("GET", "/api/connectors"), ("POST", "/api/connectors-reload"), ("GET", "/api/services"),
                         ("POST", "/api/session/launch"), ("PUT", "/api/skills/x"), ("DELETE", "/api/skills/x")]:
        r = s.c.request(method, path, json={}, headers=s.h())
        assert r.status_code == 404, (method, path, r.status_code)
    # every route the app has is either allow-listed or closed
    for route in server.app.routes:
        for m in getattr(route, "methods", None) or []:
            path = re.sub(r"\{[^}]+\}", "abc", route.path)
            if m in ("HEAD", "OPTIONS"):
                continue
            if not hosted.path_allowed(m, path):
                assert s.c.request(m, path, json={}, headers=s.h()).status_code == 404, (m, path)


def test_master_tokens_do_not_work_in_hosted_mode(monkeypatch):
    monkeypatch.setenv("AUTOMOTO_API_TOKEN", "x" * 32)
    c = TestClient(server.app)
    assert c.get("/api/conversations", headers={"X-AutoMoto-Token": server.SESSION_TOKEN}).status_code == 401
    assert c.get("/api/conversations", headers={"Authorization": "Bearer " + "x" * 32}).status_code == 401
    assert "Sign in" in c.get("/").text  # the login page, not the app


def test_local_mode_has_no_accounts_api(monkeypatch):
    monkeypatch.delenv("AUTOMOTO_MODE")
    c = TestClient(server.app)
    for path in ("/api/auth/info", "/api/me", "/api/admin/users"):
        assert c.get(path).status_code == 404
    assert c.post("/api/auth/login", json={"username": "a", "password": "b"}, headers=ORIGIN).status_code == 404
    assert c.get("/").status_code == 401  # still the one-time-link lock page


# -- admin role checks -------------------------------------------------------------------------
def test_admin_endpoints_need_the_admin_role():
    s = Session("frank")
    for method, path in [("GET", "/api/admin/users"), ("GET", "/api/admin/audit"), ("PUT", "/api/admin/settings"),
                         ("POST", f"/api/admin/users/{s.user.id}/bonus"), ("POST", "/api/admin/invites"),
                         ("PATCH", f"/api/admin/users/{s.user.id}"), ("DELETE", f"/api/admin/users/{s.user.id}")]:
        r = s.c.request(method, path, json={"minutes": 5}, headers=s.h())
        assert r.status_code == 403, (method, path, r.status_code)
    assert TestClient(server.app).get("/api/admin/users").status_code == 401


def test_admin_controls_quota_bonus_reset_and_audit():
    admin = Session("boss", role="admin")
    u = Session("gina")
    accounts.record(u.user.id, 3600)  # an hour used
    me = u.get("/api/me").json()["quota"]
    assert me["blocked"] and me["left_minutes"] == 0 and me["allowance_minutes"] == 60
    r = admin.post(f"/api/admin/users/{u.user.id}/bonus", {"minutes": 30, "note": "project week"})
    assert r.status_code == 200 and r.json()["quota"]["left_minutes"] == pytest.approx(30)
    r = admin.patch(f"/api/admin/users/{u.user.id}", {"quota_minutes": 120})
    assert r.json()["quota"]["allowance_minutes"] == 150 and r.json()["quota_minutes"] == 120
    r = admin.post(f"/api/admin/users/{u.user.id}/reset")
    assert r.json()["quota"]["used_minutes"] == 0
    r = admin.patch(f"/api/admin/users/{u.user.id}", {"unlimited": True})
    assert r.json()["quota"]["unlimited"] and not r.json()["quota"]["blocked"]
    r = admin.put("/api/admin/settings", {"default_quota_minutes": 45, "signup": "invite"})
    assert r.json()["default_quota_minutes"] == 45 and r.json()["signup"] == "invite"
    inv = admin.post("/api/admin/invites", {"uses": 3, "days": 2, "label": "class"}).json()
    assert inv["code"].startswith("am-") and admin.get("/api/admin/invites").json()["invites"][0]["uses_left"] == 3
    acts = [a["action"] for a in admin.get("/api/admin/audit").json()["audit"]]
    for a in ("bonus", "update_user", "reset_usage", "settings", "create_invite"):
        assert a in acts
    users = admin.get("/api/admin/users").json()["users"]
    assert {x["username"] for x in users} == {"boss", "gina"}


def test_admin_cannot_lock_themselves_out_and_delete_removes_files():
    admin = Session("boss", role="admin")
    assert admin.patch(f"/api/admin/users/{admin.user.id}", {"status": "suspended"}).status_code == 400
    assert admin.delete(f"/api/admin/users/{admin.user.id}").status_code == 400
    with pytest.raises(accounts.AccountError, match="last admin"):
        accounts.update_user(admin.user.id, "x", role="user")
    u = Session("hank")
    assert u.post("/api/files/upload", {"name": "a.txt", "data": "aGk="}).status_code == 200
    d = accounts.user_home(u.user.id)
    assert (d / "workspace" / "uploads" / "a.txt").is_file()
    assert admin.delete(f"/api/admin/users/{u.user.id}").json()["deleted"] == "hank"
    assert not d.exists() and accounts.find_user("hank") is None
    assert u.get("/api/me").status_code == 401


# -- quotas --------------------------------------------------------------------------------------
def test_quota_math_bonus_expiry_request_cap_and_period(monkeypatch):
    u = accounts.create_user("ivan", PW)
    q = accounts.quota(u)
    assert q["allowance_minutes"] == 60 and not q["blocked"] and q["resets_at"] > time.time()
    accounts.record(u.id, 59 * 60)
    assert not accounts.quota(u)["blocked"]
    accounts.record(u.id, 61)
    q = accounts.quota(u)
    assert q["blocked"] and "1 hour" in q["reason"] and "resets at" in accounts.limit_message(q)
    accounts.add_bonus(u.id, 10, "test", expires=time.time() + 0.5)
    assert not accounts.quota(u)["blocked"]
    time.sleep(0.6)
    assert accounts.quota(u)["blocked"]  # the bonus expired
    # old usage (before this period) doesn't count
    with accounts._db() as con:
        con.execute("UPDATE usage SET ts = ts - 2*86400")
    assert accounts.quota(u)["used_minutes"] == 0
    u = accounts.update_user(u.id, "t", request_cap=2)
    accounts.record(u.id, 1, requests=2)
    assert "requests" in accounts.quota(u)["reason"]
    # periods: daily from the reset hour (UTC); weekly
    monkeypatch.setenv("AUTOMOTO_QUOTA_RESET_HOUR", "6")
    import datetime as dt
    t = dt.datetime(2026, 10, 28, 5, 0, tzinfo=dt.timezone.utc).timestamp()
    assert accounts.period_start(t) == dt.datetime(2026, 10, 27, 6, 0, tzinfo=dt.timezone.utc).timestamp()
    monkeypatch.setenv("AUTOMOTO_QUOTA_PERIOD_DAYS", "7")
    assert accounts.period_end(t) - accounts.period_start(t) == 7 * 86400


def test_admin_is_unlimited_and_suspended_is_blocked():
    a = accounts.create_user("root1", PW, role="admin")
    accounts.record(a.id, 10 * 3600)
    assert not accounts.quota(a)["blocked"] and accounts.quota(a)["unlimited"]
    u = accounts.create_user("jill", PW)
    u = accounts.update_user(u.id, "t", status="suspended")
    assert accounts.quota(u)["blocked"]


def test_agent_run_stops_when_the_quota_runs_out(monkeypatch):
    s = Session("kim")
    accounts.update_user(s.user.id, "t", quota_minutes=0.01)  # 0.6 s
    call = {"id": "c1", "name": "list_dir", "arguments": {"path": "."}}
    fake_turns(monkeypatch, [Turn("", [call], "gemini", "m"), Turn("", [dict(call, id="c2")], "gemini", "m")], delay=0.7)
    r = s.post("/api/agent", {"messages": [{"role": "user", "content": "look around"}]})
    assert r.status_code == 200
    t = wait(r.json()["task_id"])
    assert t.result["stopped"] == "quota" and "Usage limit reached" in t.result["text"]
    assert any(e["type"] == "quota" for e in t.events)
    used = accounts.quota(accounts.get_user(s.user.id))
    assert used["blocked"] and used["requests"] == 1 and used["used_seconds"] >= 0.6
    # the next start is refused before any model call, with the reset time
    r = s.post("/api/agent", {"messages": [{"role": "user", "content": "again"}]})
    assert r.status_code == 429 and r.json()["detail"]["quota"]["blocked"] and "resets at" in r.json()["detail"]["message"]
    conv = s.post("/api/conversations", {"mode": "chat"}).json()
    r = s.post("/api/conversations/chat", {"conversation_id": conv["id"], "message": "hi"})
    assert r.status_code == 429


def test_chat_is_metered(monkeypatch):
    s = Session("lena")
    monkeypatch.setattr(server, "ask", lambda *a, **k: (time.sleep(0.2), router.Answer("hi", "gemini", "m", "chat", []))[1])
    r = s.post("/api/chat", {"messages": [{"role": "user", "content": "hello"}]})
    assert r.status_code == 200
    q = accounts.quota(accounts.get_user(s.user.id))
    assert q["requests"] == 1 and q["used_seconds"] > 0 and q["tokens"] > 0
    log = accounts.usage_log(s.user.id)
    assert log[0]["kind"] == "chat"


def test_per_user_task_limit(monkeypatch):
    s = Session("mia")
    accounts.set_settings("t", max_tasks_per_user=1)
    import threading
    gate = threading.Event()
    monkeypatch.setattr(router, "ask_turn", lambda *a, **k: (gate.wait(5), Turn("ok", provider="gemini", model="m"))[1])
    r1 = s.post("/api/agent", {"messages": [{"role": "user", "content": "one"}]})
    r2 = s.post("/api/agent", {"messages": [{"role": "user", "content": "two"}]})
    gate.set()
    assert r1.status_code == 200 and r2.status_code == 429
    wait(r1.json()["task_id"])


# -- isolation -----------------------------------------------------------------------------------
def test_users_are_isolated(monkeypatch):
    a, b = Session("ann"), Session("ben")
    assert a.post("/api/files/upload", {"name": "secret.txt", "data": "c2VjcmV0"}).status_code == 200
    assert a.get("/api/files/download?path=uploads/secret.txt").content == b"secret"
    assert b.get("/api/files/download?path=uploads/secret.txt").status_code == 404
    assert all(i["name"] != "uploads" for i in b.get("/api/files").json()["items"])
    rel = "../" + a.user.id + "/workspace/uploads/secret.txt"
    assert b.get("/api/files/download", params={"path": rel}).status_code == 400
    assert b.get("/api/files/download", params={"path": str(accounts.user_home(a.user.id) / "workspace/uploads/secret.txt")}).status_code == 400
    assert b.get("/api/files/download", params={"path": "../../accounts.db"}).status_code == 400
    ca = a.post("/api/conversations", {"title": "mine"}).json()
    assert b.get(f"/api/conversations/{ca['id']}").status_code == 404
    assert [c["id"] for c in b.get("/api/conversations").json()["conversations"]] == []
    a.post("/api/memory", {"text": "ann likes tea"})
    assert b.get("/api/memory").json()["facts"] == []
    fake_turns(monkeypatch, [Turn("ok", provider="gemini", model="m")])
    tid = a.post("/api/agent", {"messages": [{"role": "user", "content": "hi"}]}).json()["task_id"]
    wait(tid)
    assert b.get(f"/api/tasks/{tid}").status_code == 404
    assert b.post(f"/api/tasks/{tid}/cancel").status_code == 404
    assert b.post(f"/api/tasks/{tid}/approve", {"call_id": "x", "approve": True}).status_code == 409
    assert tid not in [t["id"] for t in b.get("/api/tasks").json()["tasks"]]
    assert tid in [t["id"] for t in a.get("/api/tasks").json()["tasks"]]
    # no tenant leaks into a later anonymous request
    assert TestClient(server.app).get("/api/files").status_code == 401
    assert tenancy.current() is None


def test_hosted_agent_gets_only_the_safe_tools_in_its_own_sandbox(monkeypatch):
    s = Session("noor")
    info = s.get("/api/agent/info").json()
    names = {t["name"] for t in info["tools"]}
    assert "run_shell" not in names and "run_app" not in names
    assert not {t["group"] for t in info["tools"]} & {"desktop", "apps", "services"}
    assert not any(t["group"].startswith("mcp") for t in info["tools"])
    assert {"web_search", "fetch_url", "office_create_docx", "archive_extract", "data_query", "write_file"} <= names
    assert info["workspace"] == "your private workspace" and info["extra_roots"] == [] and info["approval_mode"] == "ask"
    assert s.get("/api/settings").json() == {"theme": "dark", "default_mode": "agent", "hosted": True,
                                              "effective_approval_mode": "ask"}
    calls = [{"id": "w1", "name": "write_file", "arguments": {"path": "scratch/note.txt", "content": "hello"}},
             {"id": "r1", "name": "read_file", "arguments": {"path": "../../../accounts.db"}},
             {"id": "r2", "name": "read_file", "arguments": {"path": "~/.ssh/id_rsa"}},
             {"id": "r3", "name": "read_file", "arguments": {"path": "/etc/passwd"}},
             {"id": "s1", "name": "run_shell", "arguments": {"command": "id"}}]
    fake_turns(monkeypatch, [Turn("", calls, "gemini", "m")])
    tid = s.post("/api/agent", {"messages": [{"role": "user", "content": "try things"}]}).json()["task_id"]
    t = wait(tid)
    res = {e["id"]: e for e in t.events if e["type"] == "tool_result"}
    assert res["w1"]["ok"]
    assert (accounts.user_home(s.user.id) / "workspace" / "scratch" / "note.txt").read_text() == "hello"
    for k in ("r1", "r2", "r3"):
        assert not res[k]["ok"], res[k]
    assert not res["s1"]["ok"] and "unknown tool" in res["s1"]["output"]
    # outside a tenant (local mode) the same sandbox functions use the normal workspace again
    assert tenancy.current() is None and sandbox.extra_roots() == []


def test_upload_limits(monkeypatch):
    s = Session("omar")
    monkeypatch.setenv("AUTOMOTO_HOSTED_MAX_UPLOAD_MB", "1")
    import base64
    big = base64.b64encode(b"x" * (1024 * 1024 + 10)).decode()
    assert s.post("/api/files/upload", {"name": "big.txt", "data": big}).status_code == 413
    accounts.set_settings("t", storage_mb=0.001)
    small = base64.b64encode(b"x" * 2000).decode()
    r = s.post("/api/files/upload", {"name": "s.txt", "data": small})
    assert r.status_code == 413 and "storage" in r.json()["detail"]
    assert s.get("/api/me").json()["limits"]["max_upload_mb"] == 1


def test_bootstrap_admin_from_env(monkeypatch):
    monkeypatch.setenv("AUTOMOTO_ADMIN_USER", "Owner")
    monkeypatch.setenv("AUTOMOTO_ADMIN_PASSWORD", PW)
    assert accounts.bootstrap_admin_from_env() == "owner"
    assert accounts.find_user("owner").is_admin
    assert accounts.bootstrap_admin_from_env() is None  # only once


def test_cli_admin_commands(monkeypatch, capsys):
    from automoto import cli
    monkeypatch.setenv("PWVAR", PW)
    assert cli.main(["admin", "create", "yasin", "--password-env", "PWVAR"]) == 0
    assert cli.main(["admin", "create", "pupil", "--password-env", "PWVAR"]) == 0   # not the first: a user
    assert cli.main(["admin", "quota", "pupil", "--minutes", "1"]) == 0
    assert cli.main(["admin", "bonus", "pupil", "15", "--note", "exam week"]) == 0
    assert cli.main(["admin", "suspend", "pupil"]) == 0 and accounts.find_user("pupil").status == "suspended"
    assert cli.main(["admin", "unsuspend", "pupil"]) == 0
    assert cli.main(["admin", "settings", "--default-minutes", "90", "--signup", "closed"]) == 0
    assert cli.main(["admin", "invite", "--uses", "2"]) == 0
    assert cli.main(["admin", "list"]) == 0
    with pytest.raises(SystemExit):
        cli.main(["admin", "delete", "pupil"])  # needs --yes
    assert cli.main(["admin", "delete", "pupil", "--yes"]) == 0 and accounts.find_user("pupil") is None
    assert cli.main(["admin", "audit"]) == 0
    out = capsys.readouterr().out
    assert "created admin 'yasin'" in out and "created user 'pupil'" in out and "invite code" in out and "16.0/" not in out
    q = accounts.quota(accounts.find_user("yasin"))
    assert q["unlimited"]


def test_platform_host_names_are_allowed(monkeypatch):
    from automoto import server
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "automoto-ai.onrender.com")
    monkeypatch.setenv("SPACE_HOST", "https://ymmiah-automoto.hf.space/")
    hosts = server._allowed_hosts()
    assert "automoto-ai.onrender.com" in hosts and "ymmiah-automoto.hf.space" in hosts
    monkeypatch.delenv("RENDER_EXTERNAL_HOSTNAME")
    monkeypatch.delenv("SPACE_HOST")
    assert "automoto-ai.onrender.com" not in server._allowed_hosts()
