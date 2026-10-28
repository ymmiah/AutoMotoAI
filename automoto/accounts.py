"""Accounts, sessions, usage quotas, invites and the admin audit log for hosted mode.

Everything lives in one SQLite file, ``<AUTOMOTO_DATA_DIR>/accounts.db`` (never inside a user's
folder). Passwords are hashed with scrypt (stdlib, memory-hard) and a per-user salt; session
tokens and invite codes are stored only as SHA-256 hashes.

Usage time ("minutes") = wall-clock seconds AutoMoto spends working for the user: every model call
(agent steps and chat replies) plus every tool run. Time spent waiting for the user (approvals,
reading, typing) is not counted. The allowance resets every period (default: daily at
00:00 UTC, see ``AUTOMOTO_QUOTA_RESET_HOUR``). It is checked before every model call.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from automoto import config, home


class AccountError(ValueError):
    """A user-facing problem (bad password, taken name, …)."""


USERNAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")
MIN_PASSWORD = 10
LOCK_AFTER = 5            # failed logins in a row
LOCK_MINUTES = 15
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
_DUMMY = None             # a real hash to compare against when the user doesn't exist (same timing)
_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, pw TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user',
  status TEXT NOT NULL DEFAULT 'active', created REAL NOT NULL, last_login REAL,
  quota_minutes REAL, unlimited INTEGER NOT NULL DEFAULT 0, request_cap INTEGER, token_cap INTEGER,
  usage_reset REAL NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0,
  note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL,
  ip TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, ts REAL NOT NULL, seconds REAL NOT NULL,
  requests INTEGER NOT NULL DEFAULT 0, tokens INTEGER NOT NULL DEFAULT 0, kind TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS usage_user_ts ON usage(user_id, ts);
CREATE TABLE IF NOT EXISTS bonuses (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, minutes REAL NOT NULL, expires REAL NOT NULL,
  created REAL NOT NULL, created_by TEXT NOT NULL, note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS invites (
  code TEXT PRIMARY KEY, label TEXT NOT NULL, uses_left INTEGER NOT NULL, expires REAL NOT NULL,
  created REAL NOT NULL, created_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
  target TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def db_path() -> Path:
    return home.base() / "accounts.db"


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    p = db_path()
    con = sqlite3.connect(str(p), timeout=15, isolation_level=None)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        con.executescript(SCHEMA)
        yield con
    finally:
        con.close()
    try:
        p.chmod(0o600)
    except OSError:  # pragma: no cover
        pass


# -- settings (admin-editable, env gives the first default) ------------------------------------
def _env_float(name: str, default: float) -> float:
    try:
        return float(config.env(name, str(default)) or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(config.env(name, str(default)) or default))
    except ValueError:
        return default


DEFAULTS = {
    "default_quota_minutes": lambda: _env_float("AUTOMOTO_DEFAULT_QUOTA_MINUTES", 60),
    "default_request_cap": lambda: _env_int("AUTOMOTO_DEFAULT_REQUEST_CAP", 0),   # model calls / period, 0 = none
    "default_token_cap": lambda: _env_int("AUTOMOTO_DEFAULT_TOKEN_CAP", 0),       # estimated tokens / period
    "signup": lambda: (config.env("AUTOMOTO_SIGNUP", "invite") or "invite").lower(),  # open | invite | closed
    "reset_hour": lambda: _env_int("AUTOMOTO_QUOTA_RESET_HOUR", 0),               # UTC hour the day starts
    "period_days": lambda: max(1, _env_int("AUTOMOTO_QUOTA_PERIOD_DAYS", 1)),     # 1 = daily, 7 = weekly
    "max_tasks_per_user": lambda: max(1, _env_int("AUTOMOTO_USER_MAX_TASKS", 2)),
    "storage_mb": lambda: _env_float("AUTOMOTO_USER_STORAGE_MB", 200),
}
SIGNUP_MODES = ("open", "invite", "closed")


def get_setting(key: str) -> Any:
    with _db() as con:
        row = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else DEFAULTS[key]()


def settings() -> dict[str, Any]:
    return {k: get_setting(k) for k in DEFAULTS}


def set_settings(actor: str, **values: Any) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for k, v in values.items():
        if v is None:
            continue
        if k not in DEFAULTS:
            raise AccountError(f"unknown setting {k!r}")
        if k == "signup":
            v = str(v).lower()
            if v not in SIGNUP_MODES:
                raise AccountError("signup must be open, invite or closed")
        elif k in ("default_quota_minutes", "storage_mb"):
            v = float(v)
            if v < 0 or v > 100000:
                raise AccountError(f"{k} must be between 0 and 100000")
        else:
            v = int(v)
            if v < 0 or (k == "reset_hour" and v > 23) or (k == "period_days" and not 1 <= v <= 31) \
                    or (k == "max_tasks_per_user" and not 1 <= v <= 20):
                raise AccountError(f"bad value for {k}")
        clean[k] = v
    with _db() as con:
        for k, v in clean.items():
            con.execute("INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (k, json.dumps(v)))
    if clean:
        audit(actor, "settings", "", json.dumps(clean))
    return settings()


# -- passwords ---------------------------------------------------------------------------------
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, dklen=32, maxmem=64 * 1024 * 1024, **_SCRYPT)
    b = lambda x: base64.b64encode(x).decode()  # noqa: E731
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${b(salt)}${b(dk)}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=32, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(got, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def check_password_rules(pw: str, username: str = "") -> None:
    if len(pw) < MIN_PASSWORD:
        raise AccountError(f"password must be at least {MIN_PASSWORD} characters")
    if len(pw) > 256:
        raise AccountError("password is too long")
    if username and username.lower() in pw.lower():
        raise AccountError("password must not contain the username")
    if len(set(pw)) < 4:
        raise AccountError("password is too simple")


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# -- users ---------------------------------------------------------------------------------------
@dataclass
class User:
    id: str
    username: str
    role: str
    status: str
    created: float
    last_login: float | None
    quota_minutes: float | None
    unlimited: bool
    request_cap: int | None
    token_cap: int | None
    usage_reset: float
    note: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "username": self.username, "role": self.role, "status": self.status,
                "created": self.created, "last_login": self.last_login, "quota_minutes": self.quota_minutes,
                "unlimited": self.unlimited, "request_cap": self.request_cap, "token_cap": self.token_cap,
                "note": self.note}


def _user(row: sqlite3.Row | None) -> User | None:
    if not row:
        return None
    return User(row["id"], row["username"], row["role"], row["status"], row["created"], row["last_login"],
                row["quota_minutes"], bool(row["unlimited"]), row["request_cap"], row["token_cap"],
                row["usage_reset"], row["note"])


def norm_username(name: str) -> str:
    n = (name or "").strip().lower()
    if not USERNAME.match(n):
        raise AccountError("username: 3-32 characters, a-z 0-9 . _ - (starting with a letter or digit)")
    return n


def create_user(username: str, password: str, *, role: str = "user", actor: str = "system",
                note: str = "") -> User:
    name = norm_username(username)
    check_password_rules(password, name)
    if role not in ("user", "admin"):
        raise AccountError("role must be user or admin")
    uid = secrets.token_hex(8)
    with _db() as con:
        try:
            con.execute("INSERT INTO users(id, username, pw, role, created, note) VALUES(?,?,?,?,?,?)",
                        (uid, name, hash_password(password), role, time.time(), note[:200]))
        except sqlite3.IntegrityError:
            raise AccountError("that username is taken") from None
    audit(actor, "create_user", name, json.dumps({"role": role}))
    return get_user(uid)  # type: ignore[return-value]


def get_user(uid: str) -> User | None:
    with _db() as con:
        return _user(con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())


def find_user(username_or_id: str) -> User | None:
    key = (username_or_id or "").strip().lower()
    with _db() as con:
        return _user(con.execute("SELECT * FROM users WHERE username=? OR id=?", (key, key)).fetchone())


def list_users() -> list[User]:
    with _db() as con:
        return [_user(r) for r in con.execute("SELECT * FROM users ORDER BY created")]  # type: ignore[misc]


def admin_count() -> int:
    with _db() as con:
        return con.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND status='active'").fetchone()[0]


def update_user(uid: str, actor: str, **fields: Any) -> User:
    u = get_user(uid)
    if not u:
        raise AccountError("no such user")
    allowed = {"quota_minutes", "unlimited", "request_cap", "token_cap", "status", "role", "note"}
    sets: dict[str, Any] = {}
    for k, v in fields.items():
        if k not in allowed:
            raise AccountError(f"can't change {k}")
        if k == "status":
            if v not in ("active", "suspended"):
                raise AccountError("status must be active or suspended")
        elif k == "role":
            if v not in ("user", "admin"):
                raise AccountError("role must be user or admin")
        elif k == "quota_minutes" and v is not None:
            v = float(v)
            if not 0 <= v <= 100000:
                raise AccountError("quota_minutes must be between 0 and 100000 (or empty for the default)")
        elif k in ("request_cap", "token_cap") and v is not None:
            v = int(v)
            if v < 0:
                raise AccountError(f"{k} can't be negative")
        elif k == "unlimited":
            v = 1 if v else 0
        elif k == "note":
            v = str(v)[:200]
        sets[k] = v
    demoting = (sets.get("role") == "user" or sets.get("status") == "suspended") and u.is_admin
    if demoting and admin_count() <= 1:
        raise AccountError("you can't remove or suspend the last admin")
    if sets:
        with _db() as con:
            con.execute(f"UPDATE users SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",  # nosec B608 - keys are allow-listed
                        (*sets.values(), uid))
            if sets.get("status") == "suspended":
                con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        audit(actor, "update_user", u.username, json.dumps(sets))
    return get_user(uid)  # type: ignore[return-value]


def set_password(uid: str, password: str, actor: str) -> None:
    u = get_user(uid)
    if not u:
        raise AccountError("no such user")
    check_password_rules(password, u.username)
    with _db() as con:
        con.execute("UPDATE users SET pw=?, failed=0, locked_until=0 WHERE id=?", (hash_password(password), uid))
        con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    audit(actor, "set_password", u.username)


def delete_user(uid: str, actor: str) -> User:
    u = get_user(uid)
    if not u:
        raise AccountError("no such user")
    if u.is_admin and admin_count() <= 1:
        raise AccountError("you can't delete the last admin")
    with _db() as con:
        for t in ("sessions", "usage", "bonuses"):
            con.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))  # nosec B608 - fixed table names
        con.execute("DELETE FROM users WHERE id=?", (uid,))
    import shutil

    d = user_home(uid)
    if d.is_dir() and d.parent == (home.base() / "users").resolve():
        shutil.rmtree(d, ignore_errors=True)
    audit(actor, "delete_user", u.username)
    return u


def user_home(uid: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{16}", uid):
        raise AccountError("bad user id")
    return (home.base() / "users" / uid).resolve()


# -- login, lockout, sessions ---------------------------------------------------------------------
def session_days() -> float:
    return max(0.05, _env_float("AUTOMOTO_SESSION_DAYS", 7))


def authenticate(username: str, password: str) -> User:
    """Check a password. Raises AccountError with a deliberately vague message."""
    global _DUMMY
    bad = AccountError("wrong username or password")
    try:
        name = norm_username(username)
    except AccountError:
        name = ""
    with _db() as con:
        row = con.execute("SELECT * FROM users WHERE username=?", (name,)).fetchone() if name else None
    if row is None:
        if _DUMMY is None:
            _DUMMY = hash_password(secrets.token_hex(8))
        verify_password(password, _DUMMY)  # same work as a real check
        raise bad
    now = time.time()
    if row["locked_until"] > now:
        mins = int((row["locked_until"] - now) // 60) + 1
        raise AccountError(f"too many failed sign-ins - try again in {mins} minute(s)")
    if not verify_password(password, row["pw"]):
        failed = row["failed"] + 1
        locked = now + LOCK_MINUTES * 60 if failed >= LOCK_AFTER else 0
        with _db() as con:
            con.execute("UPDATE users SET failed=?, locked_until=? WHERE id=?",
                        (0 if locked else failed, locked, row["id"]))
        if locked:
            audit("system", "lockout", row["username"], f"{LOCK_AFTER} failed sign-ins")
        raise bad
    if row["status"] != "active":
        raise AccountError("this account is suspended - contact the admin")
    with _db() as con:
        con.execute("UPDATE users SET failed=0, locked_until=0, last_login=? WHERE id=?", (now, row["id"]))
    return _user(row)  # type: ignore[return-value]


def new_session(user: User, ip: str = "") -> tuple[str, str]:
    """Returns (session token, csrf token). Only the token's hash is stored."""
    tok, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    now = time.time()
    with _db() as con:
        con.execute("DELETE FROM sessions WHERE expires < ?", (now,))
        con.execute("INSERT INTO sessions(token, user_id, csrf, created, expires, ip) VALUES(?,?,?,?,?,?)",
                    (_h(tok), user.id, csrf, now, now + session_days() * 86400, ip[:64]))
    return tok, csrf


def session_user(token: str) -> tuple[User, str] | None:
    """(user, csrf) for a live session of an active user, else None."""
    if not token or len(token) > 200:
        return None
    with _db() as con:
        row = con.execute("SELECT s.csrf, s.expires, u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                          "WHERE s.token=?", (_h(token),)).fetchone()
    if not row or row["expires"] < time.time() or row["status"] != "active":
        return None
    return _user(row), row["csrf"]  # type: ignore[return-value]


def end_session(token: str) -> None:
    with _db() as con:
        con.execute("DELETE FROM sessions WHERE token=?", (_h(token),))


# -- invites -------------------------------------------------------------------------------------
def create_invite(actor: str, *, uses: int = 1, days: float = 7, label: str = "") -> str:
    if not 1 <= int(uses) <= 1000 or not 0 < float(days) <= 365:
        raise AccountError("uses 1-1000, days up to 365")
    code = "am-" + secrets.token_urlsafe(12)
    with _db() as con:
        con.execute("INSERT INTO invites(code, label, uses_left, expires, created, created_by) VALUES(?,?,?,?,?,?)",
                    (_h(code), label[:80] or code[:7] + "…", int(uses), time.time() + float(days) * 86400,
                     time.time(), actor))
    audit(actor, "create_invite", label[:80], json.dumps({"uses": int(uses), "days": float(days)}))
    return code


def list_invites() -> list[dict[str, Any]]:
    with _db() as con:
        return [{"id": r["code"][:12], "label": r["label"], "uses_left": r["uses_left"], "expires": r["expires"],
                 "created": r["created"], "created_by": r["created_by"]}
                for r in con.execute("SELECT * FROM invites WHERE uses_left > 0 AND expires > ? ORDER BY created DESC",
                                     (time.time(),))]


def revoke_invite(actor: str, invite_id: str) -> bool:
    if not re.fullmatch(r"[0-9a-f]{6,64}", invite_id or ""):
        return False
    with _db() as con:
        n = con.execute("DELETE FROM invites WHERE substr(code, 1, ?) = ?", (len(invite_id), invite_id)).rowcount
    if n:
        audit(actor, "revoke_invite", invite_id)
    return bool(n)


def signup(username: str, password: str, invite: str = "", ip: str = "") -> User:
    mode = get_setting("signup")
    if mode == "closed":
        raise AccountError("sign-up is closed - ask the admin for an account")
    code_h = None
    if mode == "invite":
        if not invite:
            raise AccountError("sign-up needs an invite code from the admin")
        code_h = _h(invite.strip())
        with _LOCK, _db() as con:
            n = con.execute("UPDATE invites SET uses_left = uses_left - 1 WHERE code=? AND uses_left > 0 AND expires > ?",
                            (code_h, time.time())).rowcount
        if not n:
            raise AccountError("that invite code is invalid, used up or expired")
    try:
        u = create_user(username, password, actor="signup", note=f"signed up{' with invite' if code_h else ''}")
    except AccountError:
        if code_h:  # give the use back
            with _db() as con:
                con.execute("UPDATE invites SET uses_left = uses_left + 1 WHERE code=?", (code_h,))
        raise
    return u


# -- usage & quota --------------------------------------------------------------------------------
def period_start(now: float | None = None) -> float:
    """Start of the current quota period (UTC), e.g. today 00:00 UTC."""
    now = time.time() if now is None else now
    hour, days = int(get_setting("reset_hour")), int(get_setting("period_days"))
    dt = datetime.fromtimestamp(now, timezone.utc)
    start = dt.replace(hour=hour, minute=0, second=0, microsecond=0)
    if start > dt:
        start -= timedelta(days=1)
    if days > 1:  # weekly etc.: periods counted from 2024-01-01 (a Monday)
        epoch = datetime(2024, 1, 1, hour, tzinfo=timezone.utc)
        n = (start - epoch).days // days
        start = epoch + timedelta(days=n * days)
    return start.timestamp()


def period_end(now: float | None = None) -> float:
    return period_start(now) + int(get_setting("period_days")) * 86400


def record(uid: str, seconds: float, *, requests: int = 0, tokens: int = 0, kind: str = "model",
           detail: str = "") -> None:
    if seconds <= 0 and not requests and not tokens:
        return
    with _db() as con:
        con.execute("INSERT INTO usage(user_id, ts, seconds, requests, tokens, kind, detail) VALUES(?,?,?,?,?,?,?)",
                    (uid, time.time(), max(0.0, float(seconds)), int(requests), int(tokens), kind[:20], detail[:120]))


def add_bonus(uid: str, minutes: float, actor: str, *, expires: float | None = None, note: str = "") -> dict[str, Any]:
    u = get_user(uid)
    if not u:
        raise AccountError("no such user")
    minutes = float(minutes)
    if not 0 < minutes <= 100000:
        raise AccountError("bonus minutes must be between 0 and 100000")
    exp = float(expires) if expires else period_end()
    if exp <= time.time():
        raise AccountError("the bonus would already be expired")
    with _db() as con:
        con.execute("INSERT INTO bonuses(user_id, minutes, expires, created, created_by, note) VALUES(?,?,?,?,?,?)",
                    (uid, minutes, exp, time.time(), actor, note[:120]))
    audit(actor, "bonus", u.username, json.dumps({"minutes": minutes, "expires": exp, "note": note[:120]}))
    return quota(u)


def reset_usage(uid: str, actor: str) -> dict[str, Any]:
    u = get_user(uid)
    if not u:
        raise AccountError("no such user")
    with _db() as con:
        con.execute("UPDATE users SET usage_reset=? WHERE id=?", (time.time(), uid))
    audit(actor, "reset_usage", u.username)
    return quota(get_user(uid))  # type: ignore[arg-type]


def quota(u: User, now: float | None = None) -> dict[str, Any]:
    """The user's allowance and use in the current period."""
    now = time.time() if now is None else now
    start, end = period_start(now), period_end(now)
    since = max(start, u.usage_reset or 0)
    with _db() as con:
        row = con.execute("SELECT COALESCE(SUM(seconds),0) s, COALESCE(SUM(requests),0) r, COALESCE(SUM(tokens),0) t "
                          "FROM usage WHERE user_id=? AND ts>=?", (u.id, since)).fetchone()
        bonus = con.execute("SELECT COALESCE(SUM(minutes),0) FROM bonuses WHERE user_id=? AND expires>? AND created<=?",
                            (u.id, now, now)).fetchone()[0]
    base = float(u.quota_minutes if u.quota_minutes is not None else get_setting("default_quota_minutes"))
    req_cap = u.request_cap if u.request_cap is not None else int(get_setting("default_request_cap"))
    tok_cap = u.token_cap if u.token_cap is not None else int(get_setting("default_token_cap"))
    allowance = base + float(bonus)
    used_min = row["s"] / 60
    unlimited = u.unlimited or u.is_admin  # the owner/admins are never limited
    left = None if unlimited else max(0.0, allowance - used_min)
    reason = ""
    if u.status != "active":
        reason = "this account is suspended"
    elif not unlimited:
        if used_min >= allowance:
            reason = f"you've used your {_fmt_min(allowance)} for this period"
        elif req_cap and row["r"] >= req_cap:
            reason = f"you've used your {req_cap} AI requests for this period"
        elif tok_cap and row["t"] >= tok_cap:
            reason = f"you've used your ~{tok_cap:,} tokens for this period"
    return {"unlimited": unlimited, "base_minutes": base, "bonus_minutes": float(bonus), "allowance_minutes": allowance,
            "used_minutes": round(used_min, 2), "used_seconds": round(row["s"], 1), "left_minutes": None if left is None else round(left, 2),
            "requests": row["r"], "request_cap": req_cap or None, "tokens": row["t"], "token_cap": tok_cap or None,
            "period_start": start, "resets_at": end, "blocked": bool(reason), "reason": reason}


def _fmt_min(m: float) -> str:
    if m >= 60 and abs(m / 60 - round(m / 60)) < 1e-9:
        h = int(round(m / 60))
        return f"{h} hour{'s' if h != 1 else ''}"
    return f"{m:g} minute{'s' if m != 1 else ''}"


def limit_message(q: dict[str, Any]) -> str:
    when = datetime.fromtimestamp(q["resets_at"], timezone.utc)
    left = max(0, int(q["resets_at"] - time.time()))
    return (f"Usage limit reached: {q['reason']}. It resets at {when:%H:%M} UTC on {when:%a %d %b} "
            f"(in {left // 3600}h {left % 3600 // 60}m). Ask the admin if you need more time.")


class Meter:
    """Passed to the agent loop: ``check()`` before each model call, ``add()`` after each model/tool call."""

    def __init__(self, uid: str):
        self.uid = uid

    def check(self) -> str | None:
        u = get_user(self.uid)
        if not u:
            return "Your account no longer exists."
        q = quota(u)
        return limit_message(q) if q["blocked"] else None

    def add(self, seconds: float, *, requests: int = 0, tokens: int = 0, kind: str = "model", detail: str = "") -> None:
        record(self.uid, seconds, requests=requests, tokens=tokens, kind=kind, detail=detail)


def usage_log(uid: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    base = "SELECT g.*, u.username FROM usage g LEFT JOIN users u ON u.id = g.user_id "
    with _db() as con:
        if uid:
            rows = con.execute(base + "WHERE g.user_id=? ORDER BY g.id DESC LIMIT ?", (uid, int(limit))).fetchall()
        else:
            rows = con.execute(base + "ORDER BY g.id DESC LIMIT ?", (int(limit),)).fetchall()
    return [{"ts": r["ts"], "user": r["username"] or r["user_id"], "seconds": round(r["seconds"], 2),
             "requests": r["requests"], "tokens": r["tokens"], "kind": r["kind"], "detail": r["detail"]} for r in rows]


def prune(days: float = 90) -> None:
    cut = time.time() - days * 86400
    with _db() as con:
        con.execute("DELETE FROM usage WHERE ts < ?", (cut,))
        con.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
        con.execute("DELETE FROM bonuses WHERE expires < ?", (cut,))


# -- audit -----------------------------------------------------------------------------------------
def audit(actor: str, action: str, target: str = "", detail: str = "") -> None:
    with _db() as con:
        con.execute("INSERT INTO audit(ts, actor, action, target, detail) VALUES(?,?,?,?,?)",
                    (time.time(), actor[:40], action[:40], target[:80], detail[:500]))


def audit_log(limit: int = 200) -> list[dict[str, Any]]:
    with _db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (int(limit),))]


def bootstrap_admin_from_env() -> str | None:
    """Create the first admin from AUTOMOTO_ADMIN_USER / AUTOMOTO_ADMIN_PASSWORD (hosts without a shell)."""
    name, pw = config.env("AUTOMOTO_ADMIN_USER"), config.env("AUTOMOTO_ADMIN_PASSWORD")
    if not name or not pw:
        return None
    existing = find_user(name)
    if existing:
        return None
    if admin_count() > 0:
        return None
    create_user(name, pw, role="admin", actor="env-bootstrap", note="bootstrap admin")
    return norm_username(name)
