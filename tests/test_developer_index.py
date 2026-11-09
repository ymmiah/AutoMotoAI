"""Developer Studio V7 — deterministic private incremental indexing regressions."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from automoto import developer_index as index, sandbox, server
from automoto.hosted import path_allowed

BASE = "/api/developer/studio/index"
HEADERS = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v7-project"
    root.mkdir(parents=True)
    with index.LOCK:
        index.CACHE.clear()
    yield TestClient(server.app), root
    with index.LOCK:
        index.CACHE.clear()


def request(client, method, root, **extra):
    return client.post(BASE + "/" + method, headers=HEADERS,
                       json={"project": str(root), **extra})


def test_python_ast_symbols_nested_scopes_and_lexical_tokens(workspace):
    client, root = workspace
    (root / "main.py").write_text(
        "class Engine:\n"
        "    def run(self):\n"
        "        item = 2\n"
        "        return item\n"
        "\n"
        "async def запускаю():\n"
        "    return 1\n"
        "# run must not count as a Python token\n"
        'message = "run in a string"\n', encoding="utf-8")
    r = request(client, "refresh", root)
    assert r.status_code == 200, r.text
    assert r.json()["indexed_files"] == 1
    assert r.json()["source_modified"] is False
    assert r.json()["index_persisted"] is False
    assert r.json()["source_executed"] is False
    symbols = request(client, "symbols", root).json()["items"]
    assert {(s["name"], s["qualified_name"], s["parser"]) for s in symbols} == {
        ("Engine", "Engine", "ast"), ("run", "Engine.run", "ast"),
        ("запускаю", "запускаю", "ast")
    }
    refs = request(client, "references", root, identifier="run").json()
    assert refs["meaning"].startswith("lexical occurrences")
    assert len(refs["items"]) == 1
    assert refs["items"][0]["line"] == 1
    assert all(s["confidence"] == "syntax" for s in symbols)


def test_javascript_rust_go_heuristics_are_not_claimed_as_semantic(workspace):
    client, root = workspace
    (root / "app.ts").write_text("export function render() {}\nconst service = 3;\n", encoding="utf-8")
    (root / "lib.rs").write_text("pub fn begin() {}\nstruct Event {}\n", encoding="utf-8")
    (root / "go.mod").write_text("module example.com/app\n", encoding="utf-8")
    (root / "main.go").write_text("func Launch() {}\n", encoding="utf-8")
    assert request(client, "refresh", root).status_code == 200
    symbols = request(client, "symbols", root).json()["items"]
    declared = {(s["path"], s["name"]): s for s in symbols}
    assert ("app.ts", "render") in declared
    assert ("app.ts", "service") in declared
    assert ("lib.rs", "begin") in declared
    assert ("main.go", "Launch") in declared
    assert all(s["parser"] == "heuristic" and s["confidence"] == "heuristic" for s in symbols)


def test_embedded_html_js_css_boundaries_and_json_scripts(workspace):
    client, root = workspace
    html = ('<main>Welcome</main>\n'
            '<script>\nexport function render() {}\n</script>\n'
            '<style>\n.panel { color: red; }\n</style>\n'
            '<script type="application/json">{"test": "function doNotIndex() {}"}</script>\n')
    (root / "page.html").write_text(html, encoding="utf-8")
    response = request(client, "outline", root, path="page.html")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["parser"] == "embedded_heuristic"
    assert [x["language"] for x in body["embedded_regions"]] == ["javascript", "css"]
    assert {s["name"] for s in body["symbols"]} == {"render", ".panel"}
    assert all(s["confidence"] == "heuristic" for s in body["symbols"])


def test_markdown_headings_python_invalid_syntax_and_unknowns(workspace):
    client, root = workspace
    (root / "README.md").write_text("# Top level\n## Details\nsome body\n", encoding="utf-8")
    (root / "invalid.py").write_text("def broken(:\n", encoding="utf-8")
    assert request(client, "outline", root, path="README.md").json()["symbols"][0]["name"] == "Top level"
    result = request(client, "outline", root, path="invalid.py").json()
    assert result["parser"] == "invalid_syntax"
    assert result["parse_error"] == "SyntaxError"
    assert result["symbols"] == []


def test_incremental_refresh_detects_edits_and_file_deletions(workspace):
    client, root = workspace
    source = root / "a.py"
    source.write_text("def old_symbol():\n    return 1\n", encoding="utf-8")
    first = request(client, "refresh", root).json()
    assert first["reparsed_files"] == 1 and first["reused_files"] == 0
    second = request(client, "refresh", root).json()
    assert second["reparsed_files"] == 0 and second["reused_files"] == 1
    assert second["generation"] == first["generation"]
    source.write_text("def new_symbol():\n    return 2\n", encoding="utf-8")
    result = request(client, "symbols", root).json()
    assert {s["name"] for s in result["items"]} == {"new_symbol"}
    assert result["generation"] > second["generation"]
    references = request(client, "references", root, identifier="old_symbol").json()
    assert not references["items"], "Old references must be invalidated after edits"
    source.unlink()
    final = request(client, "refresh", root).json()
    assert final["removed_files"] == 1
    assert request(client, "symbols", root).json()["items"] == []


def test_unsaved_buffer_outline_is_never_written_or_persisted(workspace):
    client, root = workspace
    source = root / "main.py"
    source.write_text("def saved():\n    return 2\n", encoding="utf-8")
    raw = source.read_bytes()
    response = request(client, "outline", root, path="main.py",
                       text="def unsaved():\n    return 4\n")
    assert response.status_code == 200
    assert response.json()["unsaved_copy"] is True
    assert response.json()["symbols"][0]["name"] == "unsaved"
    assert source.read_bytes() == raw
    assert {x["name"] for x in request(client, "symbols", root).json()["items"]} == {"saved"}
    assert not (root / ".automoto-index").exists()


def test_secret_generated_folders_binary_and_symlinks_are_excluded(workspace):
    client, root = workspace
    (root / "src").mkdir()
    (root / "src" / "public.py").write_text("def visible():\n    pass\n")
    for folder in (".git", "node_modules", "dist", "generated", "vendor", ".venv"):
        (root / folder).mkdir()
        (root / folder / "secret.py").write_text("def private():\n    pass\n")
    (root / ".env").write_text("def leak():\n    pass\n")
    (root / "secrets.json").write_text('{"client_secret":"PRIVATE"}')
    (root / "certificate.pem").write_text("def leak():\n    pass\n")
    (root / "nonutf.py").write_bytes(b"\xff\xfe\x01")
    (root / "binary.py").write_bytes(b"def leak():\x00\n")
    try:
        (root / "linked.py").symlink_to(root / "src" / "public.py")
    except (OSError, NotImplementedError):
        pass
    data = request(client, "refresh", root).json()
    assert data["indexed_files"] == 1
    assert {s["name"] for s in request(client, "symbols", root).json()["items"]} == {"visible"}
    assert request(client, "outline", root, path=".env").status_code in (403, 404)
    if (root / "linked.py").is_symlink():
        assert request(client, "outline", root, path="linked.py").status_code == 403
    assert request(client, "outline", root, path="generated/secret.py").status_code in (403, 404, 415)


def test_auth_hosted_default_deny_path_validation_and_identifier_validation(workspace, tmp_path):
    client, root = workspace
    (root / "main.py").write_text("def test():\n    pass\n")
    assert not path_allowed("POST", BASE + "/refresh")
    assert not path_allowed("POST", BASE + "/symbols")
    assert not path_allowed("POST", BASE + "/references")
    assert not path_allowed("POST", BASE + "/outline")
    assert client.post(BASE + "/refresh", json={"project": str(root)}).status_code == 403
    assert request(client, "refresh", tmp_path / "outside").status_code == 403
    assert request(client, "symbols", root, path="../escape").status_code == 403
    assert request(client, "references", root, identifier=".*").status_code == 422
    assert request(client, "outline", root, path="missing.py").status_code == 404


def test_bounded_index_and_results_are_explicitly_partial(workspace, monkeypatch):
    client, root = workspace
    monkeypatch.setattr(index, "MAX_FILES", 6)
    for i in range(40):
        (root / f"module{i:03}.py").write_text(f"def item{i:03}():\n    pass\n")
    data = request(client, "refresh", root).json()
    assert data["truncated"] is True
    assert data["indexed_files"] <= 6
    assert data["symbol_count"] <= 6
    assert request(client, "symbols", root).json()["truncated"] is True


def test_deterministic_bounded_result_count_and_unicode(workspace):
    client, root = workspace
    (root / "unicode.py").write_text(
        "def வணக்கம்():\n    return 1\n\ndef أهلا():\n    return 2\n", encoding="utf-8")
    result = request(client, "symbols", root).json()["items"]
    assert {s["name"] for s in result} == {"வணக்கம்", "أهلا"}
    assert all(s["path"] == "unicode.py" for s in result)


def test_oversized_source_is_skipped_not_truncated_silently(workspace):
    client, root = workspace
    (root / "oversized.py").write_bytes(b"def leak():\n" + b"#" * (index.MAX_FILE_BYTES + 10))
    result = request(client, "refresh", root).json()
    assert result["indexed_files"] == 0
    assert result["skipped_files"] == 1
    assert not request(client, "symbols", root).json()["items"]


def test_global_index_memory_budgets_apply_across_files(workspace, monkeypatch):
    client, root = workspace
    monkeypatch.setattr(index, "MAX_GLOBAL_TOKENS", 3)
    monkeypatch.setattr(index, "MAX_GLOBAL_SYMBOLS", 2)
    (root / "a.py").write_text("def alpha():\n    return alpha\n")
    (root / "b.py").write_text("def beta():\n    return beta\n")
    (root / "c.py").write_text("def gamma():\n    return gamma\n")
    response = request(client, "refresh", root).json()
    assert response["indexed_files"] == 3
    assert response["truncated"] is True
    assert response["symbol_count"] <= 2
    assert response["token_count"] <= 3
    assert len(request(client, "symbols", root).json()["items"]) <= 2
