"""Local web API + browser UI for AutoMoto AI v4 (the shared "brain" for every client).

Security model
--------------
* Binds to 127.0.0.1 by default.
* Browser requests must carry the per-launch session token that is injected into the
  served page (``X-AutoMoto-Token``), so other websites can't drive your local API.
* Non-loopback clients (e.g. the mobile app on your LAN) must send
  ``Authorization: Bearer $AUTOMOTO_API_TOKEN``; without that env var remote access is off.
* Desktop actions and screen capture are loopback-only and always need ``confirmed: true``.
* BYOK keys sent by a client are used for that request only - never stored or logged.
"""

from __future__ import annotations

import base64
import hmac
import ipaddress
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from automoto import APP_NAME, CODENAME, __version__, config
from automoto.agent import split_actions, system_prompt
from automoto.desktop import OS_LABEL, TOOLS, execute
from automoto.router import AllProvidersFailed, NoProviderError, ask, classify_task, recommend_provider, status

WEB_DIR = Path(__file__).parent / "web"
SESSION_TOKEN = secrets.token_urlsafe(24)
MAX_IMAGES = 4

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


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    token = SESSION_TOKEN if _is_loopback(request) else ""
    return HTMLResponse(html.replace("__AUTOMOTO_TOKEN__", token).replace("__AUTOMOTO_VERSION__", __version__))


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
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/"
    print(f"{APP_NAME} v{__version__} \"{CODENAME}\" -> {url}")
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
