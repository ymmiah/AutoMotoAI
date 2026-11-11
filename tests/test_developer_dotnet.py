"""V22 real .NET SDK, NuGet offline, xUnit/NUnit and security acceptance."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import developer_dotnet as dotnet, sandbox, server

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BASE = "/api/developer/studio/dotnet"
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v22-dotnet"
    shutil.copytree(FIXTURES / "v22-console", root)
    return TestClient(server.app), root


def replace(root, name):
    shutil.rmtree(root)
    shutil.copytree(FIXTURES / name, root)


def inspect(client, root):
    return client.get(BASE + "/inspect", headers=AUTH, params={"project": str(root)})


def trust(client, root):
    answer = client.post("/api/developer/studio/trust", headers=AUTH,
                         json={"project": str(root), "trusted": True, "confirmed": True})
    assert answer.status_code == 200, answer.text


def run(client, root, task="sdk_version", **overrides):
    answer = inspect(client, root)
    assert answer.status_code == 200, answer.text
    data = answer.json()
    tool = next((x for x in data["toolchains"] if x["name"] == "dotnet"), None)
    if tool is None or tool["status"] != "installed_not_executed":
        pytest.skip("Approved .NET SDK executable unavailable")
    body = {"project": str(root), "task": task, "tool": "dotnet",
            "expected_manifest_sha256": data["manifest_sha256"],
            "expected_source_sha256": data["source_sha256"],
            "expected_toolchain_sha256": data["toolchain_sha256"],
            "expected_executable": tool["executable"], "expected_sha256": tool["sha256"],
            "confirmed": True, "accept_unsandboxed_msbuild_and_test_execution": True}
    body.update(overrides)
    return client.post(BASE + "/run", headers=AUTH, json=body)


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def test_static_dotnet_console_inspection_does_not_run_sdk(workspace):
    client, root = workspace
    before = snapshot(root)
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["safe_to_offer_builds"], data["warnings"]
    assert data["primary_project"] == "V22.Console.csproj"
    assert data["projects"][0]["sdk"] == "Microsoft.NET.Sdk"
    assert data["projects"][0]["target_frameworks"] == ["net8.0"]
    assert data["projects"][0]["output_type"] == "Exe"
    assert data["installed_sdk_version"] is None
    assert data["source_sha256"] and data["manifest_sha256"]
    assert any(x["name"] == "Program" for x in data["symbols"])
    assert not data["project_code_executed"]
    assert not data["download_or_install_started"]
    assert not data["deployment_started"]
    assert data["central_agent_studio"] == "developer"
    assert data["agent_deployment_handoff_required"]
    assert snapshot(root) == before


def test_aspnet_blazor_and_test_framework_are_evidence_not_execution(workspace):
    client, root = workspace
    (root / "V22.Console.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk.Web">'
        '<PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>'
        '<ItemGroup><PackageReference Include="xunit" Version="2.9.2" />'
        '<PackageReference Include="NUnit" Version="4.3.2" />'
        '</ItemGroup></Project>')
    (root / "Home.razor").write_text("@page \"/\"\n<h1>Blazor</h1>\n")
    value = inspect(client, root).json()
    assert value["safe_to_offer_builds"]
    assert set(value["framework_hints"]) >= {"ASP.NET Core", "Blazor", "xUnit", "NUnit"}
    assert value["projects"][0]["target_frameworks"] == ["net10.0"]
    assert value["projects"][0]["package_references"][0]["name"] == "xunit"
    assert value["project_code_executed"] is False
    assert value["lsp"].startswith("Use separately")
    assert value["dap"].startswith("Use separately")


def test_global_json_is_only_a_declared_sdk_not_executed(workspace):
    client, root = workspace
    (root / "global.json").write_text('{"sdk":{"version":"10.0.100","rollForward":"latestPatch"}}')
    data = inspect(client, root).json()
    assert data["sdk_request"]["requested_version"] == "10.0.100"
    assert data["installed_sdk_version"] is None
    (root / "global.json").write_text('{"sdk":{"version":"unsafe"}}')
    assert inspect(client, root).status_code == 422
    (root / "global.json").write_text("{invalid")
    assert inspect(client, root).status_code == 422


def test_xml_external_entity_import_custom_targets_and_project_reference_block(workspace):
    client, root = workspace
    path = root / "V22.Console.csproj"
    path.write_text('<!DOCTYPE Project [<!ENTITY secret SYSTEM "file:///etc/passwd">]>'
                    '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                    '<TargetFramework>&secret;</TargetFramework>'
                    '</PropertyGroup></Project>')
    assert inspect(client, root).status_code == 422
    for tag in ('<Import Project="../external.targets"/>',
                '<Target Name="Download"><Exec Command="curl http://invalid"/></Target>',
                '<ItemGroup><ProjectReference Include="../other.csproj"/></ItemGroup>'):
        path.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                        '<TargetFramework>net8.0</TargetFramework></PropertyGroup>'
                        + tag + '</Project>')
        data = inspect(client, root).json()
        assert not data["safe_to_offer_builds"]
        assert data["projects"][0]["unsafe_constructs"]


def test_linked_manifests_are_never_accepted(workspace, tmp_path):
    client, root = workspace
    (root / "V22.Console.csproj").unlink()
    outside = tmp_path / "outside.csproj"
    outside.write_text('<Project Sdk="Microsoft.NET.Sdk"/>')
    try:
        (root / "V22.Console.csproj").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation unavailable")
    result = inspect(client, root)
    assert result.status_code in (200, 403)
    if result.status_code == 200:
        assert not result.json()["safe_to_offer_builds"]


def test_custom_nuget_sources_block_build_admission(workspace):
    client, root = workspace
    (root / "NuGet.Config").write_text(
        '<configuration><packageSources><add key="evil" value="https://bad.test"/></packageSources></configuration>')
    data = inspect(client, root).json()
    assert not data["safe_to_offer_builds"]
    assert any("NuGet" in warning for warning in data["warnings"])


def test_untrusted_stale_hash_and_missing_consent_are_refused(workspace):
    client, root = workspace
    assert run(client, root).status_code == 403
    trust(client, root)
    info = inspect(client, root).json()
    tool = next(x for x in info["toolchains"] if x["name"] == "dotnet")
    if tool["status"] != "installed_not_executed":
        pytest.skip(".NET SDK unavailable")
    body = {"project": str(root), "task": "sdk_version", "tool": "dotnet",
            "expected_manifest_sha256": info["manifest_sha256"],
            "expected_source_sha256": info["source_sha256"],
            "expected_toolchain_sha256": info["toolchain_sha256"],
            "expected_executable": tool["executable"], "expected_sha256": tool["sha256"],
            "confirmed": True, "accept_unsandboxed_msbuild_and_test_execution": True}
    for changed in ({"confirmed": False},
                    {"accept_unsandboxed_msbuild_and_test_execution": False}):
        result = client.post(BASE + "/run", headers=AUTH, json={**body, **changed})
        assert result.status_code == 422
    assert client.post(BASE + "/run", headers=AUTH,
                       json={**body, "expected_sha256": "0"*64}).status_code == 409
    assert client.post(BASE + "/run", headers=AUTH,
                       json={**body, "expected_toolchain_sha256": "0"*64}).status_code == 409
    (root / "Program.cs").write_text((root / "Program.cs").read_text()+"\n//changed\n")
    assert client.post(BASE + "/run", headers=AUTH, json=body).status_code == 409
    body["expected_source_sha256"] = inspect(client, root).json()["source_sha256"]
    (root / "V22.Console.csproj").write_text(
        (root / "V22.Console.csproj").read_text()+"\n<!--changed-->\n")
    assert client.post(BASE + "/run", headers=AUTH, json=body).status_code == 409


def test_real_dotnet_sdk_msbuild_build_and_smoke(workspace):
    client, root = workspace
    trust(client, root)
    before = snapshot(root)
    for task in ("sdk_version", "list_sdks", "msbuild_version", "restore_offline", "build", "run_smoke"):
        response = run(client, root, task)
        assert response.status_code == 200, (task, response.text)
        data = response.json()
        assert data["status"] == "completed", (task, data["output"])
        assert data["temporary_project_deleted"]
        assert data["external_process_unsandboxed"]
        assert data["nuget_sources_disabled_for_restore"]
        assert data["deployment_started"] is False
        assert data["agent_deployment_approved"] is False
        if task == "sdk_version":
            assert re.search(r"\d+\.\d+\.\d+", data["actual_sdk_version"])
        if task == "run_smoke":
            assert "DOTNET_V22_SMOKE_PASS" in data["output"]
    assert snapshot(root) == before, "External build must not change original project files"


def test_dotnet_compiler_error_is_not_misreported_as_success(workspace):
    client, root = workspace
    trust(client, root)
    (root / "Program.cs").write_text("public static class Program { public static void Main( { }\n")
    result = run(client, root, "build")
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["status"] == "nonzero_exit", data["output"]
    assert "error CS" in data["output"]
    assert data["deployment_started"] is False


@pytest.mark.parametrize("fixture,framework", [
    ("v22-xunit", "xUnit"), ("v22-nunit", "NUnit")
])
def test_real_offline_framework_tests_and_original_source_unchanged(workspace, fixture, framework):
    client, root = workspace
    replace(root, fixture)
    data = inspect(client, root).json()
    assert data["safe_to_offer_builds"], data["warnings"]
    assert framework in data["framework_hints"]
    assert data["projects"][0]["is_test_project"]
    if os.environ.get("AUTOMOTO_V22_TEST_PACKAGES_READY") != "1":
        pytest.skip("Real xUnit/NUnit tests require prewarmed local NuGet cache.")
    trust(client, root)
    before = snapshot(root)
    result = run(client, root, "test")
    assert result.status_code == 200, result.text
    output = result.json()
    assert output["status"] == "completed", output["output"]
    assert "Passed:" in output["output"] and "1" in output["output"]
    assert [x["stage"] for x in output["stages"]] == ["restore", "build", "test"]
    assert not output["deployment_started"]
    assert output["temporary_project_deleted"]
    assert snapshot(root) == before


def test_non_test_projects_cannot_claim_successful_suite(workspace):
    client, root = workspace
    trust(client, root)
    response = run(client, root, "test")
    assert response.status_code == 409


def test_hosted_and_unauthorised_access_denied(workspace, monkeypatch):
    client, root = workspace
    assert client.get(BASE + "/inspect", params={"project": str(root)}).status_code in (401,403)
    monkeypatch.setenv("AUTOMOTO_MODE", "multiuser")
    assert inspect(client, root).status_code in (401,403,404)
