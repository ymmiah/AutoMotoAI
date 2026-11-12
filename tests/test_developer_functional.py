"""Developer Studio V29 functional tooling: source safety and permission regression."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import developer_functional as functional
from automoto import sandbox, server

BASE = "/api/developer/studio/functional"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
FIXTURE = Path(__file__).parent / "fixtures" / "v29-functional"

@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v29-functional"
    shutil.copytree(FIXTURE, root)
    return TestClient(server.app), root

def inspect(client, root):
    return client.get(BASE + "/inspect", params={"project": str(root)}, headers=AUTH)

def trust(client, root):
    response = client.post("/api/developer/studio/trust", headers=AUTH, json={
        "project": str(root), "trusted": True, "confirmed": True
    })
    assert response.status_code == 200, response.text

def snapshot(root):
    return {item.relative_to(root).as_posix(): item.read_bytes()
            for item in root.rglob("*") if item.is_file()}

def test_inert_scan_and_manifest_evidence_without_execution(project):
    client, root = project
    original = snapshot(root)
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["language_counts"]["scala"] >= 2
    assert data["language_counts"]["fsharp"] >= 2
    assert data["language_counts"]["clojure"] >= 2
    assert {"build.sbt", "deps.edn", "Fixture.fsproj"} <= set(data["manifests"])
    assert all(not f["executed"] for f in data["files"])
    assert all(not m["evaluated"] for m in data["manifests"].values())
    assert data["packages"]["declared_only"]
    assert not data["packages"]["dependencies_resolved"]
    assert not data["source_executed"]
    assert not data["build_scripts_evaluated"]
    assert not data["package_installation_started"]
    assert not data["deployment_started"]
    assert data["central_agent_studio"] == "developer"
    assert data["agent_deployment_handoff_required"]
    assert data["inventory_sha256"]
    assert data["toolchain_sha256"]
    assert snapshot(root) == original

def test_changed_source_and_manifest_change_inventory_hash(project):
    client, root = project
    before = inspect(client, root).json()
    (root / "src" / "core.cljc").write_text("(ns core)\n(defn answer [] 7)\n")
    after = inspect(client, root).json()
    assert after["inventory_sha256"] != before["inventory_sha256"]
    (root / "build.sbt").write_text('name := "tampered"\n')
    after2 = inspect(client, root).json()
    assert after2["inventory_sha256"] != after["inventory_sha256"]

def test_manifest_read_is_inert_even_with_malicious_project_code(project, tmp_path):
    client, root = project
    hostile = tmp_path / "should-not-exist"
    (root / "build.sbt").write_text('sys.process.Process("touch ' +
                                    str(hostile) + '").!\n')
    (root / "deps.edn").write_text('#=(java.lang.Runtime/getRuntime)\n')
    before = snapshot(root)
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    assert not hostile.exists()
    assert snapshot(root) == before
    assert not response.json()["packages"]["manifests_evaluated"]

@pytest.mark.parametrize("filename", ["build.sbt", "deps.edn", "Fixture.fsproj",
                                      "test/Fixture.fsx", "test/fixture_test.clj"])
def test_symlink_files_cannot_be_accepted_for_stage(project, tmp_path, filename):
    client, root = project
    outside = tmp_path / "outside.txt"
    outside.write_text("stolen?\n")
    target = root / filename
    target.unlink()
    try:
        target.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable on test runner.")
    response = inspect(client, root)
    assert response.status_code == 403, "Linked canonical source or build manifest must be rejected"

def test_missing_auth_and_hosted_mode_denied(project, monkeypatch):
    client, root = project
    assert client.get(BASE + "/inspect", params={"project": str(root)}).status_code in (401,403)
    monkeypatch.setenv("AUTOMOTO_MODE", "multiuser")
    assert inspect(client, root).status_code in (401,403,404)

def test_run_requires_project_trust_exact_fingerprints_and_no_free_args(project, monkeypatch):
    client, root = project
    fake = str(Path(sys.executable).resolve())
    sha = hashlib.sha256(Path(fake).read_bytes()).hexdigest()
    def tools(_root):
        return ([{"name": "dotnet", "status": "installed_not_executed",
                  "executable": fake, "sha256": sha}], "a" * 64)
    monkeypatch.setattr(functional, "_tools", tools)
    state = inspect(client, root).json()
    body = {"project": str(root), "task": "fsharp_test", "tool": "dotnet",
            "expected_inventory_sha256": state["inventory_sha256"],
            "expected_toolchain_sha256": state["toolchain_sha256"],
            "expected_executable": fake, "expected_sha256": sha, "confirmed": True,
            "accept_unsandboxed_code_and_network_risk": True}
    denied = client.post(BASE + "/run", headers=AUTH, json=body)
    assert denied.status_code == 403
    trust(client, root)
    called = []
    def fake_execute(root_path, argv, env, timeout):
        called.append((root_path, argv, env))
        return {"status": "completed", "exit_code": 0,
                "output": "V29_FSHARP_PASS 42\n", "elapsed_ms": 2}
    monkeypatch.setattr(functional.native, "_execute", fake_execute)
    ok = client.post(BASE + "/run", headers=AUTH, json=body)
    assert ok.status_code == 200, ok.text
    result = ok.json()
    assert result["status"] == "completed"
    assert result["fixture_marker_matched"]
    assert called[0][1] == [fake, "fsi", "--exec", "test/Fixture.fsx"]
    assert not result["package_installation_started"]
    assert not result["deployment_started"]
    assert result["external_code_unsandboxed"]
    assert result["temporary_copy_deleted"]
    assert client.post(BASE + "/run", headers=AUTH,
                       json={**body, "expected_sha256": "0" * 64}).status_code == 409
    assert client.post(BASE + "/run", headers=AUTH,
                       json={**body, "unknown_field": "hack"}).status_code == 422
    assert client.post(BASE + "/run", headers=AUTH,
                       json={**body, "confirmed": False}).status_code == 422
    assert client.post(BASE + "/run", headers=AUTH,
                       json={**body, "accept_unsandboxed_code_and_network_risk": False}).status_code == 422
    assert client.post(BASE + "/run", headers=AUTH,
                       json={**body, "task": "arbitrary_script"}).status_code == 422
    (root / "src" / "Calculation.fs").write_text("module Calculation\nlet answer = 0\n")
    assert client.post(BASE + "/run", headers=AUTH, json=body).status_code == 409
    assert len(called) == 1

def test_source_stage_rechecks_exact_bytes(project, monkeypatch, tmp_path):
    client, root = project
    state = inspect(client, root).json()
    destination = tmp_path / "stage"
    destination.mkdir()
    functional._stage(root, state, destination)
    assert (destination / "test" / "Fixture.fsx").read_bytes() == (root / "test" / "Fixture.fsx").read_bytes()
    (root / "test" / "Fixture.fsx").write_text("printfn \"EVIL\"\n")
    with pytest.raises(Exception):
        functional._stage(root, state, destination)

def test_commands_are_fixed_and_cannot_select_any_other_file(project):
    client, root = project
    data = inspect(client, root).json()
    assert functional._command("scala_test", "scala", "/usr/bin/scala", data) == [
        "/usr/bin/scala", "-nc", "test/Fixture.scala"]
    assert functional._command("clojure_test", "clojure", "/usr/bin/clojure", data) == [
        "/usr/bin/clojure", "test/fixture_test.clj"]
    with pytest.raises(Exception):
        functional._command("fsharp_test", "scala", "/usr/bin/scala", data)
    with pytest.raises(Exception):
        functional._command("other", "scala", "/usr/bin/scala", data)

@pytest.mark.parametrize("task, tool", [
    ("scala_test", "scala"),
    ("fsharp_test", "dotnet"),
    ("clojure_test", "clojure"),
])
def test_real_installed_interpreters_only_on_ephemeral_ci(project, task, tool):
    import os
    if os.getenv("AUTOMOTO_V29_REAL_TOOL_TESTS") != "1":
        pytest.skip("Real external execution is opt-in and restricted to controlled CI.")
    client, root = project
    trust(client, root)
    before = snapshot(root)
    inventory = inspect(client, root).json()
    record = next((t for t in inventory["toolchains"]
                   if t["name"] == tool and t["status"] == "installed_not_executed"), None)
    assert record, "Required real CI interpreter is not installed or approved: " + tool
    body = {
        "project": str(root), "task": task, "tool": tool,
        "expected_inventory_sha256": inventory["inventory_sha256"],
        "expected_toolchain_sha256": inventory["toolchain_sha256"],
        "expected_executable": record["executable"],
        "expected_sha256": record["sha256"], "confirmed": True,
        "accept_unsandboxed_code_and_network_risk": True,
    }
    result = client.post(BASE + "/run", headers=AUTH, json=body)
    assert result.status_code == 200, result.text
    evidence = result.json()
    assert evidence["status"] == "completed", evidence
    assert evidence["fixture_marker_matched"], evidence
    assert evidence["temporary_copy_deleted"]
    assert before == snapshot(root), "V29 must not edit original project"
