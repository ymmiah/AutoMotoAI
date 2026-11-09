"""Developer Studio V5: evidence-first language, project and toolchain detection."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import developer_languages as languages, sandbox, server
from automoto.hosted import path_allowed

BASE = "/api/developer/studio/language"
HEADERS = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v5-language-project"
    root.mkdir(parents=True)
    return TestClient(server.app), root


def detect(client, root, path=None, probe=False):
    body = {"project": str(root), "probe_tools": probe}
    if path is not None:
        body["path"] = path
    return client.post(BASE + "/detect", json=body, headers=HEADERS)


def test_registry_is_versioned_has_unique_ids_and_explicit_capability_limits(workspace):
    client, _ = workspace
    result = client.get(BASE + "/registry", headers=HEADERS)
    assert result.status_code == 200, result.text
    payload = result.json()
    items = payload["languages"]
    ids = [item["id"] for item in items]
    assert payload["schema_version"] == languages.REGISTRY_VERSION
    assert len(ids) == len(set(ids)) >= 40
    assert {"python", "typescript", "rust", "go", "swift", "kotlin", "cpp",
            "csharp", "dart", "latex", "php", "bash"}.issubset(set(ids))
    assert all(item["registry_version"] == payload["schema_version"] for item in items)
    assert all(item["compatibility"]["windows"] == "unverified" for item in items)
    assert all("build" not in item["capabilities"] for item in items)
    assert payload["toolchain_execution"] is False


@pytest.mark.parametrize(("filename", "expected"), [
    ("src/main.py", "python"), ("src/view.tsx", "typescript"),
    ("src/💡-code.rs", "rust"), ("src/test.go", "go"),
    ("src/main.kt", "kotlin"), ("src/Class.cs", "csharp"),
    ("src/app.swift", "swift"), ("src/app.dart", "dart"),
    ("src/service.php", "php"), ("src/info.sql", "sql"),
    ("src/styles.css", "css"), ("src/page.html", "html"),
    ("src/paper.tex", "latex"), ("src/data.yml", "yaml"),
    ("src/entry.json", "json"), ("Dockerfile", "dockerfile"),
    ("Makefile", "makefile"),
])
def test_named_file_classification_is_deterministic(filename, expected):
    identified = languages._file_language(filename)
    assert identified["language"] == expected
    assert identified["confidence"] in {"high", "medium"}
    assert identified["monaco"]


def test_shebang_precedence_and_conflicts_are_reported_not_hidden():
    shell = languages._file_language("run", "#!/usr/bin/env bash\nprintf hello\n")
    assert shell["language"] == "bash"
    assert shell["confidence"] == "high"
    python = languages._file_language("tool", "#!/usr/bin/env -S python3 -u\nprint(1)\n")
    assert python["language"] == "python"
    clash = languages._file_language("tool.py", "#!/usr/bin/env node\nconsole.log(1)\n")
    assert clash["language"] is None
    assert set(clash["candidates"]) == {"python", "javascript"}
    assert clash["confidence"] == "ambiguous"
    assert any("conflict" in entry for entry in clash["evidence"])


def test_ambiguous_headers_matlab_and_unknown_extensions():
    assert languages._file_language("include/core.h")["confidence"] == "ambiguous"
    assert set(languages._file_language("matlab_function.m")["candidates"]) == {
        "objective-c", "matlab"}
    assert languages._file_language("image.zzz")["language"] is None


def test_readonly_detection_does_not_modify_project_or_source(workspace):
    client, root = workspace
    target = root / "main.py"
    target.write_text("#!/usr/bin/python3\nprint('safe')\n", encoding="utf-8")
    before = target.read_bytes()
    result = detect(client, root, "main.py")
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["file"]["language"] == "python"
    assert data["file"]["confidence"] == "high"
    assert data["source_executed"] is False
    assert data["read_only"] is True
    assert target.read_bytes() == before
    assert data["toolchains"]
    assert all(t["status"] == "not_checked" for t in data["toolchains"])


def test_npm_frameworks_require_actual_manifest_dependency(workspace):
    client, root = workspace
    (root / "package.json").write_text(json.dumps({
        "scripts": {"postinstall": "never-execute-this"},
        "dependencies": {"next": "^16.0.0", "react": "^19.0.0"}
    }), encoding="utf-8")
    (root / "app.tsx").write_text("export const App = () => null;\n")
    result = detect(client, root, "app.tsx")
    assert result.status_code == 200, result.text
    names = {item["name"] for item in result.json()["frameworks"]}
    assert {"Next.js", "React"}.issubset(names)
    assert result.json()["source_executed"] is False
    (root / "package.json").write_text('{"dependencies": {"vue": "x"}}')
    names = {item["name"] for item in detect(client, root).json()["frameworks"]}
    assert "Vue" in names
    assert "Next.js" not in names


def test_manifests_from_multiple_ecosystems(workspace):
    client, root = workspace
    (root / "composer.json").write_text(
        json.dumps({"require": {"laravel/framework": "^12.0"}}))
    (root / "requirements.txt").write_text("flask==3.1.0\nDjango>=5\n")
    (root / "manage.py").write_text("from django.core.management import execute_from_command_line\n")
    (root / "pom.xml").write_text("<dependency>spring-boot-starter-web</dependency>")
    (root / "pubspec.yaml").write_text("dependencies:\n  flutter:\n    sdk: flutter\n")
    (root / "MyApp.csproj").write_text("<Project Sdk='Microsoft.NET.Sdk' />")
    names = {f["name"] for f in detect(client, root).json()["frameworks"]}
    assert {"Laravel", "Flask", "Django", "Spring Boot", "Flutter", ".NET"}.issubset(names)


def test_wordpress_project_marker_and_malformed_manifest(workspace):
    client, root = workspace
    (root / "wp-includes").mkdir()
    (root / "wp-includes" / "version.php").write_text("<?php /* WordPress */")
    (root / "wp-config.php").write_text("<?php /* configuration */")
    (root / "package.json").write_text("{ invalid json }")
    result = detect(client, root)
    assert result.status_code == 200
    assert "WordPress" in [f["name"] for f in result.json()["frameworks"]]


def test_local_auth_hosted_deny_and_path_traversal(workspace, tmp_path):
    client, root = workspace
    (root / "source.py").write_text("print('ok')")
    assert not path_allowed("GET", BASE + "/registry")
    assert not path_allowed("POST", BASE + "/detect")
    assert client.get(BASE + "/registry").status_code == 403
    assert client.post(BASE + "/detect", json={"project": str(root)}).status_code == 403
    assert detect(client, root, "../outside.py").status_code in (403, 422)
    assert detect(client, tmp_path / "unapproved").status_code == 403
    assert detect(client, root, ".env").status_code in (403, 404)
    assert detect(client, root, "missing-file.py").status_code == 404


def test_secrets_and_symlink_targets_not_inferred(workspace):
    client, root = workspace
    (root / ".env").write_text("DJANGO_SETTINGS_MODULE=secret\n")
    (root / ".git").mkdir()
    (root / ".git" / "private.py").write_text("print(1)")
    outside = root.parent / "outside-secret.py"
    outside.write_text("print(1)")
    link = root / "outside.py"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not available")
    result = detect(client, root)
    assert result.status_code == 200
    assert result.json()["files_inspected"] == 0
    assert detect(client, root, "outside.py").status_code in (403, 404)


def test_toolchain_status_never_executes_anything(workspace, monkeypatch):
    client, root = workspace
    (root / "src.rs").write_text("fn main() {}")
    recorded = []
    binary = root.parent / "rustc"
    binary.write_text("#!/bin/sh\nexit 42\n")
    binary.chmod(0o755)
    monkeypatch.setattr(languages.shutil, "which",
        lambda name: recorded.append(name) or (str(binary) if name == "rustc" else None))
    data = detect(client, root, "src.rs", probe=True).json()
    statuses = {x["tool"]: x for x in data["toolchains"]}
    assert statuses["rustc"]["status"] == "available"
    assert statuses["rustc"]["version"] is None
    assert statuses["cargo"]["status"] == "unavailable"
    assert recorded
    assert data["source_executed"] is False


def test_project_local_executable_never_counted_as_verified_tool(workspace, monkeypatch):
    client, root = workspace
    (root / "code.rs").write_text("fn main(){}")
    unsafe = root / "rustc"
    unsafe.write_text("#!/bin/sh\nexit 0\n")
    unsafe.chmod(0o755)
    monkeypatch.setattr(languages.shutil, "which", lambda _: str(unsafe))
    result = detect(client, root, "code.rs", probe=True).json()
    assert all(entry["status"] == "unavailable" for entry in result["toolchains"])


def test_bounded_scan_and_unicode(workspace, monkeypatch):
    client, root = workspace
    monkeypatch.setattr(languages, "MAX_INSPECT", 8)
    for i in range(25):
        (root / f"মডিউল-{i:03}.py").write_text("print('test')")
    result = detect(client, root)
    assert result.status_code == 200, result.text
    assert result.json()["files_inspected"] <= 8
    assert result.json()["scan_truncated"] is True


def test_tool_selection_and_missing_runtime_do_not_imply_buildability(workspace):
    client, root = workspace
    (root / "app.rs").write_text("fn main() {}")
    result = detect(client, root, "app.rs", probe=False).json()
    assert result["primary_language"] == "rust"
    assert {x["tool"] for x in result["toolchains"]} == {"rustc", "cargo"}
    assert all(x["status"] == "not_checked" for x in result["toolchains"])
    registry = client.get(BASE + "/registry", headers=HEADERS).json()
    rust = next(x for x in registry["languages"] if x["id"] == "rust")
    assert rust["compatibility"]["linux"] == "unverified"
    assert "debug" not in rust["capabilities"]


def test_oversize_manifest_is_ignored(workspace):
    client, root = workspace
    (root / "package.json").write_text(
        '{"dependencies":{"next":"*"}}' + " " * (languages.MAX_MANIFEST + 1))
    assert "Next.js" not in {x["name"] for x in detect(client, root).json()["frameworks"]}
