"""Regression tests for the November 2026 security review (Semgrep / Bandit / manual)."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import datafiles, local_llm, providers, server, tenancy
from automoto.providers import REGISTRY

ROOT = Path(__file__).resolve().parents[1]


def test_sqlite_names_with_quotes_are_quoted_not_injected(tmp_path):
    db = tmp_path / "x.sqlite"
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE "a""b" (v INTEGER)')
    con.execute('INSERT INTO "a""b" VALUES (1)')
    con.commit()
    con.close()
    schema = datafiles.sqlite_schema(db)
    assert schema == [{"name": 'a"b', "type": "table", "rows": 1, "columns": ["v INTEGER"]}]
    assert datafiles._quote_ident('t" UNION SELECT 1 --') == '"t"" UNION SELECT 1 --"'


def test_launch_link_ignores_a_spoofed_host_header():
    c = TestClient(server.app)
    r = c.post("/api/session/launch", headers={"X-AutoMoto-Token": server.SESSION_TOKEN, "Host": "testserver"})
    assert r.status_code == 200
    url = r.json()["url"]
    assert url.startswith("http://127.0.0.1:") and "testserver" not in url and "?launch=" in url


def test_hosted_server_never_starts_ollama(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:9")
    monkeypatch.setattr(tenancy, "multiuser", lambda: True)
    monkeypatch.setattr(local_llm, "ollama_binary", lambda: "/usr/bin/ollama")
    started = []
    monkeypatch.setattr(local_llm, "start_ollama", lambda: started.append(1) or {"started": True})
    with pytest.raises(providers.ProviderError):
        providers.complete(REGISTRY["ollama"], [{"role": "user", "content": "hi"}], "qwen2.5:3b", "local")
    assert started == []


def test_all_github_actions_are_pinned_to_a_commit():
    import re

    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        for line in wf.read_text(encoding="utf-8").splitlines():
            m = re.search(r"uses:\s*([^\s#]+)", line)
            if m and not m.group(1).startswith("./"):
                assert re.search(r"@[0-9a-f]{40}$", m.group(1)), f"{wf.name}: {m.group(1)} is not pinned to a SHA"


def test_updater_signing_key_is_only_given_to_the_signing_step():
    import yaml

    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "desktop.yml").read_text(encoding="utf-8"))
    job = wf["jobs"]["windows"]
    assert "TAURI_SIGNING_PRIVATE_KEY" not in (job.get("env") or {})
    with_key = [s.get("name") for s in job["steps"] if "TAURI_SIGNING_PRIVATE_KEY" in (s.get("env") or {})]
    assert with_key == ["Sign updater payloads for the final files"]
