"""V17 Python Studio: real manifests, static syntax, permissions and tool execution."""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import venv
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import developer_python as py, sandbox, server

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BASE = "/api/developer/studio/python"
PYPROJECT = """[project]
name = "v17-python-lab"
requires-python = ">=3.11"
dependencies = ["fastapi>=0.115", "pydantic>=2", "Flask>=3"]
[project.optional-dependencies]
test = ["pytest>=8"]
[dependency-groups]
dev = ["ruff>=0.9", "ty>=0.0.1"]
[build-system]
requires = ["hatchling>=1"]
build-backend = "hatchling.build"
[tool.ruff]
line-length = 99
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v17-project"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_bytes(PYPROJECT.encode("utf-8"))
    (root / "uv.lock").write_bytes(b"version = 1\n")
    (root / "src" / "app.py").write_bytes(b"def greet(name: str) -> str:\n    return 'Hi ' + name\n")
    (root / "tests" / "test_app.py").write_bytes(
        b"def test_import():\n    assert 2 + 2 == 4\n")
    return TestClient(server.app), root


def inspect(client, root):
    return client.get(BASE + "/inspect", headers=AUTH, params={"project": str(root)})


def trust(client, root):
    result = client.post("/api/developer/studio/trust", headers=AUTH, json={
        "project": str(root), "trusted": True, "confirmed": True})
    assert result.status_code == 200, result.text


def run(client, root, task="version", tool="python", **kwargs):
    info = inspect(client, root)
    assert info.status_code == 200, info.text
    snapshot = info.json()
    selected = next(x for x in snapshot["toolchains"] if x["name"] == tool)
    if selected["status"] != "installed_not_executed":
        pytest.skip("An installed approved " + tool + " is not present on this runner.")
    body = {"project": str(root), "task": task, "tool": tool,
            "expected_manifest_sha256": snapshot["manifest_sha256"],
            "expected_executable": selected["executable"],
            "expected_sha256": selected["sha256"],
            "confirmed": True, "accept_unsandboxed_execution_and_write_risk": True}
    body.update(kwargs)
    return client.post(BASE + "/run", headers=AUTH, json=body)


def test_python_2026_metadata_lock_uv_and_framework_recognition_are_readonly(project):
    client, root = project
    before = {str(p.relative_to(root)): p.read_bytes()
              for p in root.rglob("*") if p.is_file()}
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["name"] == "v17-python-lab"
    assert data["requires_python"] == ">=3.11"
    assert data["build_backend"] == "hatchling.build"
    assert {"FastAPI", "Pydantic", "Flask", "Pytest"} <= {
        x["name"] for x in data["frameworks"]}
    assert set(data["managers_detected"]) == {"uv"}
    assert data["uv_lock_present"]
    assert "uv.lock" in data["manifests"]
    assert "src/app.py" in data["python_files"]
    assert "tests/test_app.py" in data["test_files"]
    assert data["central_agent_studio"] == "developer"
    assert data["tool_executed"] is False
    assert data["installation_performed"] is False
    assert data["deployment_started"] is False
    assert before == {str(p.relative_to(root)): p.read_bytes()
                      for p in root.rglob("*") if p.is_file()}


def test_ast_is_real_parser_with_sha_guard_and_never_executes(project):
    client, root = project
    source = root / "src" / "app.py"
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    args = {"project": str(root), "path": "src/app.py", "expected_sha256": sha}
    response = client.post(BASE + "/syntax", headers=AUTH, json=args)
    assert response.status_code == 200, response.text
    assert response.json()["valid"] and response.json()["functions"] == 1
    assert response.json()["executed"] is False
    assert not (root / "src" / "__pycache__").exists()
    source.write_bytes(b"def bad(:\n    pass\n")
    stale = client.post(BASE + "/syntax", headers=AUTH, json=args)
    assert stale.status_code == 409
    args["expected_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    invalid = client.post(BASE + "/syntax", headers=AUTH, json=args)
    assert invalid.status_code == 200
    assert invalid.json()["valid"] is False
    assert invalid.json()["diagnostics"][0]["line"] == 1


def test_symlinks_traversal_and_secret_paths_rejected(project, tmp_path):
    client, root = project
    sha = "0" * 64
    for path in ("../src/app.py", "-c", ".env", "src/../../other.py"):
        reply = client.post(BASE + "/syntax", headers=AUTH, json={
            "project": str(root), "path": path, "expected_sha256": sha})
        assert reply.status_code in (403, 422), (path, reply.text)
    outside = tmp_path / "outside.py"
    outside.write_text("SENSITIVE='private'\n", encoding="utf-8")
    link = root / "src" / "unsafe.py"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink unavailable on this platform")
    reply = client.post(BASE + "/syntax", headers=AUTH, json={
        "project": str(root), "path": "src/unsafe.py", "expected_sha256": sha})
    assert reply.status_code == 403


def test_invalid_and_oversized_manifests_fail_closed(project):
    client, root = project
    path = root / "pyproject.toml"
    path.write_bytes(b"[project\nbad")
    assert inspect(client, root).status_code == 422
    path.write_bytes(PYPROJECT.encode("utf-8"))
    (root / "uv.lock").write_bytes(b"a" * (py.MAX_MANIFEST + 1))
    assert inspect(client, root).status_code == 403


def test_system_tool_requires_trust_and_lifecycle_approval(project):
    client, root = project
    denied = run(client, root)
    assert denied.status_code == 403
    trust(client, root)
    result = run(client, root)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["status"] == "completed"
    assert "Python" in body["output"]
    assert body["external_process_unsandboxed"]
    assert body["agent_handoff_created"] is False
    assert body["deployment_started"] is False


def test_manifest_change_bad_signature_and_disallowed_tool_tasks(project):
    client, root = project
    trust(client, root)
    data = inspect(client, root).json()
    choice = next(x for x in data["toolchains"] if x["name"] == "python")
    if choice["status"] != "installed_not_executed":
        pytest.skip("No installed system Python to validate approval hash.")
    args = {"project": str(root), "task": "pytest", "tool": "python",
            "expected_manifest_sha256": data["manifest_sha256"],
            "expected_executable": choice["executable"], "expected_sha256": choice["sha256"],
            "confirmed": True, "accept_unsandboxed_execution_and_write_risk": True}
    assert client.post(BASE + "/run", headers=AUTH, json=args).status_code == 422
    args["task"] = "version"
    args["expected_sha256"] = "0" * 64
    assert client.post(BASE + "/run", headers=AUTH, json=args).status_code == 409
    args["expected_sha256"] = choice["sha256"]
    (root / "pyproject.toml").write_bytes(PYPROJECT.encode() + b"\n# changed\n")
    assert client.post(BASE + "/run", headers=AUTH, json=args).status_code == 409
    args["expected_manifest_sha256"] = inspect(client, root).json()["manifest_sha256"]
    args["confirmed"] = False
    assert client.post(BASE + "/run", headers=AUTH, json=args).status_code == 422


def test_copy_only_virtualenv_metadata_and_version(project):
    client, root = project
    try:
        venv.EnvBuilder(with_pip=False, symlinks=False).create(str(root / ".venv"))
    except (OSError, RuntimeError):
        pytest.skip("Could not create a copied venv on this runner.")
    info = inspect(client, root).json()
    assert info["virtual_environment"]["status"] == "detected_not_executed"
    selected = next(x for x in info["toolchains"] if x["name"] == "venv_python")
    if selected["status"] != "installed_not_executed":
        pytest.skip("This runner does not provide a copied virtualenv interpreter.")
    trust(client, root)
    result = run(client, root, tool="venv_python")
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "completed"
    assert result.json()["source_files_unchanged"] == "not_verified"


def test_no_hosted_project_data_and_token_required(project, monkeypatch):
    client, root = project
    no_token = client.get(BASE + "/inspect", params={"project": str(root)})
    assert no_token.status_code in (401, 403)
    monkeypatch.setenv("AUTOMOTO_MODE", "multiuser")
    blocked = inspect(client, root)
    assert blocked.status_code in (401, 403, 404)
