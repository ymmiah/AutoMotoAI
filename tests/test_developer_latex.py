"""V9: real multi-file LaTeX source analysis, safe templates and guarded LSP opt-in."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from automoto import developer_latex as tex, developer_lsp as lsp, sandbox, server
from automoto.hosted import path_allowed

BASE = "/api/developer/studio/latex"
H = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "latex-v9"
    root.mkdir(parents=True)
    (root / "chapters").mkdir()
    (root / "main.tex").write_text(
        "\\documentclass{report}\n"
        "\\begin{document}\n"
        "\\chapter{Overview}\\label{chap:overview}\n"
        "See \\ref{eq:one} and \\cite{smith2026}.\n"
        "\\input{chapters/methods}\n"
        "\\bibliography{sources}\n"
        "\\end{document}\n", encoding="utf-8",
    )
    (root / "chapters" / "methods.tex").write_text(
        "\\section{Methods}\\label{sec:methods}\n"
        "\\begin{equation}\\label{eq:one}\n"
        "  x=1\n\\end{equation}\n"
        "Refer to \\ref{chap:overview}.\n", encoding="utf-8",
    )
    (root / "sources.bib").write_text(
        "@article{smith2026,\n title = {A demonstrative, unverified source},\n year = {2026}\n}\n",
        encoding="utf-8",
    )
    yield TestClient(server.app), root, tmp_path


def analyse(client, root, **overrides):
    return client.post(BASE + "/analyse", headers=H,
                       json={"project": str(root), "main": "main.tex", **overrides})


def complete(client, root, **kw):
    return client.post(BASE + "/complete", headers=H,
                       json={"project": str(root), "main": "main.tex", **kw})


def test_real_multi_file_thesis_cross_references_and_bibliography(project):
    client, root, _ = project
    before = {p.relative_to(root).as_posix(): p.read_bytes()
              for p in root.rglob("*") if p.is_file()}
    r = analyse(client, root)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["files"] == ["chapters/methods.tex", "main.tex"]
    assert data["file_count"] == 2
    assert data["analysis_kind"] == "bounded-static-lexical-not-compiled"
    assert data["compilation_verified"] is False
    assert data["lsp_diagnostics_included"] is False
    assert data["source_executed"] is False and data["source_modified"] is False
    assert not data["truncated"]
    assert data["diagnostics"] == []
    assert {x["value"] for x in data["labels"]} == {
        "chap:overview", "sec:methods", "eq:one"
    }
    assert {x["value"] for x in data["references"]} == {
        "eq:one", "chap:overview"
    }
    assert {x["value"] for x in data["bibliography_keys"]} == {"smith2026"}
    assert {x["value"] for x in data["citations"]} == {"smith2026"}
    assert {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()} == before


def test_unsaved_current_buffer_revalidates_other_files_without_disk_write(project):
    client, root, _ = project
    before = (root / "chapters/methods.tex").read_bytes()
    new = "\\section{Changed}\\label{sec:changed}\nSee \\ref{eq:missing}.\n"
    r = analyse(client, root, active_path="chapters/methods.tex", active_text=new)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["unsaved_buffer_used"] is True
    assert "eq:one" not in {s["value"] for s in data["labels"]}
    assert {d["code"] for d in data["diagnostics"]} == {"unresolved-ref"}
    assert {d["message"] for d in data["diagnostics"]} == {
        "No local label definition for eq:one",
        "No local label definition for eq:missing",
    }
    assert (root / "chapters/methods.tex").read_bytes() == before
    assert not analyse(client, root).json()["diagnostics"]


def test_comments_escaped_percent_verbatim_and_inline_verbs_are_ignored(project):
    client, root, _ = project
    f = root / "main.tex"
    f.write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "% \\ref{ghost}% ignored\n"
        "\\verb|\\cite{phantom}|\n"
        "\\begin{verbatim}\n"
        " \\label{fake} \\cite{absent}\n"
        "\\end{verbatim}\n"
        "\\section{Valid}\\label{real}\n"
        "Value \\% literal percent. \\ref{real}\n"
        "\\end{document}\n", encoding="utf-8")
    data = analyse(client, root).json()
    assert data["diagnostics"] == []
    assert [x["value"] for x in data["labels"]] == ["real"]
    assert [x["value"] for x in data["references"]] == ["real"]
    assert not data["citations"]


def test_missing_and_duplicate_labels_citations_and_include_are_reported(project):
    client, root, _ = project
    file = root / "chapters/methods.tex"
    file.write_text("\\label{chap:overview}\\ref{badref}\\cite{badbib}\\input{missing}\n",
                    encoding="utf-8")
    data = analyse(client, root).json()
    types = {x["code"] for x in data["diagnostics"]}
    assert {"duplicate-label", "unresolved-ref", "unresolved-citation",
            "missing-include"} <= types
    assert any(i["path"] == "chapters/methods.tex" for i in data["diagnostics"])
    assert data["source_modified"] is False


def test_security_blocks_symlink_outside_root_and_generated_paths(project, tmp_path):
    client, root, _ = project
    (root / "main.tex").write_text(
        "\\input{../outside}\\input{chapters/linked}\\input{generated/internal}\n"
        "\\input{chapters/../../outside}\n\\bibliography{../../secrets}\n",
        encoding="utf-8")
    (root / "generated").mkdir()
    (root / "generated" / "internal.tex").write_text("\\label{private}\n")
    outside = tmp_path / "outside.tex"
    outside.write_text("\\label{external}\n")
    secret = tmp_path / "secrets.bib"
    secret.write_text("@article{supersecret,\n}\n")
    link = root / "chapters" / "linked.tex"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pass
    data = analyse(client, root).json()
    assert data["files"] == ["main.tex"]
    assert "external" not in repr(data)
    assert "supersecret" not in repr(data)
    assert "private" not in {x["value"] for x in data["labels"]}
    assert {x["code"] for x in data["diagnostics"]} >= {
        "unsafe-include", "unsafe-bibliography"
    }


def test_relative_internal_parent_include_is_allowed(project):
    client, root, _ = project
    (root / "chapters" / "methods.tex").write_text(
        "\\input{../extras/result}\n\\label{sec:methods}\n",
        encoding="utf-8")
    (root / "extras").mkdir()
    (root / "extras" / "result.tex").write_text("\\label{sec:result}\n",
                                                 encoding="utf-8")
    data = analyse(client, root).json()
    assert "extras/result.tex" in data["files"]
    assert "sec:result" in {x["value"] for x in data["labels"]}


def test_cross_reference_revalidates_after_saved_file_change(project):
    client, root, _ = project
    first = analyse(client, root).json()
    assert not first["diagnostics"]
    file = root / "chapters" / "methods.tex"
    file.write_text("\\section{Revised}\\label{eq:two}\n", encoding="utf-8")
    updated = analyse(client, root).json()
    assert "unresolved-ref" in {x["code"] for x in updated["diagnostics"]}
    assert any("eq:one" in d["message"] for d in updated["diagnostics"])
    file.unlink()
    missing = analyse(client, root).json()
    assert "missing-include" in {x["code"] for x in missing["diagnostics"]}


def test_safe_command_environment_label_and_citation_completions(project):
    client, root, _ = project
    for kind, prefix, target in [
        ("command", "sect", "\\section"), ("environment", "alig", "align"),
        ("label", "chap:", "chap:overview"), ("citation", "smith", "smith2026")
    ]:
        r = complete(client, root, kind=kind, prefix=prefix)
        assert r.status_code == 200, r.text
        data = r.json()
        assert target in {x["label"] for x in data["items"]}
        assert not data["execution_required"]
        assert data["source_modified"] is False
    assert len(complete(client, root, kind="auto").json()["items"]) <= tex.MAX_COMPLETIONS


def test_original_thesis_and_article_templates_are_previews_only(project):
    client, root, _ = project
    catalog = client.get(BASE + "/templates", headers=H)
    assert catalog.status_code == 200
    assert {i["id"] for i in catalog.json()["templates"]} == {"thesis", "article"}
    originals = {p.name for p in root.iterdir()}
    for variant in ("thesis", "article"):
        response = client.post(BASE + "/template-preview", headers=H, json={"id": variant})
        assert response.status_code == 200
        result = response.json()
        assert result["applied"] is False
        assert result["writes_project"] is False
        assert all(x["path"].endswith((".tex", ".bib")) for x in result["files"])
        assert (result["id"] == "thesis") == any(
            x["path"] == "chapters/introduction.tex" for x in result["files"])
    assert {p.name for p in root.iterdir()} == originals


def test_unsupported_and_invalid_paths_fail_closed(project):
    client, root, tmp = project
    for main in ("../outside.tex", ".git/secret.tex", "missing.tex",
                 "main.bib", "/etc/passwd"):
        assert analyse(client, root, main=main).status_code in (403, 404, 422)
    assert analyse(client, root, active_text="unsaved without path").status_code == 422
    assert analyse(client, root, active_path="../unsafe.tex",
                   active_text="\\label{x}").status_code in (403, 422)
    assert client.post(BASE + "/analyse", json={
        "project": str(root), "main": "main.tex"}).status_code == 403


def test_hosted_mode_is_default_denied_and_texlab_never_starts_on_analysis(project):
    client, root, _ = project
    assert path_allowed("POST", BASE + "/analyse") is False
    assert path_allowed("POST", BASE + "/complete") is False
    assert path_allowed("GET", BASE + "/templates") is False
    assert path_allowed("POST", BASE + "/template-preview") is False
    assert lsp.SERVER_COMMANDS["latex"] == ("texlab",)
    initial = len(lsp.SESSIONS)
    assert analyse(client, root).status_code == 200
    assert len(lsp.SESSIONS) == initial


def test_bounded_multifile_scan_marked_partial(project, monkeypatch):
    client, root, _ = project
    monkeypatch.setattr(tex, "MAX_FILES", 1)
    result = analyse(client, root).json()
    assert result["file_count"] == 1
    assert result["truncated"] is True
    assert result["compilation_verified"] is False


def test_utf16_reference_location_after_emoji(project):
    client, root, _ = project
    file = root / "main.tex"
    file.write_text("Text 🙂 then \\ref{missing}\n", encoding="utf-8")
    data = analyse(client, root).json()
    reference = data["references"][0]
    expected = len("Text 🙂 then \\ref{".encode("utf-16-le")) // 2
    assert reference["character"] == expected
    assert data["diagnostics"][0]["code"] == "unresolved-ref"


def test_texlab_is_only_optional_explicit_lsp_server(project):
    client, root, _ = project
    r = client.get("/api/developer/studio/lsp/servers", headers=H,
                   params={"project": str(root)})
    assert r.status_code == 200
    entry = next(x for x in r.json()["servers"] if x["language"] == "latex")
    assert entry["binary"] == "texlab"
    assert entry["requires_explicit_start"] is True
    assert r.json()["automatic_start"] is False
