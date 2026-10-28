"""Local web API + browser UI for AutoMoto AI v5 (the shared "brain" for every client).

Security model
--------------
* Binds to 127.0.0.1 by default.
* Browser requests must carry the per-launch session token that is injected into the
  served page (``X-AutoMoto-Token``), so other websites can't drive your local API.
* Non-loopback clients (e.g. the mobile app on your LAN) must send
  ``Authorization: Bearer $AUTOMOTO_API_TOKEN``; without that env var remote access is off.
* Desktop actions and screen capture are loopback-only and always need ``confirmed: true``.
* BYOK keys sent by a client are used for that request / agent task only - never stored,
  logged or echoed back in task events.
* Agent runs are background tasks; risky tool calls pause until approved via
  ``POST /api/tasks/{id}/approve``.
"""

from __future__ import annotations

import base64
import hmac
import ipaddress
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from automoto import APP_NAME, CODENAME, __version__, config, policy, sandbox
from automoto import mcp as mcp_mod
from automoto import routines as routines_mod
from automoto import settings as settings_mod
from automoto.conversations import Conversations
from automoto import skills as skills_mod
from automoto import tools as tools_mod
from automoto.agent import split_actions, system_prompt
from automoto.desktop import OS_LABEL, TOOLS, execute
from automoto.loop import Agent
from automoto.memory import Memory
from automoto.router import AllProvidersFailed, NoProviderError, ask, classify_task, recommend_provider, status
from automoto.tasks import TaskManager

WEB_DIR = Path(__file__).parent / "web"
SESSION_TOKEN = secrets.token_urlsafe(24)
MAX_IMAGES = 4

MCP_TOOLS: list[tools_mod.Tool] = []
MCP_ERRORS: list[str] = []


def _agent_factory(desktop: bool = False, client: str = "web") -> Agent:
    return Agent(desktop=desktop, extra_tools=MCP_TOOLS, client=client)


TASKS = TaskManager(_agent_factory)
SCHEDULER: routines_mod.Scheduler | None = None


def routine_runner(prompt: str) -> dict[str, Any]:
    task = TASKS.start([{"role": "user", "content": prompt}], source="routine", auto_deny=True,
                       agent_kwargs={"desktop": False, "client": "routine"})
    done = TASKS.wait(task.id, timeout=1800)
    res = (done.result if done else None) or {"text": "timed out", "stopped": "error"}
    return {**res, "task_id": task.id}


app = FastAPI(title=f"{APP_NAME} {CODENAME}", version=__version__, docs_url="/api/docs", redoc_url=None)


def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if host in ("testclient", "localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _authorise(request: Request, *, local_only: bool = False) -> None:
    if _is_loopback(request):
        tok = request.headers.get("x-automoto-token", "")
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        api_tok = config.env("AUTOMOTO_API_TOKEN")
        if hmac.compare_digest(tok, SESSION_TOKEN) or (api_tok and hmac.compare_digest(bearer, api_tok)):
            return
        raise HTTPException(403, "missing session token (open the UI from this server)")
    if local_only:
        raise HTTPException(403, "desktop tools are only available on this computer")
    api_tok = config.env("AUTOMOTO_API_TOKEN")
    bearer = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not api_tok or not hmac.compare_digest(bearer, api_tok):
        raise HTTPException(401, "remote access needs Authorization: Bearer <AUTOMOTO_API_TOKEN>")


class ChatIn(BaseModel):
    messages: list[dict[str, Any]] = Field(..., min_length=1, max_length=60)
    prefer: str | None = None
    need_vision: bool = False
    keys: dict[str, str] | None = None  # BYOK, per request only
    client: str = "web"  # web | desktop | mobile | cli


class RecommendIn(BaseModel):
    task: str = ""
    has_image: bool = False
    keys: dict[str, str] | None = None


class ExecuteIn(BaseModel):
    action: dict[str, Any]
    confirmed: bool = False


class ScreenIn(BaseModel):
    question: str = "What's on my screen? Summarise it and point out anything I should act on."
    prefer: str | None = None
    keys: dict[str, str] | None = None
    confirmed: bool = False


def _count_images(messages: list[dict[str, Any]]) -> int:
    n = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            n += sum(1 for p in c if isinstance(p, dict) and p.get("type") == "image_url")
    return n


def _run_chat(messages, *, prefer, need_vision, keys, client, desktop: bool) -> dict[str, Any]:
    msgs = [m for m in messages if m.get("role") in ("user", "assistant")]
    try:
        ans = ask(msgs, need_vision=need_vision, prefer=prefer, keys=keys,
                  system=system_prompt(desktop=desktop, client=client))
    except NoProviderError as exc:
        raise HTTPException(400, str(exc)) from None
    except AllProvidersFailed as exc:
        return JSONResponse(status_code=502, content={"error": str(exc), "tried": exc.tried})  # type: ignore[return-value]
    text, actions = split_actions(ans.text) if desktop else (ans.text, [])
    return {**ans.as_dict(), "text": text, "actions": actions}


class AgentIn(BaseModel):
    messages: list[dict[str, Any]] | None = Field(None, max_length=60)
    conversation_id: str | None = None  # GUI: server keeps the history
    message: Any = None  # GUI: the new user message (str or content parts)
    prefer: str | None = None
    keys: dict[str, str] | None = None  # BYOK, kept only for the task's lifetime
    client: str = "web"
    max_steps: int | None = Field(None, ge=1, le=50)


class ChatConvIn(BaseModel):
    conversation_id: str
    message: Any
    prefer: str | None = None
    keys: dict[str, str] | None = None
    client: str = "web"


class ConvIn(BaseModel):
    title: str = "New chat"
    mode: str = "agent"


class ConvPatch(BaseModel):
    title: str | None = None
    mode: str | None = None


class SkillIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=50_000)
    description: str = ""


class RoutinePatch(BaseModel):
    schedule: str | None = None
    prompt: str | None = None
    enabled: bool | None = None


class ApproveIn(BaseModel):
    call_id: str
    approve: bool


class FactIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    tags: str = ""


class RoutineIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    schedule: str = Field(..., min_length=3, max_length=80)
    prompt: str = Field(..., min_length=1, max_length=4000)


CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "connect-src 'self'; font-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
       "form-action 'self'")


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    token = SESSION_TOKEN if _is_loopback(request) else ""
    html = html.replace("__AUTOMOTO_TOKEN__", token).replace("__AUTOMOTO_VERSION__", __version__)
    return HTMLResponse(html, headers={"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff",
                                       "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "app": APP_NAME, "codename": CODENAME, "version": __version__, "os": OS_LABEL}


@app.get("/api/status")
def get_status(request: Request) -> dict[str, Any]:
    _authorise(request)
    return {**status(), "version": __version__, "os": OS_LABEL,
            "desktop": config.desktop_enabled() and _is_loopback(request),
            "tools": [{"name": t.name, "risk": t.risk, "args": list(t.args)} for t in TOOLS.values()]}


@app.post("/api/status")
def post_status(body: RecommendIn, request: Request) -> dict[str, Any]:
    _authorise(request)
    return {**status(body.keys), "version": __version__}


@app.post("/api/recommend")
def recommend(body: RecommendIn, request: Request) -> dict[str, Any]:
    _authorise(request)
    return {"task": classify_task(body.task, has_image=body.has_image),
            "provider": recommend_provider(body.task, has_image=body.has_image, keys=body.keys),
            "provider_any": recommend_provider(body.task, has_image=body.has_image, only_configured=False)}


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    _authorise(request)
    if _count_images(body.messages) > MAX_IMAGES:
        raise HTTPException(413, f"max {MAX_IMAGES} images per request")
    desktop = config.desktop_enabled() and _is_loopback(request) and body.client != "mobile"
    return _run_chat(body.messages, prefer=body.prefer, need_vision=body.need_vision,
                     keys=body.keys, client=body.client, desktop=desktop)


# -- v5 agent --------------------------------------------------------------------
@app.post("/api/agent")
def agent_start(body: AgentIn, request: Request) -> dict[str, Any]:
    _authorise(request)
    desktop = config.desktop_enabled() and _is_loopback(request) and body.client != "mobile"
    conv_id, on_done = None, None
    if body.conversation_id:
        convs = Conversations()
        if not convs.get(body.conversation_id, with_messages=False):
            raise HTTPException(404, "no such conversation")
        if body.message is None:
            raise HTTPException(422, "message is required with conversation_id")
        _check_message(body.message)
        convs.add_message(body.conversation_id, "user", body.message)
        msgs = convs.history(body.conversation_id)
        conv_id = body.conversation_id
        on_done = _saver(conv_id)
    else:
        if not body.messages:
            raise HTTPException(422, "messages or conversation_id is required")
        msgs = [m for m in body.messages if m.get("role") in ("user", "assistant")]
    if _count_images(msgs) > MAX_IMAGES:
        raise HTTPException(413, f"max {MAX_IMAGES} images per request")
    task = TASKS.start(msgs, source=body.client, keys=body.keys, prefer=body.prefer, max_steps=body.max_steps,
                       agent_kwargs={"desktop": desktop, "client": body.client},
                       conversation_id=conv_id, on_done=on_done)
    return {"task_id": task.id, "status": task.status, "conversation_id": conv_id}


def _check_message(message: Any) -> None:
    if isinstance(message, str):
        if not message.strip():
            raise HTTPException(422, "empty message")
        return
    if not isinstance(message, list) or not message:
        raise HTTPException(422, "message must be text or a list of content parts")
    if _count_images([{"content": message}]) > MAX_IMAGES:
        raise HTTPException(413, f"max {MAX_IMAGES} images per request")


def _saver(conv_id: str):
    def save(task) -> None:
        res = task.result or {}
        meta = {"provider": res.get("provider"), "model": res.get("model"), "steps": res.get("steps"),
                "stopped": res.get("stopped") or task.status, "task_id": task.id, "mode": "agent",
                "events": list(task.events)}
        Conversations().add_message(conv_id, "assistant", res.get("text") or "(no answer)", meta)
    return save


@app.get("/api/tasks")
def tasks_list(request: Request) -> dict[str, Any]:
    _authorise(request)
    return {"tasks": TASKS.list()}


@app.get("/api/tasks/{task_id}")
def task_get(task_id: str, request: Request, since: int = 0) -> dict[str, Any]:
    _authorise(request)
    t = TASKS.get(task_id)
    if not t:
        raise HTTPException(404, "no such task")
    events = t.events[max(0, since):]
    return {**t.summary(), "events": events, "next": max(0, since) + len(events)}


@app.post("/api/tasks/{task_id}/approve")
def task_approve(task_id: str, body: ApproveIn, request: Request) -> dict[str, Any]:
    _authorise(request)
    if not TASKS.approve(task_id, body.call_id, body.approve):
        raise HTTPException(409, "nothing waiting for that approval")
    return {"ok": True}


@app.post("/api/tasks/{task_id}/cancel")
def task_cancel(task_id: str, request: Request) -> dict[str, Any]:
    _authorise(request)
    if not TASKS.cancel(task_id):
        raise HTTPException(404, "no such task")
    return {"ok": True}


# -- conversations (GUI) --------------------------------------------------------------
@app.get("/api/conversations")
def conv_list(request: Request, q: str = "") -> dict[str, Any]:
    _authorise(request)
    return {"conversations": Conversations().list(q)}


@app.post("/api/conversations")
def conv_create(body: ConvIn, request: Request) -> dict[str, Any]:
    _authorise(request)
    return Conversations().create(body.title, body.mode)


@app.get("/api/conversations/{cid}")
def conv_get(cid: str, request: Request) -> dict[str, Any]:
    _authorise(request)
    conv = Conversations().get(cid)
    if not conv:
        raise HTTPException(404, "no such conversation")
    return conv


@app.patch("/api/conversations/{cid}")
def conv_patch(cid: str, body: ConvPatch, request: Request) -> dict[str, Any]:
    _authorise(request)
    convs = Conversations()
    if not convs.get(cid, with_messages=False):
        raise HTTPException(404, "no such conversation")
    if body.title is not None and not convs.rename(cid, body.title):
        raise HTTPException(422, "title is empty")
    if body.mode is not None and not convs.set_mode(cid, body.mode):
        raise HTTPException(422, "mode must be agent or chat")
    return convs.get(cid, with_messages=False)  # type: ignore[return-value]


@app.delete("/api/conversations/{cid}")
def conv_delete(cid: str, request: Request) -> dict[str, Any]:
    _authorise(request)
    return {"ok": Conversations().delete(cid)}


@app.post("/api/conversations/chat")
def conv_chat(body: ChatConvIn, request: Request):
    """Plain (no tools) chat turn inside a saved conversation."""
    _authorise(request)
    convs = Conversations()
    if not convs.get(body.conversation_id, with_messages=False):
        raise HTTPException(404, "no such conversation")
    _check_message(body.message)
    convs.add_message(body.conversation_id, "user", body.message)
    desktop = config.desktop_enabled() and _is_loopback(request) and body.client != "mobile"
    msgs = convs.history(body.conversation_id)
    res = _run_chat(msgs, prefer=body.prefer, need_vision=False, keys=body.keys, client=body.client, desktop=desktop)
    if isinstance(res, JSONResponse):
        return res
    convs.add_message(body.conversation_id, "assistant", res["text"],
                      {"provider": res["provider"], "model": res["model"], "tried": res["tried"], "mode": "chat",
                       "actions": res.get("actions", [])})
    return res


# -- settings & skills (GUI) ----------------------------------------------------------
@app.get("/api/settings")
def settings_get(request: Request) -> dict[str, Any]:
    _authorise(request)
    return {**settings_mod.load(), "effective_approval_mode": policy.mode()}


@app.put("/api/settings")
def settings_put(body: dict[str, Any], request: Request) -> dict[str, Any]:
    _authorise(request, local_only=True)
    try:
        return {**settings_mod.update(body), "effective_approval_mode": policy.mode()}
    except settings_mod.SettingsError as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/skills")
def skills_list(request: Request) -> dict[str, Any]:
    _authorise(request)
    return {"skills": [{"name": s.name, "description": s.description, "bundled": s.bundled}
                       for s in skills_mod.discover().values()]}


@app.get("/api/skills/{name}")
def skills_get(name: str, request: Request) -> dict[str, Any]:
    _authorise(request)
    s = skills_mod.discover().get(name)
    if not s:
        raise HTTPException(404, "no such skill")
    return {"name": s.name, "description": s.description, "bundled": s.bundled, "body": s.body()}


@app.put("/api/skills/{name}")
def skills_put(name: str, body: SkillIn, request: Request) -> dict[str, Any]:
    _authorise(request, local_only=True)
    try:
        s = skills_mod.save(name, body.body, body.description)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"name": s.name, "description": s.description, "bundled": False, "body": s.body()}


@app.delete("/api/skills/{name}")
def skills_delete(name: str, request: Request) -> dict[str, Any]:
    _authorise(request, local_only=True)
    return {"ok": skills_mod.delete(name)}


@app.get("/api/memory")
def memory_get(request: Request) -> dict[str, Any]:
    _authorise(request)
    m = Memory()
    return {"facts": m.facts(), "journal": m.journal(30)}


@app.post("/api/memory")
def memory_add(body: FactIn, request: Request) -> dict[str, Any]:
    _authorise(request)
    return Memory().remember(body.text, body.tags)


@app.delete("/api/memory/{fact_id}")
def memory_forget(fact_id: int, request: Request) -> dict[str, Any]:
    _authorise(request)
    return {"ok": Memory().forget(fact_id)}


@app.get("/api/routines")
def routines_list(request: Request) -> dict[str, Any]:
    _authorise(request)
    return {"routines": [r.__dict__ for r in routines_mod.RoutineStore().load().values()],
            "scheduler": bool(SCHEDULER and SCHEDULER.thread and SCHEDULER.thread.is_alive())}


@app.post("/api/routines")
def routines_add(body: RoutineIn, request: Request) -> dict[str, Any]:
    _authorise(request)
    try:
        return routines_mod.RoutineStore().add(body.name, body.schedule, body.prompt).__dict__
    except routines_mod.ScheduleError as exc:
        raise HTTPException(400, str(exc)) from None


@app.patch("/api/routines/{name}")
def routines_patch(name: str, body: RoutinePatch, request: Request) -> dict[str, Any]:
    _authorise(request)
    try:
        return routines_mod.RoutineStore().update(name, schedule=body.schedule, prompt=body.prompt,
                                                  enabled=body.enabled).__dict__
    except KeyError:
        raise HTTPException(404, "no such routine") from None
    except routines_mod.ScheduleError as exc:
        raise HTTPException(400, str(exc)) from None


@app.delete("/api/routines/{name}")
def routines_remove(name: str, request: Request) -> dict[str, Any]:
    _authorise(request)
    return {"ok": routines_mod.RoutineStore().remove(name)}


@app.post("/api/routines/{name}/run")
def routines_run(name: str, request: Request) -> dict[str, Any]:
    _authorise(request)
    r = routines_mod.RoutineStore().load().get(name)
    if not r:
        raise HTTPException(404, "no such routine")
    started = time.time()

    def record(task) -> None:
        res = task.result or {}
        routines_mod.RoutineStore().record(name, task.status if task.status != "done" else (res.get("stopped") or "done"),
                                           res.get("text") or "", started)

    task = TASKS.start([{"role": "user", "content": r.prompt}], title=f"routine: {name}", source="routine",
                       auto_deny=True, agent_kwargs={"desktop": False, "client": "routine"}, on_done=record)
    return {"task_id": task.id}


@app.get("/api/agent/info")
def agent_info(request: Request) -> dict[str, Any]:
    _authorise(request)
    desktop = config.desktop_enabled() and _is_loopback(request)
    tl = tools_mod.build(desktop=desktop, extra=MCP_TOOLS)
    return {"tools": [{"name": t.name, "level": t.level, "group": t.group, "description": t.description}
                      for t in tl.values()],
            "skills": [{"name": s.name, "description": s.description, "bundled": s.bundled}
                       for s in skills_mod.discover().values()],
            "approval_mode": policy.mode(), "sandbox": sandbox.mode(), "workspace": str(sandbox.root()),
            "mcp_errors": MCP_ERRORS}


@app.post("/api/actions/execute")
def actions_execute(body: ExecuteIn, request: Request) -> dict[str, Any]:
    _authorise(request, local_only=True)
    return execute(body.action, confirmed=body.confirmed)


@app.post("/api/screen/explain")
def screen_explain(body: ScreenIn, request: Request):
    _authorise(request, local_only=True)
    if not body.confirmed:
        raise HTTPException(400, "screen capture needs confirmed: true")
    res = execute({"tool": "screenshot", "args": {"path": "automoto-screen.png"}}, confirmed=True)
    if not res.get("ok"):
        raise HTTPException(500, res.get("error", "screenshot failed"))
    data = base64.b64encode(Path(res["result"]).read_bytes()).decode()
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": body.question},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}},
    ]}]
    return _run_chat(msgs, prefer=body.prefer, need_vision=True, keys=body.keys, client="desktop", desktop=True)




def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import threading
    import webbrowser

    import uvicorn

    if host not in ("127.0.0.1", "localhost", "::1") and not config.env("AUTOMOTO_API_TOKEN"):
        raise SystemExit("Refusing to listen on a network interface without AUTOMOTO_API_TOKEN set.")
    global SCHEDULER
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/"
    print(f"{APP_NAME} v{__version__} \"{CODENAME}\" -> {url}", flush=True)
    tools, errors = mcp_mod.connect_all()
    MCP_TOOLS[:] = tools
    MCP_ERRORS[:] = errors
    if tools:
        print(f"MCP: {len(tools)} tool(s) connected")
    for e in errors:
        print(f"MCP error: {e}")
    SCHEDULER = routines_mod.Scheduler(routine_runner)
    SCHEDULER.start()
    print(f"Workspace: {sandbox.root()}  ·  sandbox: {sandbox.mode()}  ·  approvals: {policy.mode()}  ·  routines: on", flush=True)
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
