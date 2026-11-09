"""Developer Studio V6 real JSON-RPC subprocess fixture and security boundaries."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from automoto import developer_lsp as lsp, sandbox, server
from automoto.hosted import path_allowed

BASE = "/api/developer/studio/lsp"
H = {"X-AutoMoto-Token": server.SESSION_TOKEN}
FAKE = r'''
import json, sys
from pathlib import Path
from urllib.parse import quote

def send(message):
    raw=json.dumps(message,ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(b"Content-Length: "+str(len(raw)).encode()+b"\r\n\r\n"+raw)
    sys.stdout.buffer.flush()

def receive():
    header=sys.stdin.buffer.readline()
    if not header:
        return None
    length=None
    while header and header.strip():
        if header.lower().startswith(b"content-length:"):
            length=int(header.split(b":",1)[1])
        header=sys.stdin.buffer.readline()
    if length is None:
        return None
    return json.loads(sys.stdin.buffer.read(length))

mode=sys.argv[1] if len(sys.argv)>1 else "normal"
if mode=="crash":
    sys.exit(1)
for item in iter(receive,None):
    method=item.get("method")
    if method=="initialize":
        if mode=="oversized":
            sys.stdout.buffer.write(b"Content-Length: 999999999\r\n\r\n")
            sys.stdout.buffer.flush()
            sys.exit(0)
        send({"jsonrpc":"2.0","id":item["id"],"result":{"capabilities":{
            "hoverProvider":True,"completionProvider":True,"definitionProvider":True,
            "referencesProvider":True,"renameProvider":True}}})
    elif method=="textDocument/didOpen":
        uri=item["params"]["textDocument"]["uri"]
        send({"jsonrpc":"2.0","method":"textDocument/publishDiagnostics","params":{
            "uri":uri,"diagnostics":[{"message":"fixture diagnostic","severity":2,
            "range":{"start":{"line":0,"character":0},"end":{"line":0,"character":5}}}]}})
    elif "id" in item and method=="textDocument/hover":
        if mode=="hang":
            continue
        send({"jsonrpc":"2.0","id":item["id"],"result":{
            "contents":{"kind":"plaintext","value":"simulated hover <script>alert(1)</script>"}}})
    elif "id" in item and method=="textDocument/completion":
        send({"jsonrpc":"2.0","id":item["id"],"result":{
            "items":[{"label":"legitimate","detail":"static fixture"},
                     {"label":"second","detail":"fixture"}]}})
    elif "id" in item and method in ("textDocument/definition","textDocument/references"):
        send({"jsonrpc":"2.0","id":item["id"],"result":[
            {"uri":Path.cwd().joinpath("src.py").as_uri(),"range":{"start":{"line":1,"character":2}}},
            {"uri":Path.cwd().parent.joinpath("outside.py").as_uri(),"range":{"start":{"line":0,"character":0}}}
        ]})
    elif "id" in item and method=="textDocument/rename":
        send({"jsonrpc":"2.0","id":item["id"],"result":{"changes":{
            Path.cwd().joinpath("src.py").as_uri():[{
                "range":{"start":{"line":0,"character":0},"end":{"line":0,"character":3}},
                "newText":item["params"]["newName"]}],
            Path.cwd().parent.joinpath("outside.py").as_uri():[{
                "range":{"start":{"line":0,"character":0},"end":{"line":0,"character":1}},
                "newText":"should never be applied"}]
        }}})
    elif "id" in item and method:
        send({"jsonrpc":"2.0","id":item["id"],"result":None})
'''


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v6"
    root.mkdir(parents=True)
    (root / "src.py").write_text("print('safe')\n", encoding="utf-8")
    fake = tmp_path / "fake_lsp.py"
    fake.write_text(FAKE, encoding="utf-8")
    monkeypatch.setattr(lsp, "_binary",
                        lambda language, r: (sys.executable, "-u", str(fake), "normal")
                        if language == "python" else None)
    with lsp.LOCK:
        for session in lsp.SESSIONS.values():
            session.close()
        lsp.SESSIONS.clear()
    yield TestClient(server.app), root, fake
    with lsp.LOCK:
        for session in lsp.SESSIONS.values():
            session.close()
        lsp.SESSIONS.clear()


def trust(client, root, value=True):
    result = client.post("/api/developer/studio/trust", headers=H, json={
        "project": str(root), "trusted": value, "confirmed": True})
    assert result.status_code == 200, result.text


def start(client, root):
    return client.post(BASE + "/start", headers=H, json={
        "project": str(root), "language": "python", "confirmed": True})


def req(client, resource, root, session_id, **data):
    return client.post(BASE + "/" + resource, headers=H, json={
        "project": str(root), "session_id": session_id, **data})


def test_server_catalog_is_local_and_no_automatic_start(workspace):
    client, root, _ = workspace
    assert not path_allowed("POST", BASE + "/start")
    assert not path_allowed("POST", BASE + "/query")
    assert not path_allowed("GET", BASE + "/servers")
    assert client.get(BASE + "/servers", params={"project": str(root)}).status_code == 403
    result = client.get(BASE + "/servers", params={"project": str(root)}, headers=H)
    assert result.status_code == 200, result.text
    assert result.json()["automatic_start"] is False
    assert result.json()["platform_sandbox"] is False
    assert len(lsp.SESSIONS) == 0


def test_start_requires_exact_project_trust_and_explicit_confirmation(workspace):
    client, root, _ = workspace
    assert start(client, root).status_code == 403
    trust(client, root)
    assert client.post(BASE + "/start", headers=H,
        json={"project": str(root), "language": "python", "confirmed": False}).status_code == 422
    response = start(client, root)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["language"] == "python"
    assert result["capabilities"]["hoverProvider"] is True
    assert result["source_modified"] is False
    assert result["explicit_approval"] is True
    assert req(client, "stop", root, result["session_id"]).json()["stopped"] is True


def test_live_lsp_hover_completion_navigation_and_readonly_rename(workspace):
    client, root, _ = workspace
    trust(client, root)
    before = (root / "src.py").read_bytes()
    token = start(client, root).json()["session_id"]
    for method, expected in (
        ("textDocument/hover", "simulated hover"),
        ("textDocument/completion", "legitimate"),
    ):
        response = req(client, "query", root, token, path="src.py", method=method,
                       line=0, character=1)
        assert response.status_code == 200, response.text
        assert expected in str(response.json()["result"])
        assert response.json()["source_modified"] is False
    for method in ("textDocument/definition", "textDocument/references"):
        result = req(client, "query", root, token, path="src.py", method=method,
                     line=0, character=2).json()["result"]
        assert result["locations"] == [{"path": "src.py", "line": 1, "character": 2}]
    rename = req(client, "query", root, token, path="src.py",
                 method="textDocument/rename", line=0, character=3, new_name="safe_name")
    assert rename.status_code == 200, rename.text
    result = rename.json()["result"]
    assert result["preview_only"] and result["applied"] is False
    assert len(result["edits"]) == 1
    assert result["edits"][0]["path"] == "src.py"
    assert (root / "src.py").read_bytes() == before


def test_diagnostics_restricted_to_project_and_bounded(workspace):
    client, root, _ = workspace
    trust(client, root)
    token = start(client, root).json()["session_id"]
    assert req(client, "document", root, token, path="src.py").status_code == 200
    files = []
    for _ in range(20):
        response = req(client, "diagnostics", root, token)
        files = response.json()["files"]
        if files:
            break
        time.sleep(0.03)
    assert files and files[0]["path"] == "src.py"
    assert files[0]["items"][0]["message"] == "fixture diagnostic"


def test_trust_revocation_shuts_down_existing_lsp_session(workspace):
    client, root, _ = workspace
    trust(client, root)
    token = start(client, root).json()["session_id"]
    trust(client, root, False)
    response = req(client, "document", root, token, path="src.py")
    assert response.status_code == 403
    assert token not in lsp.SESSIONS


def test_unsafe_paths_and_languages_refused_even_with_trust(workspace, tmp_path):
    client, root, _ = workspace
    trust(client, root)
    token = start(client, root).json()["session_id"]
    for path in ("../secret.py", ".env", "missing.py", "src.rs"):
        status = req(client, "document", root, token, path=path).status_code
        assert status in (403, 404, 422), (path, status)
    (root / "src.rs").write_text("fn main() {}")
    assert req(client, "document", root, token, path="src.rs").status_code == 422
    assert req(client, "query", root, token, path="src.py",
               method="textDocument/rename", line=0, character=0,
               new_name="../target").status_code == 422
    alias = root / "alias.py"
    try:
        alias.symlink_to(tmp_path / "fake_lsp.py")
    except (OSError, NotImplementedError):
        pass
    else:
        assert req(client, "document", root, token, path="alias.py").status_code == 403


def test_session_limits_and_isolation(workspace):
    client, root, _ = workspace
    trust(client, root)
    first = start(client, root).json()["session_id"]
    second = start(client, root).json()["session_id"]
    assert start(client, root).status_code == 429
    assert req(client, "stop", root, first).status_code == 200
    assert req(client, "stop", root, second).status_code == 200
    assert req(client, "query", root, first, path="src.py",
               method="textDocument/hover", line=0, character=0).status_code == 404


def test_invalid_or_oversized_server_message_does_not_escape_limit(workspace, monkeypatch):
    client, root, fake = workspace
    trust(client, root)
    monkeypatch.setattr(lsp, "_binary",
        lambda language, r: (sys.executable, "-u", str(fake), "oversized"))
    response = start(client, root)
    assert response.status_code in (502, 504)
    assert not lsp.SESSIONS


def test_server_crash_on_start_does_not_leak_session(workspace, monkeypatch):
    client, root, fake = workspace
    trust(client, root)
    monkeypatch.setattr(lsp, "_binary",
        lambda language, r: (sys.executable, "-u", str(fake), "crash"))
    response = start(client, root)
    assert response.status_code in (502, 504)
    assert not lsp.SESSIONS


def test_request_timeout_cancel_and_recovery(workspace, monkeypatch):
    client, root, fake = workspace
    trust(client, root)
    monkeypatch.setattr(lsp, "_binary",
        lambda language, r: (sys.executable, "-u", str(fake), "hang"))
    token = start(client, root).json()["session_id"]
    session = lsp.SESSIONS[token]
    with pytest.raises(Exception) as exc:
        session.ask("textDocument/hover", {"textDocument": {
            "uri": (root / "src.py").as_uri()}, "position": {"line": 0, "character": 0}},
            timeout=0.15)
    assert getattr(exc.value, "status_code", None) == 504
    assert req(client, "stop", root, token).status_code == 200
