"""Developer Studio V18: Go modules, workspaces, sources, real tasks and guards."""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import developer_go as go, sandbox, server

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BASE = "/api/developer/studio/go"
WORK = """go 1.22
use (
    ./service
    ./shared
)
"""
SERVICE_MOD = """module example.com/v18/service

go 1.22

require example.com/v18/shared v0.0.0
"""
SHARED_MOD = "module example.com/v18/shared\n\ngo 1.22\n"
SERVICE = """package main

import (
    "fmt"
    "example.com/v18/shared"
)

func main() { fmt.Println(shared.Greet("Go")) }
"""
SHARED = """package shared

func Greet(s string) string { return "Hello " + s }
"""
HANDLER = """package api

import "net/http"
func Handler(w http.ResponseWriter, r *http.Request) {
    w.WriteHeader(http.StatusOK)
}
"""
HANDLER_TEST = """package api

import (
    "net/http"
    "net/http/httptest"
    "testing"
)

func TestHandler(t *testing.T) {
    r := httptest.NewRequest(http.MethodGet, "/", nil)
    w := httptest.NewRecorder()
    Handler(w, r)
    if w.Code != http.StatusOK { t.Fatal(w.Code) }
}
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v18-go-services"
    for folder in ("service/api", "shared"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "go.work").write_bytes(WORK.encode())
    (root / "service/go.mod").write_bytes(SERVICE_MOD.encode())
    (root / "shared/go.mod").write_bytes(SHARED_MOD.encode())
    (root / "service/main.go").write_bytes(SERVICE.encode())
    (root / "service/api/handler.go").write_bytes(HANDLER.encode())
    (root / "service/api/handler_test.go").write_bytes(HANDLER_TEST.encode())
    (root / "shared/hello.go").write_bytes(SHARED.encode())
    return TestClient(server.app), root


def inspect(client, root):
    return client.get(BASE + "/inspect", params={"project": str(root)}, headers=AUTH)


def trust(client, root):
    result = client.post("/api/developer/studio/trust", headers=AUTH, json={
        "project": str(root), "trusted": True, "confirmed": True})
    assert result.status_code == 200, result.text


def run(client, root, task="version", tool="go", **overrides):
    info = inspect(client, root)
    assert info.status_code == 200, info.text
    data = info.json()
    item = next(x for x in data["toolchains"] if x["name"] == tool)
    if item["status"] != "installed_not_executed":
        pytest.skip("Pinned system Go tool unavailable on runner.")
    payload = {"project": str(root), "task": task, "tool": tool,
               "expected_manifest_sha256": data["manifest_sha256"],
               "expected_source_sha256": data["source_sha256"],
               "expected_executable": item["executable"], "expected_sha256": item["sha256"],
               "confirmed": True, "accept_unsandboxed_execution_and_write_risk": True}
    payload.update(overrides)
    return client.post(BASE + "/run", headers=AUTH, json=payload)


def test_go_workspace_scan_has_real_module_and_service_evidence_without_execution(project):
    client, root = project
    before = {x.relative_to(root).as_posix(): x.read_bytes()
              for x in root.rglob("*") if x.is_file()}
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["workspace"] is True
    assert data["workspace_modules"] == ["service", "shared"]
    assert data["patterns"] == ["./service/...", "./shared/..."]
    assert data["safe_to_offer_runs"] and not data["warnings"]
    assert {m["module"] for m in data["modules"]} == {
        "example.com/v18/service", "example.com/v18/shared"}
    assert {x["path"] for x in data["packages"]} == {
        "./service", "./service/api", "./shared"}
    assert "http" in next(x for x in data["packages"]
                          if x["path"] == "./service/api")["service_hints"]
    assert any(x["test"] for x in data["sources"])
    assert data["gopls"].startswith("Use existing")
    assert data["tool_executed"] is False
    assert data["dependency_downloads_performed"] is False
    assert data["central_agent_studio"] == "developer"
    assert data["agent_deployment_handoff_required"]
    assert before == {x.relative_to(root).as_posix(): x.read_bytes()
                      for x in root.rglob("*") if x.is_file()}


def test_incomplete_unsafe_workspace_directives_fail_closed(project):
    client, root = project
    (root / "go.work").write_text("go 1.22\nuse ../outside\n", encoding="utf-8")
    data = inspect(client, root).json()
    assert not data["safe_to_offer_runs"]
    assert data["warnings"]
    (root / "go.work").write_text("go 1.22\nuse ./nonexistent\n", encoding="utf-8")
    data = inspect(client, root).json()
    assert not data["safe_to_offer_runs"]
    assert any("no safely readable go.mod" in x for x in data["warnings"])
    (root / "go.work").write_bytes(WORK.encode())
    (root / "service/go.mod").write_text(SERVICE_MOD + "\nreplace example.com/other => ../outside\n")
    data = inspect(client, root).json()
    assert not data["safe_to_offer_runs"]
    assert any("replace" in x.lower() for x in data["warnings"])


def test_symlinked_go_work_and_broken_manifest_denied(project, tmp_path):
    client, root = project
    target = tmp_path / "outside-go-work"
    target.write_bytes(WORK.encode())
    (root / "go.work").unlink()
    try:
        (root / "go.work").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("System cannot create a filesystem symlink.")
    response = inspect(client, root)
    assert response.status_code == 403
    assert "Linked Go manifest" in response.text or "Go" in response.text


def test_go_manifest_change_source_change_and_exact_approval(project):
    client, root = project
    if not shutil.which("go"):
        pytest.skip("No Go SDK available to validate actual binary identity.")
    trust(client, root)
    current = inspect(client, root).json()
    item = next(t for t in current["toolchains"] if t["name"] == "go")
    if item["status"] != "installed_not_executed":
        pytest.skip("Go binary fingerprint restricted.")
    payload = {"project": str(root), "task": "version", "tool": "go",
               "expected_manifest_sha256": current["manifest_sha256"],
               "expected_source_sha256": current["source_sha256"],
               "expected_executable": item["executable"], "expected_sha256": item["sha256"],
               "confirmed": True, "accept_unsandboxed_execution_and_write_risk": True}
    url = BASE + "/run"
    bad = {**payload, "confirmed": False}
    assert client.post(url, headers=AUTH, json=bad).status_code == 422
    bad = {**payload, "expected_sha256": "0" * 64}
    assert client.post(url, headers=AUTH, json=bad).status_code == 409
    (root / "service/main.go").write_text(SERVICE + "\n// changed\n")
    assert client.post(url, headers=AUTH, json=payload).status_code == 409
    payload["expected_source_sha256"] = inspect(client, root).json()["source_sha256"]
    (root / "shared/go.mod").write_text(SHARED_MOD + "\n// changed\n")
    assert client.post(url, headers=AUTH, json=payload).status_code == 409


def test_trust_required_go_version_and_run_never_deploys(project):
    client, root = project
    denied = run(client, root)
    assert denied.status_code == 403
    trust(client, root)
    success = run(client, root)
    assert success.status_code == 200, success.text
    output = success.json()
    assert output["status"] == "completed"
    assert "go version" in output["output"]
    assert output["external_process_unsandboxed"] is True
    assert output["network_prevented_by_os"] is False
    assert output["agent_handoff_created"] is False
    assert output["deployment_started"] is False


def test_real_go_build_test_and_vet_multiple_packages_offline(project):
    client, root = project
    trust(client, root)
    before = {x.relative_to(root).as_posix(): x.read_bytes()
              for x in root.rglob("*") if x.is_file()}
    for task in ("build", "test", "vet"):
        response = run(client, root, task=task)
        assert response.status_code == 200, (task, response.text)
        result = response.json()
        assert result["status"] == "completed", (task, result["output"])
        assert result["package_installation_performed_by_app"] is False
        assert result["commands_were_pinned"]
        assert result["deployment_started"] is False
    assert before == {x.relative_to(root).as_posix(): x.read_bytes()
                      for x in root.rglob("*") if x.is_file()}


def test_profile_requires_one_discovered_test_package_and_deletes_raw_profile(project):
    client, root = project
    trust(client, root)
    originals = {p.relative_to(root).as_posix(): p.read_bytes()
                 for p in root.rglob("*") if p.is_file()}
    refused = run(client, root, task="profile", package="./outside")
    assert refused.status_code == 422
    output = run(client, root, task="profile", package="./service/api")
    assert output.status_code == 200, output.text
    result = output.json()
    assert result["status"] == "completed", result["output"]
    assert result["profile"]["requested"]
    assert result["profile"]["retained"] is False
    if result["profile"].get("sha256"):
        assert len(result["profile"]["sha256"]) == 64
        assert result["profile"]["size_bytes"] <= go.MAX_PROFILE
    assert originals == {p.relative_to(root).as_posix(): p.read_bytes()
                         for p in root.rglob("*") if p.is_file()}, (
        "Go profiling must not retain its test binary or CPU profile in user source.")


def test_unknown_binary_task_and_version_reject_package(project):
    client, root = project
    trust(client, root)
    bad = run(client, root, task="version", package="./service/api")
    assert bad.status_code == 409 or bad.status_code == 422
    bad = run(client, root, task="test", package="./service/api")
    assert bad.status_code == 422


def test_hosted_mode_and_token_fail_before_project_access(project, monkeypatch):
    client, root = project
    unauthenticated = client.get(BASE + "/inspect", params={"project": str(root)})
    assert unauthenticated.status_code in (401, 403)
    monkeypatch.setenv("AUTOMOTO_MODE", "multiuser")
    blocked = inspect(client, root)
    assert blocked.status_code in (401, 403, 404)
