"""Developer Studio V2 real source round trips and save-boundary regressions."""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import developer_editor, sandbox, server
from automoto.hosted import path_allowed

BASE = "/api/developer/studio"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    project = sandbox.default_root() / "projects" / "multilingual"
    project.mkdir(parents=True)
    file = project / "main.ts"
    file.write_bytes("export const greeting = 'Hello';\r\n".encode("utf-8"))
    yield TestClient(server.app), project, file


def open_source(client, project, filename="main.ts", **kwargs):
    return client.get(BASE + "/file", headers=AUTH,
                      params={"project": str(project), "path": filename, **kwargs})


def trust(client, project):
    response = client.post(BASE + "/trust", headers=AUTH,
                           json={"project": str(project), "trusted": True, "confirmed": True})
    assert response.status_code == 200, response.text
    assert response.json()["trusted"]


def save_source(client, project, before, text, path="main.ts", **kwargs):
    body = {
        "project": str(project), "path": path, "text": text,
        "expected_sha256": before["sha256"],
        "encoding": before["encoding"], "newline": before["newline"],
        "confirmed": True, **kwargs
    }
    return client.post(BASE + "/save-file", headers=AUTH, json=body)


def test_v2_only_local_and_requires_auth(env):
    client, project, _ = env
    assert not path_allowed("GET", BASE + "/file")
    assert not path_allowed("POST", BASE + "/save-file")
    assert client.get(BASE + "/file", params={"project": str(project), "path": "main.ts"}).status_code == 403
    assert client.post(BASE + "/save-file", json={}).status_code == 403


def test_untrusted_workspace_cannot_save_and_confirmation_required(env):
    client, project, file = env
    old = file.read_bytes()
    opened = open_source(client, project)
    assert opened.status_code == 200
    assert opened.json()["can_edit"] is False
    response = save_source(client, project, opened.json(), "const changed = true;\n")
    assert response.status_code == 403
    trust(client, project)
    missing = client.post(BASE + "/save-file", headers=AUTH, json={
        "project": str(project), "path": "main.ts", "text": "hello",
        "expected_sha256": opened.json()["sha256"],
        "encoding": "utf-8", "newline": "lf"
    })
    assert missing.status_code == 422
    assert file.read_bytes() == old


def test_crlf_utf8_multilingual_preserves_encoding_and_newlines(env):
    client, project, file = env
    trust(client, project)
    first = open_source(client, project)
    assert first.status_code == 200, first.text
    before = first.json()
    assert before["newline"] == "crlf"
    assert before["encoding"] == "utf-8"
    assert before["can_edit"] is True
    edited = "const message = 'বাংলা العربية 日本語';\nconst n = 1;\n"
    response = save_source(client, project, before, edited)
    assert response.status_code == 200, response.text
    assert response.json()["changed"]
    expected = edited.replace("\n", "\r\n").encode("utf-8")
    assert file.read_bytes() == expected
    assert response.json()["sha256"] == hashlib.sha256(expected).hexdigest()
    assert open_source(client, project).json()["newline"] == "crlf"


@pytest.mark.parametrize("encoding,bom,text", [
    ("utf-8-sig", b"\xef\xbb\xbf", "const s = 'π';\r\n"),
    ("utf-16-le", b"\xff\xfe", "const s = 'مَرْحَبًا';\r\n"),
    ("utf-16-be", b"\xfe\xff", "let value = 'বাংলা';\r\n"),
])
def test_unicode_bom_and_utf16_safe_roundtrip(env, encoding, bom, text):
    client, project, file = env
    codec = "utf-8" if encoding == "utf-8-sig" else encoding
    file.write_bytes(bom + text.encode(codec))
    trust(client, project)
    opened = open_source(client, project)
    assert opened.status_code == 200, opened.text
    data = opened.json()
    assert data["text"] == text
    assert data["encoding"] == encoding
    assert data["newline"] == "crlf"
    replacement = text.replace("value", "revised").replace("const", "let")
    saved = save_source(client, project, data, replacement)
    assert saved.status_code == 200, saved.text
    assert file.read_bytes() == bom + replacement.encode(codec)


def test_windows_1252_requires_explicit_selection_and_valid_encoding(env):
    client, project, file = env
    file.write_bytes(b"price = 'caf\xe9'\r\n")
    assert open_source(client, project).status_code == 415
    opened = open_source(client, project, encoding="cp1252")
    assert opened.status_code == 200
    data = opened.json()
    assert data["text"].startswith("price = 'café'")
    trust(client, project)
    error = save_source(client, project, data, "coffee = '漢字'")
    assert error.status_code == 422
    assert file.read_bytes() == b"price = 'caf\xe9'\r\n"
    result = save_source(client, project, data, "coffee = 'café'\n")
    assert result.status_code == 200
    assert file.read_bytes() == b"coffee = 'caf\xe9'\r\n"


def test_stale_disk_edits_are_never_overwritten(env):
    client, project, file = env
    trust(client, project)
    before = open_source(client, project).json()
    file.write_bytes(b"someone else changed this\n")
    conflict = save_source(client, project, before, "our unsaved edit\n")
    assert conflict.status_code == 409
    assert b"someone else changed this" in file.read_bytes()
    assert not list(project.glob(".automoto-edit-*"))


def test_revoke_trust_prevents_existing_editor_session_writes(env):
    client, project, file = env
    trust(client, project)
    before = open_source(client, project).json()
    revoked = client.post(BASE + "/trust", headers=AUTH,
                          json={"project": str(project), "trusted": False, "confirmed": True})
    assert revoked.status_code == 200
    result = save_source(client, project, before, "const x = 8;\n")
    assert result.status_code == 403
    assert file.read_bytes().startswith(b"export const greeting")


def test_secret_file_traversal_symlink_and_unapproved_project_denied(env, tmp_path):
    client, project, file = env
    trust(client, project)
    before = open_source(client, project).json()
    for path in (".env", ".git/config", "../secret", "src/../main.ts"):
        result = save_source(client, project, before, "replacement\n", path=path)
        assert result.status_code in (403, 404), (path, result.text)
    outside = tmp_path / "not-allowed"
    outside.mkdir()
    assert open_source(client, outside).status_code == 403
    link = project / "linked.ts"
    try:
        link.symlink_to(file)
    except (OSError, NotImplementedError):
        return
    assert open_source(client, project, "linked.ts").status_code == 403
    assert save_source(client, project, before, "replacement", path="linked.ts").status_code == 403


def test_readonly_existing_source_is_not_replaced(env):
    client, project, file = env
    trust(client, project)
    before = open_source(client, project).json()
    try:
        file.chmod(stat.S_IREAD)
        result = save_source(client, project, before, "const x = true\n")
        assert result.status_code == 403, result.text
    finally:
        file.chmod(stat.S_IREAD | stat.S_IWRITE)
    assert file.read_bytes().startswith(b"export const greeting")


def test_binary_large_bad_encoding_and_mixed_newlines(env):
    client, project, file = env
    trust(client, project)
    file.write_bytes(b"A\x00B")
    assert open_source(client, project).status_code == 415
    file.write_bytes(b"A" * (developer_editor.MAX_BYTES + 1))
    assert open_source(client, project).status_code == 413
    file.write_bytes(b"one\r\ntwo\nthree\r")
    opened = open_source(client, project)
    assert opened.status_code == 200
    assert opened.json()["newline"] == "mixed"
    assert save_source(client, project, opened.json(), "all\nlines\n").status_code == 422
    corrected = save_source(client, project, opened.json(), "all\nlines\n", newline="lf")
    assert corrected.status_code == 200
    assert file.read_bytes() == b"all\nlines\n"


def test_no_change_is_idempotent_and_preserves_bytes(env):
    client, project, file = env
    trust(client, project)
    old = file.read_bytes()
    opened = open_source(client, project).json()
    unchanged = save_source(client, project, opened, opened["text"])
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["changed"] is False
    assert file.read_bytes() == old


def test_failed_oversized_save_does_not_create_temporary_files(env):
    client, project, file = env
    trust(client, project)
    original = file.read_bytes()
    before = open_source(client, project).json()
    body = {
        "project": str(project), "path": "main.ts",
        "text": "X" * developer_editor.MAX_BYTES, "encoding": "utf-16-le",
        "newline": "lf", "confirmed": True, "expected_sha256": before["sha256"],
    }
    result = client.post(BASE + "/save-file", headers=AUTH, json=body)
    assert result.status_code in (409, 413), result.text  # original was not UTF-16
    assert file.read_bytes() == original
    assert list(project.glob(".automoto-edit-*")) == []
