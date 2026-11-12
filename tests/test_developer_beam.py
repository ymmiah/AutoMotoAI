"""V30 BEAM-language scans, consent, provenance and actual installed runtimes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import pytest
from fastapi.testclient import TestClient

from automoto import developer_beam as beam
from automoto import sandbox, server

BASE = "/api/developer/studio/beam"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
FIXTURE = Path(__file__).parent / "fixtures" / "v30-beam"

@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v30-beam"
    shutil.copytree(FIXTURE, root)
    return TestClient(server.app), root

def inspect(client, root):
    return client.get(BASE + "/inspect", params={"project": str(root)}, headers=AUTH)

def trust(client, root):
    response = client.post("/api/developer/studio/trust", headers=AUTH,
                           json={"project": str(root), "trusted": True, "confirmed": True})
    assert response.status_code == 200, response.text

def snapshot(root):
    return {file.relative_to(root).as_posix(): file.read_bytes()
            for file in root.rglob("*") if file.is_file()}

def payload(client, root, task="elixir_test", tool="elixir"):
    state = inspect(client, root)
    assert state.status_code == 200, state.text
    info = state.json()
    item = next((x for x in info["toolchains"] if x["name"] == tool and
                 x["status"] == "installed_not_executed"), None)
    if item is None:
        pytest.skip("Installed BEAM executable unavailable: " + tool)
    return {
        "project": str(root), "task": task, "tool": tool,
        "expected_inventory_sha256": info["inventory_sha256"],
        "expected_toolchain_sha256": info["toolchain_sha256"],
        "expected_executable": item["executable"],
        "expected_sha256": item["sha256"],
        "confirmed": True,
        "accept_unsandboxed_beam_and_network_risk": True,
    }

def test_inert_three_language_inventory_never_evaluates_manifest_or_source(project):
    client, root = project
    before = snapshot(root)
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["language_counts"]["elixir"] >= 2
    assert state["language_counts"]["erlang"] >= 2
    assert state["language_counts"]["gleam"] == 1
    assert {"mix.exs", "rebar.config", "gleam.toml"} <= set(state["manifests"])
    assert not any(x["source_executed"] for x in state["files"])
    assert all(not x["evaluated"] for x in state["manifests"].values())
    assert not state["source_executed"]
    assert not state["manifest_evaluated"]
    assert not state["dependency_installed"]
    assert not state["network_started"]
    assert not state["deployment_started"]
    assert state["packages"]["parsed_only"]
    assert not state["packages"]["dependencies_resolved"]
    assert state["central_agent_studio"] == "developer"
    assert state["agent_deployment_handoff_required"]
    assert state["toolchain_sha256"] and state["inventory_sha256"]
    assert snapshot(root) == before

def test_malicious_build_script_never_evaluated(project, tmp_path):
    client, root = project
    external = tmp_path / "must-not-exist"
    (root / "mix.exs").write_text(
        'File.write!("' + str(external).replace("\\", "/") + '", "bad")\n')
    (root / "rebar.config").write_text(
        '{deps, [{malicious, {git, "https://host.invalid/repo", {branch,"main"}}}]}.\n')
    before = snapshot(root)
    response = inspect(client, root)
    assert response.status_code == 200
    assert not external.exists()
    assert snapshot(root) == before

def test_source_and_manifests_change_inventory_sha(project):
    client, root = project
    original = inspect(client, root).json()["inventory_sha256"]
    (root / "src" / "v30_calc.erl").write_text(
        "-module(v30_calc).\n-export([answer/0]).\nanswer() -> 7.\n")
    changed = inspect(client, root).json()["inventory_sha256"]
    assert changed != original
    (root / "mix.exs").write_text("defmodule Changed do end\n")
    assert inspect(client, root).json()["inventory_sha256"] != changed

@pytest.mark.parametrize("relative", [
    "mix.exs", "rebar.config", "gleam.toml",
    "test/v30_fixture.exs", "test/v30_fixture.escript",
    "src/v30_fixture.gleam"
])
def test_known_manifest_and_fixture_symlink_refused(project, tmp_path, relative):
    client, root = project
    link = root / relative
    link.unlink()
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Runner does not allow symbolic links.")
    response = inspect(client, root)
    assert response.status_code == 403, response.text

def test_auth_and_hosted_mode_denied(project, monkeypatch):
    client, root = project
    assert client.get(BASE + "/inspect", params={"project": str(root)}).status_code in (401, 403)
    monkeypatch.setenv("AUTOMOTO_MODE", "multiuser")
    assert inspect(client, root).status_code in (401, 403, 404)

@pytest.mark.parametrize("task,tool,args", [
    ("elixir_test", "elixir", ["test/v30_fixture.exs"]),
    ("erlang_test", "escript", ["test/v30_fixture.escript"]),
    ("gleam_test", "gleam", ["run", "--target", "erlang", "--no-print-progress"]),
])
def test_exact_allowlisted_commands(project, task, tool, args):
    client, root = project
    data = inspect(client, root).json()
    fake = "/trusted/pinned/executable"
    body = beam.RunIn(project=str(root), task=task, tool=tool,
                      expected_inventory_sha256="a" * 64,
                      expected_toolchain_sha256="b" * 64,
                      expected_executable=fake, expected_sha256="c" * 64,
                      confirmed=True, accept_unsandboxed_beam_and_network_risk=True)
    assert beam._command(body, data) == [fake, *args]

def test_unknown_tools_and_noncanonical_fixture_denied(project):
    client, root = project
    data = inspect(client, root).json()
    with pytest.raises(Exception):
        beam.RunIn(project=str(root), task="shell", tool="elixir",
                   expected_inventory_sha256="a"*64, expected_toolchain_sha256="b"*64,
                   expected_executable="x", expected_sha256="c"*64, confirmed=True,
                   accept_unsandboxed_beam_and_network_risk=True)
    body = beam.RunIn(project=str(root), task="elixir_test", tool="escript",
                      expected_inventory_sha256="a"*64, expected_toolchain_sha256="b"*64,
                      expected_executable="/bin/mock", expected_sha256="c"*64,
                      confirmed=True, accept_unsandboxed_beam_and_network_risk=True)
    with pytest.raises(Exception):
        beam._command(body, data)
    root.joinpath("test/v30_fixture.exs").unlink()
    refreshed = inspect(client, root).json()
    with pytest.raises(Exception):
        beam._command(body.model_copy(update={"tool": "elixir"}), refreshed)

def test_gleam_manifest_strict_no_dependencies_or_extra_source(project):
    client, root = project
    state = inspect(client, root).json()
    beam._gleam_prerequisites(root, state)
    manifest = root / "gleam.toml"
    original = manifest.read_text()
    manifest.write_text(original + '\n[dependencies]\nnonexisting = ">= 1.0.0"\n')
    with pytest.raises(Exception):
        beam._gleam_prerequisites(root, inspect(client, root).json())
    manifest.write_text(original.replace('name = "v30_fixture"', 'name = "malicious"'))
    with pytest.raises(Exception):
        beam._gleam_prerequisites(root, inspect(client, root).json())
    manifest.write_text(original)
    (root / "src" / "other.gleam").write_text("pub fn run() { 42 }\n")
    with pytest.raises(Exception):
        beam._gleam_prerequisites(root, inspect(client, root).json())

def test_stage_checks_inventoried_bytes_again_before_copy(project, tmp_path):
    client, root = project
    state = inspect(client, root).json()
    dest = tmp_path / "copy"
    dest.mkdir()
    beam._stage(root, state, dest)
    assert (dest / "test/v30_fixture.exs").read_bytes() == (root / "test/v30_fixture.exs").read_bytes()
    (root / "test/v30_fixture.exs").write_text("IO.puts(:unsafe)\n")
    with pytest.raises(Exception):
        beam._stage(root, state, dest)

def test_trust_consent_sha_validation_marker_and_no_arbitrary_args(project, monkeypatch):
    client, root = project
    executable = str(Path(sys.executable).resolve())
    sha = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
    monkeypatch.setattr(beam, "_tools", lambda _root: (
        [{"name": "elixir", "status": "installed_not_executed",
          "executable": executable, "sha256": sha}], "d" * 64))
    state = inspect(client, root).json()
    body = {"project": str(root), "task": "elixir_test", "tool": "elixir",
            "expected_inventory_sha256": state["inventory_sha256"],
            "expected_toolchain_sha256": state["toolchain_sha256"],
            "expected_executable": executable, "expected_sha256": sha,
            "confirmed": True, "accept_unsandboxed_beam_and_network_risk": True}
    assert client.post(BASE + "/run", headers=AUTH, json=body).status_code == 403
    trust(client, root)
    calls = []
    def runner(cwd, args, env, timeout):
        calls.append((cwd, args))
        return {"status": "completed", "exit_code": 0,
                "output": "V30_ELIXIR_PASS 42", "elapsed_ms": 3}
    monkeypatch.setattr(beam.native, "_execute", runner)
    outcome = client.post(BASE + "/run", headers=AUTH, json=body)
    assert outcome.status_code == 200, outcome.text
    result = outcome.json()
    assert result["status"] == "completed"
    assert result["fixture_marker_matched"]
    assert result["temporary_copy_deleted"]
    assert result["external_code_unsandboxed"]
    assert result["central_agent_studio"] == "developer"
    assert len(calls) == 1
    assert calls[0][1] == [executable, "test/v30_fixture.exs"]
    for extra in [
        {"expected_sha256": "0"*64},
        {"expected_inventory_sha256": "0"*64},
        {"expected_toolchain_sha256": "0"*64},
    ]:
        assert client.post(BASE + "/run", headers=AUTH, json={**body, **extra}).status_code == 409
    for invalid in [
        {"confirmed": False},
        {"accept_unsandboxed_beam_and_network_risk": False},
        {"command": "rm -rf /"},
        {"task": "arbitrary_task"},
    ]:
        assert client.post(BASE + "/run", headers=AUTH, json={**body, **invalid}).status_code == 422
    (root / "mix.exs").write_text("defmodule New do end\n")
    assert client.post(BASE + "/run", headers=AUTH, json=body).status_code == 409
    assert len(calls) == 1

def test_non_matching_output_is_validation_failure(project, monkeypatch):
    client, root = project
    executable = str(Path(sys.executable).resolve())
    sha = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
    monkeypatch.setattr(beam, "_tools", lambda _root: (
        [{"name": "escript", "status": "installed_not_executed",
          "executable": executable, "sha256": sha}], "e" * 64))
    trust(client, root)
    monkeypatch.setattr(beam.native, "_execute", lambda *a, **kw: {
        "status": "completed", "exit_code": 0, "output": "incorrect", "elapsed_ms": 1})
    body = payload(client, root, "erlang_test", "escript")
    response = client.post(BASE + "/run", headers=AUTH, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "validation_failed"
    assert response.json()["fixture_marker_matched"] is False

@pytest.mark.parametrize("task, tool", [
    ("elixir_test", "elixir"),
    ("erlang_test", "escript"),
    ("gleam_test", "gleam"),
])
def test_real_compilers_and_api_fixtures_only_in_disposable_ci(project, task, tool):
    if os.getenv("AUTOMOTO_V30_REAL_TOOL_TESTS") != "1":
        pytest.skip("Real BEAM processes are opt-in on disposable CI runners only.")
    client, root = project
    trust(client, root)
    before = snapshot(root)
    body = payload(client, root, task, tool)
    response = client.post(BASE + "/run", headers=AUTH, json=body)
    assert response.status_code == 200, response.text
    evidence = response.json()
    assert evidence["status"] == "completed", evidence
    assert evidence["fixture_marker_matched"], evidence
    assert evidence["temporary_copy_deleted"]
    assert evidence["tool_sha256"] == body["expected_sha256"]
    assert snapshot(root) == before
