"""V24 Swift/SwiftPM/Xcode: non-executing discovery, security and real macOS acceptance."""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import developer_swift as swift
from automoto import sandbox, server

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BASE = "/api/developer/studio/swift"
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v24-swift"
    shutil.copytree(FIXTURES / "v24-swiftpm", root)
    return TestClient(server.app), root


def replace(root, name):
    shutil.rmtree(root)
    shutil.copytree(FIXTURES / name, root)


def inspect(client, root):
    return client.get(BASE + "/inspect", params={"project": str(root)}, headers=AUTH)


def trust(client, root):
    answer = client.post("/api/developer/studio/trust", headers=AUTH,
                         json={"project": str(root), "trusted": True, "confirmed": True})
    assert answer.status_code == 200, answer.text


def snapshot(root):
    return {x.relative_to(root).as_posix(): x.read_bytes()
            for x in root.rglob("*") if x.is_file()}


def run(client, root, task="swift_version", tool=None, **overrides):
    observed = inspect(client, root)
    assert observed.status_code == 200, observed.text
    evidence = observed.json()
    executable = tool or swift.TASK_TO_TOOL[task]
    record = next(x for x in evidence["toolchains"] if x["name"] == executable)
    if record["status"] != "installed_not_executed":
        pytest.skip("Installed approved Swift/Xcode executable absent: " + executable)
    request = {"project": str(root), "task": task, "tool": executable,
               "expected_manifest_sha256": evidence["manifest_sha256"],
               "expected_source_sha256": evidence["source_sha256"],
               "expected_toolchain_sha256": evidence["toolchain_sha256"],
               "expected_executable": record["executable"],
               "expected_sha256": record["sha256"],
               "confirmed": True,
               "accept_unsandboxed_compiler_manifest_and_network_risk": True}
    request.update(overrides)
    return client.post(BASE + "/run", json=request, headers=AUTH)


def test_swift_package_inventory_is_read_only(project):
    client, root = project
    original = snapshot(root)
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["project_type"] == "swiftpm"
    assert data["safe_to_offer_builds"], data["warnings"]
    assert data["swiftpm"]["declared_executable"] == "V24CLI"
    assert not data["swiftpm"]["external_dependencies"]
    assert any(f["language"] == "Swift" for f in data["files"])
    assert any(symbol["name"] == "Greeting" for symbol in data["symbols"])
    assert data["simulator_status"] == "not_queried"
    assert data["simulator_started"] is False
    assert data["package_manifest_evaluated"] is False
    assert data["project_code_executed"] is False
    assert data["package_download_started"] is False
    assert data["deployment_started"] is False
    assert data["central_agent_studio"] == "developer"
    assert snapshot(root) == original


def test_prewarmed_swiftpm_build_artifacts_are_excluded(project):
    client, root = project
    artifacts = root / ".build" / "generated"
    artifacts.mkdir(parents=True)
    for number in range(280):
        (artifacts / f"cache-{number}.bin").write_bytes(b"swiftpm-generated-cache")
    before = snapshot(root)
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["safe_to_offer_builds"], data["warnings"]
    assert any(x["name"] == "Greeting" for x in data["symbols"])
    assert not data["source_sha256"] == ""
    assert not any(".build" in x["path"] for x in data["files"])
    assert snapshot(root) == before


def test_xcode_shared_scheme_and_swiftui_are_detected_without_build(project):
    client, root = project
    replace(root, "v24-ios")
    original = snapshot(root)
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["project_type"] == "xcode_ios"
    assert result["ios"]["project"] == "V24iOS.xcodeproj"
    assert result["ios"]["scheme"] == "V24iOS"
    assert result["ios"]["bundle_ids"] == ["org.automoto.v24fixture"]
    assert result["ios"]["deployment_targets"] == ["17.0"]
    assert result["safe_to_offer_builds"], result["warnings"]
    assert "SwiftUI" in result["framework_hints"]
    assert result["simulator_started"] is False
    assert result["device_installed_to"] is False
    assert snapshot(root) == original


def test_objective_c_static_analysis_does_not_claim_full_compile(project):
    client, root = project
    replace(root, "v24-objc")
    original = snapshot(root)
    data = inspect(client, root).json()
    assert "Objective-C" in data["framework_hints"]
    assert any(x["name"] == "V24Greeter" for x in data["symbols"])
    assert not data["safe_to_offer_builds"]
    assert data["project_type"] == "unknown"
    assert data["project_code_executed"] is False
    assert snapshot(root) == original


def test_remote_swiftpm_packages_and_plugin_admission_denied(project):
    client, root = project
    package = root / "Package.swift"
    original = package.read_text()
    for injection in (
        '\n// .package(url: "https://private.invalid/evil.git", from: "1.0.0")\n',
        '\n// .unsafeFlags(["-Xfrontend"])\n',
        '\n// .binaryTarget(name: "External", url: "https://invalid", checksum: "x")\n',
        '\n// .macro(name: "Generator", dependencies: [])\n',
        '\n// Process()\n',
    ):
        package.write_text(original + injection)
        data = inspect(client, root).json()
        assert not data["safe_to_offer_builds"], injection
        assert data["swiftpm"]["external_dependencies"]


def test_manifest_without_any_swift_sources_cannot_admit_build(project):
    client, root = project
    shutil.rmtree(root / "Sources")
    shutil.rmtree(root / "Tests")
    data = inspect(client, root).json()
    assert data["project_type"] == "swiftpm"
    assert not data["safe_to_offer_builds"]
    assert any("source inventory" in issue for issue in data["warnings"])


def test_external_or_malformed_shared_xcode_scheme_is_refused(project):
    client, root = project
    replace(root, "v24-ios")
    scheme = root / "V24iOS.xcodeproj/xcshareddata/xcschemes/V24iOS.xcscheme"
    original = scheme.read_text()
    scheme.write_text(original.replace("container:V24iOS.xcodeproj", "container:../outside.xcodeproj"))
    data = inspect(client, root).json()
    assert not data["safe_to_offer_builds"]
    assert any("external build target" in x for x in data["warnings"])
    scheme.write_text('<!DOCTYPE Scheme [<!ENTITY ext SYSTEM "file:///etc/passwd">]><Scheme>&ext;</Scheme>')
    assert inspect(client, root).status_code == 422


def test_xcode_shell_scripts_and_remote_refs_block_approval(project):
    client, root = project
    replace(root, "v24-ios")
    pbx = root / "V24iOS.xcodeproj/project.pbxproj"
    original = pbx.read_text()
    for risk in ("PBXShellScriptBuildPhase", "XCRemoteSwiftPackageReference",
                 "DEVELOPMENT_TEAM", "CODE_SIGN_ENTITLEMENTS"):
        pbx.write_text(original + "\n/* " + risk + " */\n")
        data = inspect(client, root).json()
        assert not data["safe_to_offer_builds"]
        assert any(risk in x for x in data["warnings"])


def test_linked_package_manifest_rejected(project, tmp_path):
    client, root = project
    package = root / "Package.swift"
    package.unlink()
    outside = tmp_path / "other-package.swift"
    outside.write_text("// swift-tools-version: 5.9\nimport PackageDescription\n")
    try:
        package.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation unsupported on this host.")
    assert inspect(client, root).status_code == 403


def test_stale_source_invalidates_approved_command(project):
    client, root = project
    trust(client, root)
    evidence = inspect(client, root).json()
    tool = next(x for x in evidence["toolchains"] if x["name"] == "swift")
    if tool["status"] != "installed_not_executed":
        pytest.skip("Swift binary unavailable for SHA-pinning checks.")
    body = {"project": str(root), "task": "swift_version", "tool": "swift",
            "expected_manifest_sha256": evidence["manifest_sha256"],
            "expected_source_sha256": evidence["source_sha256"],
            "expected_toolchain_sha256": evidence["toolchain_sha256"],
            "expected_executable": tool["executable"],
            "expected_sha256": tool["sha256"], "confirmed": True,
            "accept_unsandboxed_compiler_manifest_and_network_risk": True}
    assert client.post(BASE + "/run", headers=AUTH,
                       json={**body, "expected_sha256": "0"*64}).status_code == 409
    assert client.post(BASE + "/run", headers=AUTH,
                       json={**body, "confirmed": False}).status_code == 422
    assert client.post(BASE + "/run", headers=AUTH,
                       json={**body, "accept_unsandboxed_compiler_manifest_and_network_risk": False}).status_code == 422
    (root / "Sources/V24Core/Greeting.swift").write_text("public struct Greeting {}\n")
    assert client.post(BASE + "/run", headers=AUTH, json=body).status_code == 409


def test_untrusted_and_hosted_access_denied(project, monkeypatch):
    client, root = project
    assert client.get(BASE + "/inspect", params={"project": str(root)}).status_code in (401, 403)
    if shutil.which("swift"):
        result = run(client, root, "swift_version")
        assert result.status_code == 403
    monkeypatch.setenv("AUTOMOTO_MODE", "multiuser")
    assert inspect(client, root).status_code in (401, 403, 404)


def test_apple_toolchain_requires_macos(project):
    client, root = project
    data = inspect(client, root).json()
    assert data["xcode_build_available_only_on_macos"]
    assert data["simulator_status"] == "not_queried"
    if sys.platform != "darwin":
        # Never advertise an Apple build option as a cross-platform executable.
        assert data["platform"] != "darwin"


def test_real_swiftpm_build_test_and_executable_smoke(project):
    if os.environ.get("AUTOMOTO_V24_REAL_SWIFT") != "1":
        pytest.skip("Real SwiftPM execution runs in installed Swift/Xcode CI only.")
    client, root = project
    trust(client, root)
    original = snapshot(root)
    for task in ("swift_version", "swiftc_version", "swift_build", "swift_test", "swift_smoke"):
        response = run(client, root, task)
        assert response.status_code == 200, (task, response.text)
        result = response.json()
        assert result["status"] == "completed", (task, "\n".join(result["output"].splitlines()[-35:]))
        assert result["temporary_project_deleted"]
        assert result["external_process_unsandboxed"] is True
        assert result["simulator_started"] is False
        assert result["deployment_started"] is False
        if task == "swift_version":
            assert re.search(r"Swift version|swift-driver version", result["output"], re.I)
        if task == "swift_smoke":
            assert "V24_SWIFTPM_SMOKE_PASS" in result["output"]
    assert snapshot(root) == original


def test_real_xcode_simulator_build_without_installing_device(project):
    if os.environ.get("AUTOMOTO_V24_REAL_XCODE") != "1":
        pytest.skip("Real unsigned iOS simulator compilation requires dedicated macOS/Xcode CI.")
    client, root = project
    replace(root, "v24-ios")
    trust(client, root)
    original = snapshot(root)
    for task in ("xcode_version", "simulator_list", "ios_simulator_build"):
        response = run(client, root, task)
        assert response.status_code == 200, (task, response.text)
        data = response.json()
        assert data["status"] == "completed", (task, "\n".join(data["output"].splitlines()[-35:]))
        assert data["temporary_project_deleted"]
        assert data["production_signed"] is False
        assert data["device_installed_to"] is False
        assert data["simulator_started"] is False
        assert data["deployment_started"] is False
    assert snapshot(root) == original
