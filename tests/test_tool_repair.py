"""Broken tool calls: lenient parsing, corrective nudges, argument repair and office_read on uploads."""

import json

import pytest

from automoto import sandbox, tools as tools_mod, toolcalls as tc
from automoto.loop import Agent
from automoto.memory import Memory
from automoto.providers import REGISTRY

FILE = "Yasin_Miah_Viva1_Team_Leader.pptx"
YASIN_REPLY = ("I apologize for the confusion. I attempted to read the PowerPoint file using the office_read tool, "
               "but it appears there was an issue with the function call. Let me try again to read the file and "
               f"provide you with a proper summary.office_readpathuploads/{FILE}")


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    for p in REGISTRY.values():
        for k in p.env_keys:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AI_PROVIDER", "auto")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")


@pytest.fixture
def deck():
    tools = tools_mod.build()
    ctx = tools_mod.ToolContext(memory=Memory(), skills={})
    ok, out = tools_mod.call(tools["office_create_pptx"], ctx, {"path": f"uploads/{FILE}", "spec": {"slides": [
        {"layout": "title", "title": "Viva 1", "subtitle": "Team leader"},
        {"layout": "bullets", "title": "My role", "bullets": ["Planned sprints", "Ran stand-ups"], "notes": "be brief"}]}})
    assert ok, out
    return tools, ctx


def scripted(*replies, log=None):
    seq = list(replies)

    def t(spec, messages, model, key, *, tools, native, **_):
        if log is not None:
            log.append({"provider": spec.id, "model": model, "native": native, "messages": messages})
        return seq.pop(0)
    return t


def agent(t):
    return Agent(memory=Memory(), skills={}, transport=t)


SPECS = tc.specs_from_schemas([t.schema() for t in tools_mod.build().values()])


# -- lenient parsing -------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    YASIN_REPLY,
    f'Let me read it.\noffice_read(path="uploads/{FILE}")',
    f"office_read(uploads/{FILE})",
    f'office_read({{"path": "uploads/{FILE}"}})',
    f'<invoke name="office_read"><parameter name="path">uploads/{FILE}</parameter></invoke>',
    f'<function=office_read>{{"path": "uploads/{FILE}"}}</function>',
    f"<office_read><path>uploads/{FILE}</path></office_read>",
    f'Sure. {{"name": "office_read", "parameters": {{"path": "uploads/{FILE}"}}}}',
    f'```json\n{{"tool_name": "office_read", "args": {{"path": "uploads/{FILE}"}}}}\n```',
    f'```tool\n{{"function": {{"name": "office_read", "arguments": "{{\\"path\\": \\"uploads/{FILE}\\"}}"}}}}\n```',
    f"office_read path: uploads/{FILE}",
])
def test_loose_shapes_parse_to_one_call(text):
    clean, calls = tc.parse_loose_calls(text, SPECS)
    assert len(calls) == 1 and calls[0]["name"] == "office_read"
    assert calls[0]["arguments"]["path"] == f"uploads/{FILE}"
    assert "office_read" not in clean or "using the office_read tool" in clean


@pytest.mark.parametrize("text", [
    "I read the file with office_read. It has two slides: Viva 1 and My role.",
    "Here is your summary: the deck has 2 slides.",
    "Use office_read to read documents.",
])
def test_normal_answers_are_left_alone(text):
    assert tc.parse_loose_calls(text, SPECS) == (text, [])
    assert tc.looks_like_failed_call(text, set(SPECS)) == ""


def test_ambiguous_calls_are_not_run():
    # write_file needs path AND content: a glued "write_filepathx" is not enough to run it
    assert tc.parse_loose_calls("write_filepathscratch/x.txt", SPECS)[1] == []
    assert tc.looks_like_failed_call("write_filepathscratch/x.txt", set(SPECS))


def test_failed_call_detection_and_stripping():
    names = set(SPECS)
    assert tc.looks_like_failed_call("I'll try again now.", names)
    assert tc.looks_like_failed_call('```tool\n{"name": "office_read", broken', names)
    assert tc.strip_failed_call(YASIN_REPLY, names).endswith("proper summary.")
    assert "office_readpath" not in tc.strip_failed_call(YASIN_REPLY, names)


# -- the agent loop ---------------------------------------------------------------------
def test_yasins_reply_runs_the_tool_instead_of_ending(deck):
    log = []
    res = agent(scripted((YASIN_REPLY, []), ("The deck has 2 slides: Viva 1 and My role.", []), log=log)).run(
        f"summarise uploads/{FILE}")
    assert res.text == "The deck has 2 slides: Viva 1 and My role." and res.stopped == "done"
    results = [e for e in res.events if e["type"] == "tool_result"]
    assert results and results[0]["name"] == "office_read" and results[0]["ok"]
    assert "Viva 1" in results[0]["output"]
    assert any(e["type"] == "repaired" for e in res.events)
    assert "office_readpath" not in " ".join(e.get("text", "") for e in res.events if e["type"] in ("say", "final"))


def test_promise_without_call_gets_a_corrective_nudge(deck):
    log = []
    res = agent(scripted(("I'll try again to read the file now.", []),
                         ("", [{"id": "c1", "name": "office_read", "arguments": {"path": f"uploads/{FILE}"}}]),
                         ("Two slides.", []), log=log)).run("summarise my deck")
    assert res.text == "Two slides."
    nudge = [m for m in log[1]["messages"] if m.get("role") == "user"][-1]["content"]
    assert "NOT executed" in nudge and "tool-calling interface" in nudge
    assert any(e["type"] == "nudge" for e in res.events)


def test_text_mode_nudge_shows_the_json_format(monkeypatch, deck):
    monkeypatch.setenv("AUTOMOTO_TOOL_MODE", "text")
    log = []
    agent(scripted(('office_read{"path" "broken', ""), ("done", []), log=log)).run("summarise")
    sent = json.dumps(log[1]["messages"])
    assert "NOT executed" in sent and "```tool" in sent and "office_read" in sent


def test_never_shows_a_raw_call_after_retries_run_out(deck):
    bad = ("Let me try again. write_filepathscratch/x.txt", [])
    res = agent(scripted(*[bad] * 8)).run("write it")
    assert "write_filepath" not in res.text
    assert "broken format" in res.text and res.stopped == "done"
    assert sum(e["type"] == "nudge" for e in res.events) == 3


# -- argument repair and error feedback ----------------------------------------------------
@pytest.mark.parametrize("args", [
    {"path": f"uploads/{FILE}"},
    {"path": f"/uploads/{FILE}"},
    {"path": f"uploads\\{FILE}"},
    {"path": FILE},
    {"file_path": f"uploads/{FILE}"},
    {"filename": f"uploads/{FILE}"},
    {"path": f"uploads/{FILE}", "max_rows": "60"},
    {"path": f"`uploads/{FILE}`"},
])
def test_office_read_works_for_uploads_paths(deck, args):
    tools, ctx = deck
    ok, out = tools_mod.call(tools["office_read"], ctx, args)
    assert ok, out
    assert "Viva 1" in out and "My role" in out and "be brief" in out


def test_path_repair_never_leaves_the_workspace(deck):
    tools, ctx = deck
    ok, out = tools_mod.call(tools["office_read"], ctx, {"path": "/etc/passwd"})
    assert not ok and ("outside" in out or "off limits" in out)
    assert tools_mod.repair_args(tools["office_read"], {"path": "/etc/hosts"})["path"] == "/etc/hosts"


@pytest.mark.parametrize("name,spec", [
    ("report.docx", "office_create_docx"), ("data.xlsx", "office_create_xlsx")])
def test_office_read_docx_xlsx_from_uploads(deck, name, spec):
    tools, ctx = deck
    body = ({"blocks": [{"type": "heading", "text": "Hello doc"}, {"type": "paragraph", "text": "Body text"}]}
            if name.endswith("docx") else {"sheets": [{"name": "S", "rows": [["a", "b"], [1, 2]]}]})
    ok, out = tools_mod.call(tools[spec], ctx, {"path": f"uploads/{name}", "spec": body})
    assert ok, out
    ok, out = tools_mod.call(tools["office_read"], ctx, {"file": name})
    assert ok, out


def test_office_read_pdf_from_uploads(deck):
    tools, ctx = deck
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(200, 200)
    with open(sandbox.root() / "uploads" / "blank.pdf", "wb") as f:
        w.write(f)
    ok, out = tools_mod.call(tools["office_read"], ctx, {"path": "/uploads/blank.pdf"})
    assert ok, out


def test_tool_errors_tell_the_model_how_to_fix_the_call(deck):
    log = []
    res = agent(scripted(("", [{"id": "c1", "name": "office_read", "arguments": {"pathh": 1, "x": 2}}]),
                         ("", [{"id": "c2", "name": "ofice_read", "arguments": {}}]),
                         ("ok", []), log=log)).run("read")
    tool_msgs = [m["content"] for m in log[-1]["messages"] if m.get("role") == "tool"]
    assert "missing argument(s): path" in tool_msgs[0] and '"name": "office_read"' in tool_msgs[0]
    assert "uploads/" in tool_msgs[0]
    assert "Did you mean: office_read" in tool_msgs[1]
    assert res.text == "ok"


# -- Gemini thought signatures --------------------------------------------------------------
def test_gemini_signature_round_trip_and_placeholder():
    class Fn:
        name = "office_read"
        arguments = json.dumps({"path": "uploads/a.pptx"})

    class Call:
        id = "c1"
        function = Fn()
        extra_content = {"google": {"thought_signature": "sig123"}}

    class Msg:
        content = ""
        tool_calls = [Call()]

    _, calls = tc.parse_openai_message(Msg())
    calls[0]["provider"] = "gemini"
    hist = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "", "tool_calls": calls},
            {"role": "tool", "tool_call_id": "c1", "name": "office_read", "content": "x"}]
    g = tc.render_openai(hist, provider="gemini")
    assert g[1]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "sig123"
    n = tc.render_openai(hist, provider="nim")
    assert "extra_content" not in n[1]["tool_calls"][0]  # other providers never get the field
    calls[0]["provider"] = "nim"  # a call made by NIM, replayed to Gemini after failover
    g2 = tc.render_openai(hist, provider="gemini")
    assert g2[1]["tool_calls"][0]["extra_content"] == tc.GEMINI_SKIP_SIGNATURE


def test_gui_upload_then_agent_summary(deck):
    """Upload through the API like the GUI does, then the agent reads uploads/<name> (even if the
    model writes the call in a broken format)."""
    import base64

    from fastapi.testclient import TestClient

    from automoto import server

    data = (sandbox.root() / "uploads" / FILE).read_bytes()
    c = TestClient(server.app)
    r = c.post("/api/files/upload", headers={"X-AutoMoto-Token": server.SESSION_TOKEN},
               json={"name": "Viva Copy.pptx", "data": base64.b64encode(data).decode()})
    assert r.status_code == 200, r.text
    reply = "Let me read it.office_readpathuploads/Viva Copy.pptx"
    res = agent(scripted((reply, []), ("Summary: Viva 1, My role.", []))).run("summarise uploads/Viva Copy.pptx")
    out = next(e for e in res.events if e["type"] == "tool_result")
    assert out["ok"] and "Viva 1" in out["output"] and res.text.startswith("Summary")
