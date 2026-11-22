"""V46-V48 PR 2: GitHub/GitLab sign-in with tokens kept only in the OS keychain.

Covers the token vault (fake OS keychain, insecure backends refused, session-only fallback),
validation against allowlisted hosts with a fake provider, scope/expiry warnings, sign-out and
expiry, .env migration, project .env host hardening, redaction of partial/encoded tokens, the
device flow and PKCE code paths (disabled without a client ID), and that a token never shows up in
API responses, logs, files on disk or browser code."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import config, git_auth, home, redaction, server, services

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
API = "/api/developer/studio/account"
GH_FINE = "github_pat_11AAAAAAA0" + "Zq9xW3vB7nK2mL5pR8tY1uI4oP6aS0dF3gH7jK9lZ2xC5vB8nM1qW4eR7tY0uI3oP6aS9dF2gH5jK8l"
GH_CLASSIC = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
GL_PAT = "glpat-" + "x7Yh2Kp9Qw3Er6Ty1Ui4"
STATIC = Path(__file__).resolve().parents[1] / "automoto" / "web" / "static"


class FakeKeychain:
    """Stands in for Windows Credential Manager / macOS Keychain / Secret Service."""
    label = "Windows Credential Manager"

    def __init__(self):
        self.items: dict[tuple[str, str], str] = {}

    def set_password(self, service, user, value):
        self.items[(service, user)] = value

    def get_password(self, service, user):
        return self.items.get((service, user))

    def delete_password(self, service, user):
        self.items.pop((service, user), None)


class FakeProvider:
    """A fake github.com / gitlab.com API. Records every request so tests can check hosts."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.valid = {GH_FINE: "fine", GH_CLASSIC: "classic", GL_PAT: "gl"}
        soon = time.gmtime(time.time() + 30 * 86400)
        self.gh_expiry = time.strftime("%Y-%m-%d 10:00:00 UTC", soon)
        self.gl_self = {"scopes": ["read_user", "read_api", "write_repository"], "expires_at": time.strftime("%Y-%m-%d", soon),
                        "active": True, "revoked": False}
        self.oauth: dict = {}

    def __call__(self, method, url, headers, data=None, allow=()):
        host = urllib.parse.urlsplit(url).hostname
        assert host in allow, f"{host} not in allowlist {allow}"
        assert url.startswith("https://")
        self.calls.append((method, url, dict(headers)))
        tok = (headers.get("Authorization") or "").removeprefix("Bearer ") or headers.get("PRIVATE-TOKEN", "")
        path = urllib.parse.urlsplit(url).path
        if path.endswith("/login/device/code") or path.endswith("/oauth/authorize_device"):
            return 200, {}, json.dumps({"device_code": "dev-123", "user_code": "WDJB-MJHT", "interval": 5,
                                        "expires_in": 900, "verification_uri": f"https://{host}/login/device"}).encode()
        if path.endswith("/login/oauth/access_token") or path.endswith("/oauth/token"):
            form = dict(urllib.parse.parse_qsl((data or b"").decode()))
            self.oauth.setdefault("forms", []).append(form)
            nxt = self.oauth.get("next", [])
            body = nxt.pop(0) if nxt else {"error": "authorization_pending"}
            return 200, {}, json.dumps(body).encode()
        kind = self.valid.get(tok)
        if tok.startswith(("gho_", "ghu_")) or tok.startswith("oauth-gl-"):
            kind = "oauth"
        if not kind:
            return 401, {}, json.dumps({"message": "Bad credentials " + tok}).encode()  # a server echoing the token
        if host == "api.github.com" and path == "/user":
            h = {"X-OAuth-Scopes": "repo, workflow, admin:org"} if kind == "classic" else {}
            if self.gh_expiry:
                h["GitHub-Authentication-Token-Expiration"] = self.gh_expiry
            return 200, h, json.dumps({"id": 7, "login": "octo", "name": "Octo Cat",
                                       "html_url": "https://github.com/octo"}).encode()
        if path == "/api/v4/user":
            return 200, {}, json.dumps({"id": 9, "username": "tanuki", "name": "Tanuki",
                                        "web_url": f"https://{host}/tanuki"}).encode()
        if path == "/api/v4/personal_access_tokens/self":
            return 200, {}, json.dumps(self.gl_self).encode()
        return 404, {}, b"{}"


@pytest.fixture
def kc(monkeypatch):
    k = FakeKeychain()
    monkeypatch.setattr(git_auth, "_backend_override", k)
    yield k
    git_auth._session.clear()
    git_auth._pending.clear()


@pytest.fixture
def prov(monkeypatch):
    p = FakeProvider()
    monkeypatch.setattr(git_auth, "http_call", p)
    return p


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    return TestClient(server.app)


def all_files_text(root: Path) -> str:
    out = []
    for p in root.rglob("*"):
        if p.is_file():
            try:
                out.append(p.read_bytes().decode("utf-8", "ignore"))
            except OSError:
                pass
    return "\n".join(out)


def assert_nowhere(token: str, *texts: str):
    for t in texts:
        assert not redaction.contains_secret(t, token), "token (or an encoded/partial form) leaked"


# ------------------------------------------------------------------ vault
def test_keychain_only_and_masked_handle(kc, prov):
    acct = git_auth.sign_in_with_token("github", "github.com", GH_FINE)
    assert acct["login"] == "octo" and acct["storage"] == "keychain" and acct["handle"] == "ends in " + GH_FINE[-4:]
    stored = kc.items[(git_auth.KEYRING_SERVICE, "github:github.com")]
    assert json.loads(stored)["token"] == GH_FINE
    assert_nowhere(GH_FINE, json.dumps(acct), json.dumps(git_auth.status()), all_files_text(home.base()))
    assert git_auth.token_for("github") == (GH_FINE, "github.com", "fine_grained")


def test_insecure_keyring_backends_are_refused(monkeypatch):
    class PlaintextKeyring:  # what keyrings.alt would give
        pass
    PlaintextKeyring.__module__ = "keyrings.alt.file"
    assert git_auth._secure_label(PlaintextKeyring()) is None

    class Fail:
        pass
    Fail.__module__ = "keyring.backends.fail"
    assert git_auth._secure_label(Fail()) is None

    class WinVaultKeyring:
        pass
    WinVaultKeyring.__module__ = "keyring.backends.Windows"
    assert git_auth._secure_label(WinVaultKeyring()) == "Windows Credential Manager"

    class ChainerBackend:
        backends = [WinVaultKeyring(), PlaintextKeyring()]
    ChainerBackend.__module__ = "keyring.backends.chainer"
    assert git_auth._secure_label(ChainerBackend()) is None  # one insecure member spoils the chain


def test_no_keychain_needs_consent_then_session_only(monkeypatch, prov):
    monkeypatch.setattr(git_auth, "_backend_override", None)
    monkeypatch.setattr(git_auth, "_backend", lambda: (None, None))
    with pytest.raises(git_auth.AuthError) as e:
        git_auth.sign_in_with_token("github", None, GH_FINE)
    assert e.value.code == "no_keychain" and not git_auth.accounts()
    acct = git_auth.sign_in_with_token("github", None, GH_FINE, session_only=True)
    assert acct["storage"] == "session"
    assert_nowhere(GH_FINE, all_files_text(home.base()))
    git_auth._session.clear()  # the app closed
    assert git_auth.accounts() == [] and git_auth.token_for("github") is None


# ------------------------------------------------------------------ validation and warnings
def test_classic_token_and_broad_scopes_warned(kc, prov):
    acct = git_auth.sign_in_with_token("github", None, GH_CLASSIC)
    codes = {w["code"] for w in acct["warnings"]}
    assert {"classic", "broad_scopes"} <= codes and acct["scopes"] == ["repo", "workflow", "admin:org"]


def test_no_expiry_warned(kc, prov):
    prov.gh_expiry = None
    acct = git_auth.sign_in_with_token("github", None, GH_FINE)
    assert "no_expiry" in {w["code"] for w in acct["warnings"]} and acct["expires_at"] is None


def test_gitlab_scopes_expiry_and_api_scope_warning(kc, prov):
    acct = git_auth.sign_in_with_token("gitlab", "gitlab.com", GL_PAT)
    assert acct["login"] == "tanuki" and acct["scopes"] == ["read_user", "read_api", "write_repository"]
    assert acct["expires_at"].startswith(prov.gl_self["expires_at"]) and not acct["warnings"] and acct["days_left"] in (29, 30)
    prov.gl_self = {**prov.gl_self, "scopes": ["api", "sudo"], "expires_at": None}
    acct = git_auth.sign_in_with_token("gitlab", "gitlab.com", GL_PAT)
    assert {"broad_scopes", "no_expiry"} <= {w["code"] for w in acct["warnings"]}
    assert prov.calls[0][2].get("PRIVATE-TOKEN") == GL_PAT and "Authorization" not in prov.calls[0][2]


def test_bad_tokens_rejected_without_echo(kc, prov):
    bad = "github_pat_" + "Q" * 70
    with pytest.raises(git_auth.AuthError) as e:
        git_auth.sign_in_with_token("github", None, bad)
    assert e.value.code == "invalid" and bad not in str(e.value)
    for wrong in ("hello", "ghs_" + "a" * 36):
        with pytest.raises(git_auth.AuthError):
            git_auth.sign_in_with_token("github", None, wrong)
    with pytest.raises(git_auth.AuthError):
        git_auth.sign_in_with_token("gitlab", None, GH_FINE)  # a GitHub token pasted under GitLab


def test_only_allowlisted_hosts(kc, prov, monkeypatch):
    with pytest.raises(git_auth.AuthError) as e:
        git_auth.sign_in_with_token("gitlab", "evil.example", GL_PAT)
    assert e.value.code == "host_not_allowed" and not prov.calls
    for bad in ("http://gitlab.example.com", "10.0.0.5", "localhost", "gitlab.local", "https://u:p@gitlab.example.com",
                "github.com", "gitlab.example.com:8443"):
        with pytest.raises(git_auth.AuthError):
            git_auth.add_host(bad, resolve=False)
    assert git_auth.add_host("https://GitLab.Example.com/", resolve=False) == ["gitlab.com", "gitlab.example.com"]
    acct = git_auth.sign_in_with_token("gitlab", "gitlab.example.com", GL_PAT)
    assert acct["host"] == "gitlab.example.com"
    assert all(urllib.parse.urlsplit(u).hostname == "gitlab.example.com" for _, u, _ in prov.calls[-2:])
    git_auth.remove_host("gitlab.example.com")
    assert git_auth.account("gitlab", "gitlab.example.com") is None
    assert (git_auth.KEYRING_SERVICE, "gitlab:gitlab.example.com") not in kc.items


def test_netguard_allow_hosts_refuses_before_dns(monkeypatch):
    from automoto import netguard

    looked = []
    monkeypatch.setattr(netguard.socket, "getaddrinfo", lambda *a, **k: looked.append(a) or [])
    with pytest.raises(netguard.BlockedURL):
        netguard.request("https://evil.example/x", allow_hosts={"api.github.com"})
    with pytest.raises(netguard.BlockedURL):
        netguard.request("http://api.github.com/x", allow_hosts={"api.github.com"})
    assert looked == []


# ------------------------------------------------------------------ sign-out, expiry
def test_sign_out_and_revoke_help(kc, prov):
    git_auth.sign_in_with_token("github", None, GH_FINE)
    out = git_auth.sign_out("github", None)
    assert out["revoke"]["url"] == "https://github.com/settings/personal-access-tokens"
    assert not kc.items and git_auth.accounts() == [] and git_auth.token_for("github") is None
    git_auth.sign_in_with_token("gitlab", None, GL_PAT)
    git_auth.sign_in_with_token("github", None, GH_FINE)
    git_auth.sign_out_all()
    assert not kc.items and git_auth.accounts() == []


def test_revoked_token_marks_expired_and_wipes_secret(kc, prov):
    git_auth.sign_in_with_token("github", None, GH_FINE)
    prov.valid.pop(GH_FINE)  # deleted on github.com
    with pytest.raises(git_auth.AuthError) as e:
        git_auth.check("github", None)
    assert e.value.code == "invalid"
    a = git_auth.account("github", "github.com")
    assert a["status"] == "expired" and not kc.items and git_auth.token_for("github") is None


def test_expiry_date_passing_is_handled(kc, prov):
    git_auth.sign_in_with_token("github", None, GH_FINE)
    items = git_auth._index()
    items[0]["expires_at"] = "2020-01-01T00:00:00Z"
    git_auth._save_index(items)
    assert git_auth.account("github", "github.com")["status"] == "expired"
    assert git_auth.token_for("github") is None


# ------------------------------------------------------------------ .env migration and hardening
def test_migrate_plaintext_env_token(kc, prov, monkeypatch, tmp_path):
    envf = home.base() / ".env"
    envf.write_text(f"OPENAI_API_KEY=keep-me\nGITHUB_TOKEN={GH_FINE}\nexport GH_TOKEN={GH_FINE}\n", "utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", GH_FINE)
    monkeypatch.setenv("GH_TOKEN", GH_FINE)
    monkeypatch.setitem(config.ENV_SOURCES, "GITHUB_TOKEN", (str(envf), GH_FINE))
    monkeypatch.setitem(config.ENV_SOURCES, "GH_TOKEN", (str(envf), GH_FINE))
    found = git_auth.env_tokens()
    assert {f["var"] for f in found} == {"GITHUB_TOKEN", "GH_TOKEN"} and all(f["can_remove"] for f in found)
    assert_nowhere(GH_FINE, json.dumps(found))
    out = git_auth.migrate("GITHUB_TOKEN")
    assert out["removed_from_file"] and envf.read_text("utf-8") == "OPENAI_API_KEY=keep-me\n"
    assert "GITHUB_TOKEN" not in os.environ and "GH_TOKEN" not in os.environ
    assert git_auth.token_for("github")[0] == GH_FINE
    assert_nowhere(GH_FINE, json.dumps(out), all_files_text(home.base()))


def test_project_env_cannot_redirect_gitlab(kc, prov, monkeypatch, tmp_path):
    proj = tmp_path / "evil-repo" / ".env"
    proj.parent.mkdir()
    proj.write_text("GITLAB_URL=https://attacker.example\n")
    monkeypatch.setenv("GITLAB_URL", "https://attacker.example")
    monkeypatch.setitem(config.ENV_SOURCES, "GITLAB_URL", (str(proj), "https://attacker.example"))
    assert config.env_trusted("GITLAB_URL") is None
    git_auth.sign_in_with_token("gitlab", None, GL_PAT)
    tok, base, auth = services._resolve(services.SERVICES["gitlab"], None)
    assert base == "https://gitlab.com/api/v4" and tok == GL_PAT
    # set by the user in ~/.automoto/.env it is honoured, but only for a host on the allowlist
    own = home.base() / ".env"
    own.write_text("GITLAB_URL=https://gitlab.mycorp.example\n")
    monkeypatch.setitem(config.ENV_SOURCES, "GITLAB_URL", (str(own), "https://attacker.example"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.mycorp.example")
    monkeypatch.setitem(config.ENV_SOURCES, "GITLAB_URL", (str(own), "https://gitlab.mycorp.example"))
    with pytest.raises(services.ServiceError):
        services._resolve(services.SERVICES["gitlab"], None)
    git_auth.add_host("gitlab.mycorp.example", resolve=False)
    assert services._resolve(services.SERVICES["gitlab"], None)[1] == "https://gitlab.mycorp.example/api/v4"


def test_browser_keys_ignored_for_git_services(kc, prov):
    svc = services.SERVICES["github"]
    assert services.token(svc, {"github": GH_FINE}) is None  # BYOK tab keys never used for GitHub
    git_auth.sign_in_with_token("github", None, GH_FINE)
    assert services.token(svc, {"github": "something-else"}) == GH_FINE


def test_services_call_uses_vault_and_redacts(kc, prov, monkeypatch):
    from automoto import netguard

    git_auth.sign_in_with_token("gitlab", None, GL_PAT)
    seen = {}

    def fake(url, **kw):
        seen.update(url=url, **kw)
        body = json.dumps({"echo": GL_PAT[:14] + "…", "b64": base64.b64encode(("oauth2:" + GL_PAT).encode()).decode()})
        return netguard.Response(url, 200, "application/json", body.encode())

    monkeypatch.setattr(netguard, "request", fake)
    out = services.call("gitlab", "GET", "/projects")
    assert seen["allow_hosts"] == {"gitlab.com"} and seen["headers"]["PRIVATE-TOKEN"] == GL_PAT
    assert_nowhere(GL_PAT, out)
    assert "glpat-" not in out


def test_hosted_mode_never_uses_keychain(kc, prov, monkeypatch):
    git_auth.sign_in_with_token("github", None, GH_FINE)
    monkeypatch.setattr(git_auth, "_hosted", lambda: True)
    assert git_auth.token_for("github") is None


# ------------------------------------------------------------------ redaction
@pytest.mark.parametrize("tok", [GH_FINE, GH_CLASSIC, GL_PAT, "gho_" + "x" * 36, "ghu_" + "y" * 36, "ghr_" + "z" * 36,
                                 "gloas-" + "a" * 30, "glrt-" + "b" * 20, "glptt-" + "c" * 30])
def test_redaction_patterns(tok):
    assert tok[:6] not in redaction.redact(f"x {tok} y")
    assert redaction.redact(tok[:12] + "…") == "[redacted]…"  # partial form


def test_redaction_of_known_secret_variants():
    secret = "github_pat_" + "k" * 10 + "Mx81Qz0Lp4Tr7Ws2Vn5Bj9Hc3Fg6Dy1Ae8Ku0Io3Pl6Zm9Xn2Cb5Vq8"
    redaction.register(secret)
    forms = [secret, urllib.parse.quote(secret, safe=""), "".join(f"%{b:02x}" for b in secret.encode()),
             base64.b64encode(("x-access-token:" + secret).encode()).decode(),
             base64.b64encode(secret.encode()).decode(), "AB" + base64.b64encode(b"zz" + secret.encode()).decode(),
             secret[:40] + "\n" + secret[40:], secret[20:50], secret.encode().hex()]
    for f in forms:
        assert_nowhere(secret, redaction.redact("before " + f + " after"))
    assert redaction.redact("commit 3f2a9b1c4d5e6f708192a3b4c5d6e7f8091a2b3c ok") == \
        "commit 3f2a9b1c4d5e6f708192a3b4c5d6e7f8091a2b3c ok"
    redaction.forget(secret)


def test_log_records_are_scrubbed(caplog, kc, prov):
    caplog.set_level(logging.DEBUG)
    git_auth.sign_in_with_token("github", None, GH_FINE)
    log = logging.getLogger("automoto.test")
    log.warning("token was %s", GH_FINE)
    log.info("encoded %s", urllib.parse.quote(GH_FINE))
    try:
        raise RuntimeError("boom " + GH_FINE)
    except RuntimeError:
        log.exception("failed")
    text = caplog.text + "\n".join(r.getMessage() + str(r.exc_text) for r in caplog.records)
    assert_nowhere(GH_FINE, text)
    assert "[redacted]" in text


# ------------------------------------------------------------------ HTTP API: no token in any response
def test_api_flow_never_returns_token(kc, prov, client, caplog):
    caplog.set_level(logging.DEBUG)
    st = client.get(API + "/status", headers=AUTH).json()
    assert st["keychain"]["available"] and st["flows"] == {"github_device": False, "gitlab_pkce": False,
                                                           "gitlab_device": False}
    assert st["token_pages"]["github"]["url"].startswith("https://github.com/settings/personal-access-tokens/new?")
    assert "contents=write" in st["token_pages"]["github"]["url"] and "workflows" not in st["token_pages"]["github"]["url"]
    assert "scopes=read_user%2Cread_api%2Cwrite_repository" in st["token_pages"]["gitlab:gitlab.com"]["url"]
    responses = []
    r = client.post(API + "/token", headers=AUTH, json={"provider": "github", "token": GH_FINE})
    assert r.status_code == 200, r.text
    responses.append(r.text)
    responses.append(client.get(API + "/status", headers=AUTH).text)
    responses.append(client.post(API + "/check", headers=AUTH, json={"provider": "github"}).text)
    bad = client.post(API + "/token", headers=AUTH, json={"provider": "github", "token": GH_FINE[:-6] + "ZZZZZZ"})
    assert bad.status_code == 401 and bad.json()["detail"]["code"] == "invalid"
    responses.append(bad.text)
    weird = client.post(API + "/token", headers=AUTH, json={"provider": "github", "token": GH_FINE + " " * 500 + "x"})
    assert weird.status_code == 400
    responses.append(weird.text)
    typed = client.post(API + "/token", headers=AUTH, json={"provider": 5, "token": [GH_FINE]})
    responses.append(typed.text)
    responses.append(client.post(API + "/signout", headers=AUTH, json={"provider": "github"}).text)
    assert_nowhere(GH_FINE, *responses, caplog.text, all_files_text(home.base()))


def test_api_needs_session_and_is_local_only(client, kc):
    assert client.get(API + "/status").status_code == 403
    assert client.post(API + "/token", json={"provider": "github", "token": GH_FINE}).status_code == 403


def test_api_hosts_and_flows_disabled(client, kc, prov, monkeypatch):
    monkeypatch.setattr(git_auth.netguard, "check_url", lambda url: (None, "1.2.3.4"))
    r = client.post(API + "/hosts", headers=AUTH, json={"action": "add", "host": "gitlab.example.org"})
    assert r.json()["gitlab"] == ["gitlab.com", "gitlab.example.org"]
    r = client.post(API + "/device/start", headers=AUTH, json={"provider": "github"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "flow_disabled"
    assert client.post(API + "/pkce/start", headers=AUTH, json={}).status_code == 409


# ------------------------------------------------------------------ device flow and PKCE (enabled by a client ID)
def test_device_flow_github(kc, prov, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_GITHUB_CLIENT_ID", "Iv23liTestClient01")
    assert git_auth.flows()["github_device"]
    start = git_auth.device_start("github")
    assert start["user_code"] == "WDJB-MJHT" and "device_code" not in json.dumps(start)
    fid = start["flow_id"]
    git_auth._pending[fid]["next"] = 0
    assert git_auth.device_poll(fid)["status"] == "pending"
    git_auth._pending[fid]["next"] = 0
    prov.oauth["next"] = [{"error": "slow_down"}]
    assert git_auth.device_poll(fid)["interval"] == 10
    git_auth._pending[fid]["next"] = 0
    access, refresh = "ghu_" + "R" * 36, "ghr_" + "S" * 70
    prov.oauth["next"] = [{"access_token": access, "refresh_token": refresh, "expires_in": 28800}]
    done = git_auth.device_poll(fid)
    assert done["status"] == "done" and done["account"]["handle"] == "browser sign-in"
    assert all("client_secret" not in f for f in prov.oauth["forms"])
    assert_nowhere(access, json.dumps(done))
    assert_nowhere(refresh, json.dumps(done), all_files_text(home.base()))
    # refresh without a client secret, rotating the pair (new one saved before the old one is dropped)
    items = git_auth._index()
    items[0]["expires_at"] = git_auth._iso(git_auth._now())
    git_auth._save_index(items)
    rec = json.loads(kc.items[(git_auth.KEYRING_SERVICE, "github:github.com")])
    rec["access_expires"] = items[0]["expires_at"]
    kc.items[(git_auth.KEYRING_SERVICE, "github:github.com")] = json.dumps(rec)
    new_access = "ghu_" + "T" * 36
    prov.oauth["next"] = [{"access_token": new_access, "refresh_token": "ghr_" + "U" * 70, "expires_in": 28800}]
    assert git_auth.token_for("github")[0] == new_access
    assert prov.oauth["forms"][-1]["grant_type"] == "refresh_token" and "client_secret" not in prov.oauth["forms"][-1]


@pytest.mark.parametrize("err,code", [("expired_token", "expired_token"), ("access_denied", "access_denied")])
def test_device_flow_errors(kc, prov, monkeypatch, err, code):
    monkeypatch.setenv("AUTOMOTO_GITHUB_CLIENT_ID", "Iv23liTestClient01")
    fid = git_auth.device_start("github")["flow_id"]
    git_auth._pending[fid]["next"] = 0
    prov.oauth["next"] = [{"error": err}]
    with pytest.raises(git_auth.AuthError) as e:
        git_auth.device_poll(fid)
    assert e.value.code == code


def test_client_id_from_project_env_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOMOTO_GITHUB_CLIENT_ID", "Iv23liEvilClient01")
    monkeypatch.setitem(config.ENV_SOURCES, "AUTOMOTO_GITHUB_CLIENT_ID", (str(tmp_path / ".env"), "Iv23liEvilClient01"))
    assert git_auth.client_id("github") is None and not git_auth.flows()["github_device"]


def test_pkce_pair_rfc7636():
    v, c = git_auth.pkce_pair()
    assert 43 <= len(v) <= 128 and re.fullmatch(r"[A-Za-z0-9\-._~]+", v)
    assert c == base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")


def test_pkce_loopback_flow(kc, prov, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_GITLAB_CLIENT_ID", "a" * 64)
    start = git_auth.pkce_start(None, port=0, timeout=20)
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(start["authorize_url"]).query))
    assert q["code_challenge_method"] == "S256" and q["redirect_uri"].startswith("http://127.0.0.1:")
    assert "client_secret" not in start["authorize_url"]
    port = urllib.parse.urlsplit(q["redirect_uri"]).port
    # a wrong state is refused and doesn't finish the flow
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/automoto/callback?code=x&state=wrong", timeout=5)
    assert git_auth.pkce_poll(start["flow_id"])["status"] == "pending"
    urllib.request.urlopen(f"http://127.0.0.1:{port}/automoto/callback?code=good&state={q['state']}", timeout=5).read()
    prov.oauth["next"] = [{"access_token": "oauth-gl-" + "Q" * 40, "refresh_token": "r" * 40, "expires_in": 7200}]
    done = git_auth.pkce_poll(start["flow_id"])
    assert done["status"] == "done" and done["account"]["login"] == "tanuki"
    form = prov.oauth["forms"][-1]
    assert form["code"] == "good" and form["code_verifier"] and form["grant_type"] == "authorization_code"
    assert hashlib.sha256(form["code_verifier"].encode()).digest() == \
        base64.urlsafe_b64decode(q["code_challenge"] + "=" * (-len(q["code_challenge"]) % 4))
    hdrs = next(h for _, u, h in reversed(prov.calls) if u.endswith("/api/v4/user"))
    assert hdrs["Authorization"].startswith("Bearer ") and "PRIVATE-TOKEN" not in hdrs  # OAuth uses Bearer


# ------------------------------------------------------------------ browser code never stores tokens
def test_browser_code_keeps_tokens_out_of_storage():
    acct = (STATIC / "developer-account.js").read_text("utf-8")
    code = re.sub(r"/\*[\s\S]*?\*/", "", acct)
    assert "localStorage" not in code and "sessionStorage" not in code and "indexedDB" not in code
    assert 'inp.type="password"' in code and 'inp.value=""' in code
    assert "inp.dataset.sensitive" in acct and 'inp.autocomplete="off"' in acct
    app = (STATIC / "app.js").read_text("utf-8")
    assert 'const GIT_KEY_IDS = ["github", "gitlab"' in app and "!GIT_KEY_IDS.includes(n)" in app
    studio = (STATIC / "developer-studio.js").read_text("utf-8")
    assert "mountDeveloperAccount" in studio and 'id="dsAccountRoot"' in studio
    simple = (STATIC / "developer-simple.js").read_text("utf-8")
    assert '["account","Connect GitHub or GitLab"' in simple


def test_redaction_leaves_ordinary_code_alone():
    text = ("from huggingface_hub import hf_hub_download\nnpm_config_cache=/tmp\nclass task-list sk-learn\n"
            "sha 3f2a9b1c4d5e6f708192a3b4c5d6e7f8091a2b3c uuid 123e4567-e89b-12d3-a456-426614174000\n"
            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
    assert redaction.redact(text) == text
