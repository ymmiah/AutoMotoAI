"""Native, lightweight REST tools for services (GitHub, GitLab, Vercel, Figma, Notion, Zotero).

One tool, ``service_api(service, method, path, query?, body?)``, calls the service's official
REST API with *your* token:

* Tokens come from the per-run BYOK keys (``keys={"github": ...}``) or environment variables
  (``GITHUB_TOKEN``, ``GITLAB_TOKEN``, ``VERCEL_TOKEN``, ``FIGMA_TOKEN``, ``NOTION_TOKEN``, ``ZOTERO_API_KEY``). They are sent only to
  that service's API host and never appear in tool output, events or logs.
* The host is fixed per service: ``path`` can't change it (no ``://``, ``..``, ``@``, ``\\``).
  Requests go through the SSRF guard.
* ``GET`` is read-only (safe). ``POST``/``PUT``/``PATCH``/``DELETE`` are risky (approval).
  Deleting a repo/project and anything touching keys, secrets, tokens, webhooks, members or
  permissions is **blocked** outright.

Canva, Google Drive and OneDrive (OAuth-only APIs) are connected through MCP
(see ``mcp_catalog.py``); shopping and travel sites are research-only (web_search/fetch_url).
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any

from automoto import config, netguard


@dataclass
class Service:
    id: str
    name: str
    base: str
    env: tuple[str, ...]
    auth: str  # bearer | private-token | zotero
    docs: str
    status: str = "unit"  # live | unit
    optional_auth: bool = False  # public GETs work without a token


SERVICES: dict[str, Service] = {s.id: s for s in [
    Service("github", "GitHub", "https://api.github.com", ("GITHUB_TOKEN", "GH_TOKEN"), "bearer",
            "https://docs.github.com/rest", status="live", optional_auth=True),
    Service("gitlab", "GitLab", "https://gitlab.com/api/v4", ("GITLAB_TOKEN",), "private-token",
            "https://docs.gitlab.com/api/rest/", status="live", optional_auth=True),
    Service("vercel", "Vercel", "https://api.vercel.com", ("VERCEL_TOKEN",), "bearer",
            "https://vercel.com/docs/rest-api"),
    Service("figma", "Figma", "https://api.figma.com", ("FIGMA_TOKEN",), "figma",
            "https://www.figma.com/developers/api"),
    Service("notion", "Notion", "https://api.notion.com", ("NOTION_TOKEN",), "bearer",
            "https://developers.notion.com/reference/intro"),
    Service("zotero", "Zotero", "https://api.zotero.org", ("ZOTERO_API_KEY",), "zotero",
            "https://www.zotero.org/support/dev/web_api/v3/start", optional_auth=True),
    # Office in the cloud (user OAuth access tokens - BYOK; never stored server-side)
    Service("google-docs", "Google Docs", "https://docs.googleapis.com", ("GOOGLE_ACCESS_TOKEN",), "bearer",
            "https://developers.google.com/workspace/docs/api/reference/rest"),
    Service("google-sheets", "Google Sheets", "https://sheets.googleapis.com", ("GOOGLE_ACCESS_TOKEN",), "bearer",
            "https://developers.google.com/workspace/sheets/api/reference/rest"),
    Service("google-slides", "Google Slides", "https://slides.googleapis.com", ("GOOGLE_ACCESS_TOKEN",), "bearer",
            "https://developers.google.com/workspace/slides/api/reference/rest"),
    Service("msgraph", "Microsoft 365 (Graph)", "https://graph.microsoft.com", ("MS_GRAPH_TOKEN",), "bearer",
            "https://learn.microsoft.com/graph/api/overview"),
]}

_BLOCKED_PATH = re.compile(
    r"/(keys|gpg_keys|ssh_signing_keys|deploy_keys|secrets|variables|hooks|webhooks|tokens|personal_access_tokens|"
    r"collaborators|members|invitations|permissions|access_requests|protected_branches|env|environment-variables|"
    r"oauth|authorizations|installations|runners|billing|"
    r"createLink|invite|share|shares|grant|grants)(/|$|\?|:)", re.I)
# Microsoft Graph: the agent works with files (OneDrive/SharePoint Word, Excel, PowerPoint) only -
# never mail, chats, calendars, contacts, identities or sending anything.
_GRAPH_BLOCKED = re.compile(
    r"/(sendMail|send|reply|replyAll|forward|createReply|createReplyAll|createForward|messages|mailFolders|"
    r"calendar|calendars|events|chats|teams|channels|contacts|people|authentication|appRoleAssignments|"
    r"oauth2PermissionGrants|users|groups|directoryRoles|applications|servicePrincipals|subscriptions)(/|$|\?|:|\()", re.I)
_DELETE_WHOLE = re.compile(r"^/(repos/[^/]+/[^/]+|projects/[^/]+|v\d+/projects/[^/]+|orgs/[^/]+|groups/[^/]+|"
                           r"users/[^/]+)/?$", re.I)


class ServiceError(Exception):
    pass


def base_url(svc: Service) -> str:
    if svc.id == "gitlab":
        b = (config.env("GITLAB_URL") or svc.base).rstrip("/")
        if not b.startswith("https://"):
            raise ServiceError("GITLAB_URL must be https://")
        return b if b.endswith("/api/v4") else b + "/api/v4"
    return svc.base


def token(svc: Service, keys: dict[str, str] | None) -> str | None:
    t = (keys or {}).get(svc.id)
    if t:
        return t.strip()
    for name in svc.env:
        v = config.env(name)
        if v:
            return v
    return None


def check_path(path: str) -> str:
    p = str(path or "").strip()
    if not p.startswith("/") or any(x in p for x in ("://", "..", "@", "\\", "\r", "\n", "#")) or len(p) > 500:
        raise ServiceError("path must be an API path like /repos/OWNER/REPO (no host, '..', '@' or '\\')")
    return p


def classify(args: dict[str, Any]) -> tuple[str, str]:
    svc = SERVICES.get(str(args.get("service", "")).lower())
    if not svc:
        return "blocked", f"unknown service. Known: {', '.join(SERVICES)}"
    method = str(args.get("method") or "GET").upper()
    try:
        path = check_path(args.get("path", ""))
    except ServiceError as exc:
        return "blocked", str(exc)
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        return "blocked", f"method {method} not allowed"
    if _BLOCKED_PATH.search(path.split("?")[0]):
        return "blocked", "keys, secrets, tokens, webhooks, members, permissions and sharing are never touched by the agent"
    if svc.id == "msgraph" and _GRAPH_BLOCKED.search(path.split("?")[0]):
        return "blocked", "Microsoft Graph access is limited to files - mail, chats, calendars, people and directory are blocked"
    if method == "DELETE" and _DELETE_WHOLE.match(path.split("?")[0]):
        return "blocked", "deleting a whole repository, project, group or account is never done by the agent"
    if method == "GET":
        return "safe", f"reads {svc.name} {path}"
    return "risky", f"{method} {svc.name} {path} (changes your {svc.name} data)"


def call(service: str, method: str = "GET", path: str = "/", query: dict[str, Any] | None = None,
         body: Any = None, *, keys: dict[str, str] | None = None, max_chars: int = 12000) -> str:
    svc = SERVICES.get(str(service or "").lower())
    if not svc:
        raise ServiceError(f"unknown service '{service}'. Known: {', '.join(SERVICES)}")
    level, reason = classify({"service": svc.id, "method": method, "path": path})
    if level == "blocked":
        raise ServiceError(reason)
    method = (method or "GET").upper()
    path = check_path(path)
    tok = token(svc, keys)
    if not tok and not (svc.optional_auth and method == "GET"):
        raise ServiceError(f"{svc.name} needs a token: set {svc.env[0]} in .env or add a '{svc.id}' key in Settings")
    if svc.id == "zotero" and "{user}" in path:
        uid = config.env("ZOTERO_USER_ID")
        if not uid or not uid.isdigit():
            raise ServiceError("set ZOTERO_USER_ID (your numeric user id from zotero.org/settings/keys)")
        path = path.replace("{user}", uid)
    url = base_url(svc) + path
    if query:
        if not isinstance(query, dict):
            raise ServiceError("query must be an object")
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode({str(k): str(v) for k, v in query.items()})
    headers = {"Accept": "application/json", "User-Agent": "AutoMoto-AI"}
    if svc.id == "github":
        headers.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    if tok:
        if svc.auth == "bearer":
            headers["Authorization"] = f"Bearer {tok}"
        elif svc.auth == "private-token":
            headers["PRIVATE-TOKEN"] = tok
        elif svc.auth == "zotero":
            headers["Zotero-API-Key"] = tok
        elif svc.auth == "figma":
            headers["X-Figma-Token"] = tok
    if svc.id == "notion":
        headers["Notion-Version"] = "2022-06-28"
    data = None
    if body is not None and method != "GET":
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    try:
        r = netguard.request(url, method=method, data=data, headers=headers, timeout=25)
    except netguard.BlockedURL as exc:
        raise ServiceError(f"blocked: {exc}") from None
    text = r.text()
    if tok:
        text = text.replace(tok, "[redacted]")
    try:
        text = json.dumps(json.loads(text), indent=1, ensure_ascii=False)
    except ValueError:
        pass
    max_chars = max(500, min(int(max_chars or 12000), 40000))
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n[…{len(text) - max_chars} more chars - use query params like per_page]"
    status = f"HTTP {r.status} {method} {svc.name} {path}"
    if r.status >= 400:
        raise ServiceError(f"{status}\n{text[:2000]}")
    return f"{status}\n{text}"


def status_list(keys: dict[str, str] | None = None) -> list[dict[str, Any]]:
    return [{"id": s.id, "name": s.name, "configured": bool(token(s, keys)), "env": list(s.env),
             "public_reads": s.optional_auth, "docs": s.docs, "status": s.status} for s in SERVICES.values()]


def _tool_fn(ctx, service: str, path: str, method: str = "GET", query: dict | None = None, body: Any = None,
             max_chars: int = 12000) -> str:
    from automoto.tools import ToolFailed

    try:
        return call(service, method, path, query, body, keys=getattr(ctx, "keys", None), max_chars=max_chars)
    except ServiceError as exc:
        raise ToolFailed(str(exc)) from None


def _make_tools():
    from automoto.tools import S, Tool, _obj

    return [Tool(
        "service_api",
        "Call a service's official REST API with the user's token: github (api.github.com), gitlab, vercel, "
        "figma (/v1/files/KEY), notion (/v1/search, /v1/pages/ID), zotero (use {user} in the path), "
        "google-docs (/v1/documents/ID), google-sheets (/v4/spreadsheets/ID/values/A1:D10), google-slides "
        "(/v1/presentations/ID), msgraph (/v1.0/me/drive/root/children - OneDrive/Word/Excel files; mail and sharing are blocked). GET is read-only; other methods need approval. "
        "Example: service=github, path=/repos/OWNER/REPO/issues, query={state: open, per_page: 10}.",
        _obj({"service": S, "path": S, "method": S, "query": {"type": "object"}, "body": {"type": "object"},
              "max_chars": {"type": "integer"}}, ["service", "path"]),
        "risky", _tool_fn, "services")]


class _Lazy(list):
    """Build the tool list on first use (avoids an import cycle with tools.py)."""

    def __iter__(self):
        if not len(self):
            self.extend(_make_tools())
        return super().__iter__()


TOOLS: list = _Lazy()
