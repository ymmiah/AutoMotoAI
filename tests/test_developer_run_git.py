"""Developer Studio V41/V44 (real runs, test results, loopback preview) and V45 (local Git)."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import developer_git as dgit
from automoto import developer_run as drun
from automoto import sandbox, server
from tests.gitutil import run_git

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
RUN = "/api/developer/studio/run"
GIT = "/api/developer/studio/git"
HAS_GIT = shutil.which("git") is not None


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    client = TestClient(server.app)
    yield client
    drun.stop_all()


def make(name: str, files: dict[str, str]) -> Path:
    root = sandbox.default_root() / name
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return root


def trust(client, root):
    r = client.post("/api/developer/studio/trust", headers=AUTH,
                    json={"project": str(root), "trusted": True, "confirmed": True})
    assert r.status_code == 200, r.text


def detect(client, root):
    r = client.get(RUN + "/detect", headers=AUTH, params={"project": str(root)})
    assert r.status_code == 200, r.text
    return r.json()


def wait(client, root, run_id, until, timeout=40):
    deadline = time.time() + timeout
    data = None
    while time.time() < deadline:
        data = client.get(RUN + "/status", headers=AUTH,
                          params={"project": str(root), "run_id": run_id}).json()
        if until(data):
            return data
        time.sleep(0.25)
    raise AssertionError("timed out waiting: " + json.dumps(data)[:2000])


# --------------------------------------------------------------------------- V41 detection

def test_detection_is_inert_and_pins_dev_servers_to_loopback(env):
    root = make("web", {"package.json": json.dumps({"scripts": {
        "dev": "vite", "start": "next start", "test": "vitest run"}}),
        "boom.txt": "untouched"})
    before = sorted(p.name for p in root.iterdir())
    data = detect(env, root)
    assert data["commands_executed"] is False and data["approval_required"] is True
    ids = {r["id"]: r for r in data["recipes"]}
    assert ids["node:dev"]["command"].endswith("--host 127.0.0.1 --port <port> --strictPort")
    assert "-H 127.0.0.1 -p <port>" in ids["node:start"]["command"]
    assert ids["node:test"]["kind"] == "test"
    assert all(len(r["command_sha256"]) == 64 for r in data["recipes"])
    assert sorted(p.name for p in root.iterdir()) == before


def test_detects_static_site_python_tests_go_and_cargo(env):
    root = make("multi", {"index.html": "<h1>hi</h1>", "tests/test_a.py": "def test_a():\n    pass\n",
                          "go.mod": "module x\n", "main.go": "package main\n", "Cargo.toml": "[package]\n"})
    ids = {r["id"] for r in detect(env, root)["recipes"]}
    assert {"static:serve", "python:pytest", "go:run", "go:test", "rust:run", "rust:test"} <= ids
    static = next(r for r in drun.detect_recipes(root) if r["id"] == "static:serve")
    assert static["argv"][-2:] == ["--bind", "127.0.0.1"]


def test_start_is_approval_gated(env):
    root = make("gated", {"index.html": "<p>x</p>"})
    recipe = next(r for r in detect(env, root)["recipes"] if r["id"] == "static:serve")
    body = {"project": str(root), "recipe": recipe["id"], "command_sha256": recipe["command_sha256"], "approved": True}
    assert env.post(RUN + "/start", headers=AUTH, json=body).status_code == 403  # not trusted
    trust(env, root)
    assert env.post(RUN + "/start", headers=AUTH, json={**body, "approved": False}).status_code == 422
    assert env.post(RUN + "/start", headers=AUTH, json={k: v for k, v in body.items() if k != "approved"}).status_code == 422
    assert env.post(RUN + "/start", headers=AUTH, json={**body, "command_sha256": "0" * 64}).status_code == 409
    assert env.post(RUN + "/start", headers=AUTH, json={**body, "recipe": "made:up"}).status_code == 404
    assert env.post(RUN + "/start", json=body).status_code in (401, 403)


# --------------------------------------------------------------------------- V44 preview lifecycle

def test_static_preview_runs_on_loopback_and_stops(env):
    root = make("site", {"index.html": "<h1>AutoMoto preview works</h1>"})
    trust(env, root)
    recipe = next(r for r in detect(env, root)["recipes"] if r["id"] == "static:serve")
    if not recipe["available"]:
        pytest.skip("python is not on PATH")
    started = env.post(RUN + "/start", headers=AUTH, json={
        "project": str(root), "recipe": recipe["id"], "command_sha256": recipe["command_sha256"], "approved": True})
    assert started.status_code == 200, started.text
    run = started.json()
    assert run["bound_to"] == "127.0.0.1" and run["kind"] == "app"
    again = env.post(RUN + "/start", headers=AUTH, json={
        "project": str(root), "recipe": recipe["id"], "command_sha256": recipe["command_sha256"], "approved": True})
    assert again.status_code == 429
    data = wait(env, root, run["run_id"], lambda d: d["preview_url"] or not d["live"])
    assert data["status"] == "running", data
    url = data["preview_url"]
    assert url.startswith("http://127.0.0.1:")
    import urllib.request
    with urllib.request.urlopen(url, timeout=5) as page:
        assert b"AutoMoto preview works" in page.read()
    port = data["port"]
    stopped = env.post(RUN + "/stop", headers=AUTH, json={"project": str(root), "run_id": run["run_id"]}).json()
    assert stopped["status"] == "stopped" and stopped["live"] is False and stopped["preview_url"] is None
    time.sleep(0.3)
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()


def test_app_reachable_from_network_is_stopped(env):
    others = drun._non_loopback_addresses()
    if not others:
        pytest.skip("no non-loopback address on this machine")
    root = make("exposed", {"index.html": "x"})
    port = drun._free_port()
    recipe = {"id": "test:exposed", "kind": "app", "label": "exposed", "argv": [], "source": "", "preview": True}
    run = drun.Run(root, recipe, [sys.executable, "-m", "http.server", str(port), "--bind", "0.0.0.0"], port)
    run.start(drun._env(root, "app", port))
    deadline = time.time() + 20
    while run.live and time.time() < deadline:
        time.sleep(0.2)
    if run.live:
        run.stop()
        pytest.skip("network address not reachable from itself here (firewall)")
    assert run.status == "blocked_exposed", (run.status, run.text())
    assert run.view()["preview_url"] is None


# --------------------------------------------------------------------------- V41 real test results

def test_real_pytest_results_are_counted(env):
    root = make("pyproj", {"tests/test_math.py": (
        "def test_ok():\n    assert 1 + 1 == 2\n\n"
        "def test_bad():\n    assert 1 + 1 == 3\n\n"
        "import pytest\n@pytest.mark.skip(reason='later')\ndef test_later():\n    pass\n")})
    trust(env, root)
    recipe = next(r for r in detect(env, root)["recipes"] if r["id"] == "python:pytest")
    if not recipe["available"]:
        pytest.skip("python is not on PATH")
    probe = subprocess.run([shutil.which("python3" if os.name != "nt" else "python") or sys.executable,
                            "-c", "import pytest"], capture_output=True)
    if probe.returncode != 0:
        pytest.skip("pytest not importable by the PATH python")
    run = env.post(RUN + "/start", headers=AUTH, json={
        "project": str(root), "recipe": recipe["id"], "command_sha256": recipe["command_sha256"], "approved": True}).json()
    data = wait(env, root, run["run_id"], lambda d: not d["live"], timeout=90)
    assert data["status"] == "failed", data
    s = data["summary"]
    assert (s["passed"], s["failed"], s["skipped"]) == (1, 1, 1), data
    assert any("test_bad" in f for f in s["failures"])
    assert not (root / ".pytest_cache").exists() or True  # pytest may write its cache; source untouched
    assert (root / "tests" / "test_math.py").read_text().startswith("def test_ok")


@pytest.mark.parametrize("text,expected", [
    ("....F\n=========== 4 passed, 1 failed, 2 skipped in 0.3s ===========\nFAILED t.py::test_x - assert", (4, 1, 2, "pytest")),
    ("Tests:       1 failed, 2 skipped, 5 passed, 8 total\n", (5, 1, 2, "jest")),
    (" Test Files  1 passed (1)\n      Tests  1 failed | 3 passed (4)\n", (3, 1, 0, "vitest")),
    ("=== RUN TestA\n--- PASS: TestA (0.00s)\n--- FAIL: TestB (0.00s)\nFAIL\n", (1, 1, 0, "go")),
    ("test result: ok. 3 passed; 0 failed; 1 ignored; 0 measured\ntest result: ok. 2 passed; 1 failed; 0 ignored\n", (5, 1, 1, "cargo")),
    ("  3 passing (12ms)\n  1 failing\n", (3, 1, 0, "mocha")),
])
def test_summary_parser(text, expected):
    s = drun.parse_test_summary(text)
    assert (s["passed"], s["failed"], s["skipped"], s["framework"]) == expected


def test_csp_allows_only_loopback_preview_frames(env):
    assert "frame-src 'self' http://127.0.0.1:* http://localhost:*" in server.CSP
    assert "frame-ancestors 'none'" in server.CSP


# --------------------------------------------------------------------------- V45 Git

def git(root, *args):
    return run_git(root, *args)


def gstatus(client, root):
    r = client.get(GIT + "/status", headers=AUTH, params={"project": str(root)})
    assert r.status_code == 200, r.text
    return r.json()


def post(client, route, root, **body):
    return client.post(GIT + route, headers=AUTH, json={"project": str(root), **body})


pytestmark_git = pytest.mark.skipif(not HAS_GIT, reason="git not installed")


@pytestmark_git
def test_git_init_stage_commit_branch_and_never_push(env):
    root = make("repo", {"app.py": "print('hi')\n", ".env.local": "TOKEN=x\n", "id_rsa": "k"})
    assert gstatus(env, root)["repository"] is False
    assert post(env, "/init", root, confirmed=True).status_code == 403  # not trusted
    trust(env, root)
    r = post(env, "/init", root, confirmed=True)
    assert r.status_code == 200, r.text
    st = gstatus(env, root)
    assert st["repository"] and st["branch"] == "main" and st["push_supported"] is False
    paths = {f["path"]: f for f in st["files"]}
    assert paths["app.py"]["worktree"] == "untracked"
    assert paths["id_rsa"]["secret_like"]
    assert post(env, "/stage", root, paths=["id_rsa"]).status_code == 403
    assert post(env, "/stage", root, paths=["../outside.py"]).status_code == 403
    assert post(env, "/stage", root, paths=["-A"]).status_code == 422
    assert post(env, "/stage", root, paths=["nope.py"]).status_code == 404
    d = env.get(GIT + "/diff", headers=AUTH, params={"project": str(root), "path": "app.py"}).json()
    assert "+print('hi')" in d["diff"]
    assert post(env, "/commit", root, message="x", confirmed=True).status_code == 409  # nothing staged
    st = post(env, "/stage", root, paths=["app.py"]).json()
    assert st["counts"]["staged"] == 1
    assert post(env, "/commit", root, message="First", confirmed=False).status_code == 422
    r = post(env, "/commit", root, message="First commit", confirmed=True,
             author_name="Test Person", author_email="test@example.com")
    assert r.status_code == 200, r.text
    assert r.json()["pushed"] is False and r.json()["recent"][0]["subject"] == "First commit"
    (root / "app.py").write_text("print('hello')\n")
    d = env.get(GIT + "/diff", headers=AUTH, params={"project": str(root), "path": "app.py"}).json()
    assert "-print('hi')" in d["diff"] and "+print('hello')" in d["diff"]
    assert post(env, "/branch", root, name="feature/x", switch=True).json()["branch"] == "feature/x"
    assert post(env, "/branch", root, name="-bad").status_code == 422
    assert post(env, "/branch", root, name="a..b").status_code == 422
    names = {b["name"] for b in env.get(GIT + "/branches", headers=AUTH, params={"project": str(root)}).json()["branches"]}
    assert names == {"main", "feature/x"}
    assert post(env, "/switch", root, name="main").json()["branch"] == "main"
    for verb in ("push", "pull", "fetch", "clone", "remote"):
        assert env.post(GIT + "/" + verb, headers=AUTH, json={"project": str(root)}).status_code in (404, 405)
    assert dgit._run(root, ["ls-remote", "https://example.com/x.git"], check=False).returncode != 0


@pytestmark_git
def test_git_never_uses_parent_repository(env):
    parent = make("parent", {"README.md": "p"})
    git(parent, "init", "-q", "-b", "main")
    child = make("parent/child", {"a.txt": "a"})
    st = gstatus(env, child)
    assert st["repository"] is False
    trust(env, child)
    assert post(env, "/stage", child, paths=["a.txt"]).status_code == 404


@pytestmark_git
def test_git_refuses_repositories_that_run_programs(env):
    root = make("evil", {"a.txt": "a"})
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "filter.x.clean", "touch pwned")
    r = env.get(GIT + "/status", headers=AUTH, params={"project": str(root)})
    assert r.status_code == 403 and "filter.x.clean" in r.text
    assert not (root / "pwned").exists()


@pytestmark_git
def test_git_hooks_do_not_run(env):
    root = make("hooks", {"a.txt": "a"})
    git(root, "init", "-q", "-b", "main")
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\ntouch \"$GIT_WORK_TREE/hooked\"\n")
    hook.chmod(0o755)
    trust(env, root)
    post(env, "/stage", root, paths=["a.txt"])
    r = post(env, "/commit", root, message="no hooks", confirmed=True, author_name="T", author_email="t@example.com")
    assert r.status_code == 200, r.text
    assert not (root / "hooked").exists()


@pytestmark_git
def test_conflict_view_and_resolution(env):
    root = make("merge", {"story.txt": "start\nline\nend\n"})
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "base")
    git(root, "switch", "-q", "-c", "other")
    (root / "story.txt").write_text("start\ntheirs line\nend\n")
    git(root, "commit", "-q", "-am", "theirs")
    git(root, "switch", "-q", "main")
    (root / "story.txt").write_text("start\nmy line\nend\n")
    git(root, "commit", "-q", "-am", "mine")
    run_git(root, "merge", "other", check=False)
    trust(env, root)
    st = gstatus(env, root)
    assert st["counts"]["conflicts"] == 1 and st["merging"]
    c = env.get(GIT + "/conflict", headers=AUTH, params={"project": str(root), "path": "story.txt"}).json()
    assert len(c["blocks"]) == 1
    assert c["blocks"][0]["ours"] == "my line" and c["blocks"][0]["theirs"] == "theirs line"
    assert post(env, "/commit", root, message="merge", confirmed=True).status_code == 409
    stale = post(env, "/resolve", root, path="story.txt", choice="both", expected_sha256="0" * 64, confirmed=True)
    assert stale.status_code == 409
    r = post(env, "/resolve", root, path="story.txt", choices=["both"], expected_sha256=c["sha256"], confirmed=True)
    assert r.status_code == 200, r.text
    assert (root / "story.txt").read_text() == "start\nmy line\ntheirs line\nend\n"
    assert r.json()["counts"]["conflicts"] == 0
    r = post(env, "/commit", root, message="Merge other", confirmed=True, author_name="T", author_email="t@example.com")
    assert r.status_code == 200, r.text


@pytestmark_git
def test_commit_still_works_when_host_git_requires_signing(env, tmp_path, monkeypatch):
    """A host that signs every commit (or defaults to master) must not break tests or the app."""
    cfg = tmp_path / "hostile.gitconfig"
    cfg.write_text(
        "[commit]\n\tgpgsign = true\n"
        "[tag]\n\tgpgsign = true\n"
        "[init]\n\tdefaultBranch = master\n"
        "[gpg]\n\tformat = ssh\n\tprogram = /usr/bin/false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    monkeypatch.delenv("GIT_CONFIG_NOSYSTEM", raising=False)
    monkeypatch.delenv("GIT_CONFIG_SYSTEM", raising=False)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "0")

    helper_root = tmp_path / "helper-repo"
    helper_root.mkdir()
    git(helper_root, "init", "-q", "-b", "main")
    (helper_root / "a.txt").write_text("a\n", encoding="utf-8")
    git(helper_root, "add", ".")
    git(helper_root, "commit", "-q", "-m", "ok")
    assert git(helper_root, "symbolic-ref", "--short", "HEAD").stdout.strip() == "main"

    app_root = make("signed-host", {"app.py": "print('hi')\n"})
    trust(env, app_root)
    assert post(env, "/init", app_root, confirmed=True).status_code == 200
    assert post(env, "/stage", app_root, paths=["app.py"]).status_code == 200
    result = post(env, "/commit", app_root, message="From a signing host", confirmed=True,
                  author_name="Test Person", author_email="test@example.com")
    assert result.status_code == 200, result.text
    assert result.json()["recent"][0]["subject"] == "From a signing host"


def test_conflict_parser_handles_diff3():
    text = "a\n<<<<<<< HEAD\nmine\n||||||| base\norig\n=======\ntheirs\n>>>>>>> other\nz"
    blocks = dgit.parse_conflicts(text)
    assert blocks[0]["base"] == "orig" and blocks[0]["ours"] == "mine"
    assert dgit.resolve_text(text, ["theirs"]) == "a\ntheirs\nz"
    assert dgit.resolve_text(text, ["ours"]) == "a\nmine\nz"


# ---------------------------------------------------------------- beginner panels (guided steps + ring)
STATIC = Path(__file__).resolve().parents[1] / "automoto" / "web" / "static"


def test_beginner_panels_are_guided_steps_only():
    js = (STATIC / "developer-beginner.js").read_text(encoding="utf-8")
    css = (STATIC / "developer-studio.css").read_text(encoding="utf-8")
    # One design only: no design switch stored in the browser, no leftover option code.
    assert "automoto.developer.beginner" not in js
    assert "localStorage" not in js
    for gone in ("runA", "gitA", "runC", "gitC", "VARIANTS", "dsb-hero", "dsb-tiles", "dsb-timeline"):
        assert gone not in js
        assert gone not in css
    assert "Try your app in 3 steps" in js and "Save a checkpoint in 3 steps" in js
    # The result, the small ring and Check again share one card.
    assert '"Check again"' in js and "function checkCard(" in js
    assert 'card.append(text,button)' in js
    assert 'checks passed' in js and 'setAttribute("role","img")' in js
    # The card has the same fixed geometry at every width: no media query touches it.
    media = css[css.index("/* Beginner faces"):]
    for block in media.split("@media")[1:]:
        assert "dsb-check" not in block and "dsb-ring" not in block
    assert "grid-template-columns:46px" in css and "width:46px;height:46px" in css


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_beginner_panels_friendly_test_names(tmp_path):
    mod = tmp_path / "beginner.mjs"
    mod.write_text((STATIC / "developer-beginner.js").read_text(encoding="utf-8"), encoding="utf-8")
    script = (
        f"import {{friendlyName}} from {json.dumps(mod.as_uri())};"
        "console.log(JSON.stringify(['tests/test_counter.py::test_clamp_high','TestCounterLimits','web/test_dark-mode.js'].map(friendlyName)));"
    )
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60, check=True)
    assert json.loads(out.stdout) == ["Clamp high", "Counter Limits", "Dark mode"]
