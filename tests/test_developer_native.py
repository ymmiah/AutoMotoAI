"""V20 native C/C++ CMake/CTest real-toolchain and security regression tests."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import developer_native as native, sandbox, server

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BASE = "/api/developer/studio/native"
CMAKE = """cmake_minimum_required(VERSION 3.16)
project(automoto_v20 LANGUAGES C CXX)
enable_testing()
add_library(v20c STATIC src/hello.c)
add_executable(v20app src/main.cpp)
target_link_libraries(v20app PRIVATE v20c)
add_test(NAME native_smoke COMMAND v20app)
"""
HELLO_C = """int v20_add(int a, int b) { return a + b; }
"""
MAIN_CPP = """#include <iostream>
extern "C" int v20_add(int, int);
int main() {
    if (v20_add(20, 22) != 42) return 1;
    std::cout << "v20 ok\\n";
    return 0;
}
"""
DEFECT_C = """#include <stdlib.h>
int main(void) {
    volatile int *p = (int *)malloc(sizeof(int));
    if (!p) return 1;
    p[2] = 20;
    free((void *)p);
    return 0;
}
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v20-c-cpp"
    (root / "src").mkdir(parents=True)
    (root / "CMakeLists.txt").write_text(CMAKE, encoding="utf-8")
    (root / "src/hello.c").write_text(HELLO_C, encoding="utf-8")
    (root / "src/main.cpp").write_text(MAIN_CPP, encoding="utf-8")
    return TestClient(server.app), root


def inspect(client, root):
    return client.get(BASE + "/inspect", params={"project": str(root)}, headers=AUTH)


def trust(client, root):
    result = client.post("/api/developer/studio/trust", headers=AUTH,
                         json={"project": str(root), "trusted": True, "confirmed": True})
    assert result.status_code == 200, result.text


def run(client, root, task="cmake_version", tool="cmake", **overrides):
    result = inspect(client, root)
    assert result.status_code == 200, result.text
    info = result.json()
    selected = next(x for x in info["toolchains"] if x["name"] == tool)
    if selected["status"] != "installed_not_executed":
        pytest.skip("No approved installed native tool: " + tool)
    payload = {"project": str(root), "task": task, "tool": tool,
               "expected_manifest_sha256": info["manifest_sha256"],
               "expected_source_sha256": info["source_sha256"],
               "expected_toolchain_sha256": info["toolchain_sha256"],
               "expected_executable": selected["executable"],
               "expected_sha256": selected["sha256"],
               "confirmed": True, "accept_unsandboxed_build_test_and_network_risk": True}
    payload.update(overrides)
    return client.post(BASE + "/run", headers=AUTH, json=payload)


def snapshot(root):
    return {x.relative_to(root).as_posix(): x.read_bytes()
            for x in root.rglob("*") if x.is_file()}


def test_native_c_and_cpp_inspection_does_not_execute_or_modify(project):
    client, root = project
    before = snapshot(root)
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["safe_to_offer_runs"], data["warnings"]
    assert data["manifest_sha256"] and data["source_sha256"]
    assert set(x["path"] for x in data["files"]) == {"src/hello.c", "src/main.cpp"}
    assert {x["language"] for x in data["files"]} == {"C", "C++"}
    assert "CMakeLists.txt" in data["manifests"]
    assert data["compile_commands"]["present"] is False
    assert any(x["name"] == "v20_add" for x in data["symbols"])
    assert data["clangd"].startswith("Use existing")
    assert data["central_agent_studio"] == "developer"
    assert data["project_code_executed"] is False
    assert data["download_or_install_performed"] is False
    assert data["deployment_started"] is False
    assert snapshot(root) == before


def test_compile_commands_paths_redacted_and_bounded(project, tmp_path):
    client, root = project
    db = root / "compile_commands.json"
    db.write_text(json.dumps([{"file": "src/hello.c", "directory": str(root),
                                "command": "gcc -DSECRET_KEY=never-expose -c src/hello.c"}]))
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["compile_commands"]["entries"][0]["file"] == "src/hello.c"
    assert data["compile_commands"]["flags_redacted"]
    assert "never-expose" not in json.dumps(data)
    assert snapshot(root)["compile_commands.json"]
    db.write_text(json.dumps([{"file": str(tmp_path / "other.c"), "directory": str(root),
                                "arguments": ["clang", "-c", "/tmp/other.c"]}]))
    assert inspect(client, root).status_code in (403, 422)
    db.write_text("{}")
    assert inspect(client, root).status_code == 422


def test_linked_cmake_and_unreviewed_scripts_block_execution(project, tmp_path):
    client, root = project
    (root / "CMakeLists.txt").write_text(CMAKE + "\ninclude(extra.cmake)\n")
    data = inspect(client, root).json()
    assert not data["safe_to_offer_runs"]
    assert any("execute or fetch" in warning for warning in data["warnings"])
    (root / "CMakeLists.txt").unlink()
    outside = tmp_path / "outside-cmake"
    outside.write_text(CMAKE)
    try:
        (root / "CMakeLists.txt").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink unavailable")
    assert inspect(client, root).status_code == 403


def test_trust_confirmation_and_file_checksums_prevent_stale_execution(project):
    client, root = project
    assert run(client, root).status_code == 403
    trust(client, root)
    data = inspect(client, root).json()
    tool = next(x for x in data["toolchains"] if x["name"] == "cmake")
    if tool["status"] != "installed_not_executed":
        pytest.skip("CMake is unavailable.")
    payload = {"project": str(root), "task": "cmake_version", "tool": "cmake",
               "expected_manifest_sha256": data["manifest_sha256"],
               "expected_source_sha256": data["source_sha256"],
               "expected_toolchain_sha256": data["toolchain_sha256"],
               "expected_executable": tool["executable"], "expected_sha256": tool["sha256"],
               "confirmed": True, "accept_unsandboxed_build_test_and_network_risk": True}
    assert client.post(BASE+"/run", headers=AUTH,
                       json={**payload, "confirmed": False}).status_code == 422
    assert client.post(BASE+"/run", headers=AUTH,
                       json={**payload, "expected_sha256": "0"*64}).status_code == 409
    assert client.post(BASE+"/run", headers=AUTH,
                       json={**payload, "expected_toolchain_sha256": "0"*64}).status_code == 409
    (root / "src/hello.c").write_text(HELLO_C + "\n// modified")
    assert client.post(BASE+"/run", headers=AUTH, json=payload).status_code == 409
    payload["expected_source_sha256"] = inspect(client, root).json()["source_sha256"]
    (root / "CMakeLists.txt").write_text(CMAKE + "\n# modified")
    assert client.post(BASE+"/run", headers=AUTH, json=payload).status_code == 409


def test_real_native_c_and_cpp_build_ctest_and_ephemeral_output(project):
    client, root = project
    trust(client, root)
    if not shutil.which("cmake") or not shutil.which("ctest"):
        pytest.skip("CMake and CTest are required")
    initial = snapshot(root)
    for task in ("cmake_version", "build", "test"):
        res = run(client, root, task=task)
        assert res.status_code == 200, (task, res.text)
        body = res.json()
        assert body["status"] == "completed", (task, body["output"])
        assert body["temporary_build_deleted"]
        assert body["external_process_unsandboxed"]
        assert body["deployment_started"] is False
        assert body["agent_handoff_created"] is False
        if task == "test":
            assert [x["stage"] for x in body["stages"]] == ["configure", "build", "test"]
            assert "100% tests passed" in body["output"]
    assert snapshot(root) == initial, "Build/CTest must not leave outputs in source"


def test_compiler_error_produces_nonzero_and_redacted_diagnostics(project):
    client, root = project
    trust(client, root)
    (root / "src/hello.c").write_text("int v20_add( {\n", encoding="utf-8")
    result = run(client, root, task="build")
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["status"] == "nonzero_exit"
    assert "error" in data["output"].lower()
    assert all(x["path"] is None or not Path(x["path"]).is_absolute()
               for x in data["diagnostics"])
    assert data["deployment_started"] is False


def test_real_sanitizer_detects_deliberate_heap_defect_on_linux(project):
    if not sys.platform.startswith("linux"):
        pytest.skip("Sanitiser runtime verified on Linux; other platforms need manual acceptance.")
    client, root = project
    if not (shutil.which("gcc") and shutil.which("g++")) and not (
            shutil.which("clang") and shutil.which("clang++")):
        pytest.skip("No local Clang/GCC sanitiser toolchain.")
    (root / "src/defect.c").write_text(DEFECT_C, encoding="utf-8")
    with (root / "CMakeLists.txt").open("a", encoding="utf-8") as out:
        out.write("\nadd_executable(v20defect src/defect.c)\n"
                  "add_test(NAME memory_defect COMMAND v20defect)\n")
    trust(client, root)
    result = run(client, root, task="sanitize")
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["status"] == "nonzero_exit", data["output"][-2500:]
    assert data["sanitizer_detected"], data["output"][-2500:]
    assert data["sanitizer_evidence"]
    assert data["temporary_build_deleted"] is True


def test_hosted_mode_and_unauthorised_calls_are_blocked(project, monkeypatch):
    client, root = project
    missing = client.get(BASE+"/inspect", params={"project": str(root)})
    assert missing.status_code in (401, 403)
    monkeypatch.setenv("AUTOMOTO_MODE", "multiuser")
    blocked = inspect(client, root)
    assert blocked.status_code in (401, 403, 404)


CMAKE_HELP = """
Generators

The following generators are available on this platform (* marks default):
* Visual Studio 18 2026        = Generates Visual Studio 2026 project files.
  Visual Studio 17 2022        = Generates Visual Studio 2022 project files.
  Ninja                        = Generates build.ninja files.
  MinGW Makefiles              = Generates a make file for use with mingw32-make.
  NMake Makefiles              = Generates NMake makefiles.

"""


def _windows_isolate(monkeypatch, tmp_path):
    """Keep toolchain discovery out of the real home directory and the project tree."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(workspace))
    monkeypatch.setenv("AUTOMOTO_ALLOWED_ROOTS", "")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    return workspace


def _hide_host_visual_studio(monkeypatch, program_files, program_x86, program_w6432):
    """A developer machine or CI image already has Visual Studio on these variables."""
    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.setenv("ProgramFiles(x86)", str(program_x86))
    monkeypatch.setenv("ProgramW6432", str(program_w6432))
    for name in ("VSINSTALLDIR", "VCINSTALLDIR", "VCToolsInstallDir", "VCToolsRedistDir",
                 "WindowsSdkDir", "WindowsSdkBinPath", "WindowsSdkVerBinPath",
                 "UniversalCRTSdkDir"):
        monkeypatch.delenv(name, raising=False)


def _vs_instance(program_files, year, edition):
    instance = program_files / "Microsoft Visual Studio" / year / edition
    (instance / "VC" / "Tools" / "MSVC").mkdir(parents=True)
    return instance


def _plant_vswhere(program_x86):
    installer = program_x86 / "Microsoft Visual Studio" / "Installer"
    installer.mkdir(parents=True)
    executable = installer / "vswhere.exe"
    executable.write_bytes(b"vswhere")
    return executable


def test_cmake_generator_help_names_visual_studio_ninja_and_mingw():
    names = native._parse_cmake_generators(CMAKE_HELP)
    assert names == {
        "Visual Studio 18 2026", "Visual Studio 17 2022", "Ninja",
        "MinGW Makefiles", "NMake Makefiles"}
    cmake = shutil.which("cmake")
    if not cmake:
        return
    text = native._decode_tool_output(subprocess.check_output([cmake, "--help"], timeout=20))
    reported = native._parse_cmake_generators(text)
    assert reported
    assert any(name in reported for name in ("Unix Makefiles", "Ninja", "NMake Makefiles"))


def test_vswhere_json_keeps_known_generators_and_drops_extra_fields():
    text = json.dumps([
        {"installationVersion": "18.11.12328.437", "installationPath": "C:/VS/18",
         "OPENAI_API_KEY": "sk-secret-value"},
        {"installationVersion": "17.11.5", "installationPath": "C:/VS/2022"},
        {"installationVersion": "14.0", "installationPath": "C:/VS/old"},
        {"installationVersion": "18.1;injected", "installationPath": "C:/VS/bad"},
        "not-an-object",
    ])
    parsed = native._parse_vswhere(text)
    assert [item["generator"] for item in parsed] == [
        "Visual Studio 18 2026", "Visual Studio 17 2022"]
    assert "sk-secret-value" not in json.dumps(parsed)
    assert native._parse_vswhere("not json") == []


def test_windows_native_environment_preserves_toolchain_locators_and_scrubs_secrets(
        tmp_path, monkeypatch):
    workspace = _windows_isolate(monkeypatch, tmp_path)
    root = workspace / "native"
    root.mkdir()
    program_files = tmp_path / "Program Files"
    program_x86 = tmp_path / "Program Files (x86)"
    program_files.mkdir()
    program_x86.mkdir()
    outside_lib = tmp_path / "outside-lib"
    outside_lib.mkdir()
    project_lib = root / "decoy-lib"
    project_lib.mkdir()
    neutral = tmp_path / "neutral-bin"
    neutral.mkdir()
    command = tmp_path / "Windows" / "System32" / "cmd.exe"
    command.parent.mkdir(parents=True)
    command.write_bytes(b"cmd")
    monkeypatch.setenv("PATH", os.pathsep.join([str(neutral), str(root / "bin")]))
    _hide_host_visual_studio(monkeypatch, program_files, program_x86, program_files)
    monkeypatch.setenv("LIB", os.pathsep.join([str(project_lib), "relative-lib", str(outside_lib)]))
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    monkeypatch.setenv("VCToolsVersion", "14.40.33807")
    monkeypatch.setenv("SystemDrive", "C:")
    monkeypatch.setenv("ComSpec", str(command))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret-value")
    monkeypatch.setenv("VCToolsVersion_IGNORE", "14.40;injected")
    env, args, problem = native._environment(root, windows=True)
    assert problem == native._COMPILER_MISSING
    assert args == []
    assert env["ProgramFiles"] == str(program_files.resolve())
    assert env["ProgramFiles(x86)"] == str(program_x86.resolve())
    assert env["LIB"] == str(outside_lib.resolve())
    assert "relative-lib" not in env["LIB"]
    assert str(project_lib.resolve()) not in env["LIB"]
    assert env["PATHEXT"] == ".COM;.EXE;.BAT;.CMD"
    assert env["VCToolsVersion"] == "14.40.33807"
    assert env["SystemDrive"] == "C:"
    assert env["ComSpec"] == str(command.resolve())
    assert env["PROCESSOR_ARCHITECTURE"] == "AMD64"
    flattened = "\n".join(env.values())
    assert "sk-secret-value" not in flattened
    assert "aws-secret-value" not in flattened
    assert "VCToolsVersion_IGNORE" not in env
    assert str(root.resolve()) not in env["PATH"]


def test_windows_native_selects_visual_studio_generator_ahead_of_ninja(tmp_path, monkeypatch):
    workspace = _windows_isolate(monkeypatch, tmp_path)
    root = workspace / "native"
    root.mkdir()
    program_files = tmp_path / "Program Files"
    program_x86 = tmp_path / "Program Files (x86)"
    current = _vs_instance(program_files, "18", "Enterprise")
    older = _vs_instance(program_files, "2022", "Community")
    vswhere = _plant_vswhere(program_x86)
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("ninja", "gcc", "g++"):
        (tools / name).write_bytes(b"tool")
    monkeypatch.setenv("PATH", str(tools))
    _hide_host_visual_studio(monkeypatch, program_files, program_x86, program_files)
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value")
    payload = json.dumps([
        {"installationVersion": "17.11.5", "installationPath": str(older),
         "OPENAI_API_KEY": "sk-secret-value"},
        {"installationVersion": "18.11.12328.437", "installationPath": str(current)},
    ])

    def runner(executable, env, component):
        assert executable == vswhere.resolve()
        assert "OPENAI_API_KEY" not in env
        assert "sk-secret-value" not in "\n".join(env.values())
        if component == native._VS_TOOL_X64:
            return payload
        return "[]"

    monkeypatch.setattr(native, "_run_vswhere", runner)
    env, args, problem = native._environment(root, windows=True)
    assert problem is None
    assert args == ["-G", "Visual Studio 18 2026", "-A", "x64"]
    assert "sk-secret-value" not in "\n".join(env.values())
    assert env["ProgramFiles"] == str(program_files.resolve())


def test_windows_native_keeps_nmake_default_when_cl_is_on_path(tmp_path, monkeypatch):
    workspace = _windows_isolate(monkeypatch, tmp_path)
    root = workspace / "native"
    root.mkdir()
    program_files = tmp_path / "Program Files"
    program_x86 = tmp_path / "Program Files (x86)"
    instance = _vs_instance(program_files, "18", "Enterprise")
    _plant_vswhere(program_x86)
    tools = tmp_path / "dev-bin"
    tools.mkdir()
    (tools / "cl.exe").write_bytes(b"cl")
    monkeypatch.setenv("PATH", str(tools))
    _hide_host_visual_studio(monkeypatch, program_files, program_x86, program_files)
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    calls = []

    def runner(executable, env, component):
        calls.append(component)
        return json.dumps([{"installationVersion": "18.11.1",
                            "installationPath": str(instance)}])

    monkeypatch.setattr(native, "_run_vswhere", runner)
    _env, args, problem = native._environment(root, windows=True)
    assert calls == []
    assert args == []
    assert problem is None


def test_windows_generator_uses_ninja_or_mingw_only_when_those_tools_exist(tmp_path, monkeypatch):
    workspace = _windows_isolate(monkeypatch, tmp_path)
    root = workspace / "native"
    root.mkdir()
    tools = tmp_path / "tools"
    tools.mkdir()
    env = {"PATH": str(tools), "PATHEXT": ".COM;.EXE;.BAT;.CMD",
           "PROCESSOR_ARCHITECTURE": "AMD64"}
    args, problem = native._windows_cmake_plan(env, {}, root, None)
    assert args == []
    assert problem == native._COMPILER_MISSING
    (tools / "ninja").write_bytes(b"n")
    (tools / "gcc").write_bytes(b"c")
    args, problem = native._windows_cmake_plan(env, {}, root, None)
    assert problem == native._COMPILER_MISSING
    (tools / "g++").write_bytes(b"c")
    args, problem = native._windows_cmake_plan(env, {}, root, None)
    assert problem is None
    assert args == ["-G", "Ninja"]
    (tools / "mingw32-make").write_bytes(b"m")
    args, problem = native._windows_cmake_plan(env, {}, root, None)
    assert args == ["-G", "Ninja"]
    (tools / "ninja").unlink()
    args, problem = native._windows_cmake_plan(env, {}, root, None)
    assert problem is None
    assert args == ["-G", "MinGW Makefiles"]
    planted = root / "bin"
    planted.mkdir()
    for name in ("ninja", "gcc", "g++", "mingw32-make", "vswhere.exe"):
        (planted / name).write_bytes(b"planted")
    env = {"PATH": str(planted), "PATHEXT": ".EXE", "PROCESSOR_ARCHITECTURE": "AMD64"}
    args, problem = native._windows_cmake_plan(env, {}, root, None)
    assert args == []
    assert problem == native._COMPILER_MISSING


def test_windows_native_explains_missing_compiler_without_host_visual_studio(
        tmp_path, monkeypatch):
    """Host Visual Studio and host compilers must not satisfy this case."""
    workspace = _windows_isolate(monkeypatch, tmp_path)
    root = workspace / "native"
    root.mkdir()
    program_files = tmp_path / "Program Files"
    program_x86 = tmp_path / "Program Files (x86)"
    program_files.mkdir()
    program_x86.mkdir()
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    _hide_host_visual_studio(monkeypatch, program_files, program_x86, program_files)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value")
    calls = []
    monkeypatch.setattr(native, "_run_vswhere", lambda *args, **kwargs: calls.append(args))
    env, args, problem = native._environment(root, windows=True)
    assert calls == []
    assert args == []
    assert problem == native._COMPILER_MISSING
    assert "Visual Studio" in problem
    assert "CMake Error" not in problem
    assert "CMAKE_CXX_COMPILER" not in problem
    assert "sk-secret-value" not in problem
    assert "sk-secret-value" not in "\n".join(env.values())
    assert env["ProgramFiles"] == str(program_files.resolve())
    planted = root / "Microsoft Visual Studio" / "Installer"
    planted.mkdir(parents=True)
    (planted / "vswhere.exe").write_bytes(b"planted")
    _hide_host_visual_studio(monkeypatch, root, root, root)
    env, args, problem = native._environment(root, windows=True)
    assert calls == []
    assert problem == native._COMPILER_MISSING
    assert "ProgramFiles" not in env


def test_windows_native_uses_an_older_visual_studio_when_cmake_lacks_the_newest(
        tmp_path, monkeypatch):
    workspace = _windows_isolate(monkeypatch, tmp_path)
    root = workspace / "native"
    root.mkdir()
    program_files = tmp_path / "Program Files"
    program_x86 = tmp_path / "Program Files (x86)"
    current = _vs_instance(program_files, "18", "Enterprise")
    older = _vs_instance(program_files, "2022", "Community")
    _plant_vswhere(program_x86)
    tools = tmp_path / "tools"
    tools.mkdir()
    monkeypatch.setenv("PATH", str(tools))
    _hide_host_visual_studio(monkeypatch, program_files, program_x86, program_files)
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    listed = {"Visual Studio 17 2022"}

    def runner(executable, env, component):
        if component != native._VS_TOOL_X64:
            return "[]"
        return json.dumps([
            {"installationVersion": "18.11.1", "installationPath": str(current)},
            {"installationVersion": "17.14.9", "installationPath": str(older)},
        ])

    monkeypatch.setattr(native, "_run_vswhere", runner)
    monkeypatch.setattr(native, "_supported_generators",
                        lambda cmake, env, root_arg: set(listed))
    _env, args, problem = native._environment(
        root, windows=True, cmake_executable=str(tools / "cmake"))
    assert problem is None
    assert args == ["-G", "Visual Studio 17 2022", "-A", "x64"]
    listed.clear()
    listed.update({"NMake Makefiles"})
    _env, args, problem = native._environment(
        root, windows=True, cmake_executable=str(tools / "cmake"))
    assert args == []
    assert problem == native._CMAKE_TOO_OLD
    assert "CMake Error" not in problem


def test_windows_arm64_uses_the_arm64_toolset_and_can_fall_back_to_x64(tmp_path, monkeypatch):
    workspace = _windows_isolate(monkeypatch, tmp_path)
    root = workspace / "native"
    root.mkdir()
    program_files = tmp_path / "Program Files"
    program_x86 = tmp_path / "Program Files (x86)"
    instance = _vs_instance(program_files, "18", "Enterprise")
    _plant_vswhere(program_x86)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    (tmp_path / "empty").mkdir()
    _hide_host_visual_studio(monkeypatch, program_files, program_x86, program_files)
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "ARM64")
    seen = []

    def runner(executable, env, component):
        seen.append(component)
        if component == native._VS_TOOL_ARM64:
            return json.dumps([{"installationVersion": "18.11.1",
                                "installationPath": str(instance)}])
        return "[]"

    monkeypatch.setattr(native, "_run_vswhere", runner)
    _env, args, problem = native._environment(root, windows=True)
    assert problem is None
    assert seen[0] == native._VS_TOOL_ARM64
    assert args == ["-G", "Visual Studio 18 2026", "-A", "ARM64"]
    seen.clear()

    def fallback(executable, env, component):
        seen.append(component)
        if component == native._VS_TOOL_X64:
            return json.dumps([{"installationVersion": "18.11.1",
                                "installationPath": str(instance)}])
        return "[]"

    monkeypatch.setattr(native, "_run_vswhere", fallback)
    _env, args, problem = native._environment(root, windows=True)
    assert problem is None
    assert native._VS_TOOL_ARM64 in seen
    assert args == ["-G", "Visual Studio 18 2026", "-A", "x64"]


def test_visual_studio_configure_build_and_ctest_request_debug(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    folder = tmp_path / "build"
    steps = native._build_steps(
        "C:/CMake/bin/cmake.exe", "C:/CMake/bin/ctest.exe", root, folder,
        ["-G", "Visual Studio 17 2022", "-A", "x64"], None)
    configure = dict(steps)["configure"]
    build = dict(steps)["build"]
    test = dict(steps)["test"]
    assert configure[configure.index("-G") + 1] == "Visual Studio 17 2022"
    assert configure[configure.index("-A") + 1] == "x64"
    assert build[build.index("--config") + 1] == "Debug"
    assert test[test.index("-C") + 1] == "Debug"
    plain = native._build_steps(
        "/usr/bin/cmake", "/usr/bin/ctest", root, folder, [], None)
    assert "-G" not in dict(plain)["configure"]
    assert "--config" in dict(plain)["build"]
    assert "-C" in dict(plain)["test"]


def test_missing_compiler_diagnostic_skips_cmake_but_version_still_runs(project, monkeypatch):
    client, root = project
    trust(client, root)
    if not shutil.which("cmake"):
        pytest.skip("CMake is required")
    original = native._environment

    def force_missing(root_arg, windows=None, cmake_executable=None):
        env, _args, _problem = original(root_arg, windows=windows,
                                        cmake_executable=cmake_executable)
        return env, [], native._COMPILER_MISSING

    monkeypatch.setattr(native, "_environment", force_missing)
    initial = snapshot(root)
    version = run(client, root, task="cmake_version")
    assert version.status_code == 200, version.text
    assert version.json()["status"] == "completed"
    built = run(client, root, task="build")
    assert built.status_code == 200, built.text
    body = built.json()
    assert body["status"] == "nonzero_exit"
    assert body["output"] == native._COMPILER_MISSING
    assert "CMake Error" not in body["output"]
    assert "CMAKE_CXX_COMPILER" not in body["output"]
    assert body["temporary_build_deleted"] is True
    assert body["deployment_started"] is False
    assert body["stages"] == [{"stage": "configure", "status": "nonzero_exit", "exit_code": 1}]
    assert snapshot(root) == initial


def test_linux_native_environment_ignores_windows_locators(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("Covered by the Windows toolchain tests.")
    _windows_isolate(monkeypatch, tmp_path)
    root = tmp_path / "workspace" / "native"
    root.mkdir()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value")
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path))
    env, args, problem = native._environment(root)
    assert problem is None
    assert args == []
    assert "ProgramFiles(x86)" not in env
    assert "sk-secret-value" not in "\n".join(env.values())
