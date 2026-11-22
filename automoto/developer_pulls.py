"""Developer Studio V48: "Ask for a review" (draft pull/merge request) and read-only "Checks on GitHub/GitLab".

Safety model (docs/PULL-REQUESTS-AND-CI.md, PLAN.md §2, §6, §11, §14, §18):

* Reuses the PR 3 sign-in: the token comes from the keychain for each call, goes only into the
  Authorization header of an allowlisted HTTPS request with redirects off, and is never returned,
  logged or written anywhere. GitHub classic tokens are not used here either (§18 #12).
* Opening a review is click-only and two-step: ``/review/preview`` shows base <- branch, the title
  and the description (draft by default) and returns an ``action_sha256`` bound to the project,
  repository, base, branch and the branch's exact commit on the website. ``/review/open``
  re-reads the branch and only creates the request if nothing changed. The title and description
  the user sees are exactly what is sent.
* There is no merge, close, approve or comment-delete code at all: AutoMoto never merges in v1.
* Checks are read-only GETs (check runs, commit statuses, pipelines, jobs). Nothing is re-run.
* GitLab: reading needs ``read_api`` (asked at sign-in); creating a merge request needs ``api``,
  which is requested only when the user first asks for a review (incremental consent, §18 #5).
* Everything from the website (titles, check and job names, summaries, logs, URLs) is untrusted:
  control/escape characters are stripped, it is redacted and capped, only https links on the
  signed-in host are passed on, and the UI renders it with textContent. It is never executed.
* Every failure ends in plain-words manual steps with copyable commands for Windows, Mac and Linux.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import brand, git_auth, redaction
from automoto import developer_git as dgit
from automoto import developer_remote as remote
from automoto.developer_remote import RemoteError, _clean

router = APIRouter(prefix="/api/developer/studio/remote/review", tags=["developer-review-remote"])
VERSION = "review-remote-1"
PREVIEW_TTL = 600
MAX_TITLE = 250
MAX_BODY = 20000
MAX_ITEMS = 100
MAX_LOG = 16000
GITLAB_REVIEW_SCOPES = ("read_user", "read_api", "write_repository", "api")
_PREVIEWS: dict[str, dict] = {}
_LOCK = threading.Lock()
NAMES = {"github": "GitHub", "gitlab": "GitLab"}

# Check states in plain words. Anything unknown counts as "running" (never as passed).
GH_FAILED = {"failure", "timed_out", "cancelled", "action_required", "startup_failure", "stale", "error"}
GH_PASSED = {"success"}
GH_SKIPPED = {"neutral", "skipped"}
GL_FAILED = {"failed", "canceled", "canceling"}
GL_PASSED = {"success"}
GL_SKIPPED = {"skipped", "manual"}
_SECTION = re.compile(r"section_(?:start|end):\d+:[A-Za-z0-9_.\-\[\]]*(?:\r|\x1b\[0K)*")


# ------------------------------------------------------------------ website calls
def _ctx(root: Path, need_write: bool) -> dict:
    t = remote.saved_target(root)
    if not t:
        raise RemoteError("Pick where to share first, in Share to GitHub or GitLab.", "no_target", 409)
    provider, host, repo = t["provider"], t["host"], t["repo"]
    try:
        git_auth.check_target(provider, host)
    except git_auth.AuthError as exc:
        raise RemoteError(str(exc), "blocked_host", 403) from None
    acct, tok = remote._account(provider, host)
    perm = remote.push_permission(provider, acct)
    if not perm["ok"]:
        # A token that may not be used for sharing is not used for reading reviews or checks either.
        if need_write or perm["code"] != "scope":  # a read-only GitLab token may still read
            raise RemoteError(perm["message"], perm["code"], 401 if perm["code"] in ("auth", "expired") else 403)
    if not tok:
        raise RemoteError("Your sign-in has ended. Connect again.", "expired", 401)
    return {"provider": provider, "host": host, "repo": repo, "acct": acct or {}, "tok": tok,
            "web": remote.web_url(provider, host, repo), "default_branch": t.get("default_branch"),
            "api": git_auth.api_base(provider, host), "pid": quote(repo, safe="")}


def _req(c: dict, method: str, path: str, body: dict | None = None, *, text: bool = False) -> tuple[int, Any, dict]:
    """One allowlisted HTTPS call. The answer is untrusted and redacted before anything reads it."""
    token, _, kind = c["tok"]
    hdrs = git_auth._auth_headers(c["provider"], token, kind)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    url = c["api"] + path
    if text:
        hdrs["Accept"] = "text/plain"
        allow = (git_auth._api_host(c["provider"], c["host"]), c["host"])
        try:
            status, h, raw = git_auth.http_call(method, url, hdrs, data, allow)
        except Exception as exc:  # netguard.BlockedURL / OSError: same plain message as JSON calls
            raise RemoteError(f"Couldn't reach {c['host']}. Check your internet connection.", "network", 502,
                              type(exc).__name__) from None
        out = redaction.redact(raw[: MAX_LOG * 8].decode("utf-8", "replace"), (token,))
        return status, out, {k.lower(): v for k, v in (h or {}).items()}
    try:
        status, h, d = git_auth._call(c["provider"], c["host"], method, url, hdrs, data, token=token)
    except git_auth.AuthError as exc:
        raise RemoteError(f"Couldn't reach {c['host']}. Check your internet connection.", "network", 502,
                          str(exc)) from None
    return status, d, h


def _fail(c: dict, status: int, d: Any, h: dict, what: str) -> RemoteError:
    """Map a website error to a fallback code. The website's own words are kept only as a cleaned detail."""
    msg = ""
    if isinstance(d, dict):
        m = d.get("message") or d.get("error") or d.get("raw") or ""
        msg = m if isinstance(m, str) else json.dumps(m)[:300]
        errs = d.get("errors")
        if isinstance(errs, list):
            msg += " " + " ".join(str(e.get("message") if isinstance(e, dict) else e)[:200] for e in errs[:3])
    detail = _clean(msg, 400, c["tok"][0])
    name = NAMES[c["provider"]]
    if status == 401:
        git_auth.mark_expired(c["provider"], c["host"])
        return RemoteError(f"{name} refused your sign-in. It may have expired or been revoked.", "auth", 401, detail)
    low = msg.lower()
    if status == 403 and (h.get("x-ratelimit-remaining") == "0" or "rate limit" in low):
        return RemoteError(f"{name} asked {brand.short()} to slow down. Wait a few minutes, then try again.",
                           "rate_limited", 429, detail)
    if status == 403 and c["provider"] == "gitlab" and ("insufficient_scope" in low or "scope" in low):
        return RemoteError("Your GitLab token can't open merge requests. GitLab needs the api scope for that.",
                           "scope_api", 403, detail)
    if status in (403, 404):
        extra = (" Make sure the token includes this repository and has Pull requests: Read and write."
                 if c["provider"] == "github" else " Make sure the token can reach this project.")
        return RemoteError(f"{name} didn't let {brand.short()} {what}.{extra}", "forbidden", status, detail)
    if status == 422:
        return RemoteError(f"{name} couldn't {what}. {detail}".strip(), "rejected", 422, detail)
    return RemoteError(f"{name} answered with an error ({status}).", "other", 502, detail)


def _ok(c: dict, path: str, what: str) -> Any:
    status, d, h = _req(c, "GET", path)
    if status != 200:
        raise _fail(c, status, d, h, what)
    return d


def _link(c: dict, url: Any) -> str | None:
    """Only https links on the signed-in host leave the engine."""
    if not isinstance(url, str) or len(url) > 2000:
        return None
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if p.scheme != "https" or (p.hostname or "").lower() != c["host"] or p.username or p.password or p.port:
        return None
    if re.search(r"[\s\"'<>\\`]", url):
        return None
    return url


def _host_of(url: Any) -> str | None:
    try:
        p = urllib.parse.urlsplit(url) if isinstance(url, str) else None
    except ValueError:
        return None
    return _clean(p.hostname or "", 100) if p and p.scheme in ("http", "https") and p.hostname else None


def _branch_sha(c: dict, branch: str) -> str | None:
    path = (f"/repos/{c['repo']}/branches/{quote(branch, safe='')}" if c["provider"] == "github"
            else f"/projects/{c['pid']}/repository/branches/{quote(branch, safe='')}")
    status, d, h = _req(c, "GET", path)
    if status == 404:
        return None
    if status != 200 or not isinstance(d, dict):
        raise _fail(c, status, d, h, "read the branch")
    sha = (d.get("commit") or {}).get("sha") if c["provider"] == "github" else (d.get("commit") or {}).get("id")
    return sha if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40,64}", sha) else None


def _review_of(c: dict, d: dict) -> dict:
    if c["provider"] == "github":
        return {"number": int(d.get("number") or 0), "title": _clean(str(d.get("title") or ""), MAX_TITLE),
                "url": _link(c, d.get("html_url")), "draft": bool(d.get("draft")),
                "state": _clean(str(d.get("state") or ""), 20), "base": _clean(str((d.get("base") or {}).get("ref") or ""), 100)}
    return {"number": int(d.get("iid") or 0), "title": _clean(str(d.get("title") or ""), MAX_TITLE),
            "url": _link(c, d.get("web_url")), "draft": bool(d.get("draft") or d.get("work_in_progress")),
            "state": _clean(str(d.get("state") or ""), 20), "base": _clean(str(d.get("target_branch") or ""), 100)}


def open_review(c: dict, branch: str) -> dict | None:
    """The open pull/merge request for this branch, if there is one."""
    if c["provider"] == "github":
        owner = c["repo"].split("/")[0]
        q = urllib.parse.urlencode({"head": f"{owner}:{branch}", "state": "open", "per_page": "5"})
        d = _ok(c, f"/repos/{c['repo']}/pulls?{q}", "list reviews")
    else:
        q = urllib.parse.urlencode({"source_branch": branch, "state": "opened", "per_page": "5"})
        d = _ok(c, f"/projects/{c['pid']}/merge_requests?{q}", "list reviews")
    if isinstance(d, list) and d and isinstance(d[0], dict):
        return _review_of(c, d[0])
    return None


def _scopes_ok(c: dict) -> bool | None:
    """GitLab: does the token have api (needed to open a merge request)? None when GitLab didn't say."""
    if c["provider"] != "gitlab":
        return True
    scopes = c["acct"].get("scopes") or []
    return ("api" in scopes) if scopes else None


def api_token_page(host: str) -> dict:
    """Incremental consent: a GitLab token page pre-filled with the sign-in scopes plus api."""
    short = brand.short()
    q = urllib.parse.urlencode({"name": f"{short} Developer Studio (reviews)",
                                "description": f"Used by {short} on this computer to open merge requests. "
                                               "You can revoke it any time.",
                                "scopes": ",".join(GITLAB_REVIEW_SCOPES)})
    return {"url": f"https://{host}/-/user_settings/personal_access_tokens?{q}",
            "why": "GitLab has no smaller permission for opening a merge request than api. "
                   f"{short} only uses it to open a draft merge request when you press the button, "
                   "and never merges, deletes or changes settings.",
            "steps": ["Open the link. It ticks read_user, read_api, write_repository and api for you.",
                      "Pick an expiry date about 30 days away, then click Create token and copy it.",
                      "Paste it in Connect GitHub or GitLab. It replaces the old token in your password store.",
                      "Prefer something smaller? A project access token limited to this one project also works."]}


# ------------------------------------------------------------------ status
def _branch_name(root: Path, branch: str | None) -> str:
    if branch:
        return remote._branch(branch)
    st = dgit._status(root)
    if st.get("detached") or not st.get("branch"):
        raise RemoteError("Switch to a branch in Checkpoints first.", "bad_branch", 409)
    return remote._branch(st["branch"])


def _base(c: dict, base: str | None) -> str | None:
    if base:
        return remote._branch(base)
    if c.get("default_branch"):
        return c["default_branch"]
    facts = remote.repo_facts(c["provider"], c["host"], c["repo"], c["tok"])
    return facts.get("default_branch") or None


def review_status(root: Path, branch: str | None) -> dict:
    t = remote.saved_target(root)
    out: dict[str, Any] = {"version": VERSION, "os": remote.host_os(), "target": t, "branch": None}
    if not t:
        return {**out, "state": "no_target", "message": "Pick where to share first, in Share to GitHub or GitLab."}
    try:
        b = _branch_name(root, branch)
        out["branch"] = b
        c = _ctx(root, need_write=False)
        out["web_url"] = c["web"]
        out["base"] = _base(c, None)
        sha = _branch_sha(c, b)
        out["shared"] = bool(sha)
        out["head_sha"] = sha
        out["review"] = open_review(c, b) if sha else None
        ok = _scopes_ok(c)
        out["need_scope"] = None if ok is not False else api_token_page(c["host"])
        out["state"] = "review_open" if out["review"] else "ready" if sha and out["base"] and out["base"] != b else (
            "same_as_base" if sha else "not_shared")
    except RemoteError as exc:
        out.update({"state": "error", "error": {"message": str(exc), "code": exc.code}})
    return out


# ------------------------------------------------------------------ preview and open (click-only)
def _clean_title(s: str) -> str:
    s = _clean(str(s or "").replace("\n", " ").replace("\t", " "), MAX_TITLE).strip()
    return re.sub(r" {2,}", " ", s)


def _clean_body(s: str) -> str:
    s = re.sub(r"\r\n?", "\n", str(s or ""))
    s = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", s)
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]", "", s)
    return s[:MAX_BODY].strip()


def _humanise(branch: str) -> str:
    last = branch.rsplit("/", 1)[-1]
    words = re.sub(r"[-_.]+", " ", last).strip()
    return (words[:1].upper() + words[1:]) if words else branch


def _commits(c: dict, base: str, branch: str) -> tuple[list[str], int]:
    """Commit subjects base..branch from the website (untrusted)."""
    if c["provider"] == "github":
        d = _ok(c, f"/repos/{c['repo']}/compare/{quote(base, safe='')}...{quote(branch, safe='')}", "compare the branches")
        items = d.get("commits") if isinstance(d, dict) else None
        msgs = [str((x.get("commit") or {}).get("message") or "") for x in (items or []) if isinstance(x, dict)]
        total = int(d.get("ahead_by") or len(msgs)) if isinstance(d, dict) else len(msgs)
        msgs = list(reversed(msgs))  # newest first
    else:
        q = urllib.parse.urlencode({"from": base, "to": branch, "straight": "false"})
        d = _ok(c, f"/projects/{c['pid']}/repository/compare?{q}", "compare the branches")
        items = d.get("commits") if isinstance(d, dict) else None
        msgs = [str(x.get("message") or x.get("title") or "") for x in (items or []) if isinstance(x, dict)]
        total = len(msgs)
        msgs = list(reversed(msgs))
    subjects = [_clean_title(m.split("\n", 1)[0]) for m in msgs if m.strip()]
    return subjects[:50], total


def _review_sha(p: dict) -> str:
    keep = {k: p.get(k) for k in ("project", "provider", "host", "repo", "base", "branch", "head_sha")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()


def preview(root: Path, branch: str | None, base: str | None) -> dict:
    c = _ctx(root, need_write=True)
    b = _branch_name(root, branch)
    base_b = _base(c, base)
    if not base_b:
        raise RemoteError(f"{NAMES[c['provider']]} didn't say which branch is the main one. Type it in.", "bad_branch", 422)
    if base_b == b:
        raise RemoteError(f"You're on {b}, which is the main branch. Share your work as a new branch first.",
                          "same_branch", 409)
    sha = _branch_sha(c, b)
    if not sha:
        raise RemoteError(f"{b} isn't on {NAMES[c['provider']]} yet. Share it first.", "not_shared", 409)
    existing = open_review(c, b)
    subjects, total = _commits(c, base_b, b)
    if total == 0:
        raise RemoteError(f"{b} has no new checkpoints compared with {base_b}, so there's nothing to review.",
                          "nothing", 409)
    title = subjects[0] if len(subjects) == 1 else _humanise(b)
    lines = [f"- {s}" for s in subjects[:20]] + ([f"- …and {total - 20} more"] if total > 20 else [])
    body = ("Changes in this request:\n" + "\n".join(lines) +
            f"\n\nOpened as a draft from {brand.short()} Developer Studio.")
    p = {"project": str(root), "provider": c["provider"], "host": c["host"], "repo": c["repo"], "base": base_b,
         "branch": b, "head_sha": sha}
    action = _review_sha(p)
    with _LOCK:
        now = time.monotonic()
        for k in [k for k, v in _PREVIEWS.items() if v["_at"] < now - PREVIEW_TTL]:
            _PREVIEWS.pop(k, None)
        _PREVIEWS[action] = {**p, "_at": now}
    ok_scope = _scopes_ok(c)
    remote.audit("review_preview", "ok", project=str(root), provider=c["provider"], host=c["host"], repo=c["repo"],
                 branch=b, base=base_b, head=sha[:12])
    kind = "pull request" if c["provider"] == "github" else "merge request"
    return {"ok": True, "provider": c["provider"], "host": c["host"], "repo": c["repo"], "base": base_b, "branch": b,
            "head_sha": sha, "commit_count": total, "commits": subjects[:20], "title": _clean_title(title),
            "body": body, "draft": True, "kind": kind, "existing": existing, "action_sha256": action,
            "need_scope": api_token_page(c["host"]) if ok_scope is False else None,
            "prefilled_note": "Written from your checkpoint messages. Change anything before you send it.",
            "summary": f"Ask for a review of {b} into {base_b} on {c['repo']} ({total} checkpoint"
                       f"{'s' if total != 1 else ''}). It opens as a draft; nobody can merge it by accident."}


def open_request(root: Path, branch: str, base: str, title: str, body: str, draft: bool, action_sha256: str,
                 confirmed: bool) -> dict:
    if not confirmed:
        raise RemoteError("Press Ask for a review to confirm.", "not_confirmed", 400)
    title_c, body_c = _clean_title(title), _clean_body(body)
    if len(title_c) < 3:
        raise RemoteError("Give the review a short title (3 characters or more).", "bad_title", 422)
    with _LOCK:
        known = _PREVIEWS.pop(action_sha256, None)
    if not known or known["project"] != str(root) or known["_at"] < time.monotonic() - PREVIEW_TTL:
        raise RemoteError("This preview is out of date. Look at it again.", "stale", 409)
    c = _ctx(root, need_write=True)
    b, base_b = remote._branch(branch), remote._branch(base)
    sha = _branch_sha(c, b)
    fresh = {"project": str(root), "provider": c["provider"], "host": c["host"], "repo": c["repo"], "base": base_b,
             "branch": b, "head_sha": sha}
    if not sha or _review_sha(fresh) != action_sha256:
        raise RemoteError("Something changed since the preview (a new share, or a different branch). "
                          "Look at the new preview and press the button again.", "stale", 409)
    existing = open_review(c, b)
    if existing:
        remote.audit("review_open", "exists", project=str(root), provider=c["provider"], repo=c["repo"], branch=b,
                     number=existing["number"])
        return {"ok": True, "created": False, "review": existing,
                "message": f"There's already an open review for {b}: #{existing['number']}."}
    if c["provider"] == "gitlab" and _scopes_ok(c) is False:
        raise RemoteError("Your GitLab token can't open merge requests. GitLab needs the api scope for that.",
                          "scope_api", 403)
    if c["provider"] == "github":
        status, d, h = _req(c, "POST", f"/repos/{c['repo']}/pulls",
                            {"title": title_c, "body": body_c, "head": b, "base": base_b, "draft": bool(draft),
                             "maintainer_can_modify": False})
        good = status == 201
    else:
        t = title_c if not draft or title_c.lower().startswith("draft:") else "Draft: " + title_c
        status, d, h = _req(c, "POST", f"/projects/{c['pid']}/merge_requests",
                            {"source_branch": b, "target_branch": base_b, "title": t[:255], "description": body_c,
                             "remove_source_branch": False, "squash": False})
        good = status == 201
    if not good or not isinstance(d, dict):
        err = _fail(c, status, d if isinstance(d, dict) else {}, h, "open the review")
        remote.audit("review_open", err.code, project=str(root), provider=c["provider"], repo=c["repo"], branch=b,
                     status=status)
        raise err
    rev = _review_of(c, d)
    remote.audit("review_open", "ok", project=str(root), provider=c["provider"], host=c["host"], repo=c["repo"],
                 branch=b, base=base_b, number=rev["number"], draft=rev["draft"], head=sha[:12])
    word = "pull request" if c["provider"] == "github" else "merge request"
    return {"ok": True, "created": True, "review": rev,
            "message": f"Opened {'draft ' if rev['draft'] else ''}{word} #{rev['number']}. "
                       f"Nothing is merged until someone merges it on {NAMES[c['provider']]}."}


# ------------------------------------------------------------------ checks (read-only)
def _gh_state(status: str, conclusion: str | None) -> str:
    if status != "completed":
        return "running"
    if conclusion in GH_PASSED:
        return "passed"
    if conclusion in GH_SKIPPED:
        return "skipped"
    if conclusion in GH_FAILED:
        return "failed"
    return "running"


def _gl_state(status: str, allow_failure: bool) -> str:
    if status in GL_PASSED:
        return "passed"
    if status in GL_SKIPPED:
        return "skipped"
    if status in GL_FAILED:
        return "warning" if allow_failure else "failed"
    return "running"


def _summarise(items: list[dict], site: str) -> dict:
    counted = [i for i in items if i["state"] in ("passed", "failed", "running", "warning")]
    passed = sum(1 for i in counted if i["state"] in ("passed", "warning"))
    failed = [i for i in counted if i["state"] == "failed"]
    running = [i for i in counted if i["state"] == "running"]
    total = len(counted)
    if not items:
        state, title, text = "none", f"No checks on {site} yet", (
            f"Nothing has run for this branch on {site}. Some projects have no automatic checks, which is fine.")
    elif running:
        state, title, text = "running", f"Checks on {site} are running", (
            f"{passed} of {total} finished and passed so far. Press Check again in a minute.")
    elif failed:
        state, title, text = "failed", f"Checks on {site}: {passed} of {total} passed", (
            f"{len(failed)} didn't pass. Open one below to read what it said.")
    else:
        state, title, text = "passed", f"Checks on {site}: {passed} of {total} passed", "Everything passed."
    return {"state": state, "passed": passed, "total": total, "failed": len(failed), "running": len(running),
            "failing_names": [i["name"] for i in failed][:6], "title": title, "text": text}


def _github_items(c: dict, sha: str) -> tuple[list[dict], bool]:
    """Check runs when the token may read them; otherwise GitHub Actions jobs (fine-grained tokens have no
    Checks permission, so private repositories answer 403 there). Commit statuses are added either way."""
    items: list[dict] = []
    truncated = False
    status, d, h = _req(c, "GET", f"/repos/{c['repo']}/commits/{sha}/check-runs?per_page={MAX_ITEMS}")
    if status == 200 and isinstance(d, dict):
        truncated = int(d.get("total_count") or 0) > MAX_ITEMS
        for r in (d.get("check_runs") or [])[:MAX_ITEMS]:
            if isinstance(r, dict):
                items.append({"id": str(int(r.get("id") or 0)), "kind": "check_run",
                              "name": _clean(str(r.get("name") or "check"), 120),
                              "state": _gh_state(str(r.get("status") or ""), r.get("conclusion")),
                              "url": _link(c, r.get("html_url"))})
    elif status in (403, 404):
        if h.get("x-ratelimit-remaining") == "0":
            raise _fail(c, status, d, h, "read the checks")
        q = urllib.parse.urlencode({"head_sha": sha, "per_page": "20"})
        runs = _ok(c, f"/repos/{c['repo']}/actions/runs?{q}", "read the checks")
        seen_wf: set = set()
        for run in (runs.get("workflow_runs") if isinstance(runs, dict) else None) or []:
            if not isinstance(run, dict) or run.get("workflow_id") in seen_wf:
                continue  # newest run of each workflow only (re-runs replace older ones)
            seen_wf.add(run.get("workflow_id"))
            wf = _clean(str(run.get("name") or "workflow"), 80)
            jobs = _ok(c, f"/repos/{c['repo']}/actions/runs/{int(run.get('id') or 0)}/jobs?per_page={MAX_ITEMS}",
                       "read the checks")
            for j in (jobs.get("jobs") if isinstance(jobs, dict) else None) or []:
                if isinstance(j, dict) and len(items) < MAX_ITEMS:
                    items.append({"id": str(int(j.get("id") or 0)), "kind": "actions_job",
                                  "name": _clean(f"{wf} / {j.get('name') or 'job'}", 160),
                                  "state": _gh_state(str(j.get("status") or ""), j.get("conclusion")),
                                  "url": _link(c, j.get("html_url"))})
            truncated = truncated or len(items) >= MAX_ITEMS
    else:
        raise _fail(c, status, d, h, "read the checks")
    status, st, h = _req(c, "GET", f"/repos/{c['repo']}/commits/{sha}/status?per_page={MAX_ITEMS}")
    if status == 200 and isinstance(st, dict):
        seen = {i["name"] for i in items}
        for s in (st.get("statuses") or [])[:MAX_ITEMS]:
            if not isinstance(s, dict):
                continue
            name = _clean(str(s.get("context") or "status"), 120)
            if name in seen:
                continue
            seen.add(name)
            state = {"success": "passed", "failure": "failed", "error": "failed"}.get(str(s.get("state")), "running")
            items.append({"id": None, "kind": "status", "name": name, "state": state,
                          "note": _clean(str(s.get("description") or ""), 200),
                          "url": _link(c, s.get("target_url")), "external_host": _host_of(s.get("target_url"))})
    elif status not in (403, 404):
        raise _fail(c, status, st, h, "read the checks")
    return items, truncated


def checks(root: Path, branch: str | None) -> dict:
    c = _ctx(root, need_write=False)
    b = _branch_name(root, branch)
    site = NAMES[c["provider"]]
    sha = _branch_sha(c, b)
    out: dict[str, Any] = {"branch": b, "provider": c["provider"], "site": site, "head_sha": sha}
    if not sha:
        return {**out, **_summarise([], site), "state": "not_shared", "title": f"{b} isn't on {site} yet",
                "text": "Share it first, then checks can run.", "items": [],
                "web_url": c["web"]}
    items: list[dict] = []
    truncated = False
    if c["provider"] == "github":
        items, truncated = _github_items(c, sha)
        web = f"{c['web']}/commit/{sha}"
    else:
        q = urllib.parse.urlencode({"sha": sha, "per_page": "1", "order_by": "id", "sort": "desc"})
        pipes = _ok(c, f"/projects/{c['pid']}/pipelines?{q}", "read the pipelines")
        web = f"{c['web']}/-/pipelines?ref={quote(b, safe='')}"
        if isinstance(pipes, list) and pipes and isinstance(pipes[0], dict):
            pid = int(pipes[0].get("id") or 0)
            web = _link(c, pipes[0].get("web_url")) or web
            jobs = _ok(c, f"/projects/{c['pid']}/pipelines/{pid}/jobs?per_page={MAX_ITEMS}&include_retried=false",
                       "read the jobs")
            for j in (jobs if isinstance(jobs, list) else [])[:MAX_ITEMS]:
                if not isinstance(j, dict):
                    continue
                items.append({"id": str(int(j.get("id") or 0)), "kind": "job",
                              "name": _clean(str(j.get("name") or "job"), 120),
                              "stage": _clean(str(j.get("stage") or ""), 60),
                              "state": _gl_state(str(j.get("status") or ""), bool(j.get("allow_failure"))),
                              "url": _link(c, j.get("web_url"))})
            truncated = len(jobs if isinstance(jobs, list) else []) >= MAX_ITEMS
    order = {"failed": 0, "running": 1, "warning": 2, "passed": 3, "skipped": 4}
    items.sort(key=lambda i: (order.get(i["state"], 5), i["name"].lower()))
    summary = _summarise(items, site)
    remote.audit("checks", summary["state"], project=str(root), provider=c["provider"], repo=c["repo"], branch=b,
                 passed=summary["passed"], total=summary["total"], head=sha[:12])
    return {**out, **summary, "items": items, "truncated": truncated, "web_url": _link(c, web) or c["web"]}


def details(root: Path, kind: str, item_id: str) -> dict:
    """What one failing check said, as plain text (never run, never rendered as HTML)."""
    if not re.fullmatch(r"[1-9][0-9]{0,18}", item_id or ""):
        raise RemoteError("That check isn't known.", "bad_id", 422)
    c = _ctx(root, need_write=False)
    if c["provider"] == "github" and kind == "check_run":
        d = _ok(c, f"/repos/{c['repo']}/check-runs/{item_id}", "read the check")
        o = d.get("output") if isinstance(d, dict) and isinstance(d.get("output"), dict) else {}
        parts = [str(o.get(k) or "") for k in ("title", "summary", "text")]
        text = "\n\n".join(p for p in parts if p.strip()) or "This check didn't leave a message. Open it on GitHub to see the full log."
        return {"name": _clean(str(d.get("name") or ""), 120), "text": _clean(text, MAX_LOG, c["tok"][0]),
                "url": _link(c, d.get("html_url"))}
    if c["provider"] == "github" and kind == "actions_job":
        # Job logs live behind a redirect to another host, which is never followed: show the steps instead.
        d = _ok(c, f"/repos/{c['repo']}/actions/jobs/{item_id}", "read the check")
        lines = []
        for st in (d.get("steps") if isinstance(d, dict) else None) or []:
            if isinstance(st, dict):
                state = _gh_state(str(st.get("status") or ""), st.get("conclusion"))
                mark = {"passed": "✓", "failed": "✗", "skipped": "–"}.get(state, "…")
                lines.append(f"{mark} {_clean(str(st.get('name') or ''), 160)}  ({state})")
        text = "\n".join(lines[:100]) or "This job didn't list its steps."
        return {"name": _clean(str(d.get("name") or ""), 120) if isinstance(d, dict) else "",
                "text": text + "\n\nThe full log is on GitHub.", "url": _link(c, d.get("html_url")) if isinstance(d, dict) else None}
    if c["provider"] == "gitlab" and kind == "job":
        status, text, h = _req(c, "GET", f"/projects/{c['pid']}/jobs/{item_id}/trace", text=True)
        if status != 200:
            raise _fail(c, status, {}, h, "read the job log")
        text = _SECTION.sub("", text)
        lines = text.splitlines()
        tail = "\n".join(lines[-200:])
        return {"name": "", "text": _clean(tail, MAX_LOG, c["tok"][0]) or "The job log is empty.",
                "url": f"{c['web']}/-/jobs/{item_id}", "tail": len(lines) > 200}
    raise RemoteError("That check isn't known.", "bad_id", 422)


# ------------------------------------------------------------------ manual steps (every error lands here)
HEADLINES = {
    "auth": "Your sign-in was refused",
    "expired": "Your sign-in has ended",
    "classic_token": "This token can't be used here",
    "scope": "Your token can only read",
    "scope_api": "GitLab needs one more permission",
    "forbidden": "The website didn't allow it",
    "rate_limited": "The website asked us to slow down",
    "rejected": "The website couldn't open the review",
    "network": "Couldn't reach the website",
    "not_shared": "Share your branch first",
    "other": "Something went wrong",
    "manual": "Ask for a review yourself",
}


def _open_cmd(os_name: str, url: str) -> str:
    q = remote._q(os_name, url)
    return {"windows": f"Start-Process {q}", "macos": f"open {q}", "linux": f"xdg-open {q}"}[os_name]


def manual_steps(provider: str, os_name: str, ctx: dict) -> list[dict]:
    q = lambda s: remote._q(os_name, s)  # noqa: E731
    site = NAMES.get(provider, "the website")
    link, repo, b, base = ctx.get("link"), ctx.get("repo") or "OWNER/REPOSITORY", ctx.get("branch") or "my-branch", ctx.get("base") or "main"
    title, body = ctx.get("title") or _humanise(b), ctx.get("body") or ""
    steps: list[dict] = []
    if ctx.get("code") == "not_shared":
        steps.append({"title": f"Share {b} first: open Share to GitHub or GitLab and press Share. "
                               "If that fails too, it gives you a .patch file and its own steps.", "action": "share"})
    if ctx.get("code") in ("auth", "expired", "classic_token", "scope"):
        steps.append({"title": "Connect again with a fine-grained token (GitHub) or a token with write_repository (GitLab).",
                      "action": "signin"})
    if ctx.get("code") == "scope_api" and ctx.get("token_page"):
        tp = ctx["token_page"]
        steps.append({"title": tp["why"]})
        steps.append({"title": "Make a token with api added (the link ticks it for you), then paste it in Connect GitHub or GitLab:",
                      "cmd": tp["url"], "link": {"url": tp["url"], "label": "Open GitLab token page"}})
    if link:
        steps.append({"title": (f"Or do it on {site}: open this page in your browser." if steps else
                                f"Open this page on {site} in your browser."),
                      "cmd": link, "link": {"url": link, "label": f"Open on {site}"}})
        steps.append({"title": remote._terminal(os_name) + " Then paste this to open the same page:",
                      "cmd": _open_cmd(os_name, link)})
    steps.append({"title": "Copy this title into the Title box:", "cmd": title})
    if body:
        steps.append({"title": "Copy this into the description box:", "cmd": body})
    if provider == "github":
        steps.append({"title": "Press the arrow next to Create pull request, choose Create draft pull request, then press it. "
                               "Don't press Merge: let the reviewer decide."})
        steps.append({"title": "Using the GitHub command-line tool (gh) instead? This makes the same draft. "
                               "It asks you to sign in through your browser; never paste a token into the terminal.",
                      "cmd": f"gh pr create --repo {q(repo)} --base {q(base)} --head {q(b)} --draft --title {q(title)} --body {q(ctx.get('body_short') or '')}"})
    else:
        steps.append({"title": "Tick Mark as draft, then press Create merge request. Don't press Merge: let the reviewer decide."})
        steps.append({"title": "Using the GitLab command-line tool (glab) instead? This makes the same draft. "
                               "It asks you to sign in through your browser; never paste a token into the terminal.",
                      "cmd": f"glab mr create --repo {q(repo)} --source-branch {q(b)} --target-branch {q(base)} --draft --title {q(title)} --description {q(ctx.get('body_short') or '')}"})
    return steps


def make_fallback(root: Path, code: str, detail: str = "", branch: str | None = None, base: str | None = None,
                  title: str = "", body: str = "") -> dict:
    t = remote.saved_target(root) or {}
    provider = t.get("provider") or "github"
    host = t.get("host") or ("github.com" if provider == "github" else "gitlab.com")
    repo = t.get("repo")
    try:
        b = _branch_name(root, branch)
    except RemoteError:
        b = None
    try:
        base_b = remote._branch(base) if base else t.get("default_branch")
    except RemoteError:
        base_b = t.get("default_branch")
    w = remote.web_url(provider, host, repo) if repo else None
    link = remote._review_link(provider, w, base_b, b) if w and b else None
    title_c, body_c = _clean_title(title), _clean_body(body)
    body_short = re.sub(r"\s+", " ", body_c)[:500]
    ctx = {"code": code, "link": link, "repo": repo, "branch": b, "base": base_b, "title": title_c, "body": body_c,
           "body_short": body_short, "token_page": api_token_page(host) if code == "scope_api" else None}
    site = NAMES.get(provider, "the website")
    explain = {
        "auth": f"{site} refused the saved sign-in. Connect again, or open the review on the website.",
        "expired": "Connect again, or open the review on the website.",
        "classic_token": f"Classic GitHub tokens reach every repository you own, so {brand.short()} doesn't use them. "
                         "Make a fine-grained token, or open the review on the website.",
        "scope": "Your token can only read. Make one with write access, or open the review on the website.",
        "scope_api": "Opening a merge request needs GitLab's api permission, which you didn't give at sign-in. "
                     "Add it, or open the merge request on the website.",
        "forbidden": "Your token can't open reviews in this repository. You can still do it on the website.",
        "rate_limited": "Wait a few minutes, or open the review on the website.",
        "rejected": "The website said no. Its reason is below. You can still do it on the website.",
        "network": "Check your internet connection, or open the review on the website.",
        "not_shared": "A review needs your branch on the website first.",
        "other": "You can still open the review on the website. Nothing was merged or changed.",
        "manual": "Open the review on the website yourself. Everything you need is below, ready to copy.",
    }.get(code, "You can still open the review on the website.")
    remote.audit("review_fallback", code, project=str(root), provider=provider, repo=repo or "")
    return {"code": code if code in HEADLINES else "other", "headline": HEADLINES.get(code, HEADLINES["other"]),
            "explain": explain, "detail": _clean(detail, 600), "link": link, "os_default": remote.host_os(),
            "steps": {o: manual_steps(provider, o, ctx) for o in ("windows", "macos", "linux")}}


# ------------------------------------------------------------------ HTTP API (local only, click-driven)
class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=4096)


class PreviewIn(ProjectIn):
    branch: str | None = Field(default=None, max_length=200)
    base: str | None = Field(default=None, max_length=200)


class OpenIn(ProjectIn):
    branch: str = Field(min_length=1, max_length=200)
    base: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=1000)
    body: str = Field(default="", max_length=MAX_BODY * 2)
    draft: bool = True
    action_sha256: str = Field(min_length=64, max_length=64)
    confirmed: bool = False


class FallbackIn(ProjectIn):
    branch: str | None = Field(default=None, max_length=200)
    base: str | None = Field(default=None, max_length=200)
    title: str = Field(default="", max_length=1000)
    body: str = Field(default="", max_length=MAX_BODY * 2)
    reason: str = Field(default="manual", max_length=40)


NO_FALLBACK = {"stale", "not_confirmed", "bad_title", "bad_branch", "no_target", "same_branch", "nothing"}


def _root(project: str) -> Path:
    return remote._root(project)


@router.get("/status")
def api_status(request: Request, project: str, branch: str | None = None):
    remote._auth(request)
    try:
        root, _ = dgit._repo(project, trusted=False)
    except HTTPException as exc:
        return {"version": VERSION, "state": "error", "os": remote.host_os(),
                "error": {"message": str(exc.detail), "code": "project"}}
    return review_status(root, branch)


@router.post("/preview")
def api_preview(request: Request, body: PreviewIn):
    remote._auth(request)
    root = _root(body.project)
    try:
        return preview(root, body.branch, body.base)
    except RemoteError as exc:
        if exc.code in NO_FALLBACK:
            raise HTTPException(exc.status, {"message": str(exc), "code": exc.code}) from None
        return {"ok": False, "error": {"message": str(exc), "code": exc.code},
                "fallback": make_fallback(root, exc.code if exc.code in HEADLINES else "other", exc.detail,
                                          body.branch, body.base)}


@router.post("/open")
def api_open(request: Request, body: OpenIn):
    remote._auth(request)
    root = _root(body.project)
    try:
        return open_request(root, body.branch, body.base, body.title, body.body, body.draft, body.action_sha256,
                            body.confirmed)
    except RemoteError as exc:
        if exc.code in NO_FALLBACK:
            raise HTTPException(exc.status, {"message": str(exc), "code": exc.code}) from None
        return {"ok": False, "error": {"message": str(exc), "code": exc.code},
                "fallback": make_fallback(root, exc.code if exc.code in HEADLINES else "other", exc.detail,
                                          body.branch, body.base, body.title, body.body)}


@router.get("/checks")
def api_checks(request: Request, project: str, branch: str | None = None):
    remote._auth(request)
    root = _root(project)
    try:
        return checks(root, branch)
    except RemoteError as exc:
        t = remote.saved_target(root) or {}
        w = remote.web_url(t["provider"], t["host"], t["repo"]) if t else None
        return {"state": "error", "error": {"message": str(exc), "code": exc.code}, "items": [],
                "title": "Couldn't read the checks", "text": str(exc), "passed": 0, "total": 0,
                "web_url": w, "site": NAMES.get(t.get("provider", ""), "the website")}


@router.get("/details")
def api_details(request: Request, project: str, kind: str, id: str):
    remote._auth(request)
    root = _root(project)
    return remote._http(details, root, kind, id)


@router.post("/fallback")
def api_fallback(request: Request, body: FallbackIn):
    remote._auth(request)
    try:
        root, _ = dgit._repo(body.project, trusted=True)
    except HTTPException as exc:
        raise HTTPException(exc.status_code, {"message": str(exc.detail), "code": "other"}) from None
    reason = body.reason if body.reason in HEADLINES else "manual"
    return {"fallback": make_fallback(root, reason, "", body.branch, body.base, body.title, body.body)}
