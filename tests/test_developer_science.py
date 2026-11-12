"""V28 scientific reproducibility: inert data, notebook and real R/Julia/Octave tests."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import developer_science as science
from automoto import sandbox, server

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BASE = "/api/developer/studio/science"
FIXTURE = Path(__file__).parent / "fixtures" / "v28-science"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v28-science"
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


def payload(client, root, lang="r", task="reproduce"):
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    data = response.json()
    name = science.EXECUTABLES[lang]
    tool = next(x for x in data["toolchains"] if x["name"] == name)
    if tool["status"] != "installed_not_executed":
        pytest.skip("Installed scientific interpreter unavailable: " + name)
    return {"project": str(root), "task": task, "language": lang, "tool": name,
            "expected_inventory_sha256": data["inventory_sha256"],
            "expected_toolchain_sha256": data["toolchain_sha256"],
            "expected_executable": tool["executable"],
            "expected_sha256": tool["sha256"],
            "confirmed": True,
            "accept_unsandboxed_scientific_code_and_network_risk": True}


def run(client, root, lang="r", task="reproduce", **updates):
    data = payload(client, root, lang, task)
    data.update(updates)
    return client.post(BASE + "/run", headers=AUTH, json=data)


def test_inspection_records_dataset_source_and_lock_provenance_without_execution(project):
    client, root = project
    original = snapshot(root)
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["safe_to_offer_reproduction"], data["warnings"]
    assert data["experiment"]["calculated_count"] == 5
    assert data["experiment"]["calculated_sum"] == "150"
    assert data["experiment"]["calculated_mean"] == "30"
    assert data["experiment"]["expected_matches_data"]
    assert data["experiment"]["data_sha256"] == hashlib.sha256(
        original["data/measurements.csv"]).hexdigest()
    assert set(data["experiment"]["source_sha256"]) == {"r", "julia", "octave"}
    assert all(data["experiment"]["source_sha256"].values())
    assert set(data["packages"]["locks"]) == {
        "renv.lock", "Project.toml", "octave-packages.json"}
    assert not data["packages"]["packages_installed"]
    assert not data["source_executed"]
    assert not data["notebook_executed"]
    assert not data["package_manager_invoked"]
    assert not data["deployment_started"]
    assert data["central_agent_studio"] == "developer"
    assert data["plot_preview_status"] == "not_rendered_during_inspection"
    assert data["notebooks"][0]["code_cells"] == 1
    assert not data["notebooks"][0]["executed"]
    assert snapshot(root) == original


def test_reference_mismatch_denies_execution_and_records_warning(project):
    client, root = project
    manifest = root / "experiment.json"
    data = json.loads(manifest.read_text())
    data["expected"]["mean"] = 35
    manifest.write_text(json.dumps(data))
    info = inspect(client, root).json()
    assert not info["safe_to_offer_reproduction"]
    assert not info["experiment"]["expected_matches_data"]
    assert "Manifest expected values do not match" in " ".join(info["warnings"])


@pytest.mark.parametrize("filename, invalid", [
    ("experiment.json", '{"version": 1, "unexpected": "yes"}'),
    ("experiment.json", '{"version":1,"name":"Bad","dataset":"../secrets.csv"}'),
    ("data/measurements.csv", "value\n10\n=1+1\n20\n"),
    ("data/measurements.csv", "value,name\n10,one\n20,two\n"),
    ("data/measurements.csv", "value\nNaN\nInfinity\n"),
    ("notebooks/study.ipynb", '{"nbformat": 4, "cells":"not-an-array"}'),
])
def test_invalid_manifest_data_or_notebook_fails_closed(project, filename, invalid):
    client, root = project
    (root / filename).write_text(invalid)
    response = inspect(client, root)
    assert response.status_code == 422


def test_csv_numeric_validation_is_bounded(project):
    client, root = project
    (root / "data/measurements.csv").write_text(
        "value\n" + "1\n" * 501)
    assert inspect(client, root).status_code == 422
    (root / "data/measurements.csv").write_text("value\n" + "9" * 150000 + "\n")
    assert inspect(client, root).status_code == 413


def test_notebook_malicious_code_is_never_executed(project):
    client, root = project
    notebook = root / "notebooks/study.ipynb"
    data = json.loads(notebook.read_text())
    data["cells"][-1]["source"] = [
        'import os; os.system("touch /tmp/V28_NOTEBOOK_SHOULD_NOT_EXIST")\n']
    notebook.write_text(json.dumps(data))
    original = snapshot(root)
    response = inspect(client, root)
    assert response.status_code == 200
    assert response.json()["notebooks"][0]["code_cells"] == 1
    assert response.json()["notebooks"][0]["executed"] is False
    assert snapshot(root) == original


def test_symlink_experiment_dataset_or_script_is_refused(project, tmp_path):
    client, root = project
    file = root / "data/measurements.csv"
    file.unlink()
    external = tmp_path / "external.csv"
    external.write_text("value\n1\n2\n")
    try:
        file.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation unavailable.")
    assert inspect(client, root).status_code == 403


def test_untrusted_hosted_and_missing_auth_refused(project, monkeypatch):
    client, root = project
    assert client.get(BASE + "/inspect", params={"project": str(root)}).status_code in (401, 403)
    if shutil.which("Rscript"):
        assert run(client, root, "r", "version").status_code == 403
    monkeypatch.setenv("AUTOMOTO_MODE", "multiuser")
    assert inspect(client, root).status_code in (401, 403, 404)


def test_consent_tool_mismatch_and_source_fingerprint_drift(project):
    client, root = project
    trust(client, root)
    if not shutil.which("Rscript"):
        pytest.skip("Rscript unavailable")
    approved = payload(client, root, "r", "reproduce")
    checks = [
        ({"confirmed": False}, 422),
        ({"accept_unsandboxed_scientific_code_and_network_risk": False}, 422),
        ({"expected_sha256": "0" * 64}, 409),
        ({"tool": "julia"}, 422),
        ({"expected_toolchain_sha256": "0" * 64}, 409),
        ({"extra_shell_options": "--eval=evil"}, 422),
    ]
    for update, code in checks:
        response = client.post(BASE + "/run", headers=AUTH, json={**approved, **update})
        assert response.status_code == code, (update, response.text)
    (root / "data/measurements.csv").write_text("value\n1\n2\n")
    response = client.post(BASE + "/run", headers=AUTH, json=approved)
    assert response.status_code == 409


def test_fixed_experiment_cannot_execute_another_script(project):
    client, root = project
    trust(client, root)
    danger = root / "experiments/danger.R"
    danger.write_text("stop('V28_DANGER_NOT_APPROVED')\n")
    info = inspect(client, root).json()
    assert "experiments/danger.R" in [x["path"] for x in info["files"]]
    if not shutil.which("Rscript"):
        pytest.skip("Rscript unavailable")
    response = run(client, root, "r", "reproduce", source="experiments/danger.R")
    assert response.status_code == 422


def test_real_installed_scientific_runtime_version_and_reproduced_computation(project):
    if os.environ.get("AUTOMOTO_V28_REAL") != "1":
        pytest.skip("Real scientific execution uses the dedicated installed-tool CI.")
    client, root = project
    trust(client, root)
    original = snapshot(root)
    languages = set(filter(None, os.environ.get("AUTOMOTO_V28_LANGUAGES", "r,julia,octave").split(",")))
    for lang in sorted(languages):
        version = run(client, root, lang, "version")
        assert version.status_code == 200, (lang, version.text)
        assert version.json()["status"] == "completed", (lang, version.json())
        assert version.json()["tool_version_output"].strip()
        result = run(client, root, lang, "reproduce")
        assert result.status_code == 200, (lang, result.text)
        data = result.json()
        assert data["status"] == "completed", (lang, data["output"][-2500:])
        assert data["reproduced"] is True, (lang, data["output"][-2500:])
        assert "V28_" + lang.upper() + "_PASS" in data["output"]
        assert data["reference"]["calculated_sum"] == "150"
        assert data["reference"]["calculated_mean"] == "30"
        assert data["source_sha256"] == hashlib.sha256(
            original[science.SCRIPTS[lang]]).hexdigest()
        assert data["data_sha256"] == hashlib.sha256(
            original["data/measurements.csv"]).hexdigest()
        assert data["temporary_project_deleted"]
        assert not data["notebook_executed"]
        assert not data["package_installation_started"]
        assert not data["deployment_started"]
        assert data["external_code_unsandboxed"]
        assert data["tool_version_output"].strip()
        if lang == "r":
            assert data["plot_png_sha256"], "Headless R PNG plot missing"
            raw = base64.b64decode(data["plot_base64"], validate=True)
            assert raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) > 500
            assert hashlib.sha256(raw).hexdigest() == data["plot_png_sha256"]
    assert snapshot(root) == original
