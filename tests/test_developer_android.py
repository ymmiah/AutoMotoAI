"""V23 Android/Kotlin inspection, security, and real Gradle SDK verification."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import developer_android as android, sandbox, server

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BASE = "/api/developer/studio/android"
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v23-mobile"
    shutil.copytree(FIXTURES / "v23-kotlin", root)
    return TestClient(server.app), root


def replace(root, fixture):
    shutil.rmtree(root)
    shutil.copytree(FIXTURES / fixture, root)


def inspect(client, root):
    return client.get(BASE + "/inspect", headers=AUTH, params={"project": str(root)})


def trust(client, root):
    out = client.post("/api/developer/studio/trust", headers=AUTH,
                      json={"project": str(root), "trusted": True, "confirmed": True})
    assert out.status_code == 200, out.text


def invoke(client, root, task="gradle_version", tool="gradle", **modifiers):
    result = inspect(client, root)
    assert result.status_code == 200, result.text
    data = result.json()
    selected = next(t for t in data["toolchains"] if t["name"] == tool)
    if selected["status"] != "installed_not_executed":
        pytest.skip("Installed approved executable not available: " + tool)
    body = {"project": str(root), "task": task, "tool": tool,
            "expected_manifest_sha256": data["manifest_sha256"],
            "expected_source_sha256": data["source_sha256"],
            "expected_toolchain_sha256": data["toolchain_sha256"],
            "expected_executable": selected["executable"], "expected_sha256": selected["sha256"],
            "confirmed": True, "accept_unsandboxed_gradle_and_test_risk": True}
    body.update(modifiers)
    return client.post(BASE + "/run", json=body, headers=AUTH)


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def test_kotlin_jvm_inert_source_inspection(project):
    client, root = project
    before = snapshot(root)
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["project_type"] == "kotlin_jvm"
    assert data["safe_to_offer_runs"], data["warnings"]
    assert data["gradle"]["kotlin_plugin_version"] == "2.2.21"
    assert data["source_sha256"] and data["manifest_sha256"]
    assert any(x["name"] == "Calculator" for x in data["symbols"])
    assert data["central_agent_studio"] == "developer"
    assert data["project_code_executed"] is False
    assert data["gradle_wrapper_executed"] is False
    assert data["packages_downloaded"] is False
    assert data["deployment_started"] is False
    assert snapshot(root) == before


def test_android_sample_inventory_sdk_and_gradle_compatibility(project):
    client, root = project
    replace(root, "v23-android")
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["project_type"] == "android"
    assert data["safe_to_offer_runs"], data["warnings"]
    assert data["gradle"]["agp_version"] == "8.13.2"
    assert data["gradle"]["kotlin_plugin_version"] == "2.2.21"
    assert data["gradle"]["wrapper_version"] == "8.13"
    assert data["gradle"]["agp_gradle_advisory"] == "declared_minimum_met"
    assert any(x["path"].endswith("MainActivity.kt") for x in data["files"])
    assert data["android_sdk"]["emulator_started"] is False
    assert data["android_sdk"]["device_connected"] is False
    assert data["project_code_executed"] is False
    assert data["deployment_started"] is False
    assert data["emulator"].startswith("Emulator discovery only")


def test_compose_heuristic_and_no_false_execution_claim(project):
    client, root = project
    replace(root, "v23-android")
    file = root / "app/src/main/java/com/automoto/v23/ComposeScreen.kt"
    file.write_text(
        "package com.automoto.v23\n"
        "import androidx.compose.runtime.Composable\n"
        "@Composable fun V23Hello() { }\n")
    before = snapshot(root)
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    data = response.json()
    assert "Jetpack Compose" in data["framework_hints"]
    assert any(x["compose_hint"] for x in data["files"] if x["path"].endswith("ComposeScreen.kt"))
    assert data["project_code_executed"] is False
    assert snapshot(root) == before


def test_gradle_plugin_wrapper_mismatch_blocks_approval(project):
    client, root = project
    replace(root, "v23-android")
    file = root / "gradle/wrapper/gradle-wrapper.properties"
    file.write_text("distributionUrl=https\\://services.gradle.org/distributions/gradle-8.9-bin.zip\n")
    result = inspect(client, root)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["gradle"]["agp_gradle_advisory"] == "declared_incompatible"
    assert not data["safe_to_offer_runs"]


def test_symlinked_android_manifest_and_malicious_xml_are_denied(project, tmp_path):
    client, root = project
    replace(root, "v23-android")
    manifest = root / "app/src/main/AndroidManifest.xml"
    manifest.write_text('<!DOCTYPE manifest [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
                        '<manifest>&x;</manifest>')
    assert inspect(client, root).status_code == 422
    manifest.unlink()
    outside = tmp_path / "other.xml"
    outside.write_text("<manifest/>")
    try:
        manifest.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not available")
    result = inspect(client, root)
    assert result.status_code in (200, 403)
    if result.status_code == 200:
        assert not result.json()["safe_to_offer_runs"]


def test_custom_gradle_properties_and_external_settings_refuse_build(project):
    client, root = project
    (root / "gradle.properties").write_text("privatePassword=secrets\n")
    data = inspect(client, root).json()
    assert not data["safe_to_offer_runs"]
    (root / "gradle.properties").unlink()
    settings = root / "settings.gradle.kts"
    settings.write_text(settings.read_text()+"\nincludeBuild(\"../outside\")\n")
    assert not inspect(client, root).json()["safe_to_offer_runs"]


def test_trust_consent_and_sha_mismatch_denied(project):
    client, root = project
    if not shutil.which("gradle"):
        pytest.skip("No host Gradle executable for fingerprint checks")
    assert invoke(client, root, "gradle_version").status_code == 403
    trust(client, root)
    data = inspect(client, root).json()
    binary = next(x for x in data["toolchains"] if x["name"] == "gradle")
    if binary["status"] != "installed_not_executed":
        pytest.skip("Gradle launcher is not approved")
    body = {"project": str(root), "task": "gradle_version", "tool": "gradle",
            "expected_manifest_sha256": data["manifest_sha256"],
            "expected_source_sha256": data["source_sha256"],
            "expected_toolchain_sha256": data["toolchain_sha256"],
            "expected_executable": binary["executable"], "expected_sha256": binary["sha256"],
            "confirmed": True, "accept_unsandboxed_gradle_and_test_risk": True}
    for patch in ({"confirmed": False},
                  {"accept_unsandboxed_gradle_and_test_risk": False}):
        assert client.post(BASE + "/run", headers=AUTH,
                           json={**body, **patch}).status_code == 422
    assert client.post(BASE + "/run", headers=AUTH,
                       json={**body, "expected_sha256": "0"*64}).status_code == 409
    (root / "src/main/kotlin/example/v23/Calculator.kt").write_text(
        "package example.v23\nfun altered() = -1\n")
    assert client.post(BASE + "/run", headers=AUTH, json=body).status_code == 409


def test_real_kotlin_jvm_gradle_build_and_tests(project):
    if os.environ.get("AUTOMOTO_V23_REAL_KOTLIN") != "1":
        pytest.skip("Real Kotlin build/test runs in pinned Gradle 8.13 CI only")
    client, root = project
    trust(client, root)
    original = snapshot(root)
    for task in ("gradle_version", "kotlin_build", "kotlin_test"):
        answer = invoke(client, root, task)
        assert answer.status_code == 200, (task, answer.text)
        data = answer.json()
        assert data["status"] == "completed", (task, "\n".join(data["output"].splitlines()[-45:]))
        assert data["temporary_project_deleted"] is True
        assert data["external_process_unsandboxed"]
        assert not data["emulator_started"]
        assert not data["device_touched"]
        assert not data["deployment_started"]
        if task == "kotlin_test":
            assert "BUILD SUCCESSFUL" in data["output"]
    assert snapshot(root) == original


def test_real_android_offline_assemble_and_unit_test(project):
    if os.environ.get("AUTOMOTO_V23_REAL_ANDROID") != "1":
        pytest.skip("Android SDK/Gradle prerequisites are installed in a dedicated CI job")
    client, root = project
    replace(root, "v23-android")
    trust(client, root)
    original = snapshot(root)
    data = inspect(client, root).json()
    assert data["android_sdk"]["status"] == "installed_not_executed"
    assert "android-35" in data["android_sdk"]["platforms"]
    for task in ("android_assemble", "android_unit_test"):
        res = invoke(client, root, task)
        assert res.status_code == 200, (task, res.text)
        result = res.json()
        assert result["status"] == "completed", (task, "\n".join(result["output"].splitlines()[-45:]))
        assert result["temporary_project_deleted"]
        assert not result["emulator_started"] and not result["device_touched"]
        assert not result["deployment_started"]
    assert snapshot(root) == original


def test_hosted_and_missing_auth_denied(project, monkeypatch):
    client, root = project
    assert client.get(BASE+"/inspect", params={"project":str(root)}).status_code in (401,403)
    monkeypatch.setenv("AUTOMOTO_MODE", "multiuser")
    assert inspect(client, root).status_code in (401,403,404)
