"""Developer Studio V26 Bash/Zsh/Fish/PowerShell/Batch static and real acceptance."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import developer_shell as shell
from automoto import sandbox, server

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BASE = "/api/developer/studio/shell"
FIXTURE = Path(__file__).parent / "fixtures" / "v26-shell"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v26-shell"
    shutil.copytree(FIXTURE, root)
    return TestClient(server.app), root


def inspect(client, root):
    return client.get(BASE + "/inspect", headers=AUTH, params={"project": str(root)})


def trust(client, root):
    response = client.post("/api/developer/studio/trust", headers=AUTH,
                           json={"project": str(root), "trusted": True, "confirmed": True})
    assert response.status_code == 200, response.text


def snapshot(root):
    return {file.relative_to(root).as_posix(): file.read_bytes()
            for file in root.rglob("*") if file.is_file()}


def payload(client, root, task, name, tool):
    evidence = inspect(client, root)
    assert evidence.status_code == 200, evidence.text
    data = evidence.json()
    candidate = next(x for x in data["tools"] if x["name"] == tool)
    if candidate["status"] != "installed_not_executed":
        pytest.skip("Installed executable unavailable or intentionally blocked: " + tool)
    return {"project": str(root), "task": task, "script": name, "tool": tool,
            "expected_inventory_sha256": data["inventory_sha256"],
            "expected_toolchain_sha256": data["toolchain_sha256"],
            "expected_executable": candidate["executable"],
            "expected_sha256": candidate["sha256"],
            "confirmed": True, "accept_unsandboxed_interpreter_risk": True}


def invoke(client, root, task, name, tool, **changes):
    args = payload(client, root, task, name, tool)
    args.update(changes)
    return client.post(BASE + "/run", headers=AUTH, json=args)


def test_all_shell_languages_detected_without_execution(project):
    client, root = project
    original = snapshot(root)
    result = inspect(client, root)
    assert result.status_code == 200, result.text
    data = result.json()
    assert set(data["language_counts"]) == {"bash", "zsh", "fish", "powershell", "batch"}
    assert data["fixture_count"] == 6, [x for x in data["files"] if x["fixture_smoke_eligible"]]
    assert len(data["files"]) == 8
    assert data["scripts_executed"] is False
    assert data["inspection_executed_code"] is False
    assert data["deployment_started"] is False
    assert data["central_agent_studio"] == "developer"
    assert data["scan_incomplete"] is False
    assert snapshot(root) == original


def test_destructive_scripts_risk_signalled_and_never_smoke_eligible(project):
    client, root = project
    data = inspect(client, root).json()
    flagged = next(x for x in data["files"] if x["path"] == "scripts/hazard.sh")
    assert not flagged["fixture_smoke_eligible"]
    assert any(x["kind"] == "recursive deletion" for x in flagged["risk_signals"])
    assert any(x["kind"] == "network or external execution" for x in flagged["risk_signals"])
    assert data["risk_files"] >= 1
    assert "no general scripts" in data["safe_execution_policy"].lower()


@pytest.mark.parametrize("bad", [
    "echo SAFE\nrm -rf /tmp/file\n",
    "echo SAFE; echo SHOULD_NOT_RUN\n",
    "echo SAFE | cat\n",
    "echo $(uname)\n",
    "echo $HOME\n",
    "echo SAFE > /tmp/pwned\n",
    "echo SAFE && echo AGAIN\n",
    "bash -c 'echo hi'\n",
    "touch marker\n",
    "curl http://example.invalid\n",
    "echo SAFE\n# harmless\n",
    "echo SAFE\n",  # safe grammar but unapproved path is checked below
])
def test_fixture_grammar_rejects_unapproved_shell_code(project, bad):
    client, root = project
    script = root / "scripts/smoke.sh"
    # Preserve the required LF bytes even on Windows: Bash fixture execution\n    # intentionally rejects CRLF / carriage returns, not just unsafe tokens.\n    script.write_bytes(("#!/usr/bin/env bash\n" + bad).encode("utf-8"))
    data = inspect(client, root).json()
    item = next(x for x in data["files"] if x["path"] == "scripts/smoke.sh")
    if bad == "echo SAFE\n":
        assert item["fixture_smoke_eligible"] is True
    else:
        assert item["fixture_smoke_eligible"] is False


def test_bad_powershell_and_batch_operations_rejected(project):
    client, root = project
    ps = root / "scripts/smoke.ps1"
    for text in ("Remove-Item -Recurse C:\\data\n",
                 "Write-Output $env:USERNAME\n",
                 "Invoke-Expression 'Get-Process'\n",
                 "Write-Output 'OK'; exit 0\n"):
        ps.write_text(text)
        entry = next(x for x in inspect(client, root).json()["files"]
                     if x["path"] == "scripts/smoke.ps1")
        assert not entry["fixture_smoke_eligible"]
    cmd = root / "scripts/smoke.cmd"
    for text in ("@echo off\necho %PATH%\n", "@echo off\nrmdir /s C:\\data\n",
                 "@echo off\necho safe & del /f bad\n",
                 "@echo off\npowershell -Command calc\n"):
        cmd.write_text(text)
        entry = next(x for x in inspect(client, root).json()["files"]
                     if x["path"] == "scripts/smoke.cmd")
        assert not entry["fixture_smoke_eligible"]


def test_dangerous_script_never_executed_even_after_project_trust(project):
    client, root = project
    trust(client, root)
    if shutil.which("bash") is None:
        pytest.skip("Bash unavailable")
    response = invoke(client, root, "fixture_smoke", "scripts/hazard.sh", "bash")
    assert response.status_code == 403, response.text


def test_source_edit_rejects_previously_consent_approved_sha(project):
    client, root = project
    trust(client, root)
    if shutil.which("bash") is None:
        pytest.skip("Bash unavailable")
    args = payload(client, root, "fixture_smoke", "scripts/smoke.sh", "bash")
    args["expected_sha256"] = "0" * 64
    assert client.post(BASE + "/run", headers=AUTH, json=args).status_code == 409
    args = payload(client, root, "syntax", "scripts/smoke.sh", "bash")
    (root / "scripts/smoke.sh").write_text("echo DIFFERENT\n")
    assert client.post(BASE + "/run", headers=AUTH, json=args).status_code == 409


def test_reject_missing_consent_and_unsandboxed_risk_acknowledgement(project):
    client, root = project
    trust(client, root)
    if shutil.which("bash") is None:
        pytest.skip("Bash unavailable")
    args = payload(client, root, "syntax", "scripts/smoke.sh", "bash")
    assert client.post(BASE + "/run", headers=AUTH,
                       json={**args, "confirmed": False}).status_code == 422
    assert client.post(BASE + "/run", headers=AUTH,
                       json={**args, "accept_unsandboxed_interpreter_risk": False}).status_code == 422
    assert client.post(BASE + "/run", headers=AUTH,
                       json={**args, "unexpected_argument": "rm -rf /"}).status_code == 422
    assert client.post(BASE + "/run", headers=AUTH,
                       json={**args, "script": "../etc/passwd"}).status_code in (404, 422)


def test_untrusted_and_hosted_access_denied(project, monkeypatch):
    client, root = project
    assert client.get(BASE + "/inspect", params={"project": str(root)}).status_code in (401, 403)
    if shutil.which("bash"):
        response = invoke(client, root, "syntax", "scripts/smoke.sh", "bash")
        assert response.status_code == 403
    monkeypatch.setenv("AUTOMOTO_MODE", "multiuser")
    assert inspect(client, root).status_code in (401, 403, 404)


def test_linked_smoke_script_rejected(project, tmp_path):
    client, root = project
    script = root / "scripts/smoke.sh"
    script.unlink()
    target = tmp_path / "outside.sh"
    target.write_text("echo BAD\n")
    try:
        script.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("This OS does not allow test symlink creation.")
    assert inspect(client, root).status_code == 403


def test_batch_has_no_unapproved_syntax_check(project):
    client, root = project
    data = inspect(client, root).json()
    assert "No general Batch syntax checker" in data["batch_policy"]
    assert all(not item["fixture_smoke_eligible"] for item in data["files"]
               if item["path"] == "scripts/hazard.sh")


def test_real_shell_syntax_and_literal_only_fixtures(project):
    if os.environ.get("AUTOMOTO_V26_REAL_SHELL") != "1":
        pytest.skip("Real shell execution runs only in the dedicated installed-tool CI.")
    client, root = project
    trust(client, root)
    original = snapshot(root)
    paths = [
        ("bash", "scripts/smoke.sh", "V26_BASH_SMOKE_PASS"),
        ("bash", "scripts/smoke.bash", "V26_BASH_EXTENSION_PASS"),
        ("zsh", "scripts/smoke.zsh", "V26_ZSH_SMOKE_PASS"),
        ("fish", "scripts/smoke.fish", "V26_FISH_SMOKE_PASS"),
        ("pwsh", "scripts/smoke.ps1", "V26_POWERSHELL_SMOKE_PASS"),
        ("cmd.exe", "scripts/smoke.cmd", "V26_BATCH_SMOKE_PASS"),
    ]
    selected = {"bash"} if os.name != "nt" else {"pwsh", "cmd.exe"}
    if os.environ.get("AUTOMOTO_V26_ALL_POSIX") == "1":
        selected.update(("zsh", "fish"))
    for tool, path, marker in paths:
        if tool not in selected:
            continue
        if tool != "cmd.exe":
            response = invoke(client, root, "syntax", path, tool)
            assert response.status_code == 200, (tool, response.text)
            assert response.json()["status"] == "completed", response.text
        run = invoke(client, root, "fixture_smoke", path, tool)
        assert run.status_code == 200, (tool, run.text)
        data = run.json()
        assert data["status"] == "completed", (tool, data)
        assert marker in data["output"]
        assert data["fixture_grammar_enforced"]
        assert not data["arbitrary_script_execution"]
        assert not data["deployment_started"]
        assert data["temporary_copy_deleted"]
    if os.environ.get("AUTOMOTO_V26_ALL_POSIX") == "1":
        response = invoke(client, root, "shellcheck", "scripts/smoke.sh", "shellcheck")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "completed", response.text
    assert snapshot(root) == original


def test_real_powershell_invalid_script_parses_without_running(project):
    if os.environ.get("AUTOMOTO_V26_REAL_SHELL") != "1":
        pytest.skip("Installed pwsh is needed for parser verification.")
    client, root = project
    trust(client, root)
    if not shutil.which("pwsh"):
        pytest.skip("PowerShell Core is unavailable on this runner.")
    result = invoke(client, root, "syntax", "scripts/malformed.ps1", "pwsh")
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "nonzero_exit"
    assert result.json()["exit_code"] != 0
    assert not result.json()["fixture_grammar_enforced"]
    assert not result.json()["arbitrary_script_execution"]
