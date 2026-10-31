"""Hosted mode (``AUTOMOTO_MODE=multiuser``): accounts, sign-in, quotas and the admin API.

Local single-user mode never loads these routes' state: ``server.py`` only consults this module
when ``tenancy.multiuser()`` is true, and then *every* API path must be on ``ALLOWED`` below,
so a new local-only endpoint is closed in hosted mode until it is reviewed and added.
"""

from __future__ import annotations

import hmac
import re
import threading
import time
from collections import deque
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from automoto import accounts, tenancy

COOKIE = "automoto_user"
router = APIRouter()

# (method, path regex) a hosted user may reach. Anything else is 404 in hosted mode.
ALLOWED: list[tuple[str, re.Pattern[str]]] = [(m, re.compile(p)) for m, p in [
    ("GET", r"/"), ("GET", r"/static/.+"), ("GET", r"/login"),
    ("GET", r"/api/health"),
    ("POST", r"/api/auth/(login|signup|logout|password)"), ("GET", r"/api/auth/info"), ("GET", r"/api/me"),
    ("POST", r"/api/auth/device/(login|launch|logout)"),
    ("GET", r"/api/devices"), ("DELETE", r"/api/devices/[0-9a-f]{16}"),
    ("GET", r"/api/status"), ("POST", r"/api/status"), ("POST", r"/api/recommend"),
    ("POST", r"/api/chat"), ("POST", r"/api/agent"), ("GET", r"/api/agent/info"), ("POST", r"/api/ideas"),
    ("GET", r"/api/tasks"), ("GET", r"/api/tasks/[\w-]+"), ("POST", r"/api/tasks/[\w-]+/(approve|cancel)"),
    ("GET", r"/api/conversations"), ("POST", r"/api/conversations"), ("POST", r"/api/conversations/chat"),
    ("GET", r"/api/conversations/[\w-]+"), ("PATCH", r"/api/conversations/[\w-]+"),
    ("DELETE", r"/api/conversations/[\w-]+"),
    ("GET", r"/api/settings"),
    ("GET", r"/api/skills"), ("GET", r"/api/skills/[\w.-]+"),
    ("GET", r"/api/memory"), ("POST", r"/api/memory"), ("DELETE", r"/api/memory/\d+"), ("PUT", r"/api/memory/\d+"),
    ("GET", r"/api/files"), ("POST", r"/api/files/upload"), ("GET", r"/api/files/(download|preview|inspect)"),
    ("POST", r"/api/files/archive"), ("POST", r"/api/files/delete"),
    ("GET", r"/api/admin/(users|settings|invites|usage|audit)"), ("PUT", r"/api/admin/settings"),
    ("PATCH", r"/api/admin/users/\w+"), ("DELETE", r"/api/admin/users/\w+"),
    ("POST", r"/api/admin/users/\w+/(bonus|reset|password)"), ("POST", r"/api/admin/users"),
    ("POST", r"/api/admin/invites"), ("DELETE", r"/api/admin/invites/\w+"),
    ("GET", r"/api/admin/devices"), ("DELETE", r"/api/admin/devices/[0-9a-f]{16}"),
]]


def is_hosted_only(path: str) -> bool:
    return path.startswith(("/api/auth/", "/api/admin/", "/api/devices")) or path in ("/api/me", "/login")


# -- native apps (Windows/macOS/Linux desktop, phones, VS Code) ---------------------------------
# Apps sign in with a device token (accounts.new_device). Their own pages may call only these few paths
# cross-origin, from the app origins below, without cookies (no credentials, so no CSRF risk).
APP_ORIGINS = ("tauri://localhost", "http://tauri.localhost", "https://tauri.localhost")
CORS_PATHS = {"/api/health", "/api/auth/info", "/api/auth/device/login", "/api/auth/device/launch",
              "/api/auth/device/logout", "/api/me"}


def app_origins() -> set[str]:
    from automoto import config

    extra = {o.strip().lower().rstrip("/") for o in (config.env("AUTOMOTO_APP_ORIGINS", "") or "").split(",")
             if o.strip()}
    return set(APP_ORIGINS) | extra


def cors_allowed(origin: str, path: str) -> bool:
    return path in CORS_PATHS and origin.strip().lower().rstrip("/") in app_origins()


def cors_headers(origin: str, preflight: bool = False) -> dict[str, str]:
    h = {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
    if preflight:
        h.update({"Access-Control-Allow-Methods": "GET, POST", "Access-Control-Max-Age": "600",
                  "Access-Control-Allow-Headers": "content-type, authorization"})
    return h


def secure_transport(request: Request) -> bool:
    """Device tokens and passwords from apps only over HTTPS, except to this computer itself."""
    from automoto import config, server

    if request.url.scheme == "https":
        return True
    if (config.env("AUTOMOTO_ALLOW_HTTP_DEVICES", "") or "").lower() in ("1", "true", "yes"):
        return True  # testing on a home network only - the token travels in clear text
    return server._host_name(request.headers.get("host", "")) in server.LOCAL_HOSTS and server._is_loopback(request)


def _device_guard(request: Request) -> None:
    from automoto import server

    if not secure_transport(request):
        raise HTTPException(403, "apps can sign in only over HTTPS (or to this computer itself)")
    origin = request.headers.get("origin")
    if origin is not None and origin.strip().lower().rstrip("/") not in app_origins() \
            and not server._origin_ok(origin, request.headers.get("host", "")):
        raise HTTPException(403, "this origin may not sign in apps")


def bearer_device(request: Request) -> tuple[accounts.User, dict[str, Any]] | None | bool:
    """False: no device token sent. None: a device token was sent but it is not valid (any more)."""
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() != "bearer ":
        return False
    tok = auth[7:].strip()
    if not tok.startswith(accounts.DEVICE_PREFIX):
        return False
    if not secure_transport(request):
        raise HTTPException(403, "device tokens are accepted only over HTTPS")
    return accounts.device_user(tok, client_ip(request))


def path_allowed(method: str, path: str) -> bool:
    m = "GET" if method == "HEAD" else method
    return any(m == am and rx.fullmatch(path) for am, rx in ALLOWED)


# -- auth rate limits (per IP and per username) -----------------------------------------------
_AUTH_HITS: dict[str, deque] = {}
_AUTH_LOCK = threading.Lock()
AUTH_PER_15MIN = 20


def _auth_limited(key: str, limit: int = AUTH_PER_15MIN, window: float = 900) -> bool:
    now = time.monotonic()
    with _AUTH_LOCK:
        q = _AUTH_HITS.setdefault(key, deque())
        while q and q[0] < now - window:
            q.popleft()
        if len(q) >= limit:
            return True
        q.append(now)
        if len(_AUTH_HITS) > 20000:  # bound memory
            for k in list(_AUTH_HITS)[:5000]:
                _AUTH_HITS.pop(k, None)
    return False


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def tenant_for(user: accounts.User) -> tenancy.Tenant:
    return tenancy.Tenant(user.id, user.username, user.role, accounts.user_home(user.id))


def current_user(request: Request) -> tuple[accounts.User, str] | None:
    return accounts.session_user(request.cookies.get(COOKIE, ""))


def authenticate(request: Request) -> accounts.User:
    """Session cookie + CSRF header (+ the Origin check in the server middleware) for hosted mode,
    or an app's device token (Authorization: Bearer amd_...; not sent automatically, so no CSRF check)."""
    dev = bearer_device(request)
    if dev is not False:
        if not dev:
            raise HTTPException(401, "this device was signed out - sign in again")
        user, device = dev  # type: ignore[misc]
        tenancy.set_current(tenant_for(user))
        request.state.user = user
        request.state.device = device
        return user
    got = current_user(request)
    if not got:
        raise HTTPException(401, "please sign in")
    user, csrf = got
    request.state.device = None
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        sent = request.headers.get("x-csrf-token", "")
        if not sent or not hmac.compare_digest(sent, csrf):
            raise HTTPException(403, "missing or wrong CSRF token - reload the page")
    tenancy.set_current(tenant_for(user))
    request.state.user = user
    return user


def require_admin(request: Request) -> accounts.User:
    from automoto import server

    server._authorise(request)
    user = request.state.user
    if not user.is_admin:
        raise HTTPException(403, "admins only")
    return user


def _cookie(resp: JSONResponse, request: Request, token: str, max_age: int | None) -> None:
    from automoto import config

    secure = request.url.scheme == "https" or (config.env("AUTOMOTO_COOKIE_SECURE", "") or "") in ("1", "true", "yes")
    resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/", secure=secure, max_age=max_age)


def _err(exc: accounts.AccountError, code: int = 400):
    raise HTTPException(code, str(exc)) from None


# -- auth endpoints --------------------------------------------------------------------------------
class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class SignupIn(LoginIn):
    invite: str = Field("", max_length=100)


class PasswordIn(BaseModel):
    current: str = Field(..., min_length=1, max_length=256)
    new: str = Field(..., min_length=1, max_length=256)


def _origin_required(request: Request) -> None:
    # login/signup set a cookie, so they must come from our own page (no login CSRF)
    from automoto import server

    origin = request.headers.get("origin")
    if not origin or not server._origin_ok(origin, request.headers.get("host", "")):
        raise HTTPException(403, "sign in from the AutoMoto page")


@router.get("/api/auth/info")
def auth_info() -> dict[str, Any]:
    return {"signup": accounts.get_setting("signup"), "min_password": accounts.MIN_PASSWORD}


@router.post("/api/auth/login")
def login(body: LoginIn, request: Request):
    _origin_required(request)
    ip = client_ip(request)
    if _auth_limited("ip:" + ip) or _auth_limited("user:" + body.username.strip().lower(), limit=10):
        raise HTTPException(429, "too many sign-in attempts - wait 15 minutes")
    try:
        user = accounts.authenticate(body.username, body.password)
    except accounts.AccountError as exc:
        raise HTTPException(401, str(exc)) from None
    tok, _ = accounts.new_session(user, ip)
    resp = JSONResponse({"ok": True, "user": user.public()})
    _cookie(resp, request, tok, int(accounts.session_days() * 86400))
    return resp


@router.post("/api/auth/signup")
def signup(body: SignupIn, request: Request):
    _origin_required(request)
    ip = client_ip(request)
    if _auth_limited("signup:" + ip, limit=5, window=3600) or _auth_limited("ip:" + ip):
        raise HTTPException(429, "too many sign-ups from here - try later")
    try:
        user = accounts.signup(body.username, body.password, body.invite, ip)
    except accounts.AccountError as exc:
        raise HTTPException(400, str(exc)) from None
    tok, _ = accounts.new_session(user, ip)
    resp = JSONResponse({"ok": True, "user": user.public()})
    _cookie(resp, request, tok, int(accounts.session_days() * 86400))
    return resp


@router.post("/api/auth/logout")
def logout(request: Request):
    from automoto import server

    server._authorise(request)
    accounts.end_session(request.cookies.get(COOKIE, ""))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@router.post("/api/auth/password")
def change_password(body: PasswordIn, request: Request):
    from automoto import server

    server._authorise(request)
    user = request.state.user
    if _auth_limited("pw:" + user.id, limit=10):
        raise HTTPException(429, "too many attempts")
    try:
        accounts.authenticate(user.username, body.current)
        accounts.set_password(user.id, body.new, actor=user.username)
    except accounts.AccountError as exc:
        raise HTTPException(400, str(exc)) from None
    tok, _ = accounts.new_session(user, client_ip(request))  # other sessions were signed out
    resp = JSONResponse({"ok": True})
    _cookie(resp, request, tok, int(accounts.session_days() * 86400))
    return resp


class DeviceLoginIn(LoginIn):
    device_name: str = Field("App", max_length=60)
    platform: str = Field("", max_length=30)


@router.post("/api/auth/device/login")
def device_login(body: DeviceLoginIn, request: Request) -> dict[str, Any]:
    """An app signs in once and gets a revocable device token (shown once; store it in the OS keychain)."""
    from automoto import __version__

    _device_guard(request)
    ip = client_ip(request)
    if _auth_limited("ip:" + ip) or _auth_limited("user:" + body.username.strip().lower(), limit=10):
        raise HTTPException(429, "too many sign-in attempts - wait 15 minutes")
    try:
        user = accounts.authenticate(body.username, body.password)
    except accounts.AccountError as exc:
        raise HTTPException(401, str(exc)) from None
    tok, dev = accounts.new_device(user, body.device_name, body.platform, ip)
    return {"ok": True, "token": tok, "device": dev, "user": user.public(), "server": {"version": __version__}}


def _require_device(request: Request) -> tuple[accounts.User, dict[str, Any]]:
    _device_guard(request)
    if _auth_limited("dev:" + client_ip(request), limit=120):
        raise HTTPException(429, "too many requests - wait a few minutes")
    dev = bearer_device(request)
    if dev is False:
        raise HTTPException(401, "send the device token: Authorization: Bearer amd_...")
    if not dev:
        raise HTTPException(401, "this device was signed out - sign in again")
    return dev  # type: ignore[return-value]


@router.post("/api/auth/device/launch")
def device_launch(request: Request) -> dict[str, Any]:
    """A one-time link (60 s) that opens the normal AutoMoto page, signed in, in the app's window."""
    user, dev = _require_device(request)
    code = accounts.device_launch_code(dev["id"], user.id)
    return {"path": "/?device_launch=" + code, "expires_in": 60, "user": user.public()}


@router.post("/api/auth/device/logout")
def device_logout(request: Request) -> dict[str, Any]:
    user, dev = _require_device(request)
    accounts.revoke_device(dev["id"], user.username, uid=user.id)
    return {"ok": True}


_OPENING = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>AutoMoto AI</title>
<meta http-equiv="refresh" content="1;url=/"><style>body{font:16px system-ui;background:#0b0f14;color:#e6edf3;
display:grid;place-items:center;min-height:100vh;margin:0}</style></head><body><p>Opening AutoMoto…</p></body></html>"""


def open_device_window(request: Request, code: str, headers: dict[str, str]):
    """``/?device_launch=<code>``: swap an app's one-time code for a normal session cookie in its window.
    A same-origin refresh (not a redirect) follows, so the SameSite=Strict cookie is sent with it."""
    from fastapi.responses import HTMLResponse

    if not secure_transport(request):
        return HTMLResponse("<h1>HTTPS required</h1>", status_code=403, headers=headers)
    ip = client_ip(request)
    if _auth_limited("launch:" + ip, limit=60):
        return HTMLResponse("<h1>Too many attempts - wait a few minutes</h1>", status_code=429, headers=headers)
    got = accounts.use_device_launch_code(code)
    if not got:
        resp = HTMLResponse(_OPENING, status_code=200, headers=headers)  # expired or used: the sign-in page follows
        return resp
    user, did = got
    tok, _ = accounts.new_session(user, ip, device_id=did)
    resp = HTMLResponse(_OPENING, headers={**headers, "Referrer-Policy": "no-referrer"})
    _cookie(resp, request, tok, int(accounts.session_days() * 86400))  # type: ignore[arg-type]
    return resp


@router.get("/api/devices")
def my_devices(request: Request) -> dict[str, Any]:
    from automoto import server

    server._authorise(request)
    user = request.state.user
    dev = getattr(request.state, "device", None)
    current = dev["id"] if dev else accounts.session_id(request.cookies.get(COOKIE, ""))
    if not dev:  # a window opened by an app: its session row says which device
        current = _session_device(request.cookies.get(COOKIE, "")) or current
    return {"devices": accounts.list_devices(user.id) + accounts.list_sessions(user.id), "current": current}


def _session_device(token: str) -> str | None:
    if not token:
        return None
    with accounts._db() as con:
        row = con.execute("SELECT device_id FROM sessions WHERE token=?", (accounts._h(token),)).fetchone()
    return row["device_id"] if row else None


@router.delete("/api/devices/{did}")
def my_device_revoke(did: str, request: Request) -> dict[str, Any]:
    from automoto import server

    server._authorise(request)
    user = request.state.user
    if accounts.revoke_device(did, user.username, uid=user.id) or accounts.end_session_by_id(user.id, did):
        return {"ok": True}
    raise HTTPException(404, "no such device")


@router.get("/api/me")
def me(request: Request) -> dict[str, Any]:
    from automoto import server

    server._authorise(request)
    user = request.state.user
    return {"mode": "multiuser", "user": user.public(), "quota": accounts.quota(user),
            "limits": {"max_upload_mb": server.max_upload() // 1048576,
                       "storage_mb": accounts.get_setting("storage_mb"),
                       "max_tasks": accounts.get_setting("max_tasks_per_user")}}


# -- admin endpoints -------------------------------------------------------------------------------
class UserPatch(BaseModel):
    quota_minutes: float | None = Field(None, ge=0, le=100000)
    default_quota: bool = False  # true = clear quota_minutes (use the default)
    unlimited: bool | None = None
    request_cap: int | None = Field(None, ge=0)
    token_cap: int | None = Field(None, ge=0)
    clear_caps: bool = False
    status: str | None = Field(None, pattern="^(active|suspended)$")
    role: str | None = Field(None, pattern="^(user|admin)$")
    note: str | None = Field(None, max_length=200)


class BonusIn(BaseModel):
    minutes: float = Field(..., gt=0, le=100000)
    days: float | None = Field(None, gt=0, le=365)  # empty = until the current period ends
    note: str = Field("", max_length=120)


class NewUserIn(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=1, max_length=256)
    role: str = Field("user", pattern="^(user|admin)$")
    quota_minutes: float | None = Field(None, ge=0, le=100000)


class AdminPasswordIn(BaseModel):
    password: str = Field(..., min_length=1, max_length=256)


class AdminSettingsIn(BaseModel):
    default_quota_minutes: float | None = Field(None, ge=0, le=100000)
    default_request_cap: int | None = Field(None, ge=0)
    default_token_cap: int | None = Field(None, ge=0)
    signup: str | None = Field(None, pattern="^(open|invite|closed)$")
    reset_hour: int | None = Field(None, ge=0, le=23)
    period_days: int | None = Field(None, ge=1, le=31)
    max_tasks_per_user: int | None = Field(None, ge=1, le=20)
    storage_mb: float | None = Field(None, ge=0, le=100000)


class InviteIn(BaseModel):
    uses: int = Field(1, ge=1, le=1000)
    days: float = Field(7, gt=0, le=365)
    label: str = Field("", max_length=80)


def _user_row(u: accounts.User) -> dict[str, Any]:
    from automoto import server

    return {**u.public(), "quota": accounts.quota(u), "running_tasks": server.TASKS.running(u.id)}


def _get(uid: str) -> accounts.User:
    u = accounts.get_user(uid)
    if not u:
        raise HTTPException(404, "no such user")
    return u


@router.get("/api/admin/users")
def admin_users(request: Request) -> dict[str, Any]:
    require_admin(request)
    return {"users": [_user_row(u) for u in accounts.list_users()], "settings": accounts.settings()}


@router.post("/api/admin/users")
def admin_create_user(body: NewUserIn, request: Request) -> dict[str, Any]:
    admin = require_admin(request)
    try:
        u = accounts.create_user(body.username, body.password, role=body.role, actor=admin.username,
                                 note="created by admin")
        if body.quota_minutes is not None:
            u = accounts.update_user(u.id, admin.username, quota_minutes=body.quota_minutes)
    except accounts.AccountError as exc:
        _err(exc)
    return _user_row(u)


@router.patch("/api/admin/users/{uid}")
def admin_patch_user(uid: str, body: UserPatch, request: Request) -> dict[str, Any]:
    admin = require_admin(request)
    u = _get(uid)
    fields: dict[str, Any] = {}
    if body.default_quota:
        fields["quota_minutes"] = None
    elif body.quota_minutes is not None:
        fields["quota_minutes"] = body.quota_minutes
    if body.clear_caps:
        fields["request_cap"] = fields["token_cap"] = None
    else:
        if body.request_cap is not None:
            fields["request_cap"] = body.request_cap
        if body.token_cap is not None:
            fields["token_cap"] = body.token_cap
    for k in ("unlimited", "status", "role", "note"):
        v = getattr(body, k)
        if v is not None:
            fields[k] = v
    if u.id == admin.id and (fields.get("status") == "suspended" or fields.get("role") == "user"):
        raise HTTPException(400, "you can't suspend or demote yourself")
    try:
        u = accounts.update_user(uid, admin.username, **fields)
    except accounts.AccountError as exc:
        _err(exc)
    if fields.get("status") == "suspended":
        from automoto import server

        for t in list(server.TASKS.tasks.values()):
            if t.owner == uid:
                server.TASKS.cancel(t.id)
    return _user_row(u)


@router.post("/api/admin/users/{uid}/bonus")
def admin_bonus(uid: str, body: BonusIn, request: Request) -> dict[str, Any]:
    admin = require_admin(request)
    _get(uid)
    try:
        accounts.add_bonus(uid, body.minutes, admin.username,
                           expires=time.time() + body.days * 86400 if body.days else None, note=body.note)
    except accounts.AccountError as exc:
        _err(exc)
    return _user_row(_get(uid))


@router.post("/api/admin/users/{uid}/reset")
def admin_reset(uid: str, request: Request) -> dict[str, Any]:
    admin = require_admin(request)
    _get(uid)
    accounts.reset_usage(uid, admin.username)
    return _user_row(_get(uid))


@router.post("/api/admin/users/{uid}/password")
def admin_password(uid: str, body: AdminPasswordIn, request: Request) -> dict[str, Any]:
    admin = require_admin(request)
    _get(uid)
    try:
        accounts.set_password(uid, body.password, admin.username)
    except accounts.AccountError as exc:
        _err(exc)
    return {"ok": True}


@router.delete("/api/admin/users/{uid}")
def admin_delete(uid: str, request: Request) -> dict[str, Any]:
    admin = require_admin(request)
    if uid == admin.id:
        raise HTTPException(400, "you can't delete yourself")
    _get(uid)
    from automoto import server

    for t in list(server.TASKS.tasks.values()):
        if t.owner == uid:
            server.TASKS.cancel(t.id)
    try:
        u = accounts.delete_user(uid, admin.username)
    except accounts.AccountError as exc:
        _err(exc)
    return {"ok": True, "deleted": u.username}


@router.get("/api/admin/settings")
def admin_settings(request: Request) -> dict[str, Any]:
    require_admin(request)
    return accounts.settings()


@router.put("/api/admin/settings")
def admin_settings_put(body: AdminSettingsIn, request: Request) -> dict[str, Any]:
    admin = require_admin(request)
    try:
        return accounts.set_settings(admin.username, **body.model_dump())
    except accounts.AccountError as exc:
        _err(exc)
    raise AssertionError  # pragma: no cover


@router.get("/api/admin/invites")
def admin_invites(request: Request) -> dict[str, Any]:
    require_admin(request)
    return {"invites": accounts.list_invites()}


@router.post("/api/admin/invites")
def admin_invite_new(body: InviteIn, request: Request) -> dict[str, Any]:
    admin = require_admin(request)
    try:
        code = accounts.create_invite(admin.username, uses=body.uses, days=body.days, label=body.label)
    except accounts.AccountError as exc:
        _err(exc)
    return {"code": code, "note": "shown once - copy it now"}


@router.delete("/api/admin/invites/{iid}")
def admin_invite_del(iid: str, request: Request) -> dict[str, Any]:
    admin = require_admin(request)
    return {"ok": accounts.revoke_invite(admin.username, iid)}


@router.get("/api/admin/usage")
def admin_usage(request: Request, user: str = "", limit: int = 200) -> dict[str, Any]:
    require_admin(request)
    uid = None
    if user:
        u = accounts.find_user(user)
        if not u:
            raise HTTPException(404, "no such user")
        uid = u.id
    return {"usage": accounts.usage_log(uid, max(1, min(int(limit), 2000)))}


@router.get("/api/admin/audit")
def admin_audit(request: Request, limit: int = 200) -> dict[str, Any]:
    require_admin(request)
    return {"audit": accounts.audit_log(max(1, min(int(limit), 2000)))}


@router.get("/api/admin/devices")
def admin_devices(request: Request, user: str = "") -> dict[str, Any]:
    require_admin(request)
    uid = None
    if user:
        u = accounts.find_user(user)
        if not u:
            raise HTTPException(404, "no such user")
        uid = u.id
    return {"devices": accounts.list_devices(uid)}


@router.delete("/api/admin/devices/{did}")
def admin_device_revoke(did: str, request: Request) -> dict[str, Any]:
    admin = require_admin(request)
    if not accounts.revoke_device(did, admin.username):
        raise HTTPException(404, "no such device")
    return {"ok": True}


def hosted_tools() -> dict[str, Any]:
    """The safe tool set for hosted users: research, files/office/archive/data in their own sandbox, memory, skills.
    No shell, no local apps, no desktop control, no services/connectors (their secrets are the host's)."""
    from automoto import tools as tools_mod

    tl = tools_mod.build(desktop=False, extra=[], local_apps=False, services=False, office=True, files=True)
    return {n: t for n, t in tl.items() if t.group in HOSTED_GROUPS and n not in BLOCKED_TOOLS}


# An allow-list: a new tool group stays out of hosted mode until it is reviewed and added here.
HOSTED_GROUPS = {"core", "web", "memory", "skills", "office", "archive", "wordpress", "data"}
BLOCKED_TOOLS = {"run_shell", "run_app"}
