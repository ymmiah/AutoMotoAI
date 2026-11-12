"""V31 functional/logic source evidence, approval and interpreter acceptance."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import sys

import pytest
from fastapi.testclient import TestClient

from automoto import developer_logic as logic
from automoto import sandbox, server

BASE = "/api/developer/studio/logic"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
FIXTURE = Path(__file__).parent / "fixtures" / "v31-logic"

@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v31-logic"
    shutil.copytree(FIXTURE, root)
    return TestClient(server.app), root

def inspect(client, root):
    return client.get(BASE + "/inspect", params={"project": str(root)}, headers=AUTH)

def trust(client, root):
    result = client.post("/api/developer/studio/trust", headers=AUTH,
                         json={"project": str(root), "trusted": True, "confirmed": True})
    assert result.status_code == 200, result.text

def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}

def approved(client, root, task, tool):
    result = inspect(client, root)
    assert result.status_code == 200, result.text
    d = result.json()
    item = next((t for t in d["toolchains"] if t["name"] == tool and
                 t["status"] == "installed_not_executed"), None)
    assert item, "Expected installed runtime unavailable: " + tool
    return {"project": str(root), "task": task, "tool": tool,
            "expected_inventory_sha256": d["inventory_sha256"],
            "expected_toolchain_sha256": d["toolchain_sha256"],
            "expected_executable": item["executable"],
            "expected_sha256": item["sha256"],
            "confirmed": True, "accept_unsandboxed_execution_and_network_risk": True}

def test_inert_five_language_inventory(project):
    client, root = project
    before = snapshot(root)
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    d = response.json()
    assert d["language_counts"] == {
        "haskell": 1, "ocaml": 1, "lisp": 1, "scheme": 1, "prolog": 1}
    assert {"cabal.project", "dune-project", "project.asd", "pack.pl", "stack.yaml"} <= set(d["manifests"])
    assert all(not m["evaluated"] for m in d["manifests"].values())
    assert len(d["files"]) == 5
    assert all(f["canonical_fixture"] and f["sha256"] for f in d["files"])
    assert any("main" in f["symbols"] for f in d["files"] if f["language"] == "haskell")
    for flag in ("source_executed", "manifest_evaluated", "packages_installed",
                 "network_started", "deployment_started"):
        assert d[flag] is False, flag
    assert d["central_agent_studio"] == "developer"
    assert d["agent_deployment_handoff_required"]
    assert before == snapshot(root)

def test_pl_ambiguity_and_malicious_asdf_are_inert(project, tmp_path):
    client, root = project
    (root / "other.pl").write_text("use strict;\nprint 42;\n")
    external = tmp_path / "should-not-exist"
    (root / "project.asd").write_text(
        '#.(uiop:run-program (list "touch" "' + str(external) + '"))\n')
    before = snapshot(root)
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    d = response.json()
    assert not any(f["path"] == "other.pl" for f in d["files"])
    assert d["language_counts"]["prolog"] == 1
    assert not external.exists() and snapshot(root) == before

def test_source_and_manifest_drift(project):
    client, root = project
    old = inspect(client, root).json()["inventory_sha256"]
    (root / "test/v31_fixture.ml").write_text("let answer = 0\n")
    changed = inspect(client, root).json()["inventory_sha256"]
    assert old != changed
    (root / "cabal.project").write_text("packages: unknown\n")
    assert inspect(client, root).json()["inventory_sha256"] != changed

@pytest.mark.parametrize("name", [
    "cabal.project", "dune-project", "project.asd", "pack.pl",
    "test/v31_fixture.hs", "test/v31_fixture.ml", "test/v31_fixture.lisp",
    "test/v31_fixture.scm", "test/v31_fixture.pl"])
def test_symlink_manifests_or_fixtures_refused(project, tmp_path, name):
    client, root = project
    link = root / name
    link.unlink()
    target = tmp_path / "outside"
    target.write_text("sensitive")
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not available on this runner")
    assert inspect(client, root).status_code == 403

def test_auth_and_hosted_denied(project, monkeypatch):
    client, root = project
    assert client.get(BASE + "/inspect", params={"project": str(root)}).status_code in (401, 403)
    monkeypatch.setenv("AUTOMOTO_MODE", "multiuser")
    assert inspect(client, root).status_code in (401, 403, 404)

@pytest.mark.parametrize("task,tool,args", [
    ("haskell_test", "runghc", ["test/v31_fixture.hs"]),
    ("ocaml_test", "ocaml", ["-noinit", "test/v31_fixture.ml"]),
    ("lisp_test", "sbcl", ["--noinform", "--no-sysinit", "--no-userinit",
                           "--script", "test/v31_fixture.lisp"]),
    ("scheme_test", "guile", ["--no-auto-compile", "-s", "test/v31_fixture.scm"]),
    ("prolog_test", "swipl", ["-q", "-f", "none", "-s", "test/v31_fixture.pl",
                              "-g", "main", "-t", "halt"]),
])
def test_fixed_commands_and_tool_mismatch(project, task, tool, args):
    client, root = project
    d = inspect(client, root).json()
    assert logic._command(task, tool, "/pinned/bin", d) == ["/pinned/bin", *args]
    with pytest.raises(Exception):
        logic._command(task, "unrelated", "/pinned/bin", d)

def test_trust_consent_hash_and_invalid_action(project, monkeypatch):
    client, root = project
    exe = str(Path(sys.executable).resolve())
    sha = hashlib.sha256(Path(exe).read_bytes()).hexdigest()
    monkeypatch.setattr(logic, "_tools", lambda _root: (
        [{"name": "runghc", "status": "installed_not_executed",
          "executable": exe, "sha256": sha}], "a" * 64))
    d = inspect(client, root).json()
    body = {
        "project": str(root), "task": "haskell_test", "tool": "runghc",
        "expected_inventory_sha256": d["inventory_sha256"],
        "expected_toolchain_sha256": d["toolchain_sha256"],
        "expected_executable": exe, "expected_sha256": sha,
        "confirmed": True, "accept_unsandboxed_execution_and_network_risk": True}
    assert client.post(BASE + "/run", headers=AUTH, json=body).status_code == 403
    trust(client, root)
    calls = []
    def runner(cwd, args, env, timeout):
        assert (cwd / "test/v31_fixture.hs").is_file()
        calls.append(args)
        return {"status": "completed", "exit_code": 0,
                "output": "V31_HASKELL_PASS 42", "elapsed_ms": 1}
    monkeypatch.setattr(logic.native, "_execute", runner)
    response = client.post(BASE + "/run", headers=AUTH, json=body)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["status"] == "completed" and value["fixture_marker_matched"]
    assert value["external_code_unsandboxed"]
    assert value["temporary_copy_deleted"]
    assert not value["original_workspace_integrity_verified"]
    assert calls == [[exe, "test/v31_fixture.hs"]]
    for field in ("expected_inventory_sha256", "expected_toolchain_sha256", "expected_sha256"):
        assert client.post(BASE + "/run", headers=AUTH,
                           json={**body, field: "0"*64}).status_code == 409
    for invalid in ({"confirmed": False},
                    {"accept_unsandboxed_execution_and_network_risk": False},
                    {"task": "arbitrary"}, {"command": "rm -rf /"}):
        assert client.post(BASE + "/run", headers=AUTH,
                           json={**body, **invalid}).status_code == 422
    (root / "dune-project").write_text("(lang dune 3.1)\n")
    assert client.post(BASE + "/run", headers=AUTH, json=body).status_code == 409
    assert len(calls) == 1

def test_wrong_marker_is_failure(project, monkeypatch):
    client, root = project
    exe = str(Path(sys.executable).resolve())
    sha = hashlib.sha256(Path(exe).read_bytes()).hexdigest()
    monkeypatch.setattr(logic, "_tools", lambda _root: (
        [{"name": "runghc", "status": "installed_not_executed",
          "executable": exe, "sha256": sha}], "b"*64))
    trust(client, root)
    monkeypatch.setattr(logic.native, "_execute", lambda *args, **kw: {
        "status": "completed", "exit_code": 0, "output": "not verified", "elapsed_ms": 1})
    body = approved(client, root, "haskell_test", "runghc")
    result = client.post(BASE + "/run", headers=AUTH, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "validation_failed"

@pytest.mark.parametrize("task,tool", [
    ("haskell_test", "runghc"), ("ocaml_test", "ocaml"),
    ("lisp_test", "sbcl"), ("scheme_test", "guile"),
    ("prolog_test", "swipl")])
def test_real_interpreter_on_disposable_ci(project, task, tool):
    if os.getenv("AUTOMOTO_V31_REAL_TOOL_TESTS") != "1":
        pytest.skip("Real V31 toolchains are opt-in on disposable CI runners")
    client, root = project
    trust(client, root)
    original = snapshot(root)
    body = approved(client, root, task, tool)
    response = client.post(BASE + "/run", headers=AUTH, json=body)
    assert response.status_code == 200, response.text
    evidence = response.json()
    assert evidence["status"] == "completed", evidence
    assert evidence["fixture_marker_matched"], evidence
    assert evidence["tool_sha256"] == body["expected_sha256"]
    assert original == snapshot(root)
