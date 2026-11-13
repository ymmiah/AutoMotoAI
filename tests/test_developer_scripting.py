"""V27 Ruby/Lua/Perl/Groovy: inert package evidence, consent/security and real fixtures."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import developer_scripting as scripting
from automoto import sandbox, server

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BASE = "/api/developer/studio/scripting"
FIXTURE = Path(__file__).parent / "fixtures" / "v27-scripting"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v27-scripting"
    shutil.copytree(FIXTURE, root)
    return TestClient(server.app), root


def inspect(client, root):
    return client.get(BASE + "/inspect", params={"project": str(root)}, headers=AUTH)


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def trust(client, root):
    response = client.post("/api/developer/studio/trust", headers=AUTH,
                           json={"project": str(root), "trusted": True, "confirmed": True})
    assert response.status_code == 200, response.text


def payload(client, root, task, tool, source=""):
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    data = response.json()
    target = next(x for x in data["toolchains"] if x["name"] == tool)
    if target["status"] != "installed_not_executed":
        pytest.skip("Approved installed interpreter absent: " + tool)
    return {
        "project": str(root), "task": task, "tool": tool, "source": source,
        "expected_inventory_sha256": data["inventory_sha256"],
        "expected_toolchain_sha256": data["toolchain_sha256"],
        "expected_executable": target["executable"],
        "expected_sha256": target["sha256"],
        "confirmed": True, "accept_unsandboxed_script_and_package_risk": True,
    }


def run(client, root, task, tool, source="", **overrides):
    request = payload(client, root, task, tool, source)
    request.update(overrides)
    return client.post(BASE + "/run", json=request, headers=AUTH)


def test_all_four_languages_and_packages_are_inert(project):
    client, root = project
    before = snapshot(root)
    response = inspect(client, root)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["language_counts"]["ruby"] >= 2
    assert data["language_counts"]["lua"] >= 2
    assert data["language_counts"]["perl"] >= 3
    assert data["language_counts"]["groovy"] >= 2
    assert "rake" in data["packages"]["ruby"]
    assert "lua" in data["packages"]["lua"]
    assert "Test::More" in data["packages"]["perl"]
    assert "org.junit.jupiter:junit-jupiter:5.11.4" in data["packages"]["groovy"]
    assert not data["packages"]["manifests_evaluated"]
    assert not data["packages"]["install_started"]
    assert not data["scripts_executed"]
    assert not data["package_installation_started"]
    assert not data["network_access_started"]
    assert not data["deployment_started"]
    assert data["central_agent_studio"] == "developer"
    assert not data["scan_incomplete"]
    assert snapshot(root) == before


def test_static_symbols_style_hints_and_risk_signals(project):
    client, root = project
    ruby = root / "lib/sample.rb"
    ruby.write_text(ruby.read_text() + "bad_whitespace = 1  \n")
    data = inspect(client, root).json()
    assert any(x["kind"] == "trailing whitespace"
               for x in next(f for f in data["files"] if f["path"] == "lib/sample.rb")["style_hints"])
    assert "V27Sample" in next(
        f for f in data["files"] if f["path"] == "lib/sample.rb")["symbols"]
    assert any(x["kind"] == "external process" for x in
               next(f for f in data["files"] if f["path"] == "test/malicious.rb")["risk_signals"])
    assert any(x["kind"] == "dynamic evaluation or startup hook" for x in
               next(f for f in data["files"] if f["path"] == "test/malicious.t")["risk_signals"])
    assert not next(f for f in data["files"] if f["path"] == "test/malicious.rb")["fixture_test_path"]


def test_untrusted_and_hosted_requests_are_denied(project, monkeypatch):
    client, root = project
    assert client.get(BASE + "/inspect", params={"project": str(root)}).status_code in (401, 403)
    if shutil.which("ruby"):
        assert run(client, root, "version", "ruby").status_code == 403
    monkeypatch.setenv("AUTOMOTO_MODE", "multiuser")
    assert inspect(client, root).status_code in (401, 403, 404)


def test_fixed_test_path_rejects_arbitrary_scripts(project):
    client, root = project
    trust(client, root)
    if not shutil.which("ruby"):
        pytest.skip("Ruby not installed")
    result = run(client, root, "ruby_test", "ruby", "test/malicious.rb")
    assert result.status_code == 403, result.text
    result = run(client, root, "ruby_syntax", "ruby", "test/malicious.rb")
    assert result.status_code == 200, result.text
    # Ruby -c must parse source but cannot execute its system() invocation.
    assert result.json()["status"] == "completed"
    assert "V27_RUBY_FIXTURE_PASS" not in result.json()["output"]


def test_interpreter_and_source_mismatch_refused(project):
    client, root = project
    trust(client, root)
    if not shutil.which("ruby"):
        pytest.skip("Ruby not installed")
    assert run(client, root, "lua_syntax", "ruby", "lib/sample.rb").status_code == 422
    assert run(client, root, "ruby_test", "ruby", "lib/sample.rb").status_code == 403
    assert run(client, root, "ruby_bundle_check", "ruby").status_code == 409


def test_source_and_toolchain_hashes_must_match_consent(project):
    client, root = project
    trust(client, root)
    if not shutil.which("ruby"):
        pytest.skip("Ruby not installed")
    p = payload(client, root, "ruby_test", "ruby", "test/fixture_test.rb")
    for change, expected in [
        ({"confirmed": False}, 422),
        ({"accept_unsandboxed_script_and_package_risk": False}, 422),
        ({"expected_sha256": "0" * 64}, 409),
        ({"expected_toolchain_sha256": "0" * 64}, 409),
        ({"source": "../outside.rb"}, 422),
        ({"custom_shell_flags": ["-e", "eval()"]}, 422),
    ]:
        assert client.post(BASE + "/run", headers=AUTH, json={**p, **change}).status_code == expected
    (root / "test/fixture_test.rb").write_text("puts 'V27_MODIFIED'\n")
    assert client.post(BASE + "/run", headers=AUTH, json=p).status_code == 409


def test_linked_manifest_and_source_are_blocked(project, tmp_path):
    client, root = project
    gemfile = root / "Gemfile"
    gemfile.unlink()
    outside = tmp_path / "malicious-Gemfile"
    outside.write_text("system('evil')\n")
    try:
        gemfile.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unsupported")
    assert inspect(client, root).status_code == 403


def test_package_lock_requirement_never_runs_unpinned_dependencies(project):
    client, root = project
    trust(client, root)
    if not shutil.which("bundle"):
        pytest.skip("Bundler unavailable")
    result = run(client, root, "ruby_bundle_check", "bundle")
    assert result.status_code == 409, result.text
    # Inspecting a dynamic Gemfile must never evaluate executable statements.
    gemfile = root / "Gemfile"
    gemfile.write_text("abort 'V27_NEVER_EVALUATE_GEMFILE_DURING_INSPECTION'\n")
    data = inspect(client, root).json()
    assert data["packages"]["parsed_only"]
    assert not data["packages"]["manifests_evaluated"]


def test_real_language_versions_syntax_and_canonical_tests(project):
    if os.environ.get("AUTOMOTO_V27_REAL") != "1":
        pytest.skip("Real interpreters execute only in dedicated CI with installed toolchains.")
    client, root = project
    trust(client, root)
    before = snapshot(root)
    choices = [
        ("ruby", "ruby_syntax", "lib/sample.rb", "ruby_test", "test/fixture_test.rb",
         "V27_RUBY_FIXTURE_PASS"),
        ("luac", "lua_syntax", "lib/v27.lua", "lua_test", "test/fixture_test.lua",
         "V27_LUA_FIXTURE_PASS"),
        ("perl", "perl_syntax", "lib/V27Sample.pm", "perl_test", "test/fixture_test.t",
         "V27_PERL_FIXTURE_PASS"),
        ("groovyc", "groovy_compile", "src/V27Sample.groovy",
         "groovy_test", "test/FixtureTest.groovy", "V27_GROOVY_FIXTURE_PASS"),
    ]
    enabled = set(filter(None, os.environ.get("AUTOMOTO_V27_TOOLS", "ruby,lua,perl,groovy").split(",")))
    for tool, syntask, source, testtask, testsource, marker in choices:
        family = {"luac": "lua", "groovyc": "groovy"}.get(tool, tool)
        if family not in enabled:
            continue
        syntax = run(client, root, syntask, tool, source)
        assert syntax.status_code == 200, (syntask, syntax.text)
        assert syntax.json()["status"] == "completed", (syntask, syntax.json())
        runner = {"luac": "lua", "groovyc": "groovy"}.get(tool, tool)
        check = run(client, root, testtask, runner, testsource)
        assert check.status_code == 200, (testtask, check.text)
        assert check.json()["status"] == "completed", (testtask, check.json())
        assert marker in check.json()["output"], (testtask, check.json()["output"])
        assert check.json()["temporary_copy_deleted"]
        assert check.json()["external_code_unsandboxed"]
        assert not check.json()["package_installation_performed"]
        assert not check.json()["deployment_started"]
    assert snapshot(root) == before


def test_real_version_queries_report_installed_toolchains(project):
    if os.environ.get("AUTOMOTO_V27_REAL") != "1":
        pytest.skip("Dedicated installed-tool CI only.")
    client, root = project
    trust(client, root)
    enabled = set(filter(None, os.environ.get("AUTOMOTO_V27_TOOLS", "ruby,lua,perl,groovy").split(",")))
    for name in enabled:
        result = run(client, root, "version", name)
        assert result.status_code == 200, (name, result.text)
        assert result.json()["status"] == "completed", (name, result.json())
        assert result.json()["output"].strip(), name
