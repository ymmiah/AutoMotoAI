"""V20 native C/C++ CMake/CTest real-toolchain and security regression tests."""
from __future__ import annotations

import hashlib
import json
import shutil
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
