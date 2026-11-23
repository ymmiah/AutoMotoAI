"""V46-V48 PR 3: Share (push) and Get latest against a local fake Git server.

The fake server runs ``git http-backend`` behind HTTP Basic auth on 127.0.0.1, so the real Git
client, the single-use credential helper and the broker are exercised end to end. Failure
injection covers every fallback path (401, 403, protected branch, push protection, network,
non-fast-forward, expired token, classic token, server garbage), and every test checks that the
token never lands in .git/config, the reflog, logs, the audit file, the patch or the API answers."""
from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import developer_remote as remote
from automoto import git_auth, redaction, sandbox, secretscan, server

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
API = "/api/developer/studio/remote"
GH_FINE = "github_pat_11CCCCCCC0" + "Rt5nQ8wE2rT6yU9iO3pA7sD1fG4hJ8kL2zX6cV0bN3mQ7wE1rT5yU8iO2pA6sD9fG3hJ7kL1zX4cV8"
GH_CLASSIC = "ghp_" + "Mn8Bv7Cx6Za5Sd4Fg3Hj2Kl1Qw9Er8Ty7Ui6"
GL_PAT = "glpat-" + "Vb4Nm8Qa2Ws6Ed0Rf3Tg"
FAKE_AWS = "AKIA" + "Q3EGHT7MZW5XJ2KP"


# ------------------------------------------------------------------ fakes
class FakeKeychain:
    label = "Windows Credential Manager"

    def __init__(self):
        self.items = {}

    def set_password(self, s, u, v):
        self.items[(s, u)] = v

    def get_password(self, s, u):
        return self.items.get((s, u))

    def delete_password(self, s, u):
        self.items.pop((s, u), None)


class FakeAPI:
    """github.com / gitlab.com REST: just enough for sign-in and repository facts."""

    def __init__(self):
        self.calls = []
        self.protected = set()
        self.default_branch = "main"
        self.can_push = True
        self.gh_expiry = time.strftime("%Y-%m-%d 10:00:00 UTC", time.gmtime(time.time() + 30 * 86400))

    def __call__(self, method, url, headers, data=None, allow=()):
        host = urllib.parse.urlsplit(url).hostname
        assert host in allow and url.startswith("https://")
        self.calls.append((method, url))
        tok = (headers.get("Authorization") or "").removeprefix("Bearer ") or headers.get("PRIVATE-TOKEN", "")
        if tok not in (GH_FINE, GH_CLASSIC, GL_PAT):
            return 401, {}, b'{"message":"Bad credentials"}'
        path = urllib.parse.urlsplit(url).path
        if path == "/user":
            h = {"GitHub-Authentication-Token-Expiration": self.gh_expiry}
            if tok == GH_CLASSIC:
                h["X-OAuth-Scopes"] = "repo"
            return 200, h, json.dumps({"id": 7, "login": "octo", "html_url": "https://github.com/octo"}).encode()
        if path == "/api/v4/user":
            return 200, {}, json.dumps({"id": 9, "username": "tanuki", "web_url": "https://gitlab.com/tanuki"}).encode()
        if path == "/api/v4/personal_access_tokens/self":
            return 200, {}, json.dumps({"scopes": ["read_user", "read_api", "write_repository"],
                                        "expires_at": time.strftime("%Y-%m-%d", time.gmtime(time.time() + 9e5)),
                                        "active": True}).encode()
        if path.startswith("/repos/") and "/branches/" in path:
            b = urllib.parse.unquote(path.split("/branches/", 1)[1])
            return 200, {}, json.dumps({"name": b, "protected": b in self.protected}).encode()
        if path.startswith("/repos/"):
            repo = path[len("/repos/"):]
            if repo == "octo/missing":
                return 404, {}, b"{}"
            # Untrusted website text: the name carries escape codes and markup.
            return 200, {}, json.dumps({"full_name": repo + "\x1b[31m<b>x</b>", "default_branch": self.default_branch,
                                        "private": True, "permissions": {"push": self.can_push}}).encode()
        if "/repository/branches/" in path:
            b = urllib.parse.unquote(path.split("/repository/branches/", 1)[1])
            return 200, {}, json.dumps({"name": b, "protected": b in self.protected}).encode()
        if path.startswith("/api/v4/projects/"):
            return 200, {}, json.dumps({"path_with_namespace": urllib.parse.unquote(path.split("/projects/")[1]),
                                        "default_branch": self.default_branch,
                                        "permissions": {"project_access": {"access_level": 40}}}).encode()
        return 404, {}, b"{}"


def _git(cwd, *args, check=True):
    # core.autocrlf=false: match the engine, which ignores the system config Git for Windows ships with.
    return subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "core.autocrlf=false",
                           "-c", "init.defaultBranch=main", "-c", "protocol.file.allow=always", *args],
                          cwd=cwd, capture_output=True, text=True, check=check)


class GitServer:
    """git http-backend behind Basic auth, with failure injection."""

    def __init__(self, root: Path, token: str):
        self.root = root
        self.token = token
        self.mode = "ok"
        self.auth_seen: list[str] = []
        self.requests: list[str] = []
        root.mkdir(parents=True, exist_ok=True)
        srv = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                return

            def do_GET(self):
                srv.handle(self)

            def do_POST(self):
                srv.handle(self)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def bare(self, repo="octo/app") -> Path:
        p = self.root / (repo + ".git")
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            _git(self.root, "init", "--bare", "-q", str(p))
            _git(p, "config", "http.receivepack", "true")
        return p

    def hook(self, repo, script: str):
        h = self.bare(repo) / "hooks" / "pre-receive"
        h.write_text("#!/bin/sh\n" + script + "\n")
        h.chmod(0o755)

    def handle(self, req: BaseHTTPRequestHandler):
        self.requests.append(req.path)
        if self.mode == "drop":
            req.close_connection = True
            try:
                req.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return
        if self.mode == "500":
            req.send_response(500)
            req.end_headers()
            return
        auth = req.headers.get("Authorization", "")
        if not auth.startswith("Basic "):
            req.send_response(401)
            req.send_header("WWW-Authenticate", 'Basic realm="fake"')
            req.end_headers()
            return
        user, _, pw = base64.b64decode(auth[6:]).decode().partition(":")
        self.auth_seen.append(user)
        if pw != self.token or self.mode == "401":
            req.send_response(401)
            req.send_header("WWW-Authenticate", 'Basic realm="fake"')
            req.end_headers()
            return
        if self.mode == "403":
            req.send_response(403)
            req.end_headers()
            req.wfile.write(b"Permission to octo/app.git denied to octo.")
            return
        if self.mode == "garbage":
            req.send_response(200)
            req.send_header("Content-Type", "application/x-git-receive-pack-advertisement")
            req.end_headers()
            req.wfile.write(b"zzzz not a pkt line")
            return
        path, _, query = req.path.partition("?")
        length = int(req.headers.get("Content-Length") or 0)
        if req.headers.get("Transfer-Encoding", "").lower() == "chunked":
            body = b""
            while True:
                size = int(req.rfile.readline().strip(), 16)
                if size == 0:
                    req.rfile.readline()
                    break
                body += req.rfile.read(size)
                req.rfile.readline()
        else:
            body = req.rfile.read(length) if length else b""
        env = {"PATH": os.environ.get("PATH", ""), "GIT_PROJECT_ROOT": str(self.root), "GIT_HTTP_EXPORT_ALL": "1",
               "PATH_INFO": path, "QUERY_STRING": query, "REQUEST_METHOD": req.command, "REMOTE_USER": user,
               "REMOTE_ADDR": "127.0.0.1", "CONTENT_TYPE": req.headers.get("Content-Type", ""),
               "CONTENT_LENGTH": str(len(body)), "HTTP_CONTENT_ENCODING": req.headers.get("Content-Encoding", ""),
               "GIT_PROTOCOL": req.headers.get("Git-Protocol", "")}
        out = subprocess.run(["git", "http-backend"], input=body, env=env, capture_output=True).stdout
        head, _, rest = out.partition(b"\r\n\r\n")
        if not rest and b"\n\n" in out:
            head, _, rest = out.partition(b"\n\n")
        status = 200
        hdrs = []
        for line in head.decode("latin-1").splitlines():
            k, _, v = line.partition(":")
            if k.lower() == "status":
                status = int(v.strip().split()[0])
            elif k:
                hdrs.append((k, v.strip()))
        req.send_response(status)
        for k, v in hdrs:
            req.send_header(k, v)
        req.end_headers()
        req.wfile.write(rest)

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


# ------------------------------------------------------------------ fixtures
@pytest.fixture
def world(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    kc = FakeKeychain()
    monkeypatch.setattr(git_auth, "_backend_override", kc)
    api = FakeAPI()
    monkeypatch.setattr(git_auth, "http_call", api)
    gs = GitServer(tmp_path / "srv", GH_FINE)
    gs.bare("octo/app")
    monkeypatch.setattr(remote, "_allow_http_loopback", True)
    monkeypatch.setattr(remote, "transport_url", lambda p, h, r: f"http://127.0.0.1:{gs.port}/{r}.git")
    patches = tmp_path / "Documents" / "AutoMoto" / "patches"
    patches.mkdir(parents=True)
    monkeypatch.setattr(remote, "patch_dir", lambda: patches)
    client = TestClient(server.app)
    w = type("W", (), {})()
    w.client, w.api, w.gs, w.kc, w.patches, w.tmp, w.caplog = client, api, gs, kc, patches, tmp_path, caplog
    yield w
    gs.close()
    git_auth._session.clear()
    remote._PLANS.clear()
    for t in (GH_FINE, GH_CLASSIC, GL_PAT):
        redaction.forget(t)


def project(w, name="app", files=None, trust=True) -> Path:
    root = sandbox.default_root() / name
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    for rel, text in (files or {"README.md": "hello\n"}).items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(text) if isinstance(text, bytes) else f.write_text(text)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "First checkpoint")
    if trust:
        r = w.client.post("/api/developer/studio/trust", headers=AUTH,
                          json={"project": str(root), "trusted": True, "confirmed": True})
        assert r.status_code == 200, r.text
    return root


def commit(root, rel, text, msg="Change"):
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(text) if isinstance(text, bytes) else f.write_text(text)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)


def signin(token=GH_FINE, provider="github"):
    return git_auth.sign_in_with_token(provider, None, token)


def post(w, route, root, **body):
    return w.client.post(API + route, headers=AUTH, json={"project": str(root), **body})


def pick(w, root, repo="octo/app", provider="github"):
    r = post(w, "/target", root, provider=provider, repo=repo)
    assert r.status_code == 200, r.text
    return r.json()


def do_plan(w, root, **kw):
    r = post(w, "/plan", root, **kw)
    assert r.status_code == 200, r.text
    return r.json()


def do_share(w, root, p, **kw):
    r = post(w, "/share", root, action_sha256=p["action_sha256"], confirmed=True,
             remote_branch=p["remote_branch"], **kw)
    assert r.status_code == 200, r.text
    return r.json()


def everything_text(w, root) -> str:
    out = []
    for base in (root / ".git", w.gs.root, w.patches, Path(os.environ["AUTOMOTO_DATA_DIR"])):
        for p in base.rglob("*"):
            if p.is_file():
                try:
                    out.append(p.read_bytes().decode("latin-1"))
                except OSError:
                    pass
    out.append(_git(root, "reflog", "--all", check=False).stdout)
    out.append(_git(root, "config", "--list", "--show-origin", check=False).stdout)
    out.append(w.caplog.text)
    return "\n".join(out)


def assert_no_token(w, root, *extra: str, token=GH_FINE):
    blob = everything_text(w, root) + "\n".join(extra)
    assert not redaction.contains_secret(blob, token), "token leaked"
    assert token not in blob


# ------------------------------------------------------------------ the happy path
def test_share_new_repo_end_to_end_and_token_never_lands_anywhere(world, monkeypatch):
    w = world
    signin()
    root = project(w)
    config_before = (root / ".git" / "config").read_bytes()
    seen = []
    real_run = subprocess.run

    def spy(argv, *a, **kw):
        if isinstance(argv, list) and argv and Path(str(argv[0])).stem.lower() == "git":
            seen.append((list(argv), dict(kw.get("env") or {})))
        return real_run(argv, *a, **kw)

    monkeypatch.setattr(remote.subprocess, "run", spy)
    t = pick(w, root)
    assert t["repo"] == "octo/app" and "\x1b" not in json.dumps(t)
    p = do_plan(w, root)
    assert p["ok"], p["blocks"]
    assert p["state"] == "new_branch" and p["commit_count"] == 1 and p["commits"][0]["subject"] == "First checkpoint"
    assert p["files"] == [{"path": "README.md", "change": "added"}]
    assert any(x["rule"] == "default_branch" for x in p["warnings"])  # main is the default branch
    out = do_share(w, root, p)
    assert out["ok"] and out["shared"] == 1 and out["links"]["branch"].endswith("/tree/main")
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    assert _git(w.gs.bare(), "rev-parse", "refs/heads/main").stdout.strip() == head
    assert w.gs.auth_seen and set(w.gs.auth_seen) == {"x-access-token"}
    # Nothing written to the repo's settings, no remote added, no token anywhere.
    assert (root / ".git" / "config").read_bytes() == config_before
    assert _git(root, "remote").stdout.strip() == ""
    for argv, env in seen:
        assert GH_FINE not in " ".join(argv) and GH_FINE not in json.dumps(env)
        assert not any("insteadOf" in a for a in argv)
        assert "--force" not in argv and not any(a.startswith("+") for a in argv if ":refs/heads/" in a)
    push = [a for a, _ in seen if "push" in a]
    assert push and any(x.endswith(":refs/heads/main") and not x.startswith("+") for x in push[0])
    assert_no_token(w, root, json.dumps(p), json.dumps(out))
    audit = remote.audit_tail(str(root))
    assert [a["action"] for a in audit][:2] == ["share", "check"] and audit[0]["result"] == "ok"


def test_share_fast_forward_then_up_to_date(world):
    w = world
    signin()
    root = project(w)
    pick(w, root)
    do_share(w, root, do_plan(w, root))
    commit(root, "a.txt", "one\n", "Second")
    p = do_plan(w, root)
    assert p["state"] == "fast_forward" and p["commit_count"] == 1 and p["commits"][0]["subject"] == "Second"
    assert do_share(w, root, p)["ok"]
    p = do_plan(w, root)
    assert p["state"] == "up_to_date" and not p["ok"]


def test_status_counts_checkpoints_not_shared_yet_offline(world, monkeypatch):
    """The workspace strip: how many checkpoints aren't on the website yet, from local facts only."""
    w = world
    signin()
    root = project(w)
    sync = lambda: w.client.get(API + "/status", params={"project": str(root)}, headers=AUTH).json()["sync"]
    assert sync() == {"state": "never_shared", "unshared": 1, "branch": "main", "dirty": False}
    pick(w, root)
    do_share(w, root, do_plan(w, root))
    assert sync()["state"] == "shared" and sync()["unshared"] == 0
    commit(root, "a.txt", "one\n", "Second")
    commit(root, "b.txt", "two\n", "Third")
    (root / "c.txt").write_text("unsaved\n", encoding="utf-8")
    # Counting never touches the network.
    monkeypatch.setattr(remote, "net_git", lambda *a, **k: pytest.fail("status must stay offline"))
    monkeypatch.setattr(git_auth, "http_call", lambda *a, **k: pytest.fail("status must stay offline"))
    assert sync() == {"state": "ahead", "unshared": 2, "branch": "main", "dirty": True}


def test_share_to_a_new_branch_counts_only_new_commits_and_gives_review_link(world):
    w = world
    signin()
    root = project(w)
    pick(w, root)
    do_share(w, root, do_plan(w, root))
    _git(root, "switch", "-q", "-c", "feature/x")
    commit(root, "f.txt", "f\n", "Feature")
    p = do_plan(w, root)
    assert p["state"] == "new_branch" and p["commit_count"] == 1 and not p["warnings"]
    out = do_share(w, root, p)
    assert out["links"]["review"].endswith("/compare/main...feature/x?expand=1")


def test_protected_branch_warning_and_suggestion(world):
    w = world
    signin()
    w.api.protected.add("release")
    root = project(w)
    _git(root, "switch", "-q", "-c", "release")
    pick(w, root)
    p = do_plan(w, root)
    assert any(x["rule"] == "protected_branch" and x["amber"] for x in p["warnings"])
    assert p["suggest_branch"].startswith("automoto/")


def test_stale_approval_is_rejected(world):
    w = world
    signin()
    root = project(w)
    pick(w, root)
    p = do_plan(w, root)
    commit(root, "late.txt", "late\n", "Late change")
    r = post(w, "/share", root, action_sha256=p["action_sha256"], confirmed=True)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stale"
    r = post(w, "/share", root, action_sha256="0" * 64, confirmed=True)
    assert r.status_code == 409
    r = post(w, "/share", root, action_sha256=p["action_sha256"], confirmed=False)
    assert r.status_code in (400, 409)


def test_force_push_impossible_when_remote_moved(world):
    w = world
    signin()
    root = project(w)
    pick(w, root)
    do_share(w, root, do_plan(w, root))
    # Someone else shares to main.
    other = w.tmp / "other"
    _git(w.tmp, "clone", "-q", str(w.gs.bare()), str(other))
    commit(other, "theirs.txt", "theirs\n", "Theirs")
    _git(other, "push", "-q", "origin", "main")
    commit(root, "mine.txt", "mine\n", "Mine")
    p = do_plan(w, root)
    assert not p["ok"] and p["state"] == "behind" and p["blocks"][0]["rule"] == "non_ff"
    r = post(w, "/share", root, action_sha256=p["action_sha256"], confirmed=True)
    body = r.json()
    assert body["ok"] is False and body["fallback"]["code"] == "non_ff"
    assert any(s.get("action") == "get_latest" for s in body["fallback"]["steps"]["windows"])
    cmds = " ".join(s["cmd"] or "" for o in body["fallback"]["steps"].values() for s in o)
    assert "--force" not in cmds.replace("Never add --force", "")
    theirs = _git(w.gs.bare(), "log", "--format=%s", "main").stdout
    assert "Theirs" in theirs and "Mine" not in theirs  # their work is intact


def test_get_latest_fast_forward_and_combine(world):
    w = world
    signin()
    root = project(w)
    pick(w, root)
    do_share(w, root, do_plan(w, root))
    other = w.tmp / "other"
    _git(w.tmp, "clone", "-q", str(w.gs.bare()), str(other))
    commit(other, "theirs.txt", "theirs\n", "Theirs \x1b[2J<script>")
    _git(other, "push", "-q", "origin", "main")
    r = post(w, "/fetch", root)
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["state"] == "fast_forward" and f["incoming_count"] == 1
    assert "\x1b" not in f["incoming"][0]["subject"] and "<script>" in f["incoming"][0]["subject"]  # plain text
    assert _git(root, "branch", "--format=%(refname)").stdout.strip() == "refs/heads/main"
    r = post(w, "/pull", root, expected=f["expected"], confirmed=True)
    assert r.status_code == 200 and r.json()["mode"] == "fast_forward", r.text
    assert (root / "theirs.txt").exists()
    # Both sides change: combine.
    commit(other, "t2.txt", "2\n", "Theirs 2")
    _git(other, "push", "-q", "origin", "main")
    commit(root, "m2.txt", "2\n", "Mine 2")
    f = post(w, "/fetch", root).json()
    assert f["state"] == "diverged" and f["ahead"] == 1
    r = post(w, "/pull", root, expected=f["expected"], confirmed=True)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "diverged", r.text
    r = post(w, "/pull", root, expected=f["expected"], confirmed=True, combine=True)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "identity"
    _git(root, "config", "user.name", "T")
    _git(root, "config", "user.email", "t@example.com")
    r = post(w, "/pull", root, expected=f["expected"], confirmed=True, combine=True)
    assert r.status_code == 200 and r.json()["mode"] == "combined", r.text
    p = do_plan(w, root)
    assert p["ok"] and p["state"] == "fast_forward"
    assert (root / ".git" / "config").read_text().count("[remote") == 0
    assert "credential" not in (root / ".git" / "config").read_text()
    assert_no_token(w, root)


def test_get_latest_stale_expected_is_refused(world):
    w = world
    signin()
    root = project(w)
    pick(w, root)
    do_share(w, root, do_plan(w, root))
    f = post(w, "/fetch", root).json()
    r = post(w, "/pull", root, expected="a" * 40, confirmed=True)
    assert r.status_code == 409 and f["state"] == "up_to_date"


# ------------------------------------------------------------------ refusing unsafe repositories
@pytest.mark.parametrize("key,value", [
    ("url.https://evil.example/.insteadOf", "https://github.com/"),
    ("url.https://evil.example/.pushInsteadOf", "https://github.com/"),
    ("credential.helper", "store"),
    ("credential.https://github.com.username", "x"),
    ("http.proxy", "http://evil.example:8080"),
    ("http.extraHeader", "X-Evil: 1"),
    ("remote.origin.pushurl", "https://evil.example/x.git"),
    ("core.sshCommand", "evil"),
    ("protocol.file.allow", "always"),
    ("submodule.x.url", "https://evil.example/x.git"),
])
def test_repos_that_redirect_traffic_are_refused(world, key, value):
    w = world
    signin()
    root = project(w)
    pick(w, root)
    _git(root, "config", key, value)
    r = post(w, "/plan", root)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "refused_config"
    st = w.client.get(API + "/status", headers=AUTH, params={"project": str(root)}).json()
    assert st["refused"]["code"] == "refused_config"
    assert w.gs.requests == []  # nothing went on the network


def test_only_allowlisted_https_hosts(world, monkeypatch):
    w = world
    signin()
    root = project(w)
    pick(w, root)
    monkeypatch.setattr(remote, "_allow_http_loopback", False)
    with pytest.raises(remote.RemoteError) as e:
        remote._check_url("github", "github.com", f"http://127.0.0.1:{w.gs.port}/octo/app.git")
    assert e.value.code == "blocked_host"
    for bad in ("https://evil.example/octo/app.git", "https://user:pw@github.com/octo/app.git",
                "https://github.com.evil.example/o/r.git", "ssh://git@github.com/o/r.git"):
        with pytest.raises(remote.RemoteError):
            remote._check_url("github", "github.com", bad)
    remote._check_url("github", "github.com", "https://github.com/octo/app.git")
    r = post(w, "/target", root, provider="gitlab", host="gitlab.evil.example", repo="a/b")
    assert r.status_code == 403
    ov = remote._net_overrides("https://github.com/o/r.git", True)
    joined = " ".join(ov)
    for need in ("protocol.allow=never", "protocol.https.allow=always", "http.followRedirects=false",
                 "http.proxy=", "credential.useHttpPath=true", "core.hooksPath=", "http.sslVerify=true"):
        assert need in joined
    env = remote._net_env(Path(root))
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull and "HTTPS_PROXY" not in env and "GIT_TRACE_CURL" not in env


def test_untrusted_project_is_refused(world):
    w = world
    signin()
    root = project(w, trust=False)
    r = post(w, "/target", root, provider="github", repo="octo/app")
    assert r.status_code == 403


def test_repo_name_parsing():
    n = remote.normalise_repo
    assert n("github", "https://github.com/ymmiah/AutoMotoAI.git") == "ymmiah/AutoMotoAI"
    assert n("github", "git@github.com:ymmiah/AutoMotoAI.git") == "ymmiah/AutoMotoAI"
    assert n("github", "ymmiah/AutoMotoAI/pull/3") == "ymmiah/AutoMotoAI"
    assert n("gitlab", "https://gitlab.com/group/sub/proj/-/tree/main") == "group/sub/proj"
    for bad in ("../x", "x", "a/b c", "-a/b", "a/b;rm"):
        with pytest.raises(remote.RemoteError):
            n("github", bad)


# ------------------------------------------------------------------ the credential broker
def test_broker_is_single_use_exact_repo_and_expires(monkeypatch):
    b = remote._Broker(GH_FINE, "x-access-token", "https", "github.com", "octo/app.git")

    def ask(**kw):
        body = {"nonce": b.nonce, "protocol": "https", "host": "github.com", "path": "octo/app.git", **kw}
        req = urllib.request.Request(b.url, data=json.dumps(body).encode(), method="POST")
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=5) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code

    try:
        assert ask(nonce="wrong") == 403
        assert ask(path="octo/other.git") == 403
        assert ask(host="evil.example") == 403
        assert ask(protocol="http") == 403
        assert ask()["password"] == GH_FINE
        assert ask() == 403  # single use
        assert b.refused == ["wrong code", "wrong repository", "wrong host", "wrong host", "already used"]
    finally:
        b.close()
    b2 = remote._Broker(GH_FINE, "x-access-token", "https", "github.com", "octo/app.git")
    try:
        b2.expires = time.monotonic() - 1
        body = {"nonce": b2.nonce, "protocol": "https", "host": "github.com", "path": "octo/app.git"}
        req = urllib.request.Request(b2.url, data=json.dumps(body).encode(), method="POST")
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=5)
        assert b2.refused == ["expired"]
    finally:
        b2.close()
    assert remote.CRED_TTL == 60


def test_helper_script_ignores_store_and_needs_loopback(monkeypatch, capsys):
    from automoto import git_credential

    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("protocol=https\nhost=github.com\n"))
    monkeypatch.setenv("AUTOMOTO_CRED_BROKER", "http://evil.example/credential")
    monkeypatch.setenv("AUTOMOTO_CRED_NONCE", "x")
    assert git_credential.main(["h", "get"]) == 0 and capsys.readouterr().out == ""
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("password=abc\n"))
    assert git_credential.main(["h", "store"]) == 0 and capsys.readouterr().out == ""


# ------------------------------------------------------------------ pre-push scan
def test_scan_blocks_secret_even_if_removed_later(world):
    w = world
    signin()
    root = project(w)
    pick(w, root)
    commit(root, "config.py", f"KEY = '{FAKE_AWS}'\n", "Add key")
    commit(root, "config.py", "KEY = os.environ['KEY']\n", "Remove key")
    p = do_plan(w, root)
    assert not p["ok"]
    hit = [b for b in p["blocks"] if b["rule"] == "secret"][0]
    assert hit["path"] == "config.py" and hit["line"] == 1 and FAKE_AWS not in json.dumps(p)
    r = post(w, "/share", root, action_sha256=p["action_sha256"], confirmed=True)
    body = r.json()
    assert body["fallback"]["code"] == "scan_blocked" and body["fallback"]["patch"] is None
    assert not list(w.patches.iterdir())  # no file made, so the secret can't leak
    assert w.gs.requests and not any("receive-pack" in x and "service" not in x for x in w.gs.requests)


@pytest.mark.parametrize("rel,content,rule", [
    (".env", "API=1\n", "secret_file"),
    ("certs/server.pem", "x\n", "secret_file"),
    (".github/workflows/ci.yml", "on: push\n", "workflow"),
    (".gitlab-ci.yml", "x: 1\n", "workflow"),
    ("tools/action.yml", "runs: x\n", "workflow"),
    ("app.js", "const t = '" + GH_CLASSIC + "';\n", "secret"),
    ("k.txt", "-----BEGIN OPENSSH PRIVATE KEY-----\n", "secret"),
])
def test_scan_rules(world, rel, content, rule):
    w = world
    signin()
    root = project(w)
    pick(w, root)
    commit(root, rel, content, "Add " + rel)
    p = do_plan(w, root)
    assert any(b["rule"] == rule for b in p["blocks"]), p["blocks"]
    assert all(b.get("message") for b in p["blocks"])


def test_scan_allows_env_example_and_placeholders(world):
    w = world
    signin()
    root = project(w)
    pick(w, root)
    commit(root, ".env.example", "API_KEY=your-key-here\nPASSWORD=changeme\n", "Example env")
    commit(root, "settings.py", "token = os.environ.get('TOKEN')\npassword = getenv('PW')\n", "Settings")
    p = do_plan(w, root)
    assert p["ok"], p["blocks"]


def test_huge_and_large_files(world, monkeypatch):
    w = world
    signin()
    monkeypatch.setattr(remote, "WARN_BYTES", 1000)
    monkeypatch.setattr(remote, "BLOCK_BYTES", 5000)
    root = project(w)
    pick(w, root)
    commit(root, "mid.bin", os.urandom(2000), "Mid")
    p = do_plan(w, root)
    assert p["ok"] and any(x["rule"] == "large_file" for x in p["warnings"])
    commit(root, "big.bin", os.urandom(6000), "Big")
    p = do_plan(w, root)
    assert any(b["rule"] == "huge_file" for b in p["blocks"])
    r = post(w, "/share", root, action_sha256=p["action_sha256"], confirmed=True).json()
    fb = r["fallback"]
    assert fb["code"] == "blocked_files" and fb["bundle"]  # binary -> a bundle as well


def test_secretscan_masks_and_rules():
    hits = secretscan.scan_text("x = '" + GH_FINE + "'\nnothing here\n")
    assert hits and hits[0].line == 1 and GH_FINE not in json.dumps([h.as_dict() for h in hits])
    assert not secretscan.scan_text("def token(self):\n    return self._token\n")
    assert secretscan.scan_text("db = 'postgres://admin:S3cr3tPassw0rd@db.example.com/x'\n")
    assert secretscan.scan_text("", known=(GH_FINE,)) == []


# ------------------------------------------------------------------ token policy
def test_classic_github_token_is_blocked_for_sharing(world):
    w = world
    signin(GH_CLASSIC)
    root = project(w)
    pick(w, root)
    p = do_plan(w, root)
    assert not p["ok"] and p["blocks"][0]["rule"] == "classic_token"
    body = post(w, "/share", root, action_sha256=p["action_sha256"], confirmed=True).json()
    assert body["fallback"]["code"] == "classic_token" and body["fallback"]["patch"]
    assert w.gs.requests == [] or not any("receive-pack" in r for r in w.gs.requests)
    assert_no_token(w, root, json.dumps(body), token=GH_CLASSIC)


def test_expired_token_falls_back(world, monkeypatch):
    w = world
    signin()
    root = project(w)
    pick(w, root)
    items = git_auth._index()
    for a in items:
        a["expires_at"] = "2020-01-01T00:00:00+00:00"
    git_auth._save_index(items)
    p = do_plan(w, root)
    assert not p["ok"] and p["blocks"][0]["rule"] == "expired"
    body = post(w, "/share", root, action_sha256=p["action_sha256"], confirmed=True).json()
    fb = body["fallback"]
    assert fb["code"] == "expired" and fb["patch"]
    assert any(s.get("action") == "signin" for s in fb["steps"]["linux"])


# ------------------------------------------------------------------ failure injection -> .patch fallback
def _fail_case(w, mode=None, hook=None, url_port=None, monkeypatch=None):
    signin()
    root = project(w)
    pick(w, root)
    commit(root, "work.txt", "my work\n", "My work")
    p = do_plan(w, root)
    assert p["ok"], p["blocks"]
    if mode:
        w.gs.mode = mode
    if hook:
        w.gs.hook("octo/app", hook)
    if url_port:
        monkeypatch.setattr(remote, "transport_url", lambda pr, h, r: f"http://127.0.0.1:{url_port}/{r}.git")
    r = w.client.post(API + "/share", headers=AUTH, json={"project": str(root), "action_sha256": p["action_sha256"],
                                                          "confirmed": True})
    assert r.status_code == 200, r.text
    return root, r.json()


def _check_patch(w, root, fb):
    assert fb["patch"] and Path(fb["patch"]["path"]).parent == w.patches
    text = Path(fb["patch"]["path"]).read_text()
    assert "Subject: [PATCH" in text and "my work" in text
    # The patch applies to a fresh copy of the server's repository.
    fresh = w.tmp / ("fresh-" + fb["code"])
    _git(w.tmp, "clone", "-q", str(w.gs.bare()), str(fresh))
    if not (fresh / "README.md").exists():
        _git(fresh, "switch", "-q", "-c", "main", check=False)
    _git(fresh, "am", "-q", fb["patch"]["path"])
    assert (fresh / "work.txt").read_text() == "my work\n"
    for os_name in ("windows", "macos", "linux"):
        steps = fb["steps"][os_name]
        assert steps and all(s["title"] for s in steps)
        for s in steps:
            assert "\n" not in (s["cmd"] or "")
    assert_no_token(w, root, json.dumps(fb))


def test_fallback_401(world):
    root, body = _fail_case(world, mode="401")
    fb = body["fallback"]
    assert body["ok"] is False and fb["code"] == "auth" and fb["headline"] == "Your GitHub sign-in ended."
    _check_patch(world, root, fb)
    assert git_auth.account("github", "github.com")["status"] == "expired"  # and the token was wiped


def test_fallback_403(world):
    root, body = _fail_case(world, mode="403")
    fb = body["fallback"]
    assert fb["code"] == "forbidden"
    # octo/app is the signed-in user's own repository: the token just doesn't include it.
    assert fb["steps"]["windows"][0]["action"] == "signin" and "octo/app" in fb["steps"]["windows"][0]["title"]
    _check_patch(world, root, fb)


def test_forbidden_steps_for_someone_elses_repo_suggest_a_fork():
    ctx = {"provider": "github", "provider_name": "GitHub", "host": "github.com", "repo": "acme/tool",
           "url": "https://github.com/acme/tool.git", "web": "https://github.com/acme/tool", "branch": "fix",
           "base": "main", "patch": "C:\\Users\\Yasin\\Documents\\AutoMoto\\patches\\tool-fix.patch",
           "login": "octo", "project": "C:\\Users\\Yasin\\proj $x"}
    steps = remote.steps_for("forbidden", "windows", ctx)
    links = [s["link"]["url"] for s in steps if s.get("link")]
    assert "https://github.com/acme/tool/fork" in links
    assert "https://github.com/acme/tool/compare/main...octo:fix?expand=1" in links
    cmds = [s["cmd"] for s in steps if s["cmd"]]
    assert 'git clone "https://github.com/octo/tool.git"' in cmds and "git push origin fix" in cmds
    assert any(c.startswith('git am "C:\\Users') for c in cmds)
    win = remote.steps_for("auth", "windows", ctx)
    assert any(s["cmd"] == 'cd "C:\\Users\\Yasin\\proj `$x"' for s in win)  # PowerShell-safe quoting
    nix = remote.steps_for("auth", "linux", {**ctx, "project": "/home/y/my proj's"})
    assert any(s["cmd"] == "cd '/home/y/my proj'\"'\"'s'" for s in nix)


def test_fallback_protected_branch(world):
    root, body = _fail_case(world, hook='echo "GH006: Protected branch update failed for refs/heads/main." >&2; exit 1')
    fb = body["fallback"]
    assert fb["code"] == "protected" and any(s.get("action") == "new_branch" for s in fb["steps"]["macos"])
    _check_patch(world, root, fb)


def test_fallback_push_protection_makes_no_patch(world):
    root, body = _fail_case(world, hook='printf "\\033[31mGH013: Repository rule violations found\\nPush cannot contain secrets\\n" >&2; exit 1')
    fb = body["fallback"]
    assert fb["code"] == "push_protection" and fb["patch"] is None and "\x1b" not in fb["detail"]
    assert not any("bypass" in (s["title"] + (s["cmd"] or "")).lower() for s in fb["steps"]["windows"])


def test_fallback_network_refused(world, monkeypatch):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    root, body = _fail_case(world, url_port=port, monkeypatch=monkeypatch)
    fb = body["fallback"]
    assert fb["code"] == "network" and any(x.get("action") == "retry" for x in fb["steps"]["linux"])
    _check_patch(world, root, fb)


def test_fallback_dropped_connection_and_server_error(world):
    root, body = _fail_case(world, mode="drop")
    assert body["fallback"]["code"] == "network"
    world.gs.mode = "500"
    r = remote.make_fallback(root, "network")
    assert r["patch"]


def test_fallback_garbage_server_is_other(world):
    root, body = _fail_case(world, mode="garbage")
    fb = body["fallback"]
    assert fb["code"] in ("other", "network")
    _check_patch(world, root, fb)


def test_fallback_non_ff_race(world):
    w = world
    signin()
    root = project(w)
    pick(w, root)
    do_share(w, root, do_plan(w, root))
    commit(root, "work.txt", "my work\n", "My work")
    p = do_plan(w, root)
    other = w.tmp / "other"
    _git(w.tmp, "clone", "-q", str(w.gs.bare()), str(other))
    commit(other, "theirs.txt", "x\n", "Theirs")
    _git(other, "push", "-q", "origin", "main")
    body = post(w, "/share", root, action_sha256=p["action_sha256"], confirmed=True)
    assert body.status_code == 409 and body.json()["detail"]["code"] == "stale"  # remote moved: check again
    p = do_plan(w, root)
    fb = post(w, "/share", root, action_sha256=p["action_sha256"], confirmed=True).json()["fallback"]
    assert fb["code"] == "non_ff"


def test_manual_fallback_and_windows_quoting(world):
    w = world
    signin()
    root = project(w, name="my app's folder")
    pick(w, root)
    commit(root, "img.png", b"\x89PNG\r\n\x1a\n\x00\x00" + os.urandom(64), "Picture")
    r = post(w, "/fallback", root, reason="manual")
    assert r.status_code == 200, r.text
    fb = r.json()["fallback"]
    assert fb["code"] == "manual" and fb["patch"] and fb["bundle"]  # binary -> bundle too
    win = " ".join(s["cmd"] or "" for s in fb["steps"]["windows"])
    nix = " ".join(s["cmd"] or "" for s in fb["steps"]["linux"])
    assert '"' + fb["patch"]["path"] + '"' in win
    assert "'" not in fb["patch"]["path"] or "\\'" in nix or "'\"'\"'" in nix
    fresh = w.tmp / "fresh-bundle"
    _git(w.tmp, "init", "-q", str(fresh))
    _git(fresh, "pull", "-q", fb["bundle"]["path"], fb["bundle"]["ref"])
    assert (fresh / "img.png").exists()
    assert_no_token(w, root, json.dumps(fb))


def test_patch_with_secret_is_never_written(world, monkeypatch):
    w = world
    signin()
    root = project(w)
    pick(w, root)
    commit(root, "notes.md", "my token " + GH_FINE + "\n", "Oops")
    fb = post(w, "/fallback", root).json()["fallback"]
    assert fb["code"] == "scan_blocked" and fb["patch"] is None and not list(w.patches.iterdir())
    assert GH_FINE not in json.dumps(fb)


def test_fallback_without_account_or_target(world):
    w = world
    root = project(w)
    fb = post(w, "/fallback", root).json()["fallback"]
    assert fb["code"] == "manual" and fb["patch"]
    assert any("OWNER/REPOSITORY" in (s["cmd"] or "") for s in fb["steps"]["windows"])


def test_gitlab_share(world, monkeypatch):
    w = world
    w.gs.token = GL_PAT
    signin(GL_PAT, "gitlab")
    root = project(w)
    pick(w, root, repo="group/sub/app", provider="gitlab")
    w.gs.bare("group/sub/app")
    _git(root, "switch", "-q", "-c", "feature")
    p = do_plan(w, root)
    assert p["ok"], p["blocks"]
    out = do_share(w, root, p)
    assert out["ok"] and "/-/tree/feature" in out["links"]["branch"]
    assert set(w.gs.auth_seen) == {"oauth2"}
    assert_no_token(w, root, json.dumps(out), token=GL_PAT)


def test_audit_has_no_secrets_and_api(world):
    w = world
    signin()
    root = project(w)
    pick(w, root)
    do_share(w, root, do_plan(w, root))
    items = w.client.get(API + "/audit", headers=AUTH, params={"project": str(root)}).json()["items"]
    assert {"pick_repository", "check", "share"} <= {i["action"] for i in items}
    assert_no_token(w, root, json.dumps(items))


def test_api_needs_session(world):
    r = world.client.post(API + "/plan", json={"project": "x"})
    assert r.status_code in (401, 403)


def test_ui_shows_remote_text_as_plain_text():
    js = (Path(__file__).resolve().parents[1] / "automoto" / "web" / "static" / "developer-share.js").read_text()
    code = "\n".join(l for l in js.splitlines() if not l.strip().startswith("//"))
    assert "innerHTML" not in code and "insertAdjacentHTML" not in code
    assert "localStorage" not in code and "sessionStorage" not in code
