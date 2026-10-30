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
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from automoto import APP_NAME, CODENAME, __version__, accounts, config, hosted, policy, sandbox, tenancy
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
SESSION_TOKEN = secrets.token_urlsafe(32)  # per launch; header X-AutoMoto-Token or the HttpOnly cookie
COOKIE = "automoto_session"
_LAUNCH: dict[str, float] = {}  # one-time launch tokens -> expiry
_LAUNCH_LOCK = threading.Lock()
MAX_IMAGES = 4

MCP_TOOLS: list[tools_mod.Tool] = []
MCP_ERRORS: list[str] = []


def _agent_factory(desktop: bool = False, client: str = "web", workspace: str | None = None,
                   local_apps: bool = False, meter: Any = None) -> Agent:
    if tenancy.current() is not None:  # hosted user: the safe tool set in their own sandbox, metered
        return Agent(tools=hosted.hosted_tools(), desktop=False, client="web", workspace=None, meter=meter)
    tl = tools_mod.build(desktop=desktop, extra=MCP_TOOLS, local_apps=local_apps)
    return Agent(tools=tl, desktop=desktop, client=client, workspace=workspace, meter=meter)


def _local(request: Request) -> bool:
    """A client on this computer in single-user mode (hosted mode never trusts loopback)."""
    return not tenancy.multiuser() and _is_loopback(request)


def _local_apps_ok(request: Request, client: str) -> bool:
    """Local apps (ffmpeg, Photoshop, …) only for clients on this computer, never the LAN/mobile app."""
    return _local(request) and client not in ("mobile", "routine")


def _owner(request: Request) -> str | None:
    """Hosted mode: the signed-in user's id (tasks are filtered by it). Local mode: None (all tasks)."""
    if tenancy.multiuser():
        return request.state.user.id
    return None


def _hosted_gate(request: Request) -> Any:
    """Hosted mode: refuse to start AI work when the user is over quota or running too many tasks."""
    if not tenancy.multiuser():
        return None
    user = request.state.user
    q = accounts.quota(user)
    if q["blocked"]:
        raise HTTPException(429, {"message": accounts.limit_message(q), "quota": q})
    if TASKS.running(user.id) >= int(accounts.get_setting("max_tasks_per_user")):
        raise HTTPException(429, "you already have the maximum number of runs going - wait or stop one")
    return accounts.Meter(user.id)


TASKS = TaskManager(_agent_factory)
SCHEDULER: routines_mod.Scheduler | None = None


def routine_runner(prompt: str) -> dict[str, Any]:
    task = TASKS.start([{"role": "user", "content": prompt}], source="routine", auto_deny=True,
                       agent_kwargs={"desktop": False, "client": "routine"})
    done = TASKS.wait(task.id, timeout=1800)
    res = (done.result if done else None) or {"text": "timed out", "stopped": "error"}
    return {**res, "task_id": task.id}


# Swagger UI loads scripts from a CDN, so it is off unless you opt in (AUTOMOTO_API_DOCS=1).
_DOCS = config.env("AUTOMOTO_API_DOCS", "") in ("1", "true", "yes")
app = FastAPI(title=f"{APP_NAME} {CODENAME}", version=__version__, docs_url="/api/docs" if _DOCS else None,
              redoc_url=None, openapi_url="/api/openapi.json" if _DOCS else None)
app.include_router(hosted.router)  # hosted-mode auth/admin API (only reachable when AUTOMOTO_MODE=multiuser)


# -- request guard: Host / Origin checks, rate limits, security headers ------------------
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
EXPENSIVE = ("/api/agent", "/api/chat", "/api/conversations/chat", "/api/screen/explain", "/api/doctor")
_HITS: dict[tuple[str, str], deque] = {}
_HITS_LOCK = threading.Lock()


def new_launch_token(ttl: float = 600) -> str:
    """A one-time token that turns into the session cookie when the UI is opened with ?launch=."""
    tok = secrets.token_urlsafe(32)
    with _LAUNCH_LOCK:
        now = time.time()
        for k in [k for k, exp in _LAUNCH.items() if exp < now]:
            _LAUNCH.pop(k, None)
        _LAUNCH[tok] = now + ttl
    return tok


def _use_launch_token(tok: str) -> bool:
    fixed = config.env("AUTOMOTO_LAUNCH_TOKEN")  # set by the desktop shell; valid for this process only
    if fixed and len(fixed) >= 24 and hmac.compare_digest(tok, fixed):
        return True
    with _LAUNCH_LOCK:
        exp = _LAUNCH.pop(tok, None)
    return bool(exp and exp >= time.time())


PLATFORM_HOST_VARS = ("RENDER_EXTERNAL_HOSTNAME", "KOYEB_PUBLIC_DOMAIN", "SPACE_HOST")


def _allowed_hosts() -> set[str]:
    extra = {h.strip().lower() for h in (config.env("AUTOMOTO_ALLOWED_HOSTS", "") or "").split(",") if h.strip()}
    # public host names that free hosts set for you (Render, Koyeb, Hugging Face Spaces)
    for var in PLATFORM_HOST_VARS:
        v = (config.env(var, "") or "").strip().lower()
        if v:
            extra.add(_host_name(v.split("://")[-1].split("/")[0]))
    return LOCAL_HOSTS | extra


def _host_name(hostport: str) -> str:
    hp = (hostport or "").strip().lower()
    if hp.startswith("["):
        return hp.split("]")[0] + "]"
    return hp.rsplit(":", 1)[0] if hp.count(":") == 1 else hp


def _origin_ok(origin: str, host_header: str) -> bool:
    origin = origin.strip().lower()
    extra = {o.strip().lower() for o in (config.env("AUTOMOTO_ALLOWED_ORIGINS", "") or "").split(",") if o.strip()}
    if origin in extra:
        return True
    if not origin.startswith("http://") and not origin.startswith("https://"):
        return False
    netloc = origin.split("://", 1)[1].rstrip("/")
    return netloc == (host_header or "").strip().lower() and _host_name(netloc) in _allowed_hosts()


def _bearer_ok(request: Request) -> bool:
    if tenancy.multiuser():
        return False  # hosted mode: people sign in with accounts, there is no master token
    api_tok = config.env("AUTOMOTO_API_TOKEN")
    bearer = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    return bool(api_tok and bearer and hmac.compare_digest(bearer, api_tok))


def _rate_limited(client: str, path: str) -> bool:
    try:
        per_min = int(config.env("AUTOMOTO_RATE_LIMIT", "600") or 600)
    except ValueError:
        per_min = 600
    if per_min <= 0:
        return False
    bucket, limit = ("expensive", max(5, per_min // 20)) if path.startswith(EXPENSIVE) or path.endswith("/run") \
        else ("all", per_min)
    now = time.monotonic()
    with _HITS_LOCK:
        q = _HITS.setdefault((client, bucket), deque())
        while q and q[0] < now - 60:
            q.popleft()
        if len(q) >= limit:
            return True
        q.append(now)
    return False


@app.middleware("http")
async def guard(request: Request, call_next):
    tenancy.set_current(None)  # never inherit a tenant; _authorise sets it per request
    origin = request.headers.get("origin")
    # hosted mode: the desktop/phone apps' own pages may call a few sign-in paths (no cookies), see hosted.CORS_PATHS
    cors = origin is not None and tenancy.multiuser() and hosted.cors_allowed(origin, request.url.path)
    if tenancy.multiuser():
        if not hosted.path_allowed(request.method, request.url.path) and not (cors and request.method == "OPTIONS"):
            return JSONResponse({"detail": "not available on this hosted AutoMoto server"}, status_code=404)
    elif hosted.is_hosted_only(request.url.path):  # local mode has no accounts
        return JSONResponse({"detail": "only in hosted mode (AUTOMOTO_MODE=multiuser)"}, status_code=404)
    host = request.headers.get("host", "")
    # DNS rebinding: a web page that re-points its domain at 127.0.0.1 still sends its own Host header.
    if _host_name(host) not in _allowed_hosts() and not _bearer_ok(request):
        return JSONResponse({"detail": "unexpected Host header"}, status_code=421)
    if cors and request.method == "OPTIONS":
        return Response(status_code=204, headers=hosted.cors_headers(origin, preflight=True))  # type: ignore[arg-type]
    # CSRF / cross-site requests: only this server's own pages (or configured origins) may call it.
    if origin is not None and not cors and not _origin_ok(origin, host) and not _bearer_ok(request):
        return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
    if request.url.path.startswith("/api/") and _rate_limited(request.client.host if request.client else "?",
                                                               request.url.path):
        return JSONResponse({"detail": "too many requests - slow down"}, status_code=429,
                            headers={"Retry-After": "10"})
    response = await call_next(request)
    if cors:
        response.headers.update(hosted.cors_headers(origin))  # type: ignore[arg-type]
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if host in ("testclient", "localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _session_ok(request: Request) -> bool:
    tok = request.headers.get("x-automoto-token", "")
    if tok and hmac.compare_digest(tok, SESSION_TOKEN):
        return True
    cookie = request.cookies.get(COOKIE, "")
    if cookie and hmac.compare_digest(cookie, SESSION_TOKEN):
        # Cookie auth is for the browser UI only: state-changing calls must come from our own page.
        if request.method in ("GET", "HEAD"):
            return True
        origin = request.headers.get("origin")
        return bool(origin) and _origin_ok(origin, request.headers.get("host", ""))
    return False


def _authorise(request: Request, *, local_only: bool = False) -> None:
    if tenancy.multiuser():
        if local_only:
            raise HTTPException(403, "not available on a hosted AutoMoto server")
        hosted.authenticate(request)
        return
    if _is_loopback(request):
        if _session_ok(request) or _bearer_ok(request):
            return
        raise HTTPException(403, "missing session token (open the UI with the link `automoto serve` printed, "
                                 "or run `python -m automoto open`)")
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


def _run_chat(messages, *, prefer, need_vision, keys, client, desktop: bool, meter: Any = None) -> dict[str, Any]:
    msgs = [m for m in messages if m.get("role") in ("user", "assistant")]
    t0 = time.monotonic()
    try:
        ans = ask(msgs, need_vision=need_vision, prefer=prefer, keys=keys,
                  system=system_prompt(desktop=desktop, client=client))
    except NoProviderError as exc:
        raise HTTPException(400, str(exc)) from None
    except AllProvidersFailed as exc:
        if meter:
            meter.add(time.monotonic() - t0, requests=1, kind="chat", detail="failed")
        return JSONResponse(status_code=502, content={"error": str(exc), "tried": exc.tried})  # type: ignore[return-value]
    if meter:
        chars = sum(len(m["content"]) if isinstance(m.get("content"), str) else 2000 for m in msgs) + len(ans.text)
        meter.add(time.monotonic() - t0, requests=1, tokens=chars // 4, kind="chat", detail=f"{ans.provider}/{ans.model}")
    text, actions = split_actions(ans.text) if desktop else (ans.text, [])
    return {**ans.as_dict(), "text": text, "actions": actions}


class AgentIn(BaseModel):
    messages: list[dict[str, Any]] | None = Field(None, max_length=60)
    workspace: str | None = Field(None, max_length=1024)  # an allowed folder to work in (VS Code project)
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


LOCKED_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>AutoMoto AI - locked</title>
<meta name="viewport" content="width=device-width, initial-scale=1"><style>body{font:16px system-ui;background:#0b0f14;
color:#e6edf3;display:grid;place-items:center;min-height:100vh;margin:0}main{max-width:520px;padding:24px}
code{background:#161b22;padding:2px 6px;border-radius:6px}</style></head><body><main><h1>🔒 AutoMoto is locked</h1>
<p>For your safety this page only opens from the one-time link AutoMoto gives you.</p>
<p>Use the link printed by <code>python -m automoto serve</code>, or run <code>python -m automoto open</code>.</p>
</main></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index(request: Request, launch: str | None = None, device_launch: str | None = None):
    base_headers = {"Content-Security-Policy": CSP, "Cache-Control": "no-store"}
    if tenancy.multiuser():
        if device_launch is not None:  # an app opening its window, signed in (accounts.device_launch_code)
            return hosted.open_device_window(request, device_launch, base_headers)
        got = hosted.current_user(request)
        if not got:
            html = (WEB_DIR / "login.html").read_text(encoding="utf-8").replace("__AUTOMOTO_VERSION__", __version__)
            return HTMLResponse(html, headers=base_headers)
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        meta = (f'<meta name="automoto-csrf" content="{got[1]}" />\n'
                '<meta name="automoto-mode" content="multiuser" />\n')
        html = html.replace("__AUTOMOTO_VERSION__", __version__).replace("</title>", "</title>\n" + meta, 1)
        return HTMLResponse(html, headers=base_headers)
    if launch is not None:
        if not _is_loopback(request) or not _use_launch_token(launch):
            return HTMLResponse(LOCKED_PAGE, status_code=403, headers=base_headers)
        from fastapi.responses import RedirectResponse

        if request.headers.get("sec-fetch-site", "") in ("cross-site", "same-site") or request.query_params.get("app"):
            # opened by another site or the desktop app's own page: a redirect would carry that origin along
            # and the SameSite=Strict cookie would not be sent with it, so refresh from our own page instead
            resp: Any = HTMLResponse(hosted._OPENING, headers=base_headers)
        else:
            resp = RedirectResponse("/", status_code=303, headers={"Cache-Control": "no-store"})
        resp.set_cookie(COOKIE, SESSION_TOKEN, httponly=True, samesite="strict", path="/",
                        secure=request.url.scheme == "https")
        return resp
    cookie = request.cookies.get(COOKIE, "")
    if not (_is_loopback(request) and cookie and hmac.compare_digest(cookie, SESSION_TOKEN)):
        return HTMLResponse(LOCKED_PAGE, status_code=401, headers=base_headers)
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("__AUTOMOTO_TOKEN__", "").replace("__AUTOMOTO_VERSION__", __version__)
    return HTMLResponse(html, headers=base_headers)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    from fastapi.responses import RedirectResponse

    return RedirectResponse("/", status_code=303)


@app.post("/api/session/launch")
def session_launch(request: Request) -> dict[str, Any]:
    """Mint a one-time browser launch URL (CLI ``automoto open`` and the VS Code extension use it)."""
    _authorise(request, local_only=True)
    if not _is_loopback(request):
        raise HTTPException(403, "local only")
    host = request.headers.get("host", "127.0.0.1")
    return {"url": f"http://{host}/?launch={new_launch_token()}"}


app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "app": APP_NAME, "codename": CODENAME, "version": __version__, "os": OS_LABEL}


@app.get("/api/status")
def get_status(request: Request) -> dict[str, Any]:
    _authorise(request)
    return {**status(), "version": __version__, "os": OS_LABEL,
            "desktop": config.desktop_enabled() and _local(request),
            "tools": [] if tenancy.multiuser() else [{"name": t.name, "risk": t.risk, "args": list(t.args)}
                                                      for t in TOOLS.values()]}


@app.post("/api/status")
def post_status(body: RecommendIn, request: Request) -> dict[str, Any]:
    _authorise(request)
    return {**status(None if tenancy.multiuser() else body.keys), "version": __version__}


@app.post("/api/doctor")
def doctor_run(body: RecommendIn, request: Request) -> dict[str, Any]:
    """Settings -> Test keys: a 1-token request to each configured model (local mode only)."""
    _authorise(request)
    if tenancy.multiuser():  # also blocked by the hosted allow-list; belt and braces
        raise HTTPException(404, "not available on a hosted AutoMoto server")
    from automoto import doctor

    return doctor.run(body.keys or None)


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
    meter = _hosted_gate(request)
    desktop = config.desktop_enabled() and _local(request) and body.client != "mobile"
    return _run_chat(body.messages, prefer=body.prefer, need_vision=body.need_vision,
                     keys=None if meter else body.keys, client=body.client, desktop=desktop, meter=meter)


# -- v5 agent --------------------------------------------------------------------
@app.post("/api/agent")
def agent_start(body: AgentIn, request: Request) -> dict[str, Any]:
    _authorise(request)
    meter = _hosted_gate(request)
    desktop = config.desktop_enabled() and _local(request) and body.client != "mobile"
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
    workspace = None
    if body.workspace:
        if not _local(request):
            raise HTTPException(403, "choosing a workspace folder is only allowed on this computer")
        try:
            workspace = str(sandbox.check_root(body.workspace))
        except sandbox.SandboxError as exc:
            raise HTTPException(400, str(exc)) from None
    task = TASKS.start(msgs, source="web" if meter else body.client, keys=None if meter else body.keys,
                       prefer=body.prefer, max_steps=body.max_steps,
                       agent_kwargs={"desktop": desktop, "client": body.client, "workspace": workspace,
                                     "local_apps": _local_apps_ok(request, body.client), "meter": meter},
                       conversation_id=conv_id, on_done=on_done, owner=_owner(request))
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
    return {"tasks": TASKS.list(_owner(request))}


@app.get("/api/tasks/{task_id}")
def task_get(task_id: str, request: Request, since: int = 0) -> dict[str, Any]:
    _authorise(request)
    t = TASKS.get(task_id, _owner(request))
    if not t:
        raise HTTPException(404, "no such task")
    events = t.events[max(0, since):]
    return {**t.summary(), "events": events, "next": max(0, since) + len(events)}


@app.post("/api/tasks/{task_id}/approve")
def task_approve(task_id: str, body: ApproveIn, request: Request) -> dict[str, Any]:
    _authorise(request)
    if not TASKS.approve(task_id, body.call_id, body.approve, _owner(request)):
        raise HTTPException(409, "nothing waiting for that approval")
    return {"ok": True}


@app.post("/api/tasks/{task_id}/cancel")
def task_cancel(task_id: str, request: Request) -> dict[str, Any]:
    _authorise(request)
    if not TASKS.cancel(task_id, _owner(request)):
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
    meter = _hosted_gate(request)
    convs.add_message(body.conversation_id, "user", body.message)
    desktop = config.desktop_enabled() and _local(request) and body.client != "mobile"
    msgs = convs.history(body.conversation_id)
    res = _run_chat(msgs, prefer=body.prefer, need_vision=False, keys=None if meter else body.keys,
                    client=body.client, desktop=desktop, meter=meter)
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
    if tenancy.multiuser():  # never the host's settings (allowed folders etc.)
        return {"theme": "dark", "default_mode": "agent", "hosted": True, "effective_approval_mode": "ask"}
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
    names = set(hosted.hosted_tools() if tenancy.multiuser() else
                tools_mod.build(desktop=config.desktop_enabled(), extra=MCP_TOOLS))
    return {"skills": [{"name": s.name, "description": s.description, "bundled": s.bundled,
                        **s.requirements(names)} for s in skills_mod.discover().values()]}


@app.get("/api/skills/{name}")
def skills_get(name: str, request: Request) -> dict[str, Any]:
    _authorise(request)
    s = skills_mod.discover().get(name)
    if not s:
        raise HTTPException(404, "no such skill")
    return {"name": s.name, "description": s.description, "bundled": s.bundled, "body": s.body(),
            **s.requirements()}


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
    desktop = config.desktop_enabled() and _local(request)
    hosted_mode = tenancy.multiuser()
    tl = hosted.hosted_tools() if hosted_mode else tools_mod.build(desktop=desktop, extra=MCP_TOOLS,
                                                                  local_apps=_local(request))
    from automoto import planner

    return {"tools": [{"name": t.name, "level": t.level, "group": t.group, "description": t.description,
                       "hidden": t.hidden} for t in tl.values()],
            "ideas": planner.default_ideas(),
            "skills": [{"name": s.name, "description": s.description, "bundled": s.bundled}
                       for s in skills_mod.discover().values()],
            "approval_mode": policy.mode(), "sandbox": "hosted (per-user)" if hosted_mode else sandbox.mode(),
            "workspace": "your private workspace" if hosted_mode else str(sandbox.root()),
            "mcp_errors": [] if hosted_mode else MCP_ERRORS,
            "extra_roots": [] if hosted_mode else [str(p) for p in sandbox.extra_roots()]}


@app.post("/api/ideas")
def ideas(body: dict[str, Any], request: Request) -> dict[str, Any]:
    """Friendly next-step chips for the chat: defaults, or ones that fit the files the user just attached."""
    _authorise(request)
    from automoto import planner

    files = [str(f)[:300] for f in (body.get("files") or [])[:20] if isinstance(f, str)]
    return {"ideas": planner.ideas_for(files) if files else planner.default_ideas()}


# -- files (workspace only): upload Office files, preview, download ------------------------
MAX_UPLOAD = 50 * 1024 * 1024
_TABLE_EXT = {".csv", ".tsv", ".tab", ".psv", ".jsonl", ".ndjson", ".parquet", ".pq"}
_DATA_EXT = {".json", ".geojson", ".yaml", ".yml", ".toml", ".xml", ".sqlite", ".sqlite3", ".db"}
_TEXT_EXT = {".log", ".txt", ".md", ".markdown", ".ini", ".cfg", ".conf", ".php", ".css", ".js", ".html"}
_PREVIEW_EXT = {".pdf", ".docx", ".doc", ".odt", ".rtf", ".xlsx", ".xls", ".ods", ".pptx", ".ppt", ".odp"}
_IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
_FILES_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv"}


class UploadIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    data: str = Field(..., max_length=MAX_UPLOAD * 4 // 3 + 1024)  # base64
    dir: str = Field("uploads", max_length=200)


def max_upload() -> int:
    if tenancy.multiuser():
        try:
            mb = float(config.env("AUTOMOTO_HOSTED_MAX_UPLOAD_MB", "20") or 20)
        except ValueError:
            mb = 20
        return int(max(1, min(mb, MAX_UPLOAD / 1048576)) * 1048576)
    return MAX_UPLOAD


def _dir_size(root: Path, cap: int = 200_000) -> int:
    total, n = 0, 0
    for p in root.rglob("*"):
        n += 1
        if n > cap:
            break
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def _ws_path(path: str) -> Path:
    """A path inside the default workspace (never extra roots, never sensitive names)."""
    try:
        return sandbox.resolve(path or ".", base=sandbox.default_root(), allow_outside=False)
    except sandbox.SandboxError as exc:
        raise HTTPException(400, str(exc)) from None


def _safe_name(name: str) -> str:
    import re as _re

    base = Path(name.replace("\\", "/")).name
    if base.startswith("."):
        raise HTTPException(400, "hidden files (names starting with '.') can't be uploaded")
    base = _re.sub(r"[^\w.\- ()]+", "_", base).strip(" .")[:120]
    if not base or base.startswith("."):
        raise HTTPException(400, "bad file name")
    return base


def _view_kind(p: Path) -> str | None:
    from automoto import archives

    n, ext = p.name.lower(), p.suffix.lower()
    if archives.is_archive_name(n) and ext not in (".docx", ".xlsx", ".pptx"):
        return "archive"
    if ext in _TABLE_EXT or ext in (".xlsx", ".xls", ".ods"):
        return "table"
    if ext in _DATA_EXT:
        return "data"
    if ext in _TEXT_EXT:
        return "text"
    return None


@app.get("/api/files")
def files_list(request: Request, dir: str = ".") -> dict[str, Any]:
    _authorise(request)
    root = sandbox.default_root()
    root.mkdir(parents=True, exist_ok=True)
    d = _ws_path(dir)
    if not d.is_dir():
        raise HTTPException(404, "no such folder")
    items = []
    for p in sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:500]:
        if p.name in _FILES_SKIP or sandbox.sensitive(p):
            continue
        st = p.stat()
        items.append({"name": p.name, "path": p.relative_to(root).as_posix(), "dir": p.is_dir(),
                      "size": st.st_size if p.is_file() else None, "mtime": int(st.st_mtime),
                      "preview": p.suffix.lower() in _PREVIEW_EXT or p.suffix.lower() in _IMAGE_MIME,
                      "view": _view_kind(p) if p.is_file() else None})
    rel_dir = d.relative_to(root.resolve()).as_posix() if d != root.resolve() else "."
    from automoto import office

    return {"dir": rel_dir, "items": items, "libreoffice": office.lo_available()}


@app.post("/api/files/upload")
def files_upload(request: Request, body: UploadIn) -> dict[str, Any]:
    _authorise(request)
    from automoto import office

    try:
        raw = base64.b64decode(body.data.split(",", 1)[-1], validate=True)
    except ValueError:
        raise HTTPException(400, "data must be base64") from None
    cap = max_upload()
    if len(raw) > cap:
        raise HTTPException(413, f"file too large (max {cap // 1048576} MB)")
    if tenancy.multiuser():
        limit = float(accounts.get_setting("storage_mb")) * 1048576
        if _dir_size(sandbox.default_root()) + len(raw) > limit:
            raise HTTPException(413, f"your storage is full ({limit / 1048576:g} MB) - delete some files first")
    d = _ws_path(body.dir)
    d.mkdir(parents=True, exist_ok=True)
    name = _safe_name(body.name)
    dest = _ws_path((d / name).relative_to(sandbox.default_root().resolve()).as_posix())
    if dest.exists():
        stem, ext = dest.stem, dest.suffix
        for i in range(2, 1000):
            cand = dest.with_name(f"{stem} ({i}){ext}")
            if not cand.exists():
                dest = cand
                break
    # write under a hidden temporary name, check it, then publish it
    probe = dest.with_name(".upload-" + secrets.token_hex(6) + dest.suffix)
    probe.write_bytes(raw)
    try:
        info = office.inspect_file(probe)
    except office.OfficeError as exc:
        probe.unlink(missing_ok=True)
        raise HTTPException(400, f"refused: {exc}") from None
    arch = None
    from automoto import archives

    if archives.is_archive_name(dest.name) and dest.suffix.lower() not in (".docx", ".xlsx", ".pptx"):
        try:
            arch = archives.inspect_path(probe)
        except (archives.ArchiveError, OSError) as exc:
            probe.unlink(missing_ok=True)
            raise HTTPException(400, f"refused: {exc}") from None
        if not arch["safe"]:
            probe.unlink(missing_ok=True)
            raise HTTPException(400, "refused: unsafe archive - " + "; ".join(arch["problems"]))
    probe.replace(dest)
    notes: list[str] = []
    if arch:
        notes.append(f"{arch['format']} archive, {arch['files']} file(s), {arch['unpacked_bytes']:,} bytes unpacked")
        notes += arch["warnings"][:3]
    if info and info.get("macros"):
        notes.append("contains macros - AutoMoto never runs them")
    if info and info.get("external_links"):
        notes.append(f"{len(info['external_links'])} external link(s) - not followed")
    return {"path": dest.relative_to(sandbox.default_root().resolve()).as_posix(), "size": len(raw), "notes": notes}


@app.get("/api/files/download")
def files_download(request: Request, path: str):
    _authorise(request)
    from fastapi.responses import FileResponse

    p = _ws_path(path)
    if not p.is_file():
        raise HTTPException(404, "no such file")
    return FileResponse(p, media_type="application/octet-stream", filename=p.name,
                        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox"})


class FileDeleteIn(BaseModel):
    path: str = Field(..., min_length=1, max_length=400)


@app.post("/api/files/delete")
def files_delete(request: Request, body: FileDeleteIn) -> dict[str, Any]:
    """Delete a file or folder inside the workspace (never the workspace itself)."""
    _authorise(request)
    import shutil as _sh

    p = _ws_path(body.path)
    root = sandbox.default_root().resolve()
    if p == root or p == root / "scratch" or not p.exists():
        raise HTTPException(404, "no such file")
    if p.is_dir() and not p.is_symlink():
        _sh.rmtree(p)
    else:
        p.unlink()
    return {"ok": True}


@app.get("/api/files/preview")
def files_preview(request: Request, path: str, page: int = 1):
    _authorise(request)
    import hashlib
    import shutil as _sh
    import tempfile as _tf

    from fastapi.responses import FileResponse

    from automoto import office

    p = _ws_path(path)
    if not p.is_file():
        raise HTTPException(404, "no such file")
    ext = p.suffix.lower()
    headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'"}
    if ext in _IMAGE_MIME:  # never SVG/HTML inline
        return FileResponse(p, media_type=_IMAGE_MIME[ext], headers=headers)
    if ext not in _PREVIEW_EXT:
        raise HTTPException(415, "no preview for this file type")
    page = max(1, min(int(page), 200))
    st = p.stat()
    key = hashlib.sha256(f"{p}|{st.st_mtime_ns}|{st.st_size}|{page}".encode()).hexdigest()[:24]
    from automoto import home as _home

    cache = _home.home() / "cache" / "previews"
    cache.mkdir(parents=True, exist_ok=True)
    png = cache / f"{key}.png"
    if not png.exists():
        if not _sh.which("pdftoppm"):
            raise HTTPException(501, "previews need pdftoppm (poppler-utils)")
        try:
            with _tf.TemporaryDirectory(prefix="automoto-prev-") as tmp:
                pdf = p if ext == ".pdf" else office.lo_convert(p, "pdf", Path(tmp), timeout=120)
                import subprocess as _sp

                _sp.run(["pdftoppm", "-png", "-r", "60", "-f", str(page), "-l", str(page), "-singlefile", str(pdf),
                         str(Path(tmp) / "pv")], capture_output=True, timeout=120, check=False)
                out = Path(tmp) / "pv.png"
                if not out.exists():
                    raise HTTPException(404, "no such page")
                _sh.move(str(out), png)
        except office.OfficeError as exc:
            raise HTTPException(422, str(exc)) from None
    return FileResponse(png, media_type="image/png", headers=headers)


@app.get("/api/files/inspect")
def files_inspect(request: Request, path: str, rows: int = 50) -> dict[str, Any]:
    """Archive tree, table preview, structured outline or the tail of a text file (all read-only)."""
    _authorise(request)
    from automoto import archives
    from automoto import datafiles as dfm

    p = _ws_path(path)
    if not p.is_file():
        raise HTTPException(404, "no such file")
    kind = _view_kind(p)
    rows = max(1, min(int(rows), 200))
    try:
        if kind == "archive":
            rep = archives.inspect_path(p)
            _, ms, _ = archives.members_path(p)
            entries = [m.as_dict() for m in sorted(ms, key=lambda m: m.name)[:3000]]
            return {"kind": "archive", "report": rep, "entries": entries, "truncated": len(ms) > 3000}
        if kind == "table":
            df, info = dfm.load_table(p, nrows=max(rows, 1000))
            head = df.head(rows)
            cells = [[None if v is None or (isinstance(v, float) and v != v) else str(v)[:200] for v in r]
                     for r in head.itertuples(index=False)]
            lines = len(df)
            if info["kind"] == "csv" and info.get("truncated_at_rows"):
                n, _ = dfm.count_lines(p, 5_000_000)  # big file: estimate from line count
                lines = max(len(df), n - (1 if info.get("header") else 0))
            return {"kind": "table", "columns": [str(c) for c in df.columns], "rows": cells, "total_rows": lines,
                    "estimated": bool(info.get("truncated_at_rows")),
                    "info": {k: v for k, v in info.items() if k in ("encoding", "delimiter", "header", "sheet", "kind")}}
        if kind == "data":
            if dfm.kind_of(p) == "sqlite":
                return {"kind": "data", "outline": [f"{t['type']} {t['name']} ({t['rows']} rows): {', '.join(t['columns'][:20])}"
                                                    for t in dfm.sqlite_schema(p)]}
            return {"kind": "data", "outline": dfm.outline(dfm.load_structured(p), max_depth=4)[:400]}
        if kind == "text":
            return {"kind": "text", "text": dfm.tail(p, 200)}
    except (archives.ArchiveError, dfm.DataError) as exc:
        raise HTTPException(422, str(exc)) from None
    raise HTTPException(415, "no inspector for this file type")


class ArchiveActionIn(BaseModel):
    action: str = Field(..., pattern="^(extract|pack|repack)$")
    path: str = Field(..., min_length=1, max_length=400)


@app.post("/api/files/archive")
def files_archive(request: Request, body: ArchiveActionIn) -> dict[str, Any]:
    """Extract an archive to a new sibling folder, zip a folder, or clean-repack an archive (workspace only)."""
    _authorise(request)
    from automoto import archives

    p = _ws_path(body.path)
    root = sandbox.default_root().resolve()

    def unique(cand: Path) -> Path:
        if not cand.exists():
            return cand
        for i in range(2, 1000):
            c = cand.with_name(f"{cand.stem} ({i}){cand.suffix}" if cand.suffix else f"{cand.name} ({i})")
            if not c.exists():
                return c
        raise HTTPException(409, "too many copies")
    try:
        if body.action == "extract":
            if not p.is_file():
                raise HTTPException(404, "no such file")
            stem = p.name
            for ext in sorted(archives.ARCHIVE_EXTS, key=len, reverse=True):
                if stem.lower().endswith(ext):
                    stem = stem[: -len(ext)]
                    break
            dest = unique(p.with_name(stem or "extracted"))
            r = archives._extract(p, dest)
            return {"path": dest.relative_to(root).as_posix(), "files": r["files"]}
        if body.action == "pack":
            if not p.is_dir() or p == root:
                raise HTTPException(400, "choose a folder inside the workspace")
            out = unique(p.with_name(p.name + ".zip"))
            r = archives._create([p], out)
        else:
            if not p.is_file():
                raise HTTPException(404, "no such file")
            out = unique(p.with_name(p.name.rsplit(".", 1)[0].removesuffix(".tar") + "-repacked.zip"))
            r = archives.repack(p, out)
        return {"path": out.relative_to(root).as_posix(), "files": r["files"], "bytes": r["bytes_out"],
                "sha256": r["sha256"], "skipped": r["skipped_count"]}
    except archives.ArchiveError as exc:
        raise HTTPException(422, str(exc)) from None


# -- local apps, services, connectors ----------------------------------------------
@app.get("/api/apps")
def apps_list(request: Request) -> dict[str, Any]:
    _authorise(request, local_only=True)
    from automoto import apps as apps_mod

    return {"apps": apps_mod.listing()}


@app.get("/api/services")
def services_list(request: Request) -> dict[str, Any]:
    _authorise(request)
    from automoto import services as services_mod

    return {"services": services_mod.status_list()}  # token presence only, never values


@app.get("/api/connectors")
def connectors_list(request: Request) -> dict[str, Any]:
    _authorise(request)
    from automoto import mcp_catalog

    return {"connectors": mcp_catalog.listing(), "connected_tools": len(MCP_TOOLS), "errors": MCP_ERRORS}


@app.post("/api/connectors/{cid}/{action}")
def connectors_toggle(cid: str, action: str, request: Request) -> dict[str, Any]:
    _authorise(request, local_only=True)
    from automoto import mcp_catalog

    if action == "enable":
        try:
            mcp_catalog.enable(cid)
        except KeyError:
            raise HTTPException(404, "no such connector") from None
    elif action == "disable":
        mcp_catalog.disable(cid)
    else:
        raise HTTPException(404, "unknown action")
    return {"ok": True, "connectors": mcp_catalog.listing(), "note": "reload connectors or restart to apply"}


@app.post("/api/connectors-reload")
def connectors_reload(request: Request) -> dict[str, Any]:
    _authorise(request, local_only=True)
    mcp_mod.close_all()
    tools, errors = mcp_mod.connect_all()
    MCP_TOOLS[:] = tools
    MCP_ERRORS[:] = errors
    return {"connected_tools": len(tools), "errors": errors}


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




def check_port(host: str, port: int) -> None:
    """Fail early with a clear message when the port is taken (usually AutoMoto is already running)."""
    import socket

    fam = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(fam, socket.SOCK_STREAM) as s:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: don't share a port someone else holds
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:  # like uvicorn: ignore TIME_WAIT leftovers from a restart, still fails if something listens
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError as exc:
            raise SystemExit(f"Port {port} on {host} is already in use ({exc.strerror or exc}). AutoMoto may already "
                             f"be running - try `automoto open` - or start on another port: "
                             f"`automoto serve --port {port + 1}`.") from None


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import threading
    import webbrowser

    import uvicorn

    if tenancy.multiuser():
        check_port(host, port)
        return run_hosted(host, port)
    if host not in ("127.0.0.1", "localhost", "::1") and not config.env("AUTOMOTO_API_TOKEN"):
        raise SystemExit("Refusing to listen on a network interface without AUTOMOTO_API_TOKEN set.")
    check_port(host, port)
    global SCHEDULER
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/"  # nosec B104 - display URL only
    launch = f"{url}?launch={new_launch_token(ttl=3600)}"
    write_session_file(url, port)
    print(f"{APP_NAME} v{__version__} \"{CODENAME}\" -> {url}", flush=True)
    print(f"Open (one-time link): {launch}", flush=True)
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
        threading.Timer(1.2, lambda: webbrowser.open(launch)).start()
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning", server_header=False)
    finally:
        remove_session_file()


def run_hosted(host: str, port: int) -> None:
    """Hosted mode: accounts and quotas, no launch link, no MCP servers, no routines, no desktop."""
    import uvicorn

    made = accounts.bootstrap_admin_from_env()
    accounts.prune()
    hosts = sorted(_allowed_hosts() - LOCAL_HOSTS)
    print(f"{APP_NAME} v{__version__} \"{CODENAME}\" - HOSTED (multi-user) mode on {host}:{port}", flush=True)
    if made:
        print(f"Created the first admin '{made}' from AUTOMOTO_ADMIN_USER / AUTOMOTO_ADMIN_PASSWORD.", flush=True)
    if accounts.admin_count() == 0:
        print("No admin yet: run `python -m automoto admin create <name>` (or set AUTOMOTO_ADMIN_USER and "
              "AUTOMOTO_ADMIN_PASSWORD) before inviting people.", flush=True)
    st = accounts.settings()
    print(f"Sign-up: {st['signup']}  ·  default quota: {st['default_quota_minutes']:g} min per "
          f"{'day' if st['period_days'] == 1 else str(st['period_days']) + ' days'}  ·  allowed hosts: "
          f"{', '.join(hosts) or '(local only - set AUTOMOTO_ALLOWED_HOSTS=your.domain)'}", flush=True)
    if config.env("AUTOMOTO_NET_ALLOW_CIDRS"):
        print("WARNING: AUTOMOTO_NET_ALLOW_CIDRS is set - hosted users can reach those private networks.", flush=True)
    fwd = config.env("AUTOMOTO_FORWARDED_ALLOW_IPS", "127.0.0.1") or "127.0.0.1"
    uvicorn.run(app, host=host, port=port, log_level="warning", server_header=False, proxy_headers=True,
                forwarded_allow_ips=fwd)


def session_file() -> Path:
    from automoto import home

    return home.home() / "session.json"


def write_session_file(url: str, port: int) -> None:
    """Let local clients (VS Code extension, ``automoto open``) find this server and its token.
    The file is readable by this user only (0600 on macOS/Linux; the user profile ACL on Windows)."""
    import json
    import os

    p = session_file()
    data = json.dumps({"url": url, "port": port, "token": SESSION_TOKEN, "pid": os.getpid(), "version": __version__})
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(data)
    try:
        os.chmod(p, 0o600)
    except OSError:  # pragma: no cover
        pass


def remove_session_file() -> None:
    import json

    p = session_file()
    try:
        if json.loads(p.read_text(encoding="utf-8")).get("token") == SESSION_TOKEN:
            p.unlink()
    except (OSError, ValueError):
        pass
