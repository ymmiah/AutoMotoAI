"""Secure sign-in to GitHub and GitLab for the Developer Studio (V46-V48 plan, PR 2).

* **Primary sign-in: a pasted fine-grained personal access token.** No app registration is needed.
  The token is checked against an allowlisted host only (github.com, gitlab.com and self-managed
  GitLab servers the user added), then shown back as the signed-in user, expiry and scopes, with
  warnings when it is too broad or never expires.
* **Tokens live only in the OS keychain** (Windows Credential Manager, macOS Keychain, Secret
  Service/libsecret on Linux) through the ``keyring`` package. Plaintext keyring backends are
  refused. With no keychain, a token is kept in this process's memory for the session only, and
  only after the user agrees. Tokens never go to files, Git config, remote URLs, logs, browser
  storage or any API response: the UI only ever sees a masked handle ("ends in 4f2a").
* **Device flow (GitHub) and PKCE / device grant (GitLab)** are implemented but stay **disabled**
  unless a public client ID is configured (``AUTOMOTO_GITHUB_CLIENT_ID`` /
  ``AUTOMOTO_GITLAB_CLIENT_ID`` in the real environment or ``~/.automoto/.env``; a project .env
  is ignored). No client secret is ever used or stored.
* An audit log (``git-auth-audit.jsonl``) records sign-ins, sign-outs, expiries and migrations,
  never a token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request

from automoto import brand, config, netguard, redaction

redaction.install_log_redaction()

VERSION = "git-auth-1"
KEYRING_SERVICE = f"{brand.DEFAULT_NAME} Git"
MAX_HOSTS = 10
ENV_VARS = {"GITHUB_TOKEN": "github", "GH_TOKEN": "github", "GITLAB_TOKEN": "gitlab"}
GITLAB_MIN_SCOPES = ("read_user", "read_api", "write_repository")
GITLAB_BROAD = {"api": "full API access, including deleting projects",
                "sudo": "acting as other users", "admin_mode": "administrator actions",
                "write_registry": "pushing container images", "create_runner": "creating CI runners",
                "manage_runner": "managing CI runners", "k8s_proxy": "Kubernetes clusters",
                "self_rotate": "making new tokens"}
GITHUB_BROAD = {"repo": "every repository you can reach, public and private",
                "workflow": "changing GitHub Actions workflows",
                "delete_repo": "deleting repositories", "admin:org": "managing organisations",
                "admin:repo_hook": "managing webhooks", "admin:public_key": "managing SSH keys",
                "admin:gpg_key": "managing GPG keys", "write:packages": "publishing packages",
                "user": "changing your profile and email", "admin:enterprise": "managing an enterprise",
                "codespace": "codespaces", "project": "projects"}
_GH_FINE = re.compile(r"^github_pat_[A-Za-z0-9_]{50,255}$")
_GH_CLASSIC = re.compile(r"^ghp_[A-Za-z0-9]{30,251}$")
_GH_OAUTH = re.compile(r"^gh[ou]_[A-Za-z0-9]{30,251}$")
_GL_TOKEN = re.compile(r"^[A-Za-z0-9_\-.]{20,255}$")
_HOST_RE = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_CLIENT_ID = re.compile(r"^[A-Za-z0-9._-]{8,128}$")

router = APIRouter(prefix="/api/developer/studio/account", tags=["developer-account"])
_lock = threading.RLock()
_session: dict[str, dict] = {}  # session-only secrets (no keychain), never written anywhere
_refresh_locks: dict[str, threading.Lock] = {}


class AuthError(Exception):
    """A plain-words problem the UI can show as is (never contains a token)."""

    def __init__(self, message: str, status: int = 400, code: str = "error"):
        super().__init__(redaction.redact(message))
        self.status, self.code = status, code


# ------------------------------------------------------------------ providers and hosts
PROVIDERS = {
    "github": {"name": "GitHub", "default_host": "github.com", "fixed": True},
    "gitlab": {"name": "GitLab", "default_host": "gitlab.com", "fixed": False},
}


def _data() -> Path:
    from automoto import home

    return home.base()


def _hosts_file() -> Path:
    return _data() / "git-hosts.json"


def saved_hosts() -> list[str]:
    try:
        data = json.loads(_hosts_file().read_text("utf-8"))
        return [h for h in data.get("gitlab", []) if isinstance(h, str) and _HOST_RE.match(h)][:MAX_HOSTS]
    except (OSError, ValueError, AttributeError):
        return []


def allowed_hosts(provider: str) -> list[str]:
    if provider == "github":
        return ["github.com"]
    if provider == "gitlab":
        return ["gitlab.com", *[h for h in saved_hosts() if h != "gitlab.com"]]
    return []


def normalise_host(raw: str) -> str:
    s = str(raw or "").strip().lower()
    if "://" in s:
        parts = urllib.parse.urlsplit(s)
        if parts.scheme != "https":
            raise AuthError("Only https:// servers are allowed.")
        if parts.username or parts.password or parts.port not in (None, 443):
            raise AuthError("Enter just the server address, like gitlab.example.com.")
        s = parts.hostname or ""
    s = s.strip("/").rstrip(".")
    try:
        s = s.encode("idna").decode("ascii")
    except UnicodeError:
        raise AuthError("That doesn't look like a server address.") from None
    if not _HOST_RE.match(s) or s in ("localhost",) or s.endswith(".localhost") or s.endswith(".local"):
        raise AuthError("Enter a public server address like gitlab.example.com (no IP addresses or local names).")
    if s in ("github.com", "api.github.com") or s.endswith(".github.com"):
        raise AuthError("GitHub is already built in. Add only your own GitLab server here.")
    return s


def add_host(raw: str, *, resolve: bool = True) -> list[str]:
    host = normalise_host(raw)
    if host == "gitlab.com":
        return allowed_hosts("gitlab")
    if resolve:
        try:
            netguard.check_url(f"https://{host}/")
        except netguard.BlockedURL as exc:
            raise AuthError(f"Can't use {host}: {exc}") from None
    with _lock:
        hosts = saved_hosts()
        if host not in hosts:
            if len(hosts) >= MAX_HOSTS:
                raise AuthError(f"You can save up to {MAX_HOSTS} servers. Remove one first.")
            hosts.append(host)
            _write_json(_hosts_file(), {"gitlab": hosts})
    audit("host_added", "gitlab", host, "ok")
    return allowed_hosts("gitlab")


def remove_host(raw: str) -> list[str]:
    host = normalise_host(raw)
    with _lock:
        hosts = [h for h in saved_hosts() if h != host]
        _write_json(_hosts_file(), {"gitlab": hosts})
    if account("gitlab", host):
        sign_out("gitlab", host)
    audit("host_removed", "gitlab", host, "ok")
    return allowed_hosts("gitlab")


def check_target(provider: str, host: str | None) -> tuple[str, str]:
    if provider not in PROVIDERS:
        raise AuthError("Choose GitHub or GitLab.")
    h = (host or PROVIDERS[provider]["default_host"]).strip().lower()
    if h not in allowed_hosts(provider):
        raise AuthError(f"{h} isn't on your list of allowed servers. Add it first.", code="host_not_allowed")
    return provider, h


def api_base(provider: str, host: str) -> str:
    return "https://api.github.com" if provider == "github" else f"https://{host}/api/v4"


def _api_host(provider: str, host: str) -> str:
    return "api.github.com" if provider == "github" else host


def token_page(provider: str, host: str) -> dict[str, Any]:
    """Where to make a token, pre-filled with the least access the Developer Studio needs."""
    short = brand.short()
    if provider == "github":
        q = urllib.parse.urlencode({
            "name": f"{short} Developer Studio"[:40],
            "description": f"Used by {short} on this computer to share your work. You can delete it any time.",
            "expires_in": "30", "contents": "write", "pull_requests": "write", "statuses": "read", "actions": "read"})
        return {"url": f"https://github.com/settings/personal-access-tokens/new?{q}",
                "kind": "Fine-grained token",
                "steps": ["Under Repository access, choose Only select repositories and pick the ones to share.",
                          "Keep the 30-day expiry. You can make a new token when it ends.",
                          "Leave every other permission set to No access."],
                "permissions": [["Contents", "Read and write", "send and get your code"],
                                ["Pull requests", "Read and write", "ask for a review"],
                                ["Commit statuses", "Read-only", "see if checks passed"],
                                ["Actions", "Read-only", "read check results"],
                                ["Metadata", "Read-only", "always included by GitHub"]],
                "never": ["Workflows", "Administration", "Secrets", "Webhooks"]}
    q = urllib.parse.urlencode({"name": f"{short} Developer Studio",
                                "description": f"Used by {short} on this computer. You can revoke it any time.",
                                "scopes": ",".join(GITLAB_MIN_SCOPES)})
    return {"url": f"https://{host}/-/user_settings/personal_access_tokens?{q}",
            "kind": "Personal access token",
            "steps": ["Pick an expiry date about 30 days away.",
                      "Keep only read_user, read_api and write_repository ticked.",
                      "Click Create token, then copy it."],
            "permissions": [["read_user", "Read", "show who you are"],
                            ["read_api", "Read", "see projects, reviews and check results"],
                            ["write_repository", "Read and write", "send and get your code"]],
            "never": ["api (only needed later, for review requests)", "sudo", "admin_mode"]}


def revoke_help(provider: str, host: str, kind: str = "pat") -> dict[str, Any]:
    if provider == "github":
        if kind == "oauth":
            return {"url": "https://github.com/settings/apps/authorizations",
                    "text": f"Open GitHub's Authorized apps page and remove {brand.short()} to turn it off everywhere."}
        url = "https://github.com/settings/tokens" if kind == "classic" else "https://github.com/settings/personal-access-tokens"
        return {"url": url, "text": "Open your GitHub tokens page and delete the token to turn it off everywhere."}
    return {"url": f"https://{host}/-/user_settings/personal_access_tokens",
            "text": "Open your GitLab access tokens page and click Revoke to turn it off everywhere."}


# ------------------------------------------------------------------ keychain vault
_SECURE_BACKENDS = {"keyring.backends.Windows.WinVaultKeyring": "Windows Credential Manager",
                    "keyring.backends.macOS.Keyring": "macOS Keychain",
                    "keyring.backends.SecretService.Keyring": "your system keyring (Secret Service)",
                    "keyring.backends.libsecret.Keyring": "your system keyring (libsecret)",
                    "keyring.backends.kwallet.DBusKeyring": "KDE Wallet"}
_backend_override: Any = None  # tests inject a fake OS keychain here


def _backend() -> tuple[Any, str] | tuple[None, None]:
    if _backend_override is not None:
        return _backend_override, getattr(_backend_override, "label", "test keychain")
    try:
        import keyring
    except Exception:
        return None, None
    try:
        kr = keyring.get_keyring()
    except Exception:
        return None, None
    found = _secure_label(kr)
    return (kr, found) if found else (None, None)


def _secure_label(kr: Any) -> str | None:
    name = f"{type(kr).__module__}.{type(kr).__name__}"
    if name == "keyring.backends.chainer.ChainerBackend":
        kids = list(getattr(kr, "backends", []) or [])
        labels = [_secure_label(k) for k in kids]
        return labels[0] if kids and all(labels) else None
    return _SECURE_BACKENDS.get(name)


def keychain() -> dict[str, Any]:
    kr, label = _backend()
    return {"available": kr is not None, "label": label or "",
            "fallback": "session" if kr is None else None}


def _entry(provider: str, host: str) -> str:
    return f"{provider}:{host}"


def _vault_put(provider: str, host: str, record: dict, session_only: bool) -> str:
    blob = json.dumps(record, separators=(",", ":"))
    key = _entry(provider, host)
    if not session_only:
        kr, _ = _backend()
        if kr is None:
            raise AuthError("No password store was found on this computer. Tick “Keep me signed in until "
                            f"{brand.short()} closes” to use the token for this session only.", code="no_keychain")
        try:
            kr.set_password(KEYRING_SERVICE, key, blob)
        except Exception:
            raise AuthError("Your computer's password store refused to save the token. Unlock it and try "
                            "again, or choose session only.", code="keychain_failed") from None
        with _lock:
            _session.pop(key, None)
        return "keychain"
    with _lock:
        _session[key] = record
    return "session"


def _vault_get(provider: str, host: str) -> dict | None:
    key = _entry(provider, host)
    with _lock:
        if key in _session:
            return dict(_session[key])
    kr, _ = _backend()
    if kr is None:
        return None
    try:
        blob = kr.get_password(KEYRING_SERVICE, key)
    except Exception:
        return None
    if not blob:
        return None
    try:
        rec = json.loads(blob)
    except ValueError:
        return None
    return rec if isinstance(rec, dict) and rec.get("token") else None


def _vault_delete(provider: str, host: str) -> None:
    key = _entry(provider, host)
    with _lock:
        old = _session.pop(key, None)
    if old:
        redaction.forget(old.get("token"))
    kr, _ = _backend()
    if kr is not None:
        try:
            rec = kr.get_password(KEYRING_SERVICE, key)
            if rec:
                try:
                    redaction.forget(json.loads(rec).get("token"))
                except ValueError:
                    pass
            kr.delete_password(KEYRING_SERVICE, key)
        except Exception:
            pass


# ------------------------------------------------------------------ public account index (no secrets)
def _index_file() -> Path:
    return _data() / "git-accounts.json"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{secrets.token_hex(4)}.tmp")
    tmp.write_text(json.dumps(data, indent=1), "utf-8")
    os.replace(tmp, path)


def _index() -> list[dict]:
    try:
        data = json.loads(_index_file().read_text("utf-8"))
        return [a for a in data.get("accounts", []) if isinstance(a, dict)]
    except (OSError, ValueError, AttributeError):
        return []


def _save_index(items: list[dict]) -> None:
    _write_json(_index_file(), {"version": VERSION, "accounts": items})


_PUBLIC = ("provider", "host", "login", "name", "user_id", "web_url", "token_kind", "handle", "expires_at",
           "scopes", "storage", "status", "checked_at", "warnings", "permissions_note")


def _public(a: dict) -> dict:
    out = {k: a.get(k) for k in _PUBLIC}
    out["provider_name"] = PROVIDERS.get(a.get("provider", ""), {}).get("name", "")
    out["revoke"] = revoke_help(a.get("provider", ""), a.get("host", ""), a.get("token_kind", "pat"))
    exp = _parse_time(a.get("expires_at"))
    out["days_left"] = None if exp is None else int((exp - _now()).total_seconds() // 86400)
    return out


def accounts() -> list[dict]:
    items = _index()
    changed = False
    for a in items:
        if a.get("storage") == "session" and _entry(a["provider"], a["host"]) not in _session:
            a["status"] = "signed_out"
            changed = True
        exp = _parse_time(a.get("expires_at"))
        if exp is not None and exp <= _now() and a.get("status") == "ok" and a.get("token_kind") != "oauth":
            # (OAuth sign-ins renew themselves with their refresh token in token_for)
            a["status"] = "expired"
            changed = True
    if changed:
        items = [a for a in items if a.get("status") != "signed_out"]
        _save_index(items)
    return items


def account(provider: str, host: str) -> dict | None:
    return next((a for a in accounts() if a.get("provider") == provider and a.get("host") == host), None)


def _upsert(a: dict) -> None:
    with _lock:
        items = [x for x in _index() if not (x.get("provider") == a["provider"] and x.get("host") == a["host"])]
        items.append(a)
        _save_index(items)


def _drop(provider: str, host: str) -> None:
    with _lock:
        _save_index([x for x in _index() if not (x.get("provider") == provider and x.get("host") == host)])


# ------------------------------------------------------------------ helpers
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def _parse_time(v: Any) -> datetime | None:
    if not v:
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if fmt == "%Y-%m-%d":  # GitLab: the token ends at midnight UTC at the end of that date
            dt = dt.replace(hour=23, minute=59, second=59)
        return dt
    return None


def _handle(token: str) -> str:
    return "ends in " + token[-4:] if len(token) >= 24 else "saved"


def audit(action: str, provider: str, host: str, result: str, **extra: Any) -> None:
    line = {"time": _iso(_now()), "action": action, "provider": provider, "host": host, "result": result}
    for k, v in extra.items():
        if isinstance(v, (str, int, bool)) or v is None:
            line[k] = v
    text = redaction.redact(json.dumps(line, ensure_ascii=False))
    try:
        p = _data() / "git-auth-audit.jsonl"
        if p.exists() and p.stat().st_size > 2_000_000:
            os.replace(p, p.with_suffix(".jsonl.1"))
        with open(p, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass


# ------------------------------------------------------------------ HTTP (allowlisted)
# Tests swap this for a fake server. Signature: (method, url, headers, data) -> (status, headers, body).
def _default_http(method: str, url: str, headers: dict[str, str], data: bytes | None = None,
                  allow: tuple[str, ...] = ()) -> tuple[int, dict, bytes]:
    r = netguard.request(url, method=method, data=data, headers=headers, timeout=20, max_redirects=0,
                         allow_hosts=set(allow))
    return r.status, r.headers, r.body


http_call: Callable[..., tuple[int, dict, bytes]] = _default_http


def _call(provider: str, host: str, method: str, url: str, headers: dict, data: bytes | None = None,
          token: str = "", raw: bool = False) -> tuple[int, dict, Any]:
    allow = (_api_host(provider, host), host)
    try:
        status, hdrs, body = http_call(method, url, headers, data, allow)
    except netguard.BlockedURL as exc:
        raise AuthError(f"Couldn't reach {host}: {exc}", status=502, code="network") from None
    except OSError as exc:
        raise AuthError(f"Couldn't reach {host}. Check your internet connection. ({type(exc).__name__})",
                        status=502, code="network") from None
    # OAuth token endpoints answer with the new token itself (raw=True): it is parsed here and goes
    # straight to the keychain. Every other answer is scrubbed before anything can show or log it.
    text = body.decode("utf-8", "replace")
    if not raw:
        text = redaction.redact(text, (token,) if token else ())
    try:
        parsed: Any = json.loads(text) if text.strip() else {}
    except ValueError:
        parsed = {"raw": text[:300]}
    return status, {k.lower(): v for k, v in (hdrs or {}).items()}, parsed


def _auth_headers(provider: str, token: str, kind: str) -> dict[str, str]:
    h = {"User-Agent": f"{brand.short()}-Developer-Studio", "Accept": "application/json"}
    if provider == "github":
        h.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                  "X-GitHub-Api-Version": "2022-11-28"})
    elif kind == "oauth":
        h["Authorization"] = f"Bearer {token}"
    else:
        h["PRIVATE-TOKEN"] = token
    return h


# ------------------------------------------------------------------ token checks
def token_kind(provider: str, token: str) -> str:
    t = token.strip()
    if provider == "github":
        if _GH_FINE.match(t):
            return "fine_grained"
        if _GH_CLASSIC.match(t):
            return "classic"
        if _GH_OAUTH.match(t):
            return "oauth"
        if t.startswith(("ghs_", "ghr_")):
            raise AuthError("That's an app or refresh token. Paste a fine-grained personal access token "
                            "(it starts with github_pat_).", code="bad_format")
        raise AuthError("That doesn't look like a GitHub token. A fine-grained token starts with github_pat_.",
                        code="bad_format")
    if t.startswith(("github_pat_", "ghp_")):
        raise AuthError("That's a GitHub token. Choose GitHub instead, or paste your GitLab token.", code="bad_format")
    if not _GL_TOKEN.match(t):
        raise AuthError("That doesn't look like a GitLab token. It usually starts with glpat-.", code="bad_format")
    return "pat"


def _warnings(provider: str, kind: str, scopes: list[str], expires: datetime | None) -> list[dict]:
    out: list[dict] = []
    if provider == "github" and kind == "classic":
        out.append({"level": "high", "code": "classic",
                    "text": "This is a classic token. It can reach every repository you can. Make a fine-grained "
                            "token for only the repositories you want to share, and use that instead."})
    broad = GITHUB_BROAD if provider == "github" else GITLAB_BROAD
    too = [s for s in scopes if s in broad or (provider == "github" and s.startswith("admin:"))]
    if too:
        what = "; ".join(f"{s} ({broad.get(s, 'admin access')})" for s in too)
        out.append({"level": "high", "code": "broad_scopes",
                    "text": f"This token can do more than the Developer Studio needs: {what}. "
                            "Make a new token with fewer permissions."})
    if expires is None:
        out.append({"level": "high", "code": "no_expiry",
                    "text": "This token never expires. If it leaks it works forever. Make one that ends in about 30 days."})
    else:
        left = (expires - _now()).total_seconds() / 86400
        if left > 366:
            out.append({"level": "medium", "code": "long_expiry",
                        "text": "This token lasts more than a year. A shorter one (about 30 days) is safer."})
        elif left < 7:
            out.append({"level": "info", "code": "expires_soon",
                        "text": f"This token ends in {max(0, int(left))} day{'s' if int(left) != 1 else ''}. "
                                "Make a new one soon."})
    return out


def validate(provider: str, host: str, token: str, kind: str | None = None) -> dict[str, Any]:
    """Ask the provider who this token belongs to. Returns public facts only."""
    provider, host = check_target(provider, host)
    token = token.strip()
    kind = kind or token_kind(provider, token)
    redaction.register(token)
    hdrs = _auth_headers(provider, token, kind)
    base = api_base(provider, host)
    status, h, user = _call(provider, host, "GET", base + "/user", hdrs, token=token)
    name = PROVIDERS[provider]["name"]
    if status == 401:
        raise AuthError(f"{name} says this token isn't valid. It may have expired or been deleted. Make a new one.",
                        status=401, code="invalid")
    if status == 403:
        raise AuthError(f"{name} refused this token (403). If your organisation uses single sign-on, authorise "
                        "the token for it on the tokens page, then try again.", status=403, code="forbidden")
    if status >= 400 or not isinstance(user, dict) or not user.get("id"):
        raise AuthError(f"{name} answered with an error ({status}). Try again in a minute.", status=502,
                        code="provider_error")
    scopes: list[str] = []
    expires: datetime | None = None
    note = None
    if provider == "github":
        scopes = [s.strip() for s in (h.get("x-oauth-scopes") or "").split(",") if s.strip()]
        expires = _parse_time(h.get("github-authentication-token-expiration"))
        if kind == "fine_grained":
            note = "Repository access and permissions are the ones you picked on GitHub."
        login, web = user.get("login"), user.get("html_url")
    else:
        s2, _, me = _call(provider, host, "GET", base + "/personal_access_tokens/self", hdrs, token=token) \
            if kind == "pat" else (0, {}, {})
        if s2 == 200 and isinstance(me, dict):
            scopes = [str(x) for x in me.get("scopes") or []]
            expires = _parse_time(me.get("expires_at"))
            if me.get("active") is False or me.get("revoked"):
                raise AuthError("GitLab says this token was revoked or has expired. Make a new one.", status=401,
                                code="invalid")
        else:
            note = "GitLab didn't share this token's scopes."
        login, web = user.get("username"), user.get("web_url")
    if expires is not None and expires <= _now():
        raise AuthError(f"This token expired on {expires:%d %b %Y}. Make a new one.", status=401, code="expired")
    return {"login": str(login or "")[:100], "name": str(user.get("name") or "")[:120],
            "user_id": user.get("id"), "web_url": str(web or "")[:300], "scopes": scopes[:40],
            "expires_at": _iso(expires), "token_kind": kind, "warnings": _warnings(provider, kind, scopes, expires),
            "permissions_note": note}


def sign_in_with_token(provider: str, host: str | None, token: str, *, session_only: bool = False,
                       source: str = "pasted", refresh: dict | None = None) -> dict:
    provider, host = check_target(provider, host)
    token = str(token or "").strip()
    if not token:
        raise AuthError("Paste your token first.", code="empty")
    if len(token) > 400 or any(c.isspace() for c in token):
        raise AuthError("That doesn't look like a token. Copy it again from the token page.", code="bad_format")
    facts = validate(provider, host, token)
    record = {"v": 1, "token": token, "kind": facts["token_kind"], "saved_at": _iso(_now())}
    if refresh:
        record.update(refresh)
    storage = _vault_put(provider, host, record, session_only)
    acct = {"provider": provider, "host": host, **facts, "handle": _handle(token), "storage": storage,
            "status": "ok", "checked_at": _iso(_now())}
    _upsert(acct)
    audit("signin", provider, host, "ok", storage=storage, source=source, token_kind=facts["token_kind"])
    return _public(acct)


def check(provider: str, host: str | None) -> dict:
    provider, host = check_target(provider, host)
    acct = account(provider, host)
    rec = _vault_get(provider, host)
    if not acct or not rec:
        if acct:
            _drop(provider, host)
        raise AuthError("You're not signed in here any more. Connect again.", status=404, code="signed_out")
    try:
        facts = validate(provider, host, rec["token"], rec.get("kind"))
    except AuthError as exc:
        if exc.code in ("invalid", "expired"):
            mark_expired(provider, host)
        raise
    acct.update(facts, status="ok", checked_at=_iso(_now()))
    _upsert(acct)
    return _public(acct)


def mark_expired(provider: str, host: str) -> None:
    """The provider said the token no longer works: wipe the secret, keep a friendly note."""
    _vault_delete(provider, host)
    acct = account(provider, host)
    if acct:
        acct.update(status="expired", checked_at=_iso(_now()))
        _upsert(acct)
    audit("expired", provider, host, "token_rejected")


def sign_out(provider: str, host: str | None) -> dict:
    provider, host = check_target(provider, host) if provider in PROVIDERS and \
        (host or PROVIDERS[provider]["default_host"]) in allowed_hosts(provider) else (provider, host or "")
    acct = next((a for a in _index() if a.get("provider") == provider and a.get("host") == host), None)
    _vault_delete(provider, host)
    _drop(provider, host)
    audit("signout", provider, host, "ok")
    return {"signed_out": True, "revoke": revoke_help(provider, host, (acct or {}).get("token_kind", "pat"))}


def sign_out_all() -> dict:
    for a in list(_index()):
        _vault_delete(a.get("provider", ""), a.get("host", ""))
    with _lock:
        _session.clear()
        _pending.clear()
    _save_index([])
    audit("signout_all", "*", "*", "ok")
    return {"signed_out": True}


def token_for(provider: str, host: str | None = None) -> tuple[str, str, str] | None:
    """(token, host, kind) for internal use only (services.py, later the Git credential helper).
    Never returned by any endpoint. Refreshes OAuth tokens that are about to expire."""
    if provider not in PROVIDERS or _hosted():
        return None
    cands = [a for a in accounts() if a.get("provider") == provider and a.get("status") == "ok"]
    if host:
        cands = [a for a in cands if a.get("host") == host]
    cands = [a for a in cands if a.get("host") in allowed_hosts(provider)]
    for a in sorted(cands, key=lambda x: x.get("host") != PROVIDERS[provider]["default_host"]):
        rec = _vault_get(provider, a["host"])
        if not rec:
            continue
        exp = _parse_time(a.get("expires_at"))
        if rec.get("refresh_token") and exp is not None and (exp - _now()).total_seconds() < 600:
            rec = _refresh(provider, a["host"], rec) or None
            if not rec:
                continue
        elif exp is not None and exp <= _now():
            continue
        redaction.register(rec["token"])
        return rec["token"], a["host"], rec.get("kind", "pat")
    return None


def _hosted() -> bool:
    """A hosted multi-user server never uses the operator's keychain for anyone's requests."""
    try:
        from automoto import tenancy

        return tenancy.multiuser()
    except Exception:
        return False


# ------------------------------------------------------------------ plaintext .env migration
def env_tokens() -> list[dict]:
    """GitHub/GitLab tokens sitting in plaintext (.env files or the environment). No values."""
    out = []
    for var, provider in ENV_VARS.items():
        val = os.environ.get(var, "").strip()
        if not val or config.real_key(val) is None:
            continue
        src = config.env_source(var)
        out.append({"var": var, "provider": provider, "provider_name": PROVIDERS[provider]["name"],
                    "file": src, "can_remove": bool(src),
                    "where": src or "a system environment variable"})
    return out


def _strip_env_line(path: str, var: str) -> bool:
    p = Path(path)
    try:
        lines = p.read_text("utf-8").splitlines(keepends=True)
    except OSError:
        return False
    pat = re.compile(r"^\s*(?:export\s+)?" + re.escape(var) + r"\s*=")
    keep = [ln for ln in lines if not pat.match(ln)]
    if len(keep) == len(lines):
        return False
    tmp = p.with_name(p.name + f".{secrets.token_hex(4)}.tmp")
    tmp.write_text("".join(keep), "utf-8")
    try:
        os.chmod(tmp, p.stat().st_mode & 0o777)
    except OSError:
        pass
    os.replace(tmp, p)
    return True


def migrate(var: str, *, session_only: bool = False, host: str | None = None) -> dict:
    if var not in ENV_VARS:
        raise AuthError("Only GITHUB_TOKEN, GH_TOKEN and GITLAB_TOKEN can be moved.")
    provider = ENV_VARS[var]
    val = os.environ.get(var, "").strip()
    if not val:
        raise AuthError(f"{var} isn't set any more.", code="gone")
    if provider == "gitlab" and not host:
        trusted = config.env_trusted("GITLAB_URL")
        host = urllib.parse.urlsplit(trusted).hostname if trusted and trusted.startswith("https://") else None
        host = host if host in allowed_hosts("gitlab") else "gitlab.com"
    src = config.env_source(var)
    acct = sign_in_with_token(provider, host, val, session_only=session_only, source="env")
    removed = False
    if src and not session_only:
        removed = _strip_env_line(src, var)
        if removed:
            for other, p in ENV_VARS.items():  # GH_TOKEN and GITHUB_TOKEN are often the same value
                if other != var and p == provider and os.environ.get(other, "").strip() == val:
                    o_src = config.env_source(other)
                    if o_src:
                        _strip_env_line(o_src, other)
                    os.environ.pop(other, None)
            os.environ.pop(var, None)
    audit("migrate", provider, acct["host"], "ok", var=var, removed_from_file=removed)
    return {"account": acct, "removed_from_file": removed, "file": src,
            "note": None if removed else (f"{var} is set outside {brand.short()}. Remove it from your system "
                                          "settings yourself so it isn't stored in plain text."
                                          if not src else "The line was kept because you chose session only.")}


# ------------------------------------------------------------------ OAuth (disabled without a client ID)
_pending: dict[str, dict] = {}
GITHUB_SCOPES = ""  # GitHub Apps ignore scopes; permissions come from the app registration
GITLAB_OAUTH_SCOPES = " ".join(GITLAB_MIN_SCOPES)
LOOPBACK_PORT = 7171
CALLBACK_PATH = "/automoto/callback"


def client_id(provider: str) -> str | None:
    v = config.env_trusted("AUTOMOTO_GITHUB_CLIENT_ID" if provider == "github" else "AUTOMOTO_GITLAB_CLIENT_ID")
    return v if v and _CLIENT_ID.match(v) else None


def flows() -> dict[str, bool]:
    gh, gl = bool(client_id("github")), bool(client_id("gitlab"))
    return {"github_device": gh, "gitlab_pkce": gl, "gitlab_device": gl}


def _need_client(provider: str) -> str:
    cid = client_id(provider)
    if not cid:
        raise AuthError("Browser sign-in isn't set up in this build. Use a token instead.", status=409,
                        code="flow_disabled")
    return cid


def _form(provider: str, host: str, url: str, fields: dict) -> tuple[int, Any]:
    status, _, body = _call(provider, host, "POST", url,
                            {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded",
                             "User-Agent": f"{brand.short()}-Developer-Studio"},
                            urllib.parse.urlencode(fields).encode(), raw=True)
    if isinstance(body, dict):
        for k in ("access_token", "refresh_token", "device_code"):
            if isinstance(body.get(k), str):
                redaction.register(body[k])
    return status, body


def device_start(provider: str, host: str | None = None) -> dict:
    provider, host = check_target(provider, host)
    cid = _need_client(provider)
    if provider == "github":
        status, d = _form(provider, host, "https://github.com/login/device/code", {"client_id": cid})
    else:
        status, d = _form(provider, host, f"https://{host}/oauth/authorize_device",
                          {"client_id": cid, "scope": GITLAB_OAUTH_SCOPES})
    if status >= 400 or not isinstance(d, dict) or not d.get("device_code"):
        raise AuthError("Couldn't start browser sign-in. Use a token instead.", status=502, code="flow_failed")
    verify = str(d.get("verification_uri") or "")
    vhost = urllib.parse.urlsplit(verify).hostname
    if not verify.startswith("https://") or vhost not in (host, "github.com"):
        raise AuthError("The sign-in page address looked wrong, so it was not opened.", status=502, code="flow_failed")
    fid = secrets.token_urlsafe(16)
    with _lock:
        _pending[fid] = {"type": "device", "provider": provider, "host": host, "device_code": d["device_code"],
                         "interval": max(5, int(d.get("interval") or 5)), "next": time.time(),
                         "expires": time.time() + min(900, int(d.get("expires_in") or 900))}
    return {"flow_id": fid, "user_code": str(d.get("user_code") or "")[:20], "verification_uri": verify,
            "expires_in": min(900, int(d.get("expires_in") or 900)), "interval": _pending[fid]["interval"],
            "warning": "Only enter a code that " + brand.short() + " shows you right now. Never enter a code someone sends you."}


def device_poll(fid: str, *, session_only: bool = False) -> dict:
    with _lock:
        f = _pending.get(fid)
    if not f or f["type"] != "device":
        raise AuthError("That sign-in has ended. Start again.", status=404, code="flow_gone")
    if time.time() > f["expires"]:
        _pending.pop(fid, None)
        raise AuthError("The code expired. Start again.", status=410, code="expired_token")
    if time.time() < f["next"]:
        return {"status": "pending", "interval": f["interval"]}
    provider, host = f["provider"], f["host"]
    cid = _need_client(provider)
    url = "https://github.com/login/oauth/access_token" if provider == "github" else f"https://{host}/oauth/token"
    status, d = _form(provider, host, url, {"client_id": cid, "device_code": f["device_code"],
                                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
    err = d.get("error") if isinstance(d, dict) else "bad_response"
    f["next"] = time.time() + f["interval"]
    if err == "authorization_pending":
        return {"status": "pending", "interval": f["interval"]}
    if err == "slow_down":
        f["interval"] += 5
        f["next"] = time.time() + f["interval"]
        return {"status": "pending", "interval": f["interval"]}
    _pending.pop(fid, None)
    if err == "expired_token":
        raise AuthError("The code expired. Start again.", status=410, code="expired_token")
    if err == "access_denied":
        raise AuthError("Sign-in was cancelled.", status=403, code="access_denied")
    if err or not d.get("access_token"):
        raise AuthError("Sign-in didn't finish. Try again or use a token.", status=502, code="flow_failed")
    return {"status": "done", "account": _finish_oauth(provider, host, d, session_only)}


def _finish_oauth(provider: str, host: str, d: dict, session_only: bool) -> dict:
    extra: dict[str, Any] = {}
    if d.get("refresh_token"):
        extra["refresh_token"] = d["refresh_token"]
        redaction.register(d["refresh_token"])
    if d.get("expires_in"):
        extra["access_expires"] = _iso(datetime.fromtimestamp(time.time() + int(d["expires_in"]), timezone.utc))
    redaction.register(d["access_token"])
    acct = _sign_in_oauth(provider, host, d["access_token"], extra, session_only)
    return acct


def _sign_in_oauth(provider: str, host: str, token: str, extra: dict, session_only: bool) -> dict:
    facts = validate(provider, host, token, "oauth")
    if extra.get("access_expires"):
        facts["expires_at"] = extra["access_expires"]
        facts["warnings"] = [w for w in facts["warnings"] if w["code"] not in ("no_expiry", "expires_soon")]
    record = {"v": 1, "token": token, "kind": "oauth", "saved_at": _iso(_now()), **extra}
    storage = _vault_put(provider, host, record, session_only)
    acct = {"provider": provider, "host": host, **facts, "handle": "browser sign-in", "storage": storage,
            "status": "ok", "checked_at": _iso(_now())}
    _upsert(acct)
    audit("signin", provider, host, "ok", storage=storage, source="oauth", token_kind="oauth")
    return _public(acct)


def _refresh(provider: str, host: str, rec: dict) -> dict | None:
    """Single-flight refresh with rotation: the new pair is saved before the old one is dropped."""
    lk = _refresh_locks.setdefault(_entry(provider, host), threading.Lock())
    with lk:
        latest = _vault_get(provider, host) or rec
        exp = _parse_time(latest.get("access_expires"))
        if exp is not None and (exp - _now()).total_seconds() >= 600:
            return latest  # another thread already refreshed
        cid = client_id(provider)
        if not cid or not latest.get("refresh_token"):
            mark_expired(provider, host)
            return None
        url = "https://github.com/login/oauth/access_token" if provider == "github" else f"https://{host}/oauth/token"
        try:
            status, d = _form(provider, host, url, {"client_id": cid, "grant_type": "refresh_token",
                                                    "refresh_token": latest["refresh_token"]})
        except AuthError:
            return None
        if status >= 400 or not isinstance(d, dict) or not d.get("access_token"):
            mark_expired(provider, host)
            audit("refresh_failed", provider, host, str((d or {}).get("error") or status))
            return None
        new = dict(latest, token=d["access_token"], refresh_token=d.get("refresh_token") or latest["refresh_token"],
                   access_expires=_iso(datetime.fromtimestamp(time.time() + int(d.get("expires_in") or 28800),
                                                              timezone.utc)))
        redaction.register(new["token"])
        redaction.register(new["refresh_token"])
        acct = account(provider, host) or {}
        _vault_put(provider, host, new, acct.get("storage") == "session")
        if acct:
            acct["expires_at"] = new["access_expires"]
            _upsert(acct)
        redaction.forget(latest.get("token"))
        return new


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(72)[:96]  # 43-128 unreserved characters (RFC 7636)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode().rstrip("=")
    return verifier, challenge


class _Callback(BaseHTTPRequestHandler):
    flow: dict = {}

    def do_GET(self):  # noqa: N802 (http.server API)
        parts = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(parts.query)
        f = self.server.flow  # type: ignore[attr-defined]
        ok = parts.path == CALLBACK_PATH and hmac.compare_digest((q.get("state") or [""])[0], f["state"])
        if ok and q.get("code"):
            f["code"] = q["code"][0]
        elif ok:
            f["error"] = (q.get("error") or ["access_denied"])[0][:60]
        msg = "You can close this tab and go back to the app." if ok else "This sign-in link isn't valid."
        body = f"<!doctype html><meta charset=utf-8><title>Sign-in</title><p>{msg}</p>".encode()
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)
        if ok:
            f["done"] = True

    def log_message(self, *a):  # never log the callback URL (it carries the code)
        return


def pkce_start(host: str | None = None, *, port: int | None = None, timeout: float = 300) -> dict:
    provider, host = check_target("gitlab", host)
    cid = _need_client(provider)
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(32)
    try:
        srv = HTTPServer(("127.0.0.1", LOOPBACK_PORT if port is None else port), _Callback)
    except OSError:
        raise AuthError("The sign-in helper port is busy. Use the code sign-in or a token instead.", status=409,
                        code="port_busy") from None
    flow = {"type": "pkce", "provider": provider, "host": host, "state": state, "verifier": verifier,
            "expires": time.time() + timeout, "done": False}
    srv.flow = flow  # type: ignore[attr-defined]
    srv.timeout = 1
    redirect = f"http://127.0.0.1:{srv.server_address[1]}{CALLBACK_PATH}"
    flow["redirect"] = redirect

    def serve():
        try:
            while not flow["done"] and time.time() < flow["expires"]:
                srv.handle_request()
        finally:
            srv.server_close()

    threading.Thread(target=serve, daemon=True, name="automoto-pkce").start()
    fid = secrets.token_urlsafe(16)
    with _lock:
        _pending[fid] = flow
    q = urllib.parse.urlencode({"client_id": cid, "redirect_uri": redirect, "response_type": "code", "state": state,
                                "scope": GITLAB_OAUTH_SCOPES, "code_challenge": challenge,
                                "code_challenge_method": "S256"})
    return {"flow_id": fid, "authorize_url": f"https://{host}/oauth/authorize?{q}", "expires_in": int(timeout)}


def pkce_poll(fid: str, *, session_only: bool = False) -> dict:
    with _lock:
        f = _pending.get(fid)
    if not f or f["type"] != "pkce":
        raise AuthError("That sign-in has ended. Start again.", status=404, code="flow_gone")
    if f.get("error"):
        _pending.pop(fid, None)
        raise AuthError("Sign-in was cancelled.", status=403, code="access_denied")
    if not f.get("code"):
        if time.time() > f["expires"]:
            _pending.pop(fid, None)
            raise AuthError("Sign-in timed out. Start again.", status=410, code="expired_token")
        return {"status": "pending"}
    _pending.pop(fid, None)
    cid = _need_client("gitlab")
    status, d = _form("gitlab", f["host"], f"https://{f['host']}/oauth/token",
                      {"client_id": cid, "code": f["code"], "grant_type": "authorization_code",
                       "redirect_uri": f["redirect"], "code_verifier": f["verifier"]})
    if status >= 400 or not isinstance(d, dict) or not d.get("access_token"):
        raise AuthError("GitLab didn't accept the sign-in. Try again or use a token.", status=502, code="flow_failed")
    return {"status": "done", "account": _finish_oauth("gitlab", f["host"], d, session_only)}


# ------------------------------------------------------------------ status for the UI
def status() -> dict:
    accts = [_public(a) for a in accounts()]
    return {"version": VERSION, "accounts": accts, "keychain": keychain(), "flows": flows(),
            "hosts": {"github": allowed_hosts("github"), "gitlab": allowed_hosts("gitlab")},
            "token_pages": {"github": token_page("github", "github.com"),
                            **{f"gitlab:{h}": token_page("gitlab", h) for h in allowed_hosts("gitlab")}},
            "env_tokens": env_tokens()}


# ------------------------------------------------------------------ HTTP API (local only)
def _auth(request: Request) -> None:
    from automoto import developer_studio as studio

    studio._auth(request)


async def _body(request: Request) -> dict:
    # Parsed by hand (not a pydantic model) so a validation error can never echo the token back.
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "send JSON") from None
    if not isinstance(data, dict):
        raise HTTPException(400, "send a JSON object")
    return data


def _str(d: dict, k: str, limit: int = 300) -> str:
    v = d.get(k)
    return v.strip()[:limit] if isinstance(v, str) else ""


def _guard(payload: dict, *secrets_: str) -> dict:
    """Last check before answering: no token, in any form, may leave in a response."""
    text = json.dumps(payload)
    for s in secrets_:
        if s and redaction.contains_secret(text, s):
            raise HTTPException(500, "blocked a response that contained a secret")
    return payload


def _run(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except AuthError as exc:
        raise HTTPException(exc.status if 400 <= exc.status < 600 else 400,
                            {"message": str(exc), "code": exc.code}) from None


@router.get("/status")
def api_status(request: Request):
    _auth(request)
    return status()


@router.post("/token")
async def api_token(request: Request):
    _auth(request)
    d = await _body(request)
    tok = d.get("token") if isinstance(d.get("token"), str) else ""
    d["token"] = None
    try:
        out = _run(sign_in_with_token, _str(d, "provider", 20), _str(d, "host", 260) or None, tok,
                   session_only=bool(d.get("session_only")))
        return _guard({"account": out}, tok)
    finally:
        tok = ""


@router.post("/check")
async def api_check(request: Request):
    _auth(request)
    d = await _body(request)
    return {"account": _run(check, _str(d, "provider", 20), _str(d, "host", 260) or None)}


@router.post("/signout")
async def api_signout(request: Request):
    _auth(request)
    d = await _body(request)
    if d.get("all"):
        return _run(sign_out_all)
    return _run(sign_out, _str(d, "provider", 20), _str(d, "host", 260) or None)


@router.post("/hosts")
async def api_hosts(request: Request):
    _auth(request)
    d = await _body(request)
    action = _str(d, "action", 10)
    if action == "add":
        return {"gitlab": _run(add_host, _str(d, "host", 300))}
    if action == "remove":
        return {"gitlab": _run(remove_host, _str(d, "host", 300))}
    raise HTTPException(400, "action must be add or remove")


@router.post("/migrate")
async def api_migrate(request: Request):
    _auth(request)
    d = await _body(request)
    val = os.environ.get(_str(d, "var", 40), "")
    return _guard(_run(migrate, _str(d, "var", 40), session_only=bool(d.get("session_only")),
                       host=_str(d, "host", 260) or None), val)


@router.post("/device/start")
async def api_device_start(request: Request):
    _auth(request)
    d = await _body(request)
    return _run(device_start, _str(d, "provider", 20), _str(d, "host", 260) or None)


@router.post("/device/poll")
async def api_device_poll(request: Request):
    _auth(request)
    d = await _body(request)
    return _run(device_poll, _str(d, "flow_id", 60), session_only=bool(d.get("session_only")))


@router.post("/pkce/start")
async def api_pkce_start(request: Request):
    _auth(request)
    d = await _body(request)
    return _run(pkce_start, _str(d, "host", 260) or None)


@router.post("/pkce/poll")
async def api_pkce_poll(request: Request):
    _auth(request)
    d = await _body(request)
    return _run(pkce_poll, _str(d, "flow_id", 60), session_only=bool(d.get("session_only")))
