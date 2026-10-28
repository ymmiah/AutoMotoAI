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
    ("GET", r"/api/status"), ("POST", r"/api/status"), ("POST", r"/api/recommend"),
    ("POST", r"/api/chat"), ("POST", r"/api/agent"), ("GET", r"/api/agent/info"),
    ("GET", r"/api/tasks"), ("GET", r"/api/tasks/[\w-]+"), ("POST", r"/api/tasks/[\w-]+/(approve|cancel)"),
    ("GET", r"/api/conversations"), ("POST", r"/api/conversations"), ("POST", r"/api/conversations/chat"),
    ("GET", r"/api/conversations/[\w-]+"), ("PATCH", r"/api/conversations/[\w-]+"),
    ("DELETE", r"/api/conversations/[\w-]+"),
    ("GET", r"/api/settings"),
    ("GET", r"/api/skills"), ("GET", r"/api/skills/[\w.-]+"),
    ("GET", r"/api/memory"), ("POST", r"/api/memory"), ("DELETE", r"/api/memory/\d+"),
    ("GET", r"/api/files"), ("POST", r"/api/files/upload"), ("GET", r"/api/files/(download|preview|inspect)"),
    ("POST", r"/api/files/archive"), ("POST", r"/api/files/delete"),
    ("GET", r"/api/admin/(users|settings|invites|usage|audit)"), ("PUT", r"/api/admin/settings"),
    ("PATCH", r"/api/admin/users/\w+"), ("DELETE", r"/api/admin/users/\w+"),
    ("POST", r"/api/admin/users/\w+/(bonus|reset|password)"), ("POST", r"/api/admin/users"),
    ("POST", r"/api/admin/invites"), ("DELETE", r"/api/admin/invites/\w+"),
]]


def is_hosted_only(path: str) -> bool:
    return path.startswith(("/api/auth/", "/api/admin/")) or path in ("/api/me", "/login")


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
    """Session cookie + CSRF header (+ the Origin check in the server middleware) for hosted mode."""
    got = current_user(request)
    if not got:
        raise HTTPException(401, "please sign in")
    user, csrf = got
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


def hosted_tools() -> dict[str, Any]:
    """The safe tool set for hosted users: research, files/office/archive/data in their own sandbox, memory, skills.
    No shell, no local apps, no desktop control, no services/connectors (their secrets are the host's)."""
    from automoto import tools as tools_mod

    tl = tools_mod.build(desktop=False, extra=[], local_apps=False, services=False, office=True, files=True)
    return {n: t for n, t in tl.items() if t.group in HOSTED_GROUPS and n not in BLOCKED_TOOLS}


# An allow-list: a new tool group stays out of hosted mode until it is reviewed and added here.
HOSTED_GROUPS = {"core", "web", "memory", "skills", "office", "archive", "wordpress", "data"}
BLOCKED_TOOLS = {"run_shell", "run_app"}
