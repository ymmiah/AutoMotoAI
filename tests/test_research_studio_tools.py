"""Research Studio tools pin local sources and stay offline-safe."""

from automoto import hosted, research_discovery, sandbox, tools as tools_mod
from automoto.research_studio_tools import research_query, research_save, research_verify_doi
from automoto.tools import ToolContext, ToolFailed

CTX = ToolContext()


def test_registered_levels_and_offline_filter(monkeypatch):
    tools = tools_mod.build()
    assert tools["research_query"].level == "safe"
    assert tools["research_save"].level == "risky"
    assert tools["research_verify_doi"].level == "safe"
    assert "research_query" in hosted.hosted_tools()
    monkeypatch.setenv("AUTOMOTO_OFFLINE", "1")
    offline = tools_mod.build()
    assert "research_verify_doi" not in offline and "research_query" in offline


def test_query_and_save_call_the_studio(monkeypatch):
    notes = sandbox.default_root() / "uploads" / "notes.md"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text("# Meeting notes\n\n- Ship the beta on Friday\n- Yasin owns the release\n", encoding="utf-8")
    seen = {}
    from automoto import research_studio
    real = research_studio.query_project

    def wrap(body, request):
        seen["sha"] = body.sources[0].sha256
        seen["question"] = body.question
        return real(body, request)

    monkeypatch.setattr(research_studio, "query_project", wrap)
    out = research_query(CTX, "What was agreed about the Friday beta release?", ["uploads/notes.md"], "Friday beta")
    assert seen["sha"] and "Friday" in out and seen["question"].startswith("What was agreed")
    saved = research_save(CTX, "What was agreed about the Friday beta release?", ["uploads/notes.md"], "Friday beta")
    assert "artifacts/research/" in saved and ".research.json" in saved


def test_verify_doi_calls_the_studio(monkeypatch):
    def fake(body, request):
        return {"doi": body.doi, "verified": False, "saved": False}

    monkeypatch.setattr(research_discovery, "verify_doi", fake)
    out = research_verify_doi(CTX, "10.1000/xyz123")
    assert "10.1000/xyz123" in out and "false" in out.lower()


def test_bad_doi_is_the_studios_error():
    try:
        research_verify_doi(CTX, "not-a-doi")
    except ToolFailed as exc:
        assert exc
    else:
        raise AssertionError("expected the studio to reject the DOI")
