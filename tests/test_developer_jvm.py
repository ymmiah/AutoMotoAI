"""V21: real JDK service, cached JUnit Maven, Gradle and security acceptance."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from automoto import developer_jvm as jvm, sandbox, server

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BASE = "/api/developer/studio/jvm"
FIXTURES = Path(__file__).parent / "fixtures"
GREETER = """package example;
public final class Greeter {
    public static int add(int a, int b) { return a + b; }
}
"""
SMOKE = """package example;
public class SmokeTest {
    public static void main(String[] args) {
        if (Greeter.add(20, 22) != 42) System.exit(1);
        System.out.println("JVM_SMOKE_PASS");
    }
}
"""


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v21-jvm"
    (root / "src/main/java/example").mkdir(parents=True)
    (root / "src/test/java/example").mkdir(parents=True)
    (root / "src/main/java/example/Greeter.java").write_text(GREETER)
    (root / "src/test/java/example/SmokeTest.java").write_text(SMOKE)
    return TestClient(server.app), root


def inspect(client, root):
    return client.get(BASE+"/inspect", headers=AUTH, params={"project": str(root)})


def trust(client, root):
    res=client.post("/api/developer/studio/trust", headers=AUTH,
                    json={"project": str(root), "trusted": True, "confirmed": True})
    assert res.status_code == 200, res.text


def run(client, root, task="jdk_version", tool="java", **overrides):
    info = inspect(client, root)
    assert info.status_code == 200, info.text
    details = info.json()
    item = next(x for x in details["toolchains"] if x["name"] == tool)
    if item["status"] != "installed_not_executed":
        pytest.skip("Verified installed JVM tool unavailable: "+tool)
    body = {"project": str(root), "task": task, "tool": tool,
            "expected_manifest_sha256": details["manifest_sha256"],
            "expected_source_sha256": details["source_sha256"],
            "expected_toolchain_sha256": details["toolchain_sha256"],
            "expected_executable": item["executable"], "expected_sha256": item["sha256"],
            "confirmed": True, "accept_unsandboxed_build_test_and_network_risk": True}
    body.update(overrides)
    return client.post(BASE+"/run", headers=AUTH, json=body)


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def replace_with_fixture(root, fixture):
    shutil.rmtree(root)
    shutil.copytree(FIXTURES / fixture, root)


def test_jdk_only_source_inventory_is_inert_and_sources_stay_unchanged(workspace):
    client, root = workspace
    before = snapshot(root)
    result = inspect(client, root)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["build_system"] == "jdk_only"
    assert set(x["path"] for x in data["files"]) == {
        "src/main/java/example/Greeter.java", "src/test/java/example/SmokeTest.java"}
    assert data["source_sha256"] and data["manifest_sha256"]
    assert any(item["class"] == "example.SmokeTest" and item["test"]
               for item in data["main_classes"])
    assert data["project_code_executed"] is False
    assert data["dependency_download_requested"] is False
    assert data["deployment_started"] is False
    assert data["central_agent_studio"] == "developer"
    assert snapshot(root) == before


def test_real_javac_java_compile_smoke_and_ephemeral_staging(workspace):
    client, root = workspace
    trust(client, root)
    before = snapshot(root)
    for task, tool in (("jdk_version", "java"), ("javac_version", "javac"),
                       ("jdk_compile", "javac"), ("jdk_smoke", "javac")):
        response = run(client, root, task, tool)
        assert response.status_code == 200, (task, response.text)
        data = response.json()
        assert data["status"] == "completed", (task, data["output"])
        assert data["temporary_project_deleted"]
        assert data["external_process_unsandboxed"]
        assert not data["deployment_started"]
        if task == "jdk_smoke":
            assert [x["stage"] for x in data["stages"]] == ["compile", "smoke"]
            assert "JVM_SMOKE_PASS" in data["output"]
    assert snapshot(root) == before, "JDK tools must not modify original project files"


def test_real_compiler_error_is_surfaced_not_misclassified(workspace):
    client, root = workspace
    trust(client, root)
    (root / "src/main/java/example/Greeter.java").write_text(
        "package example; public class Greeter { public static int add( { }\n")
    result=run(client, root, "jdk_compile", "javac")
    assert result.status_code == 200, result.text
    data=result.json()
    assert data["status"] == "nonzero_exit", data["output"]
    assert "error:" in data["output"]


def test_maven_junit5_evidence_and_real_offline_tests(workspace):
    client, root = workspace
    replace_with_fixture(root, "v21-junit")
    info = inspect(client, root)
    assert info.status_code == 200, info.text
    data = info.json()
    assert data["build_system"] == "maven"
    assert data["maven"]["artifact"] == "v21-junit-service"
    assert data["maven"]["java_release"] == "21"
    assert "JUnit Jupiter" in data["framework_hints"]
    assert data["safe_to_offer_builds"]
    assert "org.junit.jupiter:junit-jupiter" in data["maven"]["dependencies"]
    if os.getenv("AUTOMOTO_V21_JUNIT_READY") != "1":
        pytest.skip("CI has not pre-warmed JUnit Maven dependencies for an offline test.")
    trust(client, root)
    before = snapshot(root)
    result = run(client, root, "maven_test", "mvn")
    assert result.status_code == 200, result.text
    output = result.json()
    assert output["status"] == "completed", output["output"]
    assert "Tests run: 1" in output["output"]
    assert output["temporary_project_deleted"] and not output["deployment_started"]
    assert snapshot(root) == before


def test_gradle_java_compatibility_and_real_offline_build(workspace):
    client, root = workspace
    replace_with_fixture(root, "v21-gradle")
    wrapper = root / "gradle/wrapper/gradle-wrapper.properties"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text(
        "distributionUrl=https\\://services.gradle.org/distributions/gradle-9.2.1-bin.zip\n")
    data = inspect(client, root).json()
    assert data["build_system"] == "gradle"
    assert data["gradle"]["wrapper_version"] == "9.2.1"
    assert data["gradle"]["declared_java"] == 21
    assert data["gradle"]["compatibility"] == "declared_range_matches_reference"
    assert data["gradle"]["wrapper_executed"] is False
    if os.name == "nt":
        pytest.skip("Windows Gradle .bat wrapper is deliberately not executed by the app.")
    trust(client, root)
    original = snapshot(root)
    for task in ("gradle_build", "gradle_test"):
        result = run(client, root, task, "gradle")
        assert result.status_code == 200, result.text
        data = result.json()
        assert data["status"] == "completed", data["output"]
        assert data["temporary_project_deleted"]
        assert not data["deployment_started"]
    assert snapshot(root) == original


def test_gradle_incompatible_wrapper_and_malformed_pom_block_unsafe_builds(workspace):
    client, root = workspace
    replace_with_fixture(root, "v21-gradle")
    prop = root / "gradle/wrapper/gradle-wrapper.properties"
    prop.parent.mkdir(parents=True)
    prop.write_text(
        "distributionUrl=https\\://services.gradle.org/distributions/gradle-7.6-bin.zip\n")
    info=inspect(client, root).json()
    assert info["gradle"]["compatibility"] == "potential_version_mismatch"
    assert not info["safe_to_offer_builds"]
    replace_with_fixture(root, "v21-junit")
    (root/"pom.xml").write_text("<!DOCTYPE a [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><a>&x;</a>")
    result=inspect(client, root)
    assert result.status_code == 422


def test_stale_source_manifest_tool_hash_and_confirmation_are_rejected(workspace):
    client, root = workspace
    trust(client, root)
    info=inspect(client, root).json()
    tool=next(x for x in info["toolchains"] if x["name"]=="javac")
    if tool["status"]!="installed_not_executed":
        pytest.skip("javac is not installed")
    body={"project":str(root),"task":"javac_version","tool":"javac",
          "expected_manifest_sha256":info["manifest_sha256"],
          "expected_source_sha256":info["source_sha256"],
          "expected_toolchain_sha256":info["toolchain_sha256"],
          "expected_executable":tool["executable"],"expected_sha256":tool["sha256"],
          "confirmed":True,"accept_unsandboxed_build_test_and_network_risk":True}
    assert client.post(BASE+"/run",headers=AUTH,json={**body,"confirmed":False}).status_code==422
    assert client.post(BASE+"/run",headers=AUTH,json={**body,"expected_sha256":"0"*64}).status_code==409
    assert client.post(BASE+"/run",headers=AUTH,json={**body,"expected_toolchain_sha256":"0"*64}).status_code==409
    (root/"src/main/java/example/Greeter.java").write_text(GREETER+"\n// changed")
    assert client.post(BASE+"/run",headers=AUTH,json=body).status_code==409
    body["expected_source_sha256"]=inspect(client,root).json()["source_sha256"]
    (root/"pom.xml").write_text(
        '<project><modelVersion>4.0.0</modelVersion><artifactId>later</artifactId></project>')
    assert client.post(BASE+"/run",headers=AUTH,json=body).status_code==409


def test_untrusted_and_hosted_jvm_calls_denied(workspace, monkeypatch):
    client, root = workspace
    assert run(client, root, "jdk_version","java").status_code == 403
    assert client.get(BASE+"/inspect",params={"project":str(root)}).status_code in (401,403)
    monkeypatch.setenv("AUTOMOTO_MODE","multiuser")
    assert inspect(client,root).status_code in (401,403,404)


def _plant_jdk(home: Path, version: str, body: str = "#!/bin/sh\necho ok\n") -> Path:
    bindir = home / "bin"
    bindir.mkdir(parents=True)
    for name in ("java", "javac"):
        exe = bindir / name
        exe.write_text(body)
        exe.chmod(0o755)
    (home / "release").write_text('JAVA_VERSION="' + version + '"\n')
    return home.resolve()


def _plant_launcher(folder: Path, body: str) -> Path:
    bindir = folder / "bin"
    bindir.mkdir(parents=True)
    for name in ("java", "javac"):
        exe = bindir / name
        exe.write_text(body)
        exe.chmod(0o755)
    return (bindir / "java").resolve()


def _java_summary(executable: Path) -> dict:
    return {"toolchains": [{
        "name": "java",
        "status": "installed_not_executed",
        "executable": str(executable),
    }]}


STUB_LAUNCHER = """#!/bin/sh
tool=$(basename "$0")
target="${JAVA_HOME}/bin/${tool}"
if [ ! -x "$target" ] || [ "$target" -ef "$0" ]; then
  echo STUB_REEXEC
  exit 1
fi
exec "$target" "$@"
"""
REAL_TOOL = """#!/bin/sh
if [ -n "${OPENAI_API_KEY:-}" ] || [ -n "${AWS_SECRET_ACCESS_KEY:-}" ]; then
  echo LEAKED
  exit 1
fi
echo "JAVA_HOME=$JAVA_HOME"
echo HOME_OK
"""


def test_apple_stub_directories_are_not_jdk_homes():
    assert jvm._apple_stub_dir(Path("/usr/bin"))
    assert jvm._apple_stub_dir(
        Path("/System/Library/Frameworks/JavaVM.framework/Versions/Current/Commands"))
    assert jvm._apple_stub_dir(
        Path("/System/Library/Frameworks/JavaVM.framework/Versions/A/Commands"))
    assert not jvm._apple_stub_dir(Path("/usr/lib/jvm/java-21-openjdk/bin"))
    assert jvm._apple_launcher(Path("/usr/bin/java"), darwin=False) is False


def test_launcher_without_jdk_release_uses_host_locator_not_its_parent(tmp_path):
    """The macOS /usr/bin/java hang: JAVA_HOME must not become the stub's parent."""
    project = tmp_path / "project"
    project.mkdir()
    stub = _plant_launcher(tmp_path / "stub", "#!/bin/sh\necho stub\n")
    planted = _plant_jdk(project / "vendor-jdk", "99")
    jdk17 = _plant_jdk(tmp_path / "jdk17", "17.0.20")
    jdk21 = _plant_jdk(tmp_path / "jdk21", "21.0.12")
    env = jvm._environment(project, _java_summary(stub), darwin=False, source={
        "JAVA_HOME": str(planted),
        "JAVA_HOME_17_ARM64": str(jdk17),
        "JAVA_HOME_21_X64": str(jdk21),
        "JAVA_HOME_11_X64": "relative/jdk",
        "OPENAI_API_KEY": "sk-secret-value",
        "AWS_SECRET_ACCESS_KEY": "aws-secret-value",
        "JAVA_HOME_NOT_A_LOCATOR": str(jdk17),
    })
    assert env["JAVA_HOME"] == str(jdk21)
    assert env["PATH"].split(os.pathsep)[0] == str(jdk21 / "bin")
    assert str(stub.parent.parent) not in env["JAVA_HOME"]
    flattened = "\n".join(env.values())
    assert "sk-secret-value" not in flattened
    assert "aws-secret-value" not in flattened
    assert "JAVA_HOME_NOT_A_LOCATOR" not in env
    assert "OPENAI_API_KEY" not in env


def test_java_home_tool_and_install_scan_run_only_after_locators_miss(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    stub = _plant_launcher(tmp_path / "stub", "#!/bin/sh\necho stub\n")
    from_tool = _plant_jdk(tmp_path / "from-tool", "21.0.1")
    scanned = _plant_jdk(
        tmp_path / "Library" / "Java" / "JavaVirtualMachines" / "jdk-25.jdk" / "Contents" / "Home",
        "25.0.1")
    monkeypatch.setattr(jvm, "_system_java_home", lambda root: str(from_tool))
    env = jvm._environment(project, _java_summary(stub), darwin=True, source={})
    assert env["JAVA_HOME"] == str(from_tool)
    assert env["PATH"].split(os.pathsep)[0] == str(from_tool / "bin")

    monkeypatch.setattr(jvm, "_system_java_home", lambda root: None)
    bases = [tmp_path / "Library" / "Java" / "JavaVirtualMachines"]
    assert jvm._scan_installed_jdks(project, bases, darwin=False) == scanned
    # darwin=True scans the host image after the tool returns nothing. Point the
    # scan at the planted tree so this stays hermetic on Linux and macOS.
    monkeypatch.setattr(jvm, "_darwin_jdk_bases", lambda: bases)
    env = jvm._environment(project, _java_summary(stub), darwin=True, source={})
    assert env["JAVA_HOME"] == str(scanned)


def test_installed_jdk_scan_prefers_the_highest_home_outside_the_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside" / "JavaVirtualMachines"
    jdk17 = _plant_jdk(outside / "jdk-17.jdk" / "Contents" / "Home", "17.0.2")
    jdk21 = _plant_jdk(outside / "jdk-21.jdk" / "Contents" / "Home", "21.0.4")
    _plant_jdk(project / "JavaVirtualMachines" / "jdk-99.jdk" / "Contents" / "Home", "99")
    brew = tmp_path / "opt"
    _plant_jdk(brew / "openjdk@11" / "libexec" / "openjdk.jdk" / "Contents" / "Home", "11.0.5")
    chosen = jvm._scan_installed_jdks(project, [outside, project / "JavaVirtualMachines", brew])
    assert chosen == jdk21
    assert jvm._release_major(jdk21) == 21
    assert jvm._release_major(jdk17) == 17


def test_missing_jdk_locator_fails_before_a_stub_can_hang(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    stub = _plant_launcher(tmp_path / "stub", "#!/bin/sh\necho stub\n")
    with pytest.raises(HTTPException) as caught:
        jvm._environment(project, _java_summary(stub), darwin=False, source={
            "JAVA_HOME": str(stub.parent.parent),
            "OPENAI_API_KEY": "sk-secret-value",
        })
    assert caught.value.status_code == 409


def test_real_jdk_binary_keeps_its_own_home(tmp_path):
    discovered = shutil.which("java")
    if not discovered:
        pytest.skip("java is not installed")
    executable = Path(discovered).resolve()
    if executable.parent.name.lower() != "bin":
        pytest.skip("java is not inside a JDK bin directory")
    project = tmp_path / "project"
    project.mkdir()
    home = jvm._approved_jdk_home(str(executable.parent.parent), project, darwin=False)
    if home is None:
        pytest.skip("java on PATH is not an approved JDK home")
    other = _plant_jdk(tmp_path / "other-jdk", "17")
    env = jvm._environment(project, _java_summary(executable), darwin=False, source={
        "JAVA_HOME": str(other),
        "OPENAI_API_KEY": "sk-secret-value",
    })
    assert env["JAVA_HOME"] == str(home)
    assert not env["PATH"].startswith(str(other / "bin"))
    assert "sk-secret-value" not in "\n".join(env.values())


def test_apple_java_stub_runs_the_located_jdk_instead_of_reexec(workspace, monkeypatch, tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX shell stand-ins cover the stub; Windows blocks script launchers.")
    client, root = workspace
    jdk = _plant_jdk(tmp_path / "real-jdk", "21.0.12", REAL_TOOL)
    stub_java = _plant_launcher(tmp_path / "apple-stub", STUB_LAUNCHER)
    gradle = tmp_path / "gradle"
    gradle.write_text(REAL_TOOL)
    gradle.chmod(0o755)
    monkeypatch.setenv("JAVA_HOME", str(jdk))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret-value")
    original = shutil.which

    def which(name, path=None):
        if name == "java":
            return str(stub_java)
        if name == "javac":
            return str(stub_java.parent / "javac")
        if name == "gradle":
            return str(gradle)
        return original(name, path=path)

    monkeypatch.setattr(jvm.shutil, "which", which)
    trust(client, root)
    for task, tool in (("jdk_version", "java"), ("javac_version", "javac"),
                       ("gradle_version", "gradle")):
        response = run(client, root, task, tool)
        assert response.status_code == 200, (task, response.text)
        data = response.json()
        assert data["status"] == "completed", (task, data["output"])
        assert "STUB_REEXEC" not in data["output"]
        assert "LEAKED" not in data["output"]
        assert "HOME_OK" in data["output"]
        assert "JAVA_HOME=" + str(jdk) in data["output"]
        assert "JAVA_HOME=" + str(stub_java.parent.parent) not in data["output"]
