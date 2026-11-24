"""V35 emerging languages: inert inspection, version notes and bundled toolchain checks."""
import os
import pytest
from fastapi.testclient import TestClient

from automoto import developer_emerging as emerging
from automoto import sandbox, server

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
URL = "/api/developer/studio/emerging"
REAL = os.environ.get("AUTOMOTO_V35_REAL_TOOL_TESTS") == "1"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    root = sandbox.default_root() / "v35-emerging"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.zig").write_text(
        'const std = @import("std");\npub fn main() void {\n    var child = std.process.Child.init(&.{"ls"}, std.heap.page_allocator);\n    _ = child;\n}\n')
    (root / "src" / "app.nim").write_text('proc greet(): string = staticExec("whoami")\necho greet()\n')
    (root / "src" / "app.cr").write_text("def hello\n  Process.run(\"ls\")\nend\n")
    (root / "src" / "game.odin").write_text('package game\nimport "core:fmt"\nmain :: proc() {\n\tfmt.println("hi")\n}\n')
    (root / "src" / "model.mojo").write_text("fn main():\n    print(1)\n")
    (root / "src" / "lib.mbt").write_text("pub fn add(a : Int, b : Int) -> Int {\n  a + b\n}\n")
    (root / "build.zig.zon").write_text('.{ .name = .demo, .version = "0.1.0", .minimum_zig_version = "0.11.0", .paths = .{""} }\n')
    (root / "demo.nimble").write_text('version = "0.1.0"\nrequires "nim >= 2.2.0"\n')
    (root / "shard.yml").write_text('name: demo\nversion: 0.1.0\ncrystal: ">= 1.12.0"\n')
    (root / "build.zig").write_text("// would run during zig build\n")
    return TestClient(server.app), root


def inspect(client, root):
    return client.get(URL + "/inspect", params={"project": str(root)}, headers=AUTH)


def trust(client, root):
    result = client.post("/api/developer/studio/trust", headers=AUTH,
                         json={"project": str(root), "trusted": True, "confirmed": True})
    assert result.status_code == 200, result.text


def test_inspection_reads_only_and_reports_every_language(project):
    client, root = project
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    data = inspect(client, root).json()
    langs = {item["language"]: item for item in data["languages"]}
    assert set(langs) == {"zig", "nim", "crystal", "odin", "mojo", "moonbit"}
    assert all(langs[name]["files"] == 1 for name in langs)
    assert data["source_executed"] is False
    assert data["manifest_evaluated"] is False
    assert data["dependencies_installed"] is False
    assert data["release_ready_claimed"] is False
    assert all(f["executed"] is False for f in data["files"])
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_preview_languages_never_offer_a_check(project):
    client, root = project
    langs = {item["language"]: item for item in inspect(client, root).json()["languages"]}
    for name in ("mojo", "moonbit"):
        assert langs[name]["check_offered"] is False
        assert "does not run" in langs[name]["check_unavailable_reason"]
        assert langs[name]["maturity"] in ("preview", "beta (pre-1.0)")


def test_missing_toolchain_is_reported_not_claimed(project, monkeypatch):
    client, root = project
    monkeypatch.setattr(emerging.shutil, "which", lambda name: None)
    langs = {item["language"]: item for item in inspect(client, root).json()["languages"]}
    for item in langs.values():
        assert item["installed"] is False
        assert item["check_offered"] is False
        assert item["install_hint"]


def test_risk_signals_and_compile_time_execution(project):
    client, root = project
    files = {f["path"]: f for f in inspect(client, root).json()["files"]}
    assert files["src/app.nim"]["risk_signals"][0]["kind"] == "runs code while compiling"
    assert any(s["kind"] == "runs other programs" for s in files["src/main.zig"]["risk_signals"])
    assert any(s["kind"] == "runs other programs" for s in files["src/app.cr"]["risk_signals"])
    assert "greet" in files["src/app.nim"]["symbols"]


def test_project_version_requirements_are_classified(project):
    client, root = project
    langs = {item["language"]: item for item in inspect(client, root).json()["languages"]}
    assert langs["zig"]["project_requires"]["requires"] == "0.11.0"
    assert langs["zig"]["project_requirement_support"]["support"] == "older_than_tested"
    assert langs["nim"]["project_requirement_support"]["support"] == "tested"
    assert langs["crystal"]["project_requirement_support"]["support"] == "tested"


@pytest.mark.parametrize("language,version,expected", [
    ("zig", "0.17.1", "tested"), ("zig", "0.13.0", "older_than_tested"),
    ("zig", "0.18.0", "newer_than_tested"), ("nim", "1.6.14", "older_than_tested"),
    ("nim", "2.4.2", "tested"), ("odin", "dev-2026-11", "tested"),
    ("odin", "dev-2024-03", "older_than_tested"), ("crystal", "nonsense", "unrecognised"),
    ("crystal", None, "unknown"),
])
def test_version_classification(language, version, expected):
    assert emerging.classify(language, version)["support"] == expected


def test_check_requires_trust_and_pinned_compiler(project, tmp_path, monkeypatch):
    client, root = project
    fake = tmp_path / "bin" / "zig"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\necho V35_ZIG_PASS 42 version=0.17.1\n")
    fake.chmod(0o755)
    monkeypatch.setattr(emerging.shutil, "which", lambda name: str(fake) if name == "zig" else None)
    body = {"project": str(root), "language": "zig", "expected_executable": str(fake.resolve()),
            "expected_sha256": "0" * 64, "confirmed": True, "accept_unsandboxed_toolchain": True}
    assert client.post(URL + "/check", json=body, headers=AUTH).status_code == 403
    trust(client, root)
    assert client.post(URL + "/check", json=body, headers=AUTH).status_code == 409
    tool = next(t for t in inspect(client, root).json()["toolchains"] if t["name"] == "zig")
    body["expected_sha256"] = tool["sha256"]
    if os.name == "nt":
        pytest.skip("shell-script fake compiler is POSIX only")
    result = client.post(URL + "/check", json=body, headers=AUTH)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["passed"] is True and data["version"] == "0.17.1"
    assert data["project_code_executed"] is False
    assert data["example_source"] == "bundled_with_automoto"


def test_check_without_marker_is_not_success(project, tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("shell-script fake compiler is POSIX only")
    client, root = project
    fake = tmp_path / "bin" / "nim"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\necho hello\n")
    fake.chmod(0o755)
    monkeypatch.setattr(emerging.shutil, "which", lambda name: str(fake) if name == "nim" else None)
    trust(client, root)
    tool = next(t for t in inspect(client, root).json()["toolchains"] if t["name"] == "nim")
    body = {"project": str(root), "language": "nim", "expected_executable": tool["executable"],
            "expected_sha256": tool["sha256"], "confirmed": True, "accept_unsandboxed_toolchain": True}
    data = client.post(URL + "/check", json=body, headers=AUTH).json()
    assert data["status"] == "validation_failed" and data["passed"] is False


def test_check_rejects_preview_language_and_missing_consent(project):
    client, root = project
    base = {"project": str(root), "expected_executable": "/usr/bin/true", "expected_sha256": "0" * 64}
    assert client.post(URL + "/check", json={**base, "language": "mojo", "confirmed": True,
                                             "accept_unsandboxed_toolchain": True}, headers=AUTH).status_code == 422
    assert client.post(URL + "/check", json={**base, "language": "zig", "confirmed": True}, headers=AUTH).status_code == 422


def test_linked_manifest_refused(project, tmp_path):
    client, root = project
    (root / "shard.yml").unlink()
    outside = tmp_path / "outside.yml"
    outside.write_text("name: x\n")
    try:
        (root / "shard.yml").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert inspect(client, root).status_code == 403


def test_oversized_source_refused(project):
    client, root = project
    (root / "src" / "big.zig").write_text("x" * (emerging.MAX_SOURCE + 10))
    assert inspect(client, root).status_code == 413


def test_requires_session(project):
    client, root = project
    assert client.get(URL + "/inspect", params={"project": str(root)}).status_code in (401, 403)


@pytest.mark.skipif(not REAL, reason="real Zig/Nim/Crystal/Odin toolchains run in the V35 CI job")
@pytest.mark.parametrize("language", ["zig", "nim", "crystal", "odin"])
def test_real_toolchain_check(project, language):
    client, root = project
    trust(client, root)
    tool = next((t for t in inspect(client, root).json()["toolchains"]
                 if t["name"] == emerging.RUNNABLE[language] and t["status"] == "installed_not_executed"), None)
    assert tool, f"{language} toolchain must be installed for the real job"
    body = {"project": str(root), "language": language, "expected_executable": tool["executable"],
            "expected_sha256": tool["sha256"], "confirmed": True, "accept_unsandboxed_toolchain": True}
    result = client.post(URL + "/check", json=body, headers=AUTH)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["passed"] is True, data["output"]
    assert data["version"]
    assert data["version_support"]["support"] in ("tested", "newer_than_tested")
