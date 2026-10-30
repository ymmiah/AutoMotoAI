"""v5.1 GUI back end: conversations, settings, skills/routines editing and static assets."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from automoto import policy, router, server, settings, tasks
from automoto.conversations import Conversations, make_title
from automoto.loop import AgentResult
from automoto.providers import REGISTRY

H = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture
def c(monkeypatch):
    for p in REGISTRY.values():
        for k in p.env_keys:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    return TestClient(server.app)


# -- conversations store -------------------------------------------------------------
def test_make_title():
    assert make_title("How do I bake bread? Please be quick.") == "How do I bake bread?"
    assert len(make_title("word " * 50)) <= 60
    assert make_title([{"type": "image_url", "image_url": {"url": "data:x"}}]) == "Image question"
    assert make_title([{"type": "text", "text": "what is this"}, {"type": "image_url", "image_url": {"url": "x"}}]) == "What is this"


def test_conversation_crud_title_search_history():
    cv = Conversations()
    a = cv.create()
    assert a["title"] == "New chat"
    cv.add_message(a["id"], "user", "Plan a trip to Lisbon in spring")
    cv.add_message(a["id"], "assistant", "Here is a plan with pastel de nata", {"provider": "nim", "keys": {"nim": "x"}})
    cv.add_message(a["id"], "user", "second message does not retitle")
    b = cv.create(mode="chat")
    cv.add_message(b["id"], "user", "Fix my python code")
    got = cv.get(a["id"])
    assert got["title"] == "Plan a trip to Lisbon in spring"
    assert [m["role"] for m in got["messages"]] == ["user", "assistant", "user"]
    assert "keys" not in got["messages"][1]["meta"]
    assert {x["id"] for x in cv.list()} == {a["id"], b["id"]}
    assert [x["id"] for x in cv.list("nata")] == [a["id"]]   # content search
    assert [x["id"] for x in cv.list("python")] == [b["id"]]
    assert cv.rename(a["id"], "Lisbon") and cv.get(a["id"], with_messages=False)["title"] == "Lisbon"
    assert cv.history(a["id"], limit=2)[-1]["content"] == "second message does not retitle"
    assert cv.delete(b["id"]) and cv.get(b["id"]) is None


def test_slim_meta_drops_thinking_and_big_outputs():
    cv = Conversations()
    a = cv.create()
    evs = [{"type": "thinking"}, {"type": "tool_result", "output": "x" * 5000}, {"type": "final", "text": "ok"}]
    cv.add_message(a["id"], "assistant", "ok", {"events": evs})
    meta = cv.get(a["id"])["messages"][0]["meta"]
    assert [e["type"] for e in meta["events"]] == ["tool_result", "final"]
    assert len(meta["events"][0]["output"]) <= 2100


# -- conversations API ---------------------------------------------------------------
def test_conversation_api(c):
    assert c.get("/api/conversations").status_code == 403
    cid = c.post("/api/conversations", headers=H, json={"mode": "chat"}).json()["id"]
    assert c.get("/api/conversations", headers=H).json()["conversations"][0]["id"] == cid
    assert c.patch(f"/api/conversations/{cid}", headers=H, json={"title": "Renamed"}).json()["title"] == "Renamed"
    assert c.patch(f"/api/conversations/{cid}", headers=H, json={"mode": "bogus"}).status_code in (400, 422)
    assert c.delete(f"/api/conversations/{cid}", headers=H).json()["ok"]
    assert c.get(f"/api/conversations/{cid}", headers=H).status_code == 404


def test_chat_endpoint_saves_both_turns(c, monkeypatch):
    seen = {}

    def fake_ask(msgs, **k):
        seen["msgs"] = msgs
        return router.Answer("Hello cousin", "gemini", "g-1", "chat", [{"provider": "nim", "ok": False}, {"provider": "gemini", "ok": True}])

    monkeypatch.setattr(server, "ask", fake_ask)
    cid = c.post("/api/conversations", headers=H, json={"mode": "chat"}).json()["id"]
    r = c.post("/api/conversations/chat", headers=H, json={"conversation_id": cid, "message": "hi there", "keys": {"nim": "byok-secret"}})
    assert r.status_code == 200 and r.json()["text"] == "Hello cousin"
    assert seen["msgs"][-1] == {"role": "user", "content": "hi there"}
    conv = c.get(f"/api/conversations/{cid}", headers=H).json()
    assert conv["title"] == "Hi there"
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    assert conv["messages"][1]["meta"]["provider"] == "gemini"
    assert "byok-secret" not in json.dumps(conv)
    assert c.post("/api/conversations/chat", headers=H, json={"conversation_id": "nope", "message": "x"}).status_code == 404
    assert c.post("/api/conversations/chat", headers=H, json={"conversation_id": cid, "message": "  "}).status_code == 422


class EchoAgent:
    def __init__(self, **_):
        pass

    def run(self, messages, *, on_event, **_):
        on_event({"type": "model", "step": 1, "provider": "nim", "model": "m", "switched": []})
        on_event({"type": "final", "step": 1, "text": "done"})
        return AgentResult(f"saw {len(messages)} messages", 1, "nim", "m")


def test_agent_with_conversation_saves_assistant(c, monkeypatch):
    monkeypatch.setattr(server, "TASKS", tasks.TaskManager(EchoAgent))
    cid = c.post("/api/conversations", headers=H, json={}).json()["id"]
    r = c.post("/api/agent", headers=H, json={"conversation_id": cid, "message": "first goal", "keys": {"nim": "byok-secret"}}).json()
    assert r["conversation_id"] == cid
    server.TASKS.wait(r["task_id"], 5)
    for _ in range(100):
        conv = c.get(f"/api/conversations/{cid}", headers=H).json()
        if len(conv["messages"]) == 2:
            break
        time.sleep(0.01)
    bot = conv["messages"][1]
    assert bot["content"] == "saw 1 messages" and bot["meta"]["provider"] == "nim" and bot["meta"]["mode"] == "agent"
    assert any(e["type"] == "final" for e in bot["meta"]["events"])
    assert "byok-secret" not in json.dumps(conv)
    assert c.get("/api/tasks", headers=H).json()["tasks"][-1]["conversation_id"] == cid
    r2 = c.post("/api/agent", headers=H, json={"conversation_id": cid, "message": "second"}).json()
    server.TASKS.wait(r2["task_id"], 5)
    assert server.TASKS.get(r2["task_id"]).result["text"] == "saw 3 messages"   # history comes from the DB
    assert c.post("/api/agent", headers=H, json={"conversation_id": "missing", "message": "x"}).status_code == 404
    assert c.post("/api/agent", headers=H, json={"conversation_id": cid}).status_code == 422


# -- settings ------------------------------------------------------------------------
def test_settings_validation_and_never_keys():
    assert settings.load()["theme"] == "dark"
    for bad in ({"api_key": "x"}, {"nim_token": "x"}, {"theme": "pink"}, {"accent": "red"},
                {"approval_mode": "yolo"}, {"provider_order": ["nope"]}, {"surprise": 1}):
        with pytest.raises(settings.SettingsError):
            settings.update(bad)
    out = settings.update({"theme": "light", "accent": "#112233", "provider_order": ["groq", "nim"]})
    assert out["theme"] == "light" and settings.load()["provider_order"] == ["groq", "nim"]
    assert "key" not in settings.path().read_text().lower().replace("keys are", "")


def test_settings_api_and_approval_override(c, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_APPROVAL", "ask")
    assert c.get("/api/settings", headers=H).json()["effective_approval_mode"] == "ask"
    r = c.put("/api/settings", headers=H, json={"approval_mode": "readonly"})
    assert r.status_code == 200 and r.json()["effective_approval_mode"] == "readonly"
    assert policy.mode() == "readonly"
    assert c.put("/api/settings", headers=H, json={"openai_api_key": "sk-x"}).status_code == 400
    c.put("/api/settings", headers=H, json={"approval_mode": None})
    assert policy.mode() == "ask"


def test_provider_order_changes_plan(monkeypatch):
    for p in REGISTRY.values():
        for k in p.env_keys:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "a")
    monkeypatch.setenv("GROQ_API_KEY", "b")
    settings.update({"provider_order": ["groq", "nim"]})
    order = [s.id for s in router.plan_order(need_vision=False, prefer=None, task="general")]
    assert order[0] == "groq"
    settings.update({"provider_order": ["nim", "groq"]})
    order = [s.id for s in router.plan_order(need_vision=False, prefer=None, task="general")]
    assert order[0] == "nim"


# -- skills & routines editing -----------------------------------------------------------
def test_skill_save_view_delete_api(c):
    assert c.put("/api/skills/Bad Name", headers=H, json={"body": "x"}).status_code == 400
    r = c.put("/api/skills/my-skill", headers=H, json={"body": "# Do it\n1. step", "description": "Use when testing"})
    assert r.status_code == 200 and r.json()["bundled"] is False
    names = {s["name"]: s for s in c.get("/api/skills", headers=H).json()["skills"]}
    assert names["my-skill"]["description"] == "Use when testing" and names["research-brief"]["bundled"]
    assert "1. step" in c.get("/api/skills/my-skill", headers=H).json()["body"]
    assert c.delete("/api/skills/my-skill", headers=H).json()["ok"]
    assert not c.delete("/api/skills/research-brief", headers=H).json()["ok"]   # bundled stays
    assert c.get("/api/skills/my-skill", headers=H).status_code == 404


def test_routine_patch_and_run_records_result(c, monkeypatch):
    monkeypatch.setattr(server, "TASKS", tasks.TaskManager(EchoAgent))
    c.post("/api/routines", headers=H, json={"name": "news", "schedule": "every 1h", "prompt": "p"})
    r = c.patch("/api/routines/news", headers=H, json={"enabled": False, "schedule": "0 8 * * *"}).json()
    assert r["enabled"] is False and r["schedule"] == "0 8 * * *"
    assert c.patch("/api/routines/news", headers=H, json={"schedule": "whenever"}).status_code == 400
    assert c.patch("/api/routines/ghost", headers=H, json={"enabled": True}).status_code == 404
    tid = c.post("/api/routines/news/run", headers=H).json()["task_id"]
    server.TASKS.wait(tid, 5)
    for _ in range(100):
        rt = c.get("/api/routines", headers=H).json()["routines"][0]
        if rt["last_result"]:
            break
        time.sleep(0.01)
    assert rt["last_result"] == "saw 1 messages" and rt["last_status"] == "done"


# -- static GUI ------------------------------------------------------------------------
def test_gui_assets_and_csp(c):
    c.get("/?launch=" + server.new_launch_token())
    r = c.get("/")
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-eval" not in csp and "frame-ancestors 'none'" in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "<script>" not in r.text   # no inline scripts
    for path in ("/static/app.js", "/static/app.css", "/static/icons.js", "/static/theme-boot.js",
                 "/static/vendor/marked.min.js", "/static/vendor/purify.min.js", "/static/vendor/highlight.min.js",
                 "/static/vendor/hljs-dark.css", "/static/vendor/hljs-light.css"):
        assert c.get(path).status_code == 200, path
    js = c.get("/static/app.js").text
    assert "sessionStorage" in js and "localStorage.setItem(\"automoto_keys\"" not in js
    assert "Student of BCU, BSc Computing Top-Up (Hons)" in js


def test_help_guide_link_is_a_safe_external_link(c):
    import re
    c.get("/?launch=" + server.new_launch_token())
    html = c.get("/").text
    m = re.search(r'<a href="([^"]+)" id="helpLink"([^>]*)>', html)
    assert m, "Help / Guide link missing from the sidebar"
    assert m.group(1) == "https://ymmiah.github.io/AutoMotoAI/GUI-GUIDE.html"
    assert 'target="_blank"' in m.group(2) and "noopener" in m.group(2)
    js = c.get("/static/app.js").text
    assert 'const GUIDE_URL = "https://ymmiah.github.io/AutoMotoAI/GUI-GUIDE.html"' in js and '"_blank", "noopener"' in js


def test_gui_guide_images_exist():
    import pathlib
    import re
    docs = pathlib.Path(__file__).resolve().parent.parent / "docs"
    text = (docs / "GUI-GUIDE.md").read_text(encoding="utf-8")
    imgs = re.findall(r'\(gui-guide/([^)]+)\)|src="gui-guide/([^"]+)"', text)
    assert len(imgs) >= 30
    for a, b in imgs:
        assert (docs / "gui-guide" / (a or b)).is_file(), a or b
