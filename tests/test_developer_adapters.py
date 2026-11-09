"""V8: exercised external subprocess adapter SDK and DAP trust/permission gates."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from automoto import developer_adapters as adapters, sandbox, server
from automoto.hosted import path_allowed

BASE = "/api/developer/studio/adapters"
HEADERS = {"X-AutoMoto-Token": server.SESSION_TOKEN}

FAKE_DAP = r'''
import json
import sys
import time
from pathlib import Path

mode = sys.argv[1]
trace = Path(sys.argv[2])
def send(message):
    raw = json.dumps(message).encode("utf-8")
    sys.stdout.buffer.write(b"Content-Length: " + str(len(raw)).encode() + b"\r\n\r\n" + raw)
    sys.stdout.buffer.flush()

line = sys.stdin.buffer.readline()
if not line.lower().startswith(b"content-length:"):
    sys.exit(7)
size = int(line.split(b":", 1)[1].strip())
assert sys.stdin.buffer.readline() == b"\r\n"
message = json.loads(sys.stdin.buffer.read(size))
trace.write_text(message.get("command", "missing"), encoding="utf-8")
if mode == "hang":
    time.sleep(25)
elif mode == "invalid":
    sys.stdout.buffer.write(b"Content-Length: 999999999\r\n\r\n")
    sys.stdout.buffer.flush()
elif mode == "reject":
    send({"seq": 4, "type": "response", "request_seq": 1,
          "command": "initialize", "success": False})
else:
    send({"seq": 4, "type": "response", "request_seq": 1,
          "command": "initialize", "success": True, "body": {
              "supportsConfigurationDoneRequest": True,
              "supportsSetVariable": False,
              "untrustedUnknownKey": "<script>alert(1)</script>",
              "supportsFunctionBreakpoints": True,
          }})
'''


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(tmp_path / "automoto-private"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    workspace_root = sandbox.default_root()
    root = workspace_root / "v8"
    root.mkdir(parents=True)
    (root / "safe.py").write_text("def safe():\n    return True\n", encoding="utf-8")
    with adapters.REGISTRY_LOCK:
        state = adapters._registry_file()
        if state.exists():
            state.unlink()
    yield TestClient(server.app), root, tmp_path
    with adapters.REGISTRY_LOCK:
        state = adapters._registry_file()
        if state.exists():
            state.unlink()


def trust(client, root, trusted=True):
    reply = client.post("/api/developer/studio/trust", headers=HEADERS,
                        json={"project": str(root), "trusted": trusted,
                              "confirmed": True})
    assert reply.status_code == 200, reply.text


def request(client, endpoint, root, **fields):
    return client.post(BASE + "/" + endpoint, headers=HEADERS,
                       json={"project": str(root), **fields})


def fingerprint(client, root, executable=None):
    return request(client, "inspect", root,
                   executable=executable or sys.executable)


def register(client, root, *, identifier="python-test", category="test",
             language="python", args=None, executable=None,
             expected_sha256=None, protocol=None):
    executable = executable or sys.executable
    sha = expected_sha256 or fingerprint(client, root, executable).json()["sha256"]
    return request(client, "register", root, id=identifier, label="Test external adapter",
                   category=category, language=language,
                   protocol=protocol or ("dap" if category == "debugger" else "process"),
                   executable=executable, args=args or [], expected_sha256=sha,
                   confirmed=True)


def run(client, root, identifier="python-test", endpoint="run", **kw):
    return request(client, endpoint, root, id=identifier, confirmed=True,
                   accept_execution_and_write_risk=True, **kw)


def test_catalog_does_not_install_execute_or_enable_hosted_routes(workspace):
    client, root, _ = workspace
    for endpoint in ("register", "inspect", "run", "dap/initialize", "unregister"):
        assert path_allowed("POST", BASE + "/" + endpoint) is False
    assert path_allowed("GET", BASE + "/catalog") is False
    assert client.get(BASE + "/catalog", params={"project": str(root)}).status_code == 403
    response = client.get(BASE + "/catalog", params={"project": str(root)}, headers=HEADERS)
    assert response.status_code == 200
    value = response.json()
    assert set(value["roles"]) == set(adapters.TYPES)
    assert value["registered"] == []
    assert value["auto_install"] is False
    assert value["auto_execute"] is False
    assert value["platform_sandbox"] is False


def test_registration_needs_trust_exact_pinned_sha_and_never_runs(workspace):
    client, root, tmp = workspace
    before = (root / "safe.py").read_bytes()
    assert fingerprint(client, root).status_code == 403
    trust(client, root)
    info = fingerprint(client, root).json()
    assert info["sha256"] == hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
    assert info["size_bytes"] > 0
    mismatch = register(client, root, expected_sha256="0" * 64)
    assert mismatch.status_code == 409
    answer = register(client, root, args=["-c", "print('hello from trusted adapter')"])
    assert answer.status_code == 200, answer.text
    assert answer.json()["registered"] is True
    assert answer.json()["executable_started"] is False
    assert answer.json()["installed_binary"] is False
    assert not (root / "unknown-output.txt").exists()
    assert (root / "safe.py").read_bytes() == before
    duplicate = register(client, root)
    assert duplicate.status_code == 409
    listed = client.get(BASE + "/catalog", headers=HEADERS,
                        params={"project": str(root)}).json()["registered"]
    assert len(listed) == 1
    assert listed[0]["sha256"] == info["sha256"]
    assert (tmp / "automoto-private" / "developer-studio" / "external-adapters.json").is_file()


def test_real_execution_requires_fresh_confirmation_and_scrubs_secret_environment(workspace, monkeypatch):
    client, root, _ = workspace
    trust(client, root)
    monkeypatch.setenv("OPENAI_API_KEY", "not-for-external-tools")
    monkeypatch.setenv("PYTHONPATH", "not-for-external-tools")
    script = "import os; print(os.getenv('OPENAI_API_KEY')); print(os.getenv('PYTHONPATH'))"
    assert register(client, root, args=["-c", script]).status_code == 200
    assert request(client, "run", root, id="python-test", confirmed=False,
                   accept_execution_and_write_risk=True).status_code == 422
    assert request(client, "run", root, id="python-test", confirmed=True,
                   accept_execution_and_write_risk=False).status_code == 422
    result = run(client, root)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["status"] == "completed"
    assert data["exit_code"] == 0
    assert data["output"].splitlines() == ["None", "None"]
    assert data["explicit_approval"] is True
    assert data["platform_sandbox"] is False
    assert data["source_files_unchanged"] == "not_verified"
    assert data["registry_modified"] is False


@pytest.mark.parametrize("role", adapters.TYPES)
def test_external_sdk_registers_each_role_without_core_changes(workspace, role):
    client, root, _ = workspace
    trust(client, root)
    result = register(client, root, identifier=f"local-{role}",
                      category=role, args=["--version"])
    assert result.status_code == 200, result.text
    assert result.json()["adapter"]["category"] == role
    assert result.json()["adapter"]["protocol"] == ("dap" if role == "debugger" else "process")
    if role == "debugger":
        assert run(client, root, identifier=f"local-{role}").status_code == 422
    else:
        assert run(client, root, identifier=f"local-{role}",
                   endpoint="dap/initialize").status_code == 422


def test_register_rejects_unknown_language_wrong_dap_protocol_unsafe_args(workspace):
    client, root, _ = workspace
    trust(client, root)
    assert register(client, root, language="invented-language").status_code == 422
    assert register(client, root, category="debugger", protocol="process").status_code == 422
    assert register(client, root, category="compiler", protocol="dap").status_code == 422
    assert register(client, root, args=["ok\nbad"]).status_code == 422
    assert register(client, root, args=["x" * 257]).status_code == 422
    assert register(client, root, args=["x"] * 13).status_code == 422
    no_confirm = request(client, "register", root, id="custom-tool", label="Custom",
                         category="test", language="python", protocol="process",
                         executable=sys.executable, args=[],
                         expected_sha256=fingerprint(client, root).json()["sha256"],
                         confirmed=False)
    assert no_confirm.status_code == 422


def test_revocation_prevents_execution_and_project_identity_isolated(workspace):
    client, root, tmp = workspace
    other = root.parent / "another"
    other.mkdir()
    trust(client, root)
    trust(client, other)
    assert register(client, root).status_code == 200
    assert run(client, other).status_code == 404
    trust(client, root, False)
    assert run(client, root).status_code == 403
    pinned = hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
    assert register(client, root, identifier="another-probe", expected_sha256=pinned).status_code == 403
    trust(client, root, True)
    assert run(client, root).status_code == 200
    removed = request(client, "unregister", root, id="python-test", confirmed=True)
    assert removed.status_code == 200
    assert removed.json()["binary_uninstalled"] is False
    assert run(client, root).status_code == 404


def test_binary_hash_is_rechecked_at_execution(workspace, monkeypatch):
    client, root, _ = workspace
    trust(client, root)
    assert register(client, root).status_code == 200
    real = adapters._fingerprint
    def changed(executable, project):
        data = real(executable, project)
        data["sha256"] = "0" * 64
        return data
    monkeypatch.setattr(adapters, "_fingerprint", changed)
    assert run(client, root).status_code == 409


def test_process_output_is_capped_and_subprocess_is_terminated(workspace):
    client, root, _ = workspace
    trust(client, root)
    code = "import sys;sys.stdout.write('A'*90000);sys.stdout.flush()"
    assert register(client, root, args=["-u", "-c", code]).status_code == 200
    result = run(client, root)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["status"] == "output_limit"
    assert data["output_truncated"] is True
    assert len(data["output"].encode("utf-8")) <= adapters.MAX_OUTPUT_BYTES


def test_process_timeout_kills_hung_executable(workspace, monkeypatch):
    client, root, _ = workspace
    trust(client, root)
    monkeypatch.setattr(adapters, "RUN_TIMEOUT", .15)
    assert register(client, root, args=["-c", "import time; time.sleep(25)"]).status_code == 200
    result = run(client, root)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["timed_out"] is True
    assert data["status"] == "timeout"


def test_registry_corruption_fails_closed_and_does_not_overwrite(workspace):
    client, root, _ = workspace
    trust(client, root)
    file = adapters._registry_file()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("invalid-json", encoding="utf-8")
    assert register(client, root).status_code == 409
    assert file.read_text(encoding="utf-8") == "invalid-json"


def test_executable_inside_workspace_is_rejected(workspace):
    client, root, _ = workspace
    trust(client, root)
    local = root / "local-binary"
    local.write_text("non-executable", encoding="utf-8")
    local.chmod(0o755)
    assert fingerprint(client, root, str(local)).status_code == 403
    assert fingerprint(client, root, "not-an-absolute-path").status_code == 422


def test_dap_initialize_is_real_framed_subprocess_not_debuggee_launch(workspace):
    client, root, tmp = workspace
    trust(client, root)
    script = tmp / "sample_dap.py"
    script.write_text(FAKE_DAP, encoding="utf-8")
    commands = tmp / "dap-commands.txt"
    assert register(client, root, identifier="custom-debugger", category="debugger",
                    args=["-u", str(script), "normal", str(commands)]).status_code == 200
    result = run(client, root, identifier="custom-debugger", endpoint="dap/initialize")
    assert result.status_code == 200, result.text
    item = result.json()
    assert item["status"] == "initialized_only"
    assert item["capabilities"]["supportsFunctionBreakpoints"] is True
    assert item["capabilities"]["supportsSetVariable"] is False
    assert "untrustedUnknownKey" not in item["capabilities"]
    assert item["launch_sent"] is False
    assert item["attach_sent"] is False
    assert item["configuration_sent"] is False
    assert item["process_terminated"] is True
    assert commands.read_text(encoding="utf-8") == "initialize"


@pytest.mark.parametrize("mode,expected", [("invalid", 502), ("reject", 502), ("hang", 504)])
def test_dap_bad_frames_rejected_and_timeout_bounded(workspace, monkeypatch, mode, expected):
    client, root, tmp = workspace
    trust(client, root)
    script = tmp / "sample_dap.py"
    script.write_text(FAKE_DAP, encoding="utf-8")
    commands = tmp / "dap-commands.txt"
    monkeypatch.setattr(adapters, "DAP_TIMEOUT", 0.2)
    assert register(client, root, identifier="custom-debugger", category="debugger",
                    args=["-u", str(script), mode, str(commands)]).status_code == 200
    result = run(client, root, identifier="custom-debugger", endpoint="dap/initialize")
    assert result.status_code == expected, result.text
    assert commands.read_text(encoding="utf-8") == "initialize"
