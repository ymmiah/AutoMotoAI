"""V25 Flutter / React Native: inert inventory, security, offline build and bridge tests."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import developer_mobile as mobile
from automoto import sandbox, server

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BASE = "/api/developer/studio/mobile"
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v25-mobile"
    shutil.copytree(FIXTURES / "v25-flutter", root, ignore=shutil.ignore_patterns(".dart_tool", "build"))
    return TestClient(server.app), root


def replace(root, name):
    shutil.rmtree(root)
    shutil.copytree(FIXTURES / name, root, ignore=shutil.ignore_patterns(
        "node_modules", ".dart_tool", "build", ".gradle"))


def inspect(client, root):
    return client.get(BASE+"/inspect", headers=AUTH, params={"project": str(root)})


def trust(client, root):
    answer = client.post("/api/developer/studio/trust", headers=AUTH,
                         json={"project": str(root), "trusted": True, "confirmed": True})
    assert answer.status_code == 200, answer.text


def snapshot(root):
    return {x.relative_to(root).as_posix(): x.read_bytes()
            for x in root.rglob("*") if x.is_file() and
            not any(name in (".dart_tool", "build", "node_modules") for name in x.parts)}


def invoke(client, root, task, tool=None, **patch):
    evidence = inspect(client, root)
    assert evidence.status_code == 200, evidence.text
    data = evidence.json()
    selected = tool or mobile.TASK_TOOL[task]
    executable = next(x for x in data["toolchains"] if x["name"] == selected)
    if executable["status"] != "installed_not_executed":
        pytest.skip("Approved installed tool not available: " + selected)
    request = {"project": str(root), "task": task, "tool": selected,
               "expected_manifest_sha256": data["manifest_sha256"],
               "expected_source_sha256": data["source_sha256"],
               "expected_toolchain_sha256": data["toolchain_sha256"],
               "expected_executable": executable["executable"],
               "expected_sha256": executable["sha256"],
               "confirmed": True,
               "accept_unsandboxed_build_packages_and_network_risk": True}
    request.update(patch)
    return client.post(BASE + "/run", headers=AUTH, json=request)


def test_flutter_source_inventory_is_inert(project):
    client, root = project
    original = snapshot(root)
    result = inspect(client, root)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["project_type"] == "flutter"
    assert data["safe_to_offer_runs"], data["warnings"]
    assert data["flutter"]["name"] == "automoto_v25_flutter"
    assert "flutter" in data["flutter"]["dependencies"]
    assert data["flutter"]["web_entry_present"]
    assert "Flutter widgets" in data["framework_hints"]
    assert any(item["name"] == "V25App" for item in data["symbols"])
    assert data["device_targets"] == "not_queried"
    assert data["device_query_performed"] is False
    assert data["dependencies_installed"] is False
    assert data["external_code_executed"] is False
    assert data["simulator_started"] is False
    assert data["app_installed"] is False
    assert data["deployment_started"] is False
    assert data["central_agent_studio"] == "developer"
    assert snapshot(root) == original


def test_react_native_metro_bridge_and_manifest_detected(project):
    client, root = project
    replace(root, "v25-react-native")
    original = snapshot(root)
    data = inspect(client, root).json()
    assert data["project_type"] == "react_native"
    assert data["safe_to_offer_runs"], data["warnings"]
    assert data["react_native"]["name"] == "automoto-v25-react-native"
    assert data["react_native"]["version"] == "0.88.1"
    assert data["react_native"]["metro_config_present"]
    assert "React Native components" in data["framework_hints"]
    assert any(item["name"] == "V25App" for item in data["symbols"])
    assert not data["device_query_performed"]
    assert not data["dependencies_installed"]
    assert snapshot(root) == original


def test_cross_framework_mixed_project_is_not_run_eligible(project):
    client, root = project
    (root / "package.json").write_text('{"name":"hybrid","dependencies":{"react-native":"0.88.1"}}')
    (root / "index.js").write_text("'use strict';\n")
    data = inspect(client, root).json()
    assert data["project_type"] == "mixed"
    assert not data["safe_to_offer_runs"]


def test_invalid_pubspec_and_package_json_refused(project):
    client, root = project
    (root / "pubspec.yaml").write_text("name: [invalid yaml\n")
    assert inspect(client, root).status_code == 422
    replace(root, "v25-react-native")
    (root / "package.json").write_text('{"dependencies":')
    assert inspect(client, root).status_code == 422


def test_flutter_git_dependencies_warn_and_block(project):
    client, root = project
    pub = root / "pubspec.yaml"
    pub.write_text(pub.read_text() + "\n# additional risk\n")
    pub.write_text(pub.read_text().replace(
        "dependencies:\n  flutter:",
        "dependencies:\n  dangerous:\n    git: https://example.invalid/a.git\n  flutter:"))
    data = inspect(client, root).json()
    assert not data["safe_to_offer_runs"]
    assert any("git/path/hosted" in x for x in data["warnings"])


def test_react_native_unsafe_metro_config_warns(project):
    client, root = project
    replace(root, "v25-react-native")
    file = root / "metro.config.js"
    file.write_text(file.read_text() + "\n// require('child_process').spawnSync()\n")
    data = inspect(client, root).json()
    assert not data["safe_to_offer_runs"]
    assert any("Metro config" in x for x in data["warnings"])


def test_generated_flutter_caches_are_excluded_from_inventory(project):
    client, root = project
    cache = root / ".dart_tool" / "generated"
    cache.mkdir(parents=True)
    for n in range(290):
        (cache / f"cache-{n}.json").write_text("{}")
    data = inspect(client, root).json()
    assert data["safe_to_offer_runs"], data["warnings"]
    assert all(".dart_tool" not in x["path"] for x in data["files"])


def test_symlink_manifest_denied(project, tmp_path):
    client, root = project
    pub = root / "pubspec.yaml"
    pub.unlink()
    outside = tmp_path / "external.yaml"
    outside.write_text("name: external\n")
    try:
        pub.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("No symlink support.")
    assert inspect(client, root).status_code == 403


def test_auth_and_hosted_remote_operation_denied(project, monkeypatch):
    client, root = project
    assert client.get(BASE+"/inspect", params={"project": str(root)}).status_code in (401,403)
    monkeypatch.setenv("AUTOMOTO_MODE", "multiuser")
    assert inspect(client, root).status_code in (401,403,404)


def test_untrusted_then_consent_then_stale_source(project):
    client, root = project
    if not shutil.which("node"):
        pytest.skip("Installed Node not available.")
    response = invoke(client, root, "node_version")
    assert response.status_code == 403
    trust(client, root)
    evidence = inspect(client, root).json()
    tool = next(x for x in evidence["toolchains"] if x["name"] == "node")
    if tool["status"] != "installed_not_executed":
        pytest.skip("Approved Node binary not present.")
    request = {"project": str(root), "task": "node_version", "tool": "node",
               "expected_manifest_sha256": evidence["manifest_sha256"],
               "expected_source_sha256": evidence["source_sha256"],
               "expected_toolchain_sha256": evidence["toolchain_sha256"],
               "expected_executable": tool["executable"],
               "expected_sha256": tool["sha256"], "confirmed": True,
               "accept_unsandboxed_build_packages_and_network_risk": True}
    for change in ({"confirmed":False}, {"accept_unsandboxed_build_packages_and_network_risk":False}):
        assert client.post(BASE+"/run",headers=AUTH,json={**request,**change}).status_code == 422
    assert client.post(BASE+"/run",headers=AUTH,json={**request,"expected_sha256":"0"*64}).status_code == 409
    (root / "lib/main.dart").write_text("void main() { }\n")
    assert client.post(BASE+"/run",headers=AUTH,json=request).status_code == 409


def test_react_native_real_node_bridge_and_syntax(project):
    client, root = project
    replace(root, "v25-react-native")
    trust(client, root)
    for task in ("node_version", "rn_node_check", "rn_node_test"):
        answer = invoke(client, root, task)
        assert answer.status_code == 200, (task, answer.text)
        data = answer.json()
        assert data["status"] == "completed", (task, "\n".join(data["output"].splitlines()[-40:]))
        assert data["temporary_project_deleted"] is True
        assert not data["app_installed"]
        assert not data["app_deployed"]
        assert not data["emulator_started"]


def test_real_flutter_analyse_widget_and_web_build(project):
    if os.environ.get("AUTOMOTO_V25_REAL_FLUTTER") != "1":
        pytest.skip("Real Flutter SDK tests run in dedicated installed Flutter CI.")
    client, root = project
    trust(client, root)
    before = snapshot(root)
    for task in ("flutter_version", "flutter_pub_offline", "flutter_analyze",
                 "flutter_test", "flutter_build_web"):
        result = invoke(client, root, task)
        assert result.status_code == 200, (task, result.text)
        data = result.json()
        assert data["status"] == "completed", (task, "\n".join(data["output"].splitlines()[-40:]))
        assert data["temporary_project_deleted"]
        assert data["external_code_unsandboxed"]
        assert not data["emulator_started"]
        assert not data["app_installed"]
        assert not data["app_deployed"]
    assert snapshot(root) == before
