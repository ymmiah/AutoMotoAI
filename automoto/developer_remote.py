"""Developer Studio V46: share (push) and get latest (fetch/pull) for a signed-in GitHub or GitLab account.

Safety model (docs/SHARE-TO-GITHUB.md, PLAN.md §4-§7, §12):

* The token never touches Git's settings, remote URLs, files, argv or a long-lived environment.
  Each network Git command gets a one-off credential helper (``-c credential.helper=...`` on that
  single command). The helper asks a broker on 127.0.0.1 that lives only for that command, answers
  once, within 60 seconds, for the exact host and repository path, after a one-time code.
* Git is pinned to the project (``GIT_DIR``/``GIT_WORK_TREE``), ignores the user's global and system
  config, runs no hooks, follows no redirects, uses no proxy and talks only HTTPS to an allowlisted
  host. Repositories whose own config redirects traffic or credentials are refused.
* Sharing is a two-step, click-only action: ``/plan`` computes exactly what will be sent and returns
  an ``action_sha256``; ``/share`` recomputes the plan and only pushes if it is still identical.
  Force-push, deleting branches and pushing tags are not possible: the refspec is always
  ``<exact commit>:refs/heads/<branch>`` without ``+``, and non-fast-forward is refused before Git runs.
* Every outgoing commit is scanned (secrets, key files, .env files, huge files, CI/workflow changes).
* Any failure produces a secret-scanned ``.patch`` (or ``.bundle``) in Documents/AutoMoto/patches
  plus plain-words, per-OS steps to share it by hand. A token is never part of either.
* Text from the remote or the website (Git's ``remote:`` lines, repo names, error bodies) is
  untrusted: control characters are stripped, it is redacted and capped, and the UI shows it as text.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import brand, git_auth, redaction, secretscan
from automoto import developer_git as dgit

router = APIRouter(prefix="/api/developer/studio/remote", tags=["developer-remote"])
VERSION = "remote-1"
NET_TIMEOUT = 120
CRED_TTL = 60
PLAN_TTL = 600
MAX_COMMITS = 2000
MAX_SCAN_BYTES = 40 * 1024 * 1024
WARN_BYTES = 50 * 1024 * 1024
BLOCK_BYTES = 95 * 1024 * 1024
MAX_PATCH = 25 * 1024 * 1024
WORKFLOW_RE = re.compile(r"(?i)^(\.github/workflows/|\.github/actions/|\.gitlab/ci/|\.gitlab-ci\.ya?ml$|"
                         r"(.*/)?action\.ya?ml$|\.circleci/|azure-pipelines\.ya?ml$|Jenkinsfile$|\.travis\.ya?ml$)")
# Repository-local settings that send traffic or credentials somewhere else, or run programs.
REFUSED_CONFIG = re.compile(
    r"^(url\..+\.(insteadof|pushinsteadof)|http\..*|https\..*|credential\..*|core\.(sshcommand|gitproxy|askpass)|"
    r"remote\..+\.(pushurl|receivepack|uploadpack|proxy|proxyauthmethod|vcs|mirror)|protocol\..*|"
    r"submodule\..*|transfer\.(credentialsinurl|bundleuri)|fetch\.bundleuri|lfs\..*|ssh\..*)$", re.I)
GH_REPO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
GL_REPO = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}(?:/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}){1,5}$")
_PLANS: dict[str, dict] = {}
_PLANS_LOCK = threading.Lock()
_STRIP_ENV = ("GIT_TRACE", "GIT_TRACE_CURL", "GIT_TRACE_CURL_NO_DATA", "GIT_TRACE_PACKET", "GIT_TRACE_PERFORMANCE",
              "GIT_TRACE_SETUP", "GIT_TRACE2", "GIT_TRACE2_EVENT", "GIT_TRACE2_PERF", "GIT_CURL_VERBOSE",
              "GIT_SSL_NO_VERIFY", "GIT_PROXY_SSL_CERT", "GIT_PROXY_SSL_KEY", "GIT_HTTP_PROXY_AUTHMETHOD",
              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy", "NO_PROXY",
              "no_proxy", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_HTTP_USER_AGENT", "GIT_ASKPASS",
              "SSH_ASKPASS", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_PROXY_COMMAND", "AUTOMOTO_CRED_BROKER",
              "AUTOMOTO_CRED_NONCE")
# Tests run a fake Git server on plain http://127.0.0.1. Only test code can switch this on;
# there is deliberately no environment variable or setting for it.
_allow_http_loopback = False


class RemoteError(Exception):
    """A failure with a plain-words message and a code the fallback understands."""

    def __init__(self, message: str, code: str = "other", status: int = 400, detail: str = ""):
        super().__init__(message)
        self.code, self.status, self.detail = code, status, detail


# ------------------------------------------------------------------ small helpers
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(text: str, limit: int = 1200, token: str = "") -> str:
    """Untrusted text from the remote: no control or escape characters, no secrets, capped."""
    text = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text or "")
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]", "", text)
    text = redaction.redact(text, (token,) if token else ())
    return text[:limit]


def _data() -> Path:
    from automoto import home

    return home.home()


def patch_dir() -> Path:
    """Documents/AutoMoto/patches (the Documents folder Windows/macOS/Linux users already know)."""
    from automoto import config

    override = config.env_trusted("AUTOMOTO_PATCH_DIR")  # real environment only, never a project .env
    if override:
        p = Path(override).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p
    docs = Path.home() / "Documents"
    if os.name == "nt":
        docs = Path(os.environ.get("USERPROFILE") or Path.home()) / "Documents"
    p = docs / brand.short() / "patches"
    p.mkdir(parents=True, exist_ok=True)
    return p


def audit(action: str, result: str, **extra: Any) -> None:
    """One line per remote action. Only plain facts; everything goes through redaction first."""
    line: dict[str, Any] = {"time": _now().isoformat(timespec="seconds"), "action": action, "result": result}
    for k, v in extra.items():
        if isinstance(v, (str, int, bool)) or v is None:
            line[k] = v[:300] if isinstance(v, str) else v
    text = redaction.redact(json.dumps(line, ensure_ascii=False))
    try:
        p = _data() / "remote-audit.jsonl"
        if p.exists() and p.stat().st_size > 2_000_000:
            os.replace(p, p.with_suffix(".jsonl.1"))
        with open(p, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass


def audit_tail(project: str | None = None, limit: int = 30) -> list[dict]:
    try:
        lines = (_data() / "remote-audit.jsonl").read_text("utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if project and item.get("project") != project:
            continue
        out.append(item)
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------ targets (kept outside .git)
def _targets_file() -> Path:
    d = _data() / "developer-studio"
    d.mkdir(parents=True, exist_ok=True)
    return d / "share-targets.json"


def _targets() -> dict:
    try:
        data = json.loads(_targets_file().read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def saved_target(root: Path) -> dict | None:
    t = _targets().get(str(root))
    return t if isinstance(t, dict) else None


def _save_target(root: Path, target: dict | None) -> None:
    data = _targets()
    if target is None:
        data.pop(str(root), None)
    else:
        data[str(root)] = target
    p = _targets_file()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), "utf-8")
    os.replace(tmp, p)


def normalise_repo(provider: str, raw: str) -> str:
    """'owner/repo' from what the user typed or pasted (a web address is fine)."""
    s = (raw or "").strip()
    s = re.sub(r"^(?:https?://)?(?:www\.)?[^/\s]+\.[a-z]{2,}(?::\d+)?/", "", s, flags=re.I) if "://" in s or \
        re.match(r"^[^/\s]+\.[a-z]{2,}/", s, re.I) else s
    s = re.sub(r"^git@[^:]+:", "", s)
    s = s.split("?")[0].split("#")[0].strip("/")
    s = re.sub(r"/-/.*$", "", s)
    if provider == "github":
        s = "/".join(s.split("/")[:2])
    if s.endswith(".git"):
        s = s[:-4]
    ok = GH_REPO if provider == "github" else GL_REPO
    if not ok.match(s) or ".." in s:
        raise RemoteError("Type the repository as owner/name, for example ymmiah/AutoMotoAI.", "bad_repo", 422)
    return s


def transport_url(provider: str, host: str, repo: str) -> str:
    return f"https://{host}/{repo}.git"


def web_url(provider: str, host: str, repo: str) -> str:
    return f"https://{host}/{repo}"


def _branch(name: str) -> str:
    name = (name or "").strip()
    if not dgit.BRANCH_RE.match(name) or name.endswith(".lock") or name == "HEAD":
        raise RemoteError("That branch name isn't allowed. Use letters, numbers, dashes and slashes.", "bad_branch", 422)
    return name


def suggest_from_origin(root: Path) -> dict | None:
    """Read (never write) remote.origin.url to pre-fill 'Pick where'. Credentials in it are ignored."""
    done = dgit._run(root, ["config", "--local", "--get", "remote.origin.url"], check=False)
    url = done.stdout.decode("utf-8", "replace").strip()
    if not url:
        return None
    m = re.match(r"^(?:https?://(?:[^@/]+@)?|ssh://git@|git@)([^/:]+)(?::\d+)?[:/](.+?)(?:\.git)?/?$", url)
    if not m:
        return None
    host, path = m.group(1).lower(), m.group(2)
    provider = "github" if host == "github.com" else "gitlab" if host in git_auth.allowed_hosts("gitlab") else None
    if not provider:
        return {"host": host, "repo": None, "provider": None, "allowed": False}
    try:
        return {"provider": provider, "host": host, "repo": normalise_repo(provider, path), "allowed": True}
    except RemoteError:
        return None


# ------------------------------------------------------------------ the credential broker
class _Broker:
    """A loopback-only, single-answer, 60-second credential source for exactly one Git process."""

    def __init__(self, token: str, username: str, protocol: str, host: str, path: str):
        self._token, self._user = token, username
        self.protocol, self.host, self.path = protocol, host, path.strip("/")
        self.nonce = secrets.token_urlsafe(32)
        self.expires = time.monotonic() + CRED_TTL
        self.used = False
        self.refused: list[str] = []
        broker = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:  # never log requests
                return

            def do_POST(self) -> None:  # noqa: N802
                answer = broker._answer(self)
                body = json.dumps(answer or {}).encode()
                self.send_response(200 if answer else 403)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/credential"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def _answer(self, req: BaseHTTPRequestHandler) -> dict | None:
        if req.client_address[0] != "127.0.0.1" or req.path != "/credential":
            return None
        try:
            n = min(int(req.headers.get("Content-Length") or 0), 8192)
            d = json.loads(req.rfile.read(n).decode("utf-8"))
        except (ValueError, OSError):
            return None
        if not isinstance(d, dict):
            return None
        why = None
        if not hmac.compare_digest(str(d.get("nonce", "")), self.nonce):
            why = "wrong code"
        elif self.used:
            why = "already used"
        elif time.monotonic() > self.expires:
            why = "expired"
        elif d.get("protocol") != self.protocol or str(d.get("host", "")).lower() != self.host:
            why = "wrong host"
        elif str(d.get("path", "")).strip("/").removesuffix(".git") != self.path.removesuffix(".git"):
            why = "wrong repository"
        if why:
            self.refused.append(why)
            return None
        self.used = True
        return {"username": self._user, "password": self._token}

    def env(self) -> dict:
        return {"AUTOMOTO_CRED_BROKER": self.url, "AUTOMOTO_CRED_NONCE": self.nonce}

    def close(self) -> None:
        self._token = ""
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception:
            pass


def _helper_value() -> str:
    """The credential.helper value for one command: run this Python with git_credential.py."""
    helper = Path(__file__).with_name("git_credential.py")

    def q(p: str) -> str:
        return "'" + p.replace("'", "'\\''") + "'"

    return "!" + q(Path(sys.executable).as_posix()) + " " + q(helper.as_posix())


def _net_env(root: Path) -> dict:
    env = dgit._env(root)
    for k in _STRIP_ENV:
        env.pop(k, None)
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "never", "GIT_HTTP_LOW_SPEED_LIMIT": "1000", "GIT_HTTP_LOW_SPEED_TIME": "60"})
    return env


def _net_overrides(url: str, helper: bool) -> list[str]:
    scheme = url.split("://", 1)[0]
    out = [*dgit.OVERRIDES, "-c", "core.hooksPath=" + os.devnull,
           "-c", "protocol.allow=never", "-c", f"protocol.{scheme}.allow=always",
           "-c", "http.followRedirects=false", "-c", "http.sslVerify=true", "-c", "http.proxy=",
           "-c", "http.emptyAuth=false", "-c", "credential.helper=", "-c", "credential.useHttpPath=true",
           "-c", "credential.interactive=never", "-c", "submodule.recurse=false",
           "-c", "push.recurseSubmodules=no", "-c", "fetch.recurseSubmodules=false",
           "-c", "transfer.fsckObjects=true", "-c", "push.followTags=false", "-c", "core.askPass=",
           "-c", "lfs.fetchexclude=*"]
    if helper:
        out += ["-c", "credential.helper=" + _helper_value()]
    return out


def _check_url(provider: str, host: str, url: str) -> None:
    allowed = set(git_auth.allowed_hosts(provider))
    m = re.match(r"^(https|http)://([^/@:]+(?::\d+)?)/[^\s@]+\.git$", url)
    if not m:
        raise RemoteError("That repository address isn't allowed.", "blocked_host", 403)
    scheme, netloc = m.group(1), m.group(2).lower()
    if scheme == "http":
        if not (_allow_http_loopback and netloc.startswith("127.0.0.1:")):
            raise RemoteError("Only secure (https) connections are allowed.", "blocked_host", 403)
        return
    if netloc not in allowed or host not in allowed or netloc != host:
        raise RemoteError(f"{netloc} isn't on your list of allowed servers.", "blocked_host", 403)


def _username(provider: str, kind: str) -> str:
    return "x-access-token" if provider == "github" else "oauth2"


def net_git(root: Path, target: dict, args: list[str], *, token: str | None, kind: str = "pat",
            timeout: int = NET_TIMEOUT) -> subprocess.CompletedProcess:
    """Run one network Git command against the target's exact URL with a single-use credential."""
    url = target["url"]
    _check_url(target["provider"], target["host"], url)
    env = _net_env(root)
    broker = None
    if token:
        scheme, rest = url.split("://", 1)
        netloc, path = rest.split("/", 1)
        broker = _Broker(token, _username(target["provider"], kind), scheme, netloc.lower(), path)
        env.update(broker.env())
    argv = [dgit._git_binary(env), *_net_overrides(url, bool(broker)), *args]
    try:
        done = subprocess.run(argv, cwd=root, env=env, capture_output=True, timeout=timeout, check=False,
                              shell=False, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise RemoteError("The connection took too long and was stopped.", "network", 504) from None
    except OSError:
        raise RemoteError("Git could not start.", "other", 502) from None
    finally:
        if broker:
            broker.close()
    return done


# ------------------------------------------------------------------ repository checks
def _refuse_redirects(root: Path) -> None:
    config = root / ".git" / "config"
    if config.is_symlink():
        raise RemoteError("This repository's settings file is a link, which isn't allowed.", "refused_config", 403)
    done = dgit._run(root, ["config", "--local", "--no-includes", "--name-only", "--list"], check=False)
    bad = sorted({ln.strip() for ln in done.stdout.decode("utf-8", "replace").splitlines()
                  if REFUSED_CONFIG.match(ln.strip())})
    if bad:
        raise RemoteError("This repository's own settings could send your sign-in or your code somewhere else ("
                          + ", ".join(bad[:4]) + "). " + brand.short() + " won't share from it. Remove those "
                          "settings, or share it yourself from a terminal.", "refused_config", 403)
    if (root / ".git" / "shallow").exists():
        raise RemoteError("This is a shallow copy of a repository. Get the full history before sharing.",
                          "refused_config", 409)


def _open(project: str) -> Path:
    try:
        root, _ = dgit._repo(project, trusted=True)
    except HTTPException as exc:
        raise RemoteError(str(exc.detail), "refused_config" if exc.status_code == 403 else "other",
                          exc.status_code) from None
    _refuse_redirects(root)
    return root


def _git(root: Path, args: list[str], check: bool = True) -> str:
    try:
        return dgit._run(root, args, check=check).stdout.decode("utf-8", "replace")
    except HTTPException as exc:
        raise RemoteError(str(exc.detail), "other", exc.status_code) from None


def _has(root: Path, sha: str) -> bool:
    return dgit._run(root, ["cat-file", "-e", sha + "^{commit}"], check=False).returncode == 0


def _ancestor(root: Path, a: str, b: str) -> bool:
    return dgit._run(root, ["merge-base", "--is-ancestor", a, b], check=False).returncode == 0


# ------------------------------------------------------------------ account and provider facts
def _account(provider: str, host: str) -> tuple[dict | None, tuple[str, str, str] | None]:
    acct = git_auth.account(provider, host)
    tok = git_auth.token_for(provider, host) if acct and acct.get("status") == "ok" else None
    return acct, tok


def push_permission(provider: str, acct: dict | None) -> dict:
    """Decision (PLAN §18 #12): GitHub classic tokens are blocked for sharing; fine-grained or app tokens only."""
    if not acct:
        return {"ok": False, "code": "auth", "message": "Connect your account first."}
    if acct.get("status") != "ok":
        return {"ok": False, "code": "expired", "message": "Your sign-in has ended. Connect again."}
    kind = acct.get("token_kind")
    if provider == "github" and kind == "classic":
        return {"ok": False, "code": "classic_token",
                "message": "This is a classic GitHub token, which can reach every repository you own. For "
                           "sharing, " + brand.short() + " needs a fine-grained token limited to the repositories "
                           "you pick. Make one in Connect GitHub or GitLab and paste it there."}
    scopes = acct.get("scopes") or []
    if provider == "gitlab" and scopes and not ({"write_repository", "api"} & set(scopes)):
        return {"ok": False, "code": "scope",
                "message": "Your GitLab token can only read. Make a token with write_repository and connect again."}
    return {"ok": True}


def repo_facts(provider: str, host: str, repo: str, tok: tuple[str, str, str] | None) -> dict:
    """Public facts about the repository from the website. All text is untrusted."""
    if not tok:
        return {}
    token, _, kind = tok
    hdrs = git_auth._auth_headers(provider, token, kind)
    base = git_auth.api_base(provider, host)
    url = f"{base}/repos/{repo}" if provider == "github" else f"{base}/projects/{quote(repo, safe='')}"
    try:
        status, _, d = git_auth._call(provider, host, "GET", url, hdrs, token=token)
    except git_auth.AuthError as exc:
        raise RemoteError(f"Couldn't reach {host}.", "network", 502, str(exc)) from None
    if status == 401:
        raise RemoteError("Your sign-in was refused. It may have expired or been revoked.", "auth", 401)
    if status in (403, 404):
        raise RemoteError("This repository wasn't found, or your token can't see it. Check the name, and that "
                          "the token includes this repository.", "forbidden", status)
    if status >= 400 or not isinstance(d, dict):
        raise RemoteError(f"{host} answered with an error ({status}).", "other", 502)
    if provider == "github":
        perms = d.get("permissions") if isinstance(d.get("permissions"), dict) else {}
        can = perms.get("push") if perms else None
        return {"name": _clean(str(d.get("full_name") or repo), 200), "default_branch": _clean(str(d.get("default_branch") or ""), 100),
                "private": bool(d.get("private")), "archived": bool(d.get("archived")), "can_push": can}
    access = 0
    p = d.get("permissions") if isinstance(d.get("permissions"), dict) else {}
    for k in ("project_access", "group_access"):
        if isinstance(p.get(k), dict):
            access = max(access, int(p[k].get("access_level") or 0))
    return {"name": _clean(str(d.get("path_with_namespace") or repo), 200),
            "default_branch": _clean(str(d.get("default_branch") or ""), 100),
            "private": d.get("visibility") == "private", "archived": bool(d.get("archived")),
            "can_push": (access >= 30) if p else None}


def branch_facts(provider: str, host: str, repo: str, branch: str, tok: tuple[str, str, str] | None) -> dict:
    if not tok:
        return {}
    token, _, kind = tok
    hdrs = git_auth._auth_headers(provider, token, kind)
    base = git_auth.api_base(provider, host)
    url = (f"{base}/repos/{repo}/branches/{quote(branch, safe='')}" if provider == "github"
           else f"{base}/projects/{quote(repo, safe='')}/repository/branches/{quote(branch, safe='')}")
    try:
        status, _, d = git_auth._call(provider, host, "GET", url, hdrs, token=token)
    except git_auth.AuthError:
        return {}
    if status != 200 or not isinstance(d, dict):
        return {}
    return {"protected": bool(d.get("protected"))}


# ------------------------------------------------------------------ remote heads (over Git itself)
def remote_head(root: Path, target: dict, branch: str, tok: tuple[str, str, str] | None) -> str | None:
    done = net_git(root, target, ["ls-remote", "--heads", target["url"], "refs/heads/" + branch],
                   token=tok[0] if tok else None, kind=tok[2] if tok else "pat", timeout=60)
    if done.returncode != 0:
        err = classify(done, tok[0] if tok else "")
        if err.code == "auth" and tok:
            git_auth.mark_expired(target["provider"], target["host"])
        raise err
    for line in done.stdout.decode("utf-8", "replace").splitlines():
        sha, _, ref = line.partition("\t")
        if ref == "refs/heads/" + branch and re.fullmatch(r"[0-9a-f]{40,64}", sha):
            return sha
    return None


def classify(done: subprocess.CompletedProcess, token: str = "") -> RemoteError:
    """Turn Git's (untrusted) output into one of the fallback cases."""
    err = _clean(done.stderr.decode("utf-8", "replace") + "\n" + done.stdout.decode("utf-8", "replace"), 2000, token)
    low = err.lower()
    tail = "\n".join(x for x in err.strip().splitlines()[-6:] if x)[:600]
    if re.search(r"gh013|push protection|secret[_ ]detect|secret push protection|contains secrets", low):
        return RemoteError("The website stopped this because it looks like it contains a password or key.",
                           "push_protection", 409, tail)
    if re.search(r"gh006|protected branch|not allowed to push code to protected|"
                 r"not allowed to force push|pre-receive hook declined|changes must be made through a pull request", low):
        return RemoteError("This branch is protected, so changes need a review.", "protected", 409, tail)
    if re.search(r"non-fast-forward|fetch first|\[rejected\]|updates were rejected|stale info", low):
        return RemoteError("Someone else shared changes first.", "non_ff", 409, tail)
    if re.search(r"returned error: 401|authentication failed|invalid username or password|"
                 r"could not read (username|password)|bad credentials|terminal prompts disabled", low):
        return RemoteError("Your sign-in was refused. It may have expired or been revoked.", "auth", 401, tail)
    if re.search(r"returned error: 403|permission to .* denied|access denied|you are not allowed|"
                 r"forbidden|write access to repository not granted|denied to ", low):
        return RemoteError("You don't have permission to share to this repository.", "forbidden", 403, tail)
    if re.search(r"returned error: 404|repository not found|not found", low):
        return RemoteError("The repository wasn't found, or your token can't see it.", "forbidden", 404, tail)
    if re.search(r"could not resolve host|failed to connect|couldn't connect|connection (refused|reset|timed out)|"
                 r"timed out|operation too slow|ssl|tls|certificate|network is unreachable|empty reply|"
                 r"unexpected disconnect|rpc failed|early eof|returned error: 5\d\d", low):
        return RemoteError("Couldn't reach the website.", "network", 502, tail)
    return RemoteError("Something went wrong while sharing.", "other", 502, tail)


# ------------------------------------------------------------------ outgoing commits and the scan
def _rev_args(head: str, exclude: list[str]) -> list[str]:
    return [head, *("^" + e for e in exclude)]


def outgoing(root: Path, head: str, exclude: list[str]) -> list[dict]:
    out = _git(root, ["rev-list", "--reverse", "--topo-order", f"--max-count={MAX_COMMITS + 1}",
                      "--format=%H%x1f%an%x1f%ae%x1f%aI%x1f%s", *_rev_args(head, exclude), "--"])
    commits = []
    for line in out.splitlines():
        if line.startswith("commit "):
            continue
        bits = line.split("\x1f")
        if len(bits) == 5:
            commits.append({"sha": bits[0], "short": bits[0][:8], "author": bits[1][:120], "email": bits[2][:200],
                            "date": bits[3], "subject": _clean(bits[4], 200)})
    if len(commits) > MAX_COMMITS:
        raise RemoteError(f"More than {MAX_COMMITS} checkpoints would be shared at once. Share them yourself "
                          "from a terminal.", "too_big", 413)
    return commits


def scan(root: Path, commits: list[dict], known: tuple[str, ...] = ()) -> dict:
    """Check every outgoing commit: added lines (so a secret removed later still counts), file names,
    file sizes and CI/workflow files."""
    blocks: list[dict] = []
    warns: list[dict] = []
    files: dict[str, str] = {}
    binaries: set[str] = set()
    for c in commits:
        raw = _git(root, ["diff-tree", "-r", "--root", "--no-commit-id", "--no-renames", "-z", "--raw",
                          "--no-abbrev", c["sha"]])
        parts = raw.split("\0")
        i = 0
        while i < len(parts) - 1:
            meta, path = parts[i], parts[i + 1]
            i += 2
            if not meta.startswith(":"):
                continue
            fields = meta[1:].split(" ")
            if len(fields) < 5:
                continue
            new_mode, new_sha, status = fields[1], fields[3], fields[4][:1]
            files[path] = {"A": "added", "M": "changed", "D": "deleted", "T": "changed"}.get(status, "changed")
            if status == "D":
                continue
            if new_mode == "160000":
                blocks.append({"rule": "submodule", "path": path, "commit": c["short"],
                               "message": f"{path} points to another repository (a submodule). Share it yourself."})
                continue
            if dgit._secret(path):
                blocks.append({"rule": "secret_file", "path": path, "commit": c["short"],
                               "message": f"{path} looks like a file of passwords or keys. Keep it on this computer "
                                          "and add it to .gitignore."})
            if WORKFLOW_RE.match(path):
                blocks.append({"rule": "workflow", "path": path, "commit": c["short"],
                               "message": f"{path} changes how the website runs automatic jobs (CI). Changes like "
                                          "this can leak secrets or run code on the website, so share them yourself "
                                          "after checking them carefully."})
            size_s = _git(root, ["cat-file", "-s", new_sha], check=False).strip()
            size = int(size_s) if size_s.isdigit() else 0
            if size > BLOCK_BYTES:
                blocks.append({"rule": "huge_file", "path": path, "commit": c["short"], "bytes": size,
                               "message": f"{path} is {size // (1024 * 1024)} MB. Websites refuse files over 100 MB; "
                                          "add it to .gitignore and share without it."})
            elif size > WARN_BYTES:
                warns.append({"rule": "large_file", "path": path, "bytes": size,
                              "message": f"{path} is {size // (1024 * 1024)} MB, which is big. Consider .gitignore."})
        patch = dgit._run(root, ["show", "--format=", "--no-color", "--no-ext-diff", "--no-textconv", "--unified=0",
                                 "--no-renames", "--root", c["sha"]], check=False).stdout[:MAX_SCAN_BYTES]
        current = None
        lineno = 0
        for line in patch.decode("utf-8", "replace").splitlines():
            if line.startswith("+++ "):
                current = line[6:] if line.startswith("+++ b/") else None
                continue
            if line.startswith("Binary files ") and " differ" in line:
                m = re.search(r" and b/(.+) differ$", line)
                if m:
                    binaries.add(m.group(1))
                continue
            if line.startswith("@@"):
                m = re.search(r"\+(\d+)", line)
                lineno = int(m.group(1)) - 1 if m else 0
                continue
            if line.startswith("+") and current is not None:
                lineno += 1
                safe_env = bool(dgit.SAFE_ENV_FILES.search(current))
                for rule, name, masked in secretscan.scan_line(line[1:], generic=not safe_env):
                    blocks.append({"rule": "secret", "kind": rule, "path": current, "line": lineno,
                                   "commit": c["short"], "masked": masked,
                                   "message": f"{current} line {lineno} looks like it contains a secret: {name} ({masked})."})
                for k in known:
                    if k and redaction.contains_secret(line, k):
                        blocks.append({"rule": "secret", "kind": "signed_in_token", "path": current, "line": lineno,
                                       "commit": c["short"], "masked": "hidden",
                                       "message": f"{current} line {lineno} contains your sign-in token."})
    seen = set()
    uniq = []
    for b in blocks:
        key = (b["rule"], b.get("path"), b.get("line"), b.get("kind"))
        if key not in seen:
            seen.add(key)
            uniq.append(b)
    return {"ok": not uniq, "blocks": uniq[:100], "warnings": warns[:50],
            "files": [{"path": p, "change": s} for p, s in sorted(files.items())][:500],
            "file_count": len(files), "binaries": sorted(binaries)[:50]}


# ------------------------------------------------------------------ plan / share
class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)


class TargetIn(ProjectIn):
    provider: str = Field(pattern=r"^(github|gitlab)$")
    host: str | None = Field(default=None, max_length=260)
    repo: str = Field(min_length=3, max_length=400)


class PlanIn(ProjectIn):
    remote_branch: str | None = Field(default=None, max_length=100)


class ShareIn(PlanIn):
    action_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: bool


class FetchIn(ProjectIn):
    remote_branch: str | None = Field(default=None, max_length=100)


class PullIn(FetchIn):
    expected: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    combine: bool = False
    confirmed: bool


class FallbackIn(PlanIn):
    reason: str | None = Field(default=None, max_length=40, pattern=r"^[a-z_]{1,40}$")


def set_target(root: Path, provider: str, host: str | None, repo: str) -> dict:
    try:
        provider, host = git_auth.check_target(provider, host)
    except git_auth.AuthError as exc:
        raise RemoteError(str(exc), "blocked_host", 403) from None
    repo = normalise_repo(provider, repo)
    acct, tok = _account(provider, host)
    if not acct or not tok:
        raise RemoteError("Connect your account first.", "auth", 401)
    facts = repo_facts(provider, host, repo, tok)
    target = {"provider": provider, "host": host, "repo": repo, "default_branch": facts.get("default_branch") or None}
    _save_target(root, target)
    audit("pick_repository", "ok", project=str(root), provider=provider, host=host, repo=repo)
    return {**target, "facts": facts, "web_url": web_url(provider, host, repo)}


def _target(root: Path) -> dict:
    t = saved_target(root)
    if not t:
        raise RemoteError("Pick where to share first.", "no_target", 409)
    t = dict(t)
    t["url"] = transport_url(t["provider"], t["host"], t["repo"])
    return t


def _local_head(root: Path) -> tuple[str | None, str]:
    st = dgit._status(root)
    if st.get("initial"):
        raise RemoteError("There are no checkpoints to share yet. Save one in Checkpoints first.", "nothing", 409)
    if st.get("merging") or st.get("rebasing") or st["counts"]["conflicts"]:
        raise RemoteError("Finish combining changes in Checkpoints first.", "busy", 409)
    head = _git(root, ["rev-parse", "--verify", "HEAD^{commit}"]).strip()
    return st.get("branch"), head


def _action_sha(p: dict) -> str:
    keep = {k: p.get(k) for k in ("project", "provider", "host", "repo", "local_branch", "remote_branch", "head",
                                  "remote_head", "commit_shas", "new_branch")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()


def plan(root: Path, remote_branch: str | None = None) -> dict:
    """Exactly what Share would do. Nothing is sent except reading the remote branch head."""
    target = _target(root)
    provider, host, repo = target["provider"], target["host"], target["repo"]
    acct, tok = _account(provider, host)
    perm = push_permission(provider, acct)
    if not tok and perm["ok"]:
        perm = {"ok": False, "code": "expired", "message": "Your sign-in has ended. Connect again."}
    local_branch, head = _local_head(root)
    rb = _branch(remote_branch or local_branch or "")
    facts = repo_facts(provider, host, repo, tok) if tok else {}
    default = facts.get("default_branch") or target.get("default_branch")
    # A token that may not be used for sharing is not used for anything else here either.
    rhead = remote_head(root, target, rb, tok) if tok and perm["ok"] else None
    blocks: list[dict] = []
    warnings: list[dict] = []
    if not perm["ok"]:
        blocks.append({"rule": perm["code"], "message": perm["message"]})
    if facts.get("archived"):
        blocks.append({"rule": "archived", "message": "This repository is archived (read-only) on the website."})
    if facts.get("can_push") is False:
        blocks.append({"rule": "no_permission",
                       "message": "Your account can't share to this repository. Ask the owner for access, "
                                  "or make your own copy (a fork) and pick that instead."})
    exclude: list[str] = []
    state = "new_branch"
    if rhead:
        if not _has(root, rhead):
            state = "behind"
        elif _ancestor(root, rhead, head):
            state = "up_to_date" if rhead == head else "fast_forward"
            exclude = [rhead]
        else:
            state = "diverged"
    if state in ("behind", "diverged"):
        blocks.append({"rule": "non_ff", "message": "Someone else shared changes to this branch first. Press "
                       "Get latest to bring them in, then share again. " + brand.short() + " never overwrites "
                       "other people's work (no force-push)."})
    if state == "new_branch" and default and default != rb and tok and perm["ok"]:
        try:
            dhead = remote_head(root, target, default, tok)
        except RemoteError:
            dhead = None
        if dhead and _has(root, dhead):
            exclude = [dhead]
    commits = [] if state in ("up_to_date", "behind", "diverged") else outgoing(root, head, exclude)
    if state == "up_to_date":
        blocks.append({"rule": "nothing", "message": "Everything is already shared. Nothing new to send."})
    known = (tok[0],) if tok else ()
    result = scan(root, commits, known) if commits else {"ok": True, "blocks": [], "warnings": [], "files": [],
                                                         "file_count": 0, "binaries": []}
    blocks.extend(result["blocks"])
    warnings.extend(result["warnings"])
    bf = branch_facts(provider, host, repo, rb, tok) if tok else {}
    if default and rb == default:
        warnings.append({"rule": "default_branch", "amber": True,
                         "message": f"{rb} is the main branch everyone uses. It's safer to share as a new branch "
                                    "and ask for a review."})
    if bf.get("protected"):
        warnings.append({"rule": "protected_branch", "amber": True,
                         "message": f"{rb} is protected on the website, so it may refuse direct changes. Share as a "
                                    "new branch instead."})
    suggestion = None
    if (default and rb == default) or bf.get("protected"):
        suggestion = "automoto/" + datetime.now().strftime("%Y%m%d-%H%M")
    p = {"project": str(root), "provider": provider, "host": host, "repo": repo,
         "provider_name": git_auth.PROVIDERS[provider]["name"], "local_branch": local_branch,
         "remote_branch": rb, "head": head, "remote_head": rhead, "state": state, "new_branch": state == "new_branch",
         "default_branch": default, "commits": commits[:200], "commit_count": len(commits),
         "commit_shas": [c["sha"] for c in commits], "files": result["files"], "file_count": result["file_count"],
         "binaries": result["binaries"], "blocks": blocks, "warnings": warnings, "ok": not blocks,
         "suggest_branch": suggestion, "web_url": web_url(provider, host, repo),
         "account": {"login": (acct or {}).get("login"), "token_kind": (acct or {}).get("token_kind")}}
    p["summary"] = (f"Send {len(commits)} checkpoint{'s' if len(commits) != 1 else ''} from "
                    f"{local_branch or 'this checkpoint'} to {rb} on {repo} ({host}).")
    p["action_sha256"] = _action_sha(p)
    with _PLANS_LOCK:
        for k in [k for k, v in _PLANS.items() if v["_at"] < time.monotonic() - PLAN_TTL]:
            _PLANS.pop(k, None)
        _PLANS[p["action_sha256"]] = {"_at": time.monotonic(), "project": str(root)}
    p.pop("commit_shas", None)
    audit("check", "ok" if p["ok"] else "blocked", project=str(root), provider=provider, host=host, repo=repo,
          branch=rb, commits=len(commits), blocked=len(blocks))
    return p


def share(root: Path, remote_branch: str | None, action_sha256: str, confirmed: bool) -> dict:
    if not confirmed:
        raise RemoteError("Press Share to confirm.", "not_confirmed", 400)
    with _PLANS_LOCK:
        known_plan = _PLANS.pop(action_sha256, None)
    if not known_plan or known_plan["project"] != str(root) or known_plan["_at"] < time.monotonic() - PLAN_TTL:
        raise RemoteError("This check is out of date. Run the check again.", "stale", 409)
    fresh = plan(root, remote_branch)
    if fresh["action_sha256"] != action_sha256:
        raise RemoteError("Something changed since the check (a new checkpoint, branch or remote change). "
                          "Look at the new check and press Share again.", "stale", 409)
    if not fresh["ok"]:
        raise RemoteError(fresh["blocks"][0]["message"], fresh["blocks"][0].get("rule", "blocked"), 409)
    with _PLANS_LOCK:
        _PLANS.pop(fresh["action_sha256"], None)
    target = _target(root)
    acct, tok = _account(target["provider"], target["host"])
    if not tok:
        raise RemoteError("Your sign-in has ended. Connect again.", "expired", 401)
    rb, head = fresh["remote_branch"], fresh["head"]
    # No '+', no --force, no tags, exact commit: Git itself refuses anything but a fast-forward.
    refspec = f"{head}:refs/heads/{rb}"
    lock = dgit._lock(root)
    with lock:
        done = net_git(root, target, ["push", "--porcelain", "--no-follow-tags", "--no-verify",
                                      "--no-recurse-submodules", target["url"], refspec],
                       token=tok[0], kind=tok[2])
    if done.returncode != 0:
        err = classify(done, tok[0])
        if err.code == "auth":
            git_auth.mark_expired(target["provider"], target["host"])
        raise err
    audit("share", "ok", project=str(root), provider=target["provider"], host=target["host"], repo=target["repo"],
          branch=rb, commits=fresh["commit_count"], head=head[:12])
    base = target.get("default_branch") or fresh.get("default_branch")
    w = fresh["web_url"]
    links = {"branch": f"{w}/tree/{quote(rb, safe='/')}" if target["provider"] == "github" else f"{w}/-/tree/{quote(rb, safe='/')}"}
    if base and base != rb:
        links["review"] = (f"{w}/compare/{quote(base, safe='/')}...{quote(rb, safe='/')}?expand=1"
                           if target["provider"] == "github"
                           else f"{w}/-/merge_requests/new?merge_request%5Bsource_branch%5D={quote(rb, safe='')}")
    return {"ok": True, "shared": fresh["commit_count"], "remote_branch": rb, "links": links,
            "message": f"Shared {fresh['commit_count']} checkpoint{'s' if fresh['commit_count'] != 1 else ''} to "
                       f"{rb} on {target['repo']}."}


# ------------------------------------------------------------------ get latest
def _private_ref(rb: str) -> str:
    return "refs/automoto/remotes/" + rb


def fetch(root: Path, remote_branch: str | None) -> dict:
    target = _target(root)
    acct, tok = _account(target["provider"], target["host"])
    local_branch, head = _local_head(root)
    rb = _branch(remote_branch or local_branch or target.get("default_branch") or "")
    # Into AutoMoto's own ref only: never touches your branches or remote-tracking settings.
    done = net_git(root, target, ["fetch", "--no-tags", "--no-recurse-submodules", "--no-write-fetch-head",
                                  "--no-auto-gc", target["url"], f"+refs/heads/{rb}:{_private_ref(rb)}"],
                   token=tok[0] if tok else None, kind=tok[2] if tok else "pat")
    if done.returncode != 0:
        err = classify(done, tok[0] if tok else "")
        if "couldn't find remote ref" in (err.detail or "").lower():
            raise RemoteError(f"{rb} doesn't exist on the website yet. Share it first.", "no_branch", 404)
        if err.code == "auth" and tok:
            git_auth.mark_expired(target["provider"], target["host"])
        raise err
    theirs = _git(root, ["rev-parse", "--verify", _private_ref(rb) + "^{commit}"]).strip()
    incoming = outgoing(root, theirs, [head])
    ahead = len(outgoing(root, head, [theirs]))
    files = scan(root, incoming)["files"] if incoming else []
    state = "up_to_date" if not incoming else "fast_forward" if _ancestor(root, head, theirs) else "diverged"
    audit("get_latest", "ok", project=str(root), provider=target["provider"], host=target["host"],
          repo=target["repo"], branch=rb, incoming=len(incoming))
    return {"remote_branch": rb, "state": state, "incoming": incoming[:100], "incoming_count": len(incoming),
            "ahead": ahead, "files": files, "expected": theirs, "local_branch": local_branch,
            "message": ("You're up to date." if not incoming else
                        f"{len(incoming)} new checkpoint{'s' if len(incoming) != 1 else ''} on the website.")}


def pull(root: Path, remote_branch: str | None, expected: str, combine: bool, confirmed: bool) -> dict:
    if not confirmed:
        raise RemoteError("Press the button to confirm.", "not_confirmed", 400)
    local_branch, head = _local_head(root)
    target = _target(root)
    rb = _branch(remote_branch or local_branch or target.get("default_branch") or "")
    theirs = _git(root, ["rev-parse", "--verify", _private_ref(rb) + "^{commit}"], check=False).strip()
    if theirs != expected:
        raise RemoteError("The website changed since you looked. Press Get latest again.", "stale", 409)
    st = dgit._status(root)
    if not st["clean"]:
        names = ", ".join(f["path"] for f in st["files"][:5])
        raise RemoteError("Save a checkpoint (or undo your edits) before bringing in new changes. Changed: "
                          + names + ".", "dirty", 409)
    with dgit._lock(root):
        if _ancestor(root, head, theirs):
            done = dgit._run(root, ["merge", "--ff-only", "--no-edit", theirs], check=False)
            mode = "fast_forward"
        elif combine:
            if not dgit._identity(root)["configured"]:
                raise RemoteError("Combining makes a new checkpoint, so Git needs your name and email. Add them in "
                                  "Checkpoints first.", "identity", 409)
            done = dgit._run(root, ["merge", "--no-ff", "--no-edit", "-m", f"Combine latest {rb} from {target['repo']}",
                                    theirs], check=False)
            mode = "combined"
        else:
            raise RemoteError("Your checkpoints and the website's both changed. Combine them to continue.",
                              "diverged", 409)
    if done.returncode != 0:
        conflicts = (root / ".git" / "MERGE_HEAD").is_file()
        audit("bring_in", "conflict" if conflicts else "failed", project=str(root), branch=rb)
        if conflicts:
            return {"ok": False, "conflicts": True,
                    "message": "Some files were changed on both sides. Open Checkpoints to pick what to keep."}
        raise RemoteError(_clean(done.stderr.decode("utf-8", "replace"), 300) or "Git refused.", "other", 409)
    audit("bring_in", "ok", project=str(root), branch=rb, mode=mode)
    return {"ok": True, "mode": mode, "message": "Your project now has the latest changes."}


# ------------------------------------------------------------------ .patch fallback
HEADLINES = {
    "auth": "Your {P} sign-in ended.",
    "expired": "Your {P} sign-in ended.",
    "forbidden": "You don't have permission to share to this repository.",
    "protected": "This branch is protected, so changes need a review.",
    "non_ff": "Someone else shared changes first.",
    "network": "{B} couldn't reach {P}.",
    "push_protection": "{P} stopped this because it looks like it contains a password or key.",
    "scan_blocked": "{B} stopped this before anything was sent.",
    "blocked_files": "Some files need you to share them yourself.",
    "classic_token": "This token can't be used for sharing.",
    "refused_config": "This repository's settings aren't safe for {B} to use.",
    "manual": "Share it yourself.",
    "other": "Something went wrong while sharing.",
}
EXPLAIN = {
    "auth": "The website didn't accept your saved sign-in. It may have expired or been revoked. Nothing was sent.",
    "expired": "Your saved sign-in has expired. Nothing was sent.",
    "forbidden": "Your account (or your token) isn't allowed to change this repository. Nothing was sent.",
    "protected": "The owner set this branch so changes go through a review. Share to a new branch instead.",
    "non_ff": "The website has checkpoints you don't have yet. {B} never overwrites other people's work.",
    "network": "Check your internet or VPN. Your work is saved in a file below so you can share it another way.",
    "push_protection": "Remove the password or key, save a new checkpoint, and try again. There is no way around this check.",
    "scan_blocked": "Something that looks like a password or key is in the checkpoints. No file was made, so it can't leak.",
    "blocked_files": "These changes include files that {B} doesn't send for you (automatic job files, very big files "
                     "or submodules). Check them carefully, then share with the steps below.",
    "classic_token": "Classic GitHub tokens reach every repository you own, so {B} doesn't share with them. Make a "
                     "fine-grained token in Connect GitHub or GitLab, or share yourself with the steps below.",
    "refused_config": "Its settings could send your sign-in or code somewhere else. You can still share yourself.",
    "manual": "Your checkpoints are saved in a file. Follow the steps to share them from a terminal.",
    "other": "{B} saved your work in a file so nothing is lost. The steps below share it by hand.",
}
NO_PATCH = {"scan_blocked", "push_protection"}
SCAN_SECRET_RULES = {"secret", "secret_file"}


def host_os() -> str:
    return "windows" if os.name == "nt" or sys.platform.startswith("win") else (
        "macos" if sys.platform == "darwin" else "linux")


def _slug(s: str, limit: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s or "").strip("-.")
    return (s or "project")[:limit]


def _q(os_name: str, s: str) -> str:
    s = s.replace("\r", "").replace("\n", "")
    if os_name == "windows":
        return '"' + s.replace("`", "``").replace('"', '`"').replace("$", "`$") + '"'
    return shlex.quote(s)


def _terminal(os_name: str) -> str:
    return {"windows": "Open PowerShell: press the Windows key, type PowerShell, then press Enter.",
            "macos": "Open Terminal: press Cmd+Space, type Terminal, then press Return.",
            "linux": "Open a terminal (often Ctrl+Alt+T)."}[os_name]


def _review_link(provider: str, w: str, base: str | None, branch: str, fork_owner: str | None = None) -> str | None:
    if not base:
        return None
    if provider == "github":
        head = f"{fork_owner}:{branch}" if fork_owner else branch
        return f"{w}/compare/{quote(base, safe='/')}...{quote(head, safe=':/')}?expand=1"
    return f"{w}/-/merge_requests/new?merge_request%5Bsource_branch%5D={quote(branch, safe='')}"


def steps_for(code: str, os_name: str, ctx: dict) -> list[dict]:
    """Beginner steps for one error on one OS. Every command is complete and copyable; no token anywhere."""
    q = lambda s: _q(os_name, s)  # noqa: E731
    P = ctx.get("provider_name") or "the website"
    url, w, rb, base = ctx.get("url"), ctx.get("web"), ctx.get("branch") or "my-changes", ctx.get("base")
    project, patch, bundle = ctx.get("project") or "", ctx.get("patch"), ctx.get("bundle")
    provider = ctx.get("provider") or "github"
    repo_name = (ctx.get("repo") or "project").split("/")[-1]
    out: list[dict] = []

    def add(title: str, cmd: str | None = None, link: dict | None = None, action: str | None = None) -> None:
        out.append({"title": title, "cmd": cmd, "link": link, "action": action})

    def apply_steps(clone_url: str | None, fork_owner: str | None = None, branch: str = rb) -> None:
        add(_terminal(os_name))
        if clone_url:
            add("Download a fresh copy of the repository (it asks you to sign in through your browser if needed).",
                f"git clone {q(clone_url)}")
            add("Go into it.", f"cd {q(repo_name)}")
        else:
            add("Download a fresh copy of the repository (replace the address with yours).",
                "git clone https://github.com/OWNER/REPOSITORY.git")
            add("Go into it (use the folder name git just made).", "cd REPOSITORY")
        if bundle and not patch:
            add("Bring in your checkpoints from the saved file.", f"git pull {q(bundle)} {ctx.get('bundle_ref') or 'HEAD'}")
            add("Put them on their own branch.", f"git switch -c {branch}")
        else:
            add("Make a branch for your changes.", f"git switch -c {branch}")
            add("Add your checkpoints from the saved file.", f"git am {q(patch or 'PATCH-FILE.patch')}")
        add("Send them to the website.", f"git push origin {branch}")
        link = _review_link(provider, w, base, branch, fork_owner) if w else None
        if link:
            add("Ask for a review: open this page and press Create.", None, {"label": "Ask for a review", "url": link})
        if patch:
            add("If git am says the patch doesn't fit: undo it, get the latest code, and try again with a 3-way merge.",
                f"git am --abort; git pull; git am -3 {q(patch)}")

    if code in ("auth", "expired"):
        add(f"Easiest: sign in to {P} again in Connect GitHub or GitLab, then press Share again.", action="signin")
        if url:
            add("Or share it yourself. " + _terminal(os_name))
            add("Go to your project folder.", f"cd {q(project)}")
            add("Send your checkpoints. Git opens your browser to sign in (Git Credential Manager).",
                f"git push {q(url)} HEAD:{rb}")
    elif code == "forbidden" and ctx.get("login") and ctx.get("repo", "").split("/")[0].lower() == ctx["login"].lower():
        # Your own repository: the token just doesn't include it (fine-grained tokens list repositories).
        add(f"Your token doesn't include this repository. Make a new token that includes {ctx.get('repo')} in "
            "Connect GitHub or GitLab, then press Share again.", action="signin")
        add("Or share it yourself:")
        apply_steps(url)
    elif code == "forbidden":
        login = ctx.get("login")
        if w and provider == "github":
            add("Make your own copy of the repository (a fork) on GitHub.", None,
                {"label": "Fork on GitHub", "url": f"{w}/fork"})
        elif w:
            add("Make your own copy of the project (a fork) on GitLab.", None,
                {"label": "Fork on GitLab", "url": f"{w}/-/forks/new"})
        else:
            add("Ask the owner for access, or make your own copy (a fork) on the website.")
        clone = f"https://{ctx['host']}/{login}/{repo_name}.git" if login and ctx.get("host") else None
        apply_steps(clone, login if provider == "github" else None)
    elif code == "protected":
        nb = ctx.get("new_branch") or "automoto/my-changes"
        add(f"Easiest: share as a new branch ({nb}) and ask for a review.", action="new_branch")
        if url:
            add("Or do it yourself. " + _terminal(os_name))
            add("Go to your project folder.", f"cd {q(project)}")
            add("Send your checkpoints to a new branch.", f"git push {q(url)} HEAD:refs/heads/{nb}")
            link = _review_link(provider, w, base or rb, nb) if w else None
            if link:
                add("Ask for a review: open this page and press Create.", None, {"label": "Ask for a review", "url": link})
    elif code == "non_ff":
        add("Easiest: press Get latest, then Share again.", action="get_latest")
        if url:
            add("Or do it yourself. " + _terminal(os_name))
            add("Go to your project folder.", f"cd {q(project)}")
            add("Get the new checkpoints without mixing anything yet.", f"git pull --ff-only {q(url)} {rb}")
            add("If it says the branches have diverged, combine them (fix any conflicts in Checkpoints).",
                f"git pull --no-rebase {q(url)} {rb}")
            add("Send your checkpoints. Never add --force: it would delete other people's work.",
                f"git push {q(url)} HEAD:{rb}")
    elif code == "network":
        add("Check your internet or VPN, then press Try again.", action="retry")
        add("Or copy the saved file to a computer that's online and share it from there:")
        apply_steps(url)
    elif code in ("push_protection", "scan_blocked"):
        for f in ctx.get("findings", [])[:10]:
            add("Remove this: " + f)
        add("Open Checkpoints and save a new checkpoint without the secret.")
        add("If the secret was ever real, change it (revoke it) on the website it came from, because it may be in "
            "older checkpoints too.")
        add("Press Share again.", action="retry")
    elif code == "classic_token":
        add("Make a fine-grained token in Connect GitHub or GitLab, then press Share again.", action="signin")
        apply_steps(url)
    else:
        apply_steps(url)
    return out


def _base_for_fallback(root: Path, head: str, rb: str | None, default: str | None) -> str | None:
    cands = []
    for b in (rb, default):
        if b:
            cands += [_private_ref(b), "refs/remotes/origin/" + b]
    for ref in cands:
        sha = dgit._run(root, ["rev-parse", "--verify", "--quiet", ref + "^{commit}"], check=False).stdout.decode().strip()
        if sha:
            mb = dgit._run(root, ["merge-base", sha, head], check=False).stdout.decode().strip()
            if mb:
                return mb
    return None


def make_fallback(root: Path, code: str, detail: str = "", remote_branch: str | None = None,
                  findings: list[str] | None = None) -> dict:
    target = saved_target(root)
    provider = (target or {}).get("provider")
    host = (target or {}).get("host")
    repo = (target or {}).get("repo")
    tok = None
    acct = None
    if target:
        acct, tok = _account(provider, host)
    token = tok[0] if tok else ""
    try:
        local_branch, head = _local_head(root)
    except RemoteError:
        local_branch, head = None, None
    rb = remote_branch or local_branch
    try:
        rb = _branch(rb) if rb else None
    except RemoteError:
        rb = None
    default = (target or {}).get("default_branch")
    patch_info = bundle_info = None
    commits: list[dict] = []
    blocks: list[dict] = []
    if head:
        base = _base_for_fallback(root, head, rb, default)
        commits = outgoing(root, head, [base] if base else [])
        if commits:
            result = scan(root, commits, (token,) if token else ())
            blocks = [b for b in result["blocks"] if b["rule"] in SCAN_SECRET_RULES]
            if blocks:
                code = "scan_blocked"
                findings = [b["message"] for b in blocks]
            elif code not in NO_PATCH:
                patch_info, bundle_info = _write_files(root, repo, rb or "changes", head, base, local_branch,
                                                       bool(result["binaries"]), token)
                if patch_info is None and bundle_info is None:
                    code = "scan_blocked"
                    findings = ["The saved file itself contained something that looks like a secret, so it was deleted."]
    P = git_auth.PROVIDERS.get(provider or "", {}).get("name") or "the website"
    B = brand.short()
    ctx = {"provider": provider, "provider_name": P, "host": host, "repo": repo, "project": str(root),
           "url": transport_url(provider, host, repo) if target else None,
           "web": web_url(provider, host, repo) if target else None, "branch": rb, "base": default,
           "patch": patch_info["path"] if patch_info else None, "bundle": bundle_info["path"] if bundle_info else None,
           "bundle_ref": bundle_info.get("ref") if bundle_info else None,
           "login": (acct or {}).get("login"), "new_branch": "automoto/" + datetime.now().strftime("%Y%m%d-%H%M"),
           "findings": findings or []}
    out = {"code": code, "headline": HEADLINES.get(code, HEADLINES["other"]).format(P=P, B=B),
           "explain": EXPLAIN.get(code, EXPLAIN["other"]).format(P=P, B=B),
           "detail": _clean(detail, 600, token), "patch": patch_info, "bundle": bundle_info,
           "commit_count": len(commits), "folder": str(patch_dir()), "os_default": host_os(),
           "steps": {o: steps_for(code, o, ctx) for o in ("windows", "macos", "linux")}}
    text = json.dumps(out)
    if token and redaction.contains_secret(text, token):
        raise RemoteError("Blocked instructions that contained a secret.", "other", 500)
    audit("fallback", code, project=str(root), provider=provider, host=host, repo=repo, branch=rb,
          patch=bool(patch_info), bundle=bool(bundle_info), commits=len(commits))
    return out


def _write_files(root: Path, repo: str | None, rb: str, head: str, base: str | None, local_branch: str | None,
                 binary: bool, token: str) -> tuple[dict | None, dict | None]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = f"{_slug((repo or root.name).split('/')[-1])}-{_slug(rb)}-{stamp}"
    folder = patch_dir()
    rng = [f"{base}..{head}"] if base else ["--root", head]
    done = dgit._run(root, ["format-patch", "--stdout", "--no-signature", "--binary", "--no-color", "--no-ext-diff",
                            "--no-textconv", "--no-renames", "--zero-commit", *rng], check=False, timeout=120)
    patch_info = None
    data = done.stdout
    if done.returncode == 0 and data and len(data) <= MAX_PATCH:
        text = data.decode("utf-8", "replace")
        hits = [h for h in secretscan.scan_text(text, known=(token,) if token else (), generic=False)]
        if hits:
            return None, None
        p = folder / (stem + ".patch")
        p.write_bytes(data)
        patch_info = {"path": str(p), "name": p.name, "bytes": len(data), "kind": "patch"}
    bundle_info = None
    if binary or patch_info is None:
        ref = f"refs/heads/{local_branch}" if local_branch else "HEAD"
        b = folder / (stem + ".bundle")
        args = ["bundle", "create", str(b), ref] + (["^" + base] if base else [])
        made = dgit._run(root, args, check=False, timeout=300)
        if made.returncode == 0 and b.exists():
            blob = b.read_bytes()
            if token and redaction.contains_secret(blob.decode("latin-1"), token):
                b.unlink(missing_ok=True)
                if patch_info:
                    Path(patch_info["path"]).unlink(missing_ok=True)
                return None, None
            bundle_info = {"path": str(b), "name": b.name, "bytes": len(blob), "kind": "bundle",
                           "ref": local_branch or "HEAD"}
    return patch_info, bundle_info


# ------------------------------------------------------------------ status for the UI
def status(root: Path) -> dict:
    accts = [a for a in git_auth.status()["accounts"]]
    target = saved_target(root)
    st = dgit._status(root)
    last = audit_tail(str(root), 5)
    perm = push_permission(target["provider"], git_auth.account(target["provider"], target["host"])) if target else None
    return {"version": VERSION, "accounts": accts, "target": target, "suggestion": suggest_from_origin(root),
            "branch": st.get("branch"), "detached": st.get("detached"), "clean": st.get("clean"),
            "has_commits": not st.get("initial"), "push_permission": perm, "recent": last,
            "patch_folder": str(patch_dir()), "os": host_os()}


# ------------------------------------------------------------------ HTTP API (local only, click-driven)
def _auth(request: Request) -> None:
    from automoto import developer_studio as studio

    studio._auth(request)


def _http(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except RemoteError as exc:
        raise HTTPException(exc.status if 400 <= exc.status < 600 else 400,
                            {"message": str(exc), "code": exc.code}) from None


def _root(project: str) -> Path:
    return _http(_open, project)


# Every failure while sharing ends in the fallback, except "look again" cases.
NO_FALLBACK = {"stale", "not_confirmed", "nothing", "no_target", "bad_branch", "bad_repo", "busy", "dirty"}
CODE_MAP = {"no_permission": "forbidden", "archived": "forbidden", "scope": "classic_token", "secret": "scan_blocked",
            "secret_file": "scan_blocked", "workflow": "blocked_files", "huge_file": "blocked_files",
            "submodule": "blocked_files", "blocked_host": "forbidden", "too_big": "other"}


@router.get("/status")
def api_status(request: Request, project: str):
    _auth(request)
    try:
        root, _ = dgit._repo(project, trusted=False)
    except HTTPException as exc:
        return {"version": VERSION, "error": {"message": str(exc.detail), "status": exc.status_code},
                "accounts": git_auth.status()["accounts"], "os": host_os(), "patch_folder": str(patch_dir())}
    out = status(root)
    try:
        _refuse_redirects(root)
    except RemoteError as exc:
        out["refused"] = {"message": str(exc), "code": exc.code}
    return out


@router.post("/target")
def api_target(request: Request, body: TargetIn):
    _auth(request)
    root = _root(body.project)
    return _http(set_target, root, body.provider, body.host, body.repo)


@router.post("/plan")
def api_plan(request: Request, body: PlanIn):
    _auth(request)
    root = _root(body.project)
    return _http(plan, root, body.remote_branch)


@router.post("/share")
def api_share(request: Request, body: ShareIn):
    _auth(request)
    root = _root(body.project)
    try:
        return share(root, body.remote_branch, body.action_sha256, body.confirmed)
    except RemoteError as exc:
        if exc.code in NO_FALLBACK:
            raise HTTPException(exc.status, {"message": str(exc), "code": exc.code}) from None
        audit("share", exc.code, project=str(root))
        code = CODE_MAP.get(exc.code, exc.code if exc.code in HEADLINES else "other")
        fb = _http(make_fallback, root, code, exc.detail or str(exc), body.remote_branch)
        return {"ok": False, "error": {"message": str(exc), "code": exc.code}, "fallback": fb}


@router.post("/fallback")
def api_fallback(request: Request, body: FallbackIn):
    _auth(request)
    try:
        root, _ = dgit._repo(body.project, trusted=True)
    except HTTPException as exc:
        raise HTTPException(exc.status_code, {"message": str(exc.detail), "code": "other"}) from None
    reason = body.reason if body.reason in HEADLINES else "manual"
    reason = CODE_MAP.get(reason, reason)
    return {"fallback": _http(make_fallback, root, reason, "", body.remote_branch)}


@router.post("/fetch")
def api_fetch(request: Request, body: FetchIn):
    _auth(request)
    root = _root(body.project)
    return _http(fetch, root, body.remote_branch)


@router.post("/pull")
def api_pull(request: Request, body: PullIn):
    _auth(request)
    root = _root(body.project)
    return _http(pull, root, body.remote_branch, body.expected, body.combine, body.confirmed)


@router.get("/audit")
def api_audit(request: Request, project: str | None = None):
    _auth(request)
    return {"items": audit_tail(project, 50)}
