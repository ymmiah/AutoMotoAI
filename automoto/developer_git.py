"""Developer Studio V45: local Git, confined to the open project and never pushing.

What it does: status, branches (list, create, switch), stage/unstage, commit,
per-file diffs, recent history and a conflict view with keep-mine / keep-theirs /
keep-both resolution.

Confinement and safety (see docs/DEVELOPER-STUDIO-V41-V45.md):

* Every call pins ``GIT_DIR=<project>/.git`` and ``GIT_WORK_TREE=<project>``, so
  Git cannot walk up into a parent repository or touch files outside the folder.
  A ``.git`` *file* (worktree or submodule pointer) or symlink is refused.
* There is no push, pull, fetch, clone or remote endpoint, and every call runs with
  ``protocol.allow=never`` so no network transport can be used even by accident.
* Repository hooks, fsmonitor, external diff, textconv and signing programs are
  switched off per call, and a repository whose own config defines commands
  (filters, merge drivers, includes, sshCommand...) is refused.
* Changes (stage, commit, branch, resolve) need the project to be trusted and the
  commit itself needs explicit confirmation. Likely secret files cannot be staged.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import threading
from pathlib import Path, PurePosixPath
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import brand
from automoto import developer_adapters as adapters
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/git", tags=["developer-git"])
VERSION = "1.0.0"
TIMEOUT = 30
MAX_OUTPUT = 2 * 1024 * 1024
MAX_FILES = 1000
MAX_DIFF = 192 * 1024
MAX_CONFLICT_FILE = 512 * 1024
LOCKS: dict[str, threading.Lock] = {}
LOCKS_GUARD = threading.Lock()
BRANCH_RE = re.compile(r"^(?!-)(?!.*\.\.)(?!.*//)(?!.*@\{)[A-Za-z0-9._/-]{1,100}(?<![./])$")
SECRET_NAMES = re.compile(
    r"(?i)(^|/)(\.env(\.[^/]*)?|id_rsa|id_dsa|id_ecdsa|id_ed25519|\.npmrc|\.pypirc|\.netrc|"
    r"credentials(\.json)?|secrets?\.(json|ya?ml|toml))$|\.(pem|key|p12|pfx|jks|keystore|kdbx)$")
SAFE_ENV_FILES = re.compile(r"(?i)(^|/)\.env\.(example|sample|template|dist)$")
# Repository-local settings that make Git run other programs and cannot be fully
# switched off per call. Hooks, fsmonitor, pager, editor, sshCommand, signing and
# credential helpers are overridden on every call instead (see OVERRIDES / _env).
DANGEROUS_CONFIG = re.compile(
    r"^(filter\..+\.(clean|smudge|process)|diff\..+\.(textconv|command)|merge\..+\.driver|"
    r"include\.path|includeif\..+|core\.worktree|gpg\..*program)$", re.I)
OVERRIDES = [
    "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
    "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false",
    "-c", "protocol.allow=never", "-c", "core.pager=cat", "-c", "credential.helper=",
    "-c", "core.sshCommand=false", "-c", "diff.external=", "-c", "core.quotepath=false",
    "-c", "advice.detachedHead=false", "-c", "init.defaultBranch=main",
]


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)


class InitIn(ProjectIn):
    confirmed: Literal[True]


class StageIn(ProjectIn):
    paths: list[str] = Field(min_length=1, max_length=200)
    stage: bool = True


class CommitIn(ProjectIn):
    message: str = Field(min_length=1, max_length=5000)
    confirmed: Literal[True]
    author_name: str | None = Field(default=None, min_length=1, max_length=120)
    author_email: str | None = Field(default=None, min_length=3, max_length=200,
                                     pattern=r"^[^\s<>@]+@[^\s<>@]+$")


class BranchIn(ProjectIn):
    name: str = Field(min_length=1, max_length=100)
    switch: bool = True


class SwitchIn(ProjectIn):
    name: str = Field(min_length=1, max_length=100)


class ResolveIn(ProjectIn):
    path: str = Field(min_length=1, max_length=1024)
    choice: Literal["ours", "theirs", "both"] | None = None
    choices: list[Literal["ours", "theirs", "both"]] | None = Field(default=None, max_length=500)
    expected_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    confirmed: Literal[True]


# --------------------------------------------------------------------------- plumbing

def _lock(root: Path) -> threading.Lock:
    with LOCKS_GUARD:
        return LOCKS.setdefault(str(root), threading.Lock())


def _empty_hooks() -> str:
    # A device, not a folder: Git finds no hooks there and nobody can plant one.
    return os.devnull


def _env(root: Path) -> dict:
    env = adapters._environment(root)
    env.pop("AUTOMOTO_TOOLCHAIN_SDK", None)
    env.update({
        "GIT_DIR": str(root / ".git"), "GIT_WORK_TREE": str(root),
        "GIT_CEILING_DIRECTORIES": str(root.parent), "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_EDITOR": "false",
        "GIT_SEQUENCE_EDITOR": "false", "GIT_ASKPASS": "", "SSH_ASKPASS": "",
        "GIT_PAGER": "cat", "LC_ALL": "C", "GIT_NO_REPLACE_OBJECTS": "1",
    })
    for name in ("GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                 "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_PROXY_COMMAND",
                 "GIT_EXTERNAL_DIFF", "GIT_EXEC_PATH"):
        env.pop(name, None)
    return env


def _git_binary(env: dict) -> str:
    import shutil
    found = shutil.which("git", path=env.get("PATH", ""))
    if not found:
        raise HTTPException(424, "Git is not installed or not on PATH.")
    return found


def _run(root: Path, args: list[str], *, check: bool = True, stdin: bytes | None = None,
         timeout: int = TIMEOUT) -> subprocess.CompletedProcess:
    env = _env(root)
    argv = [_git_binary(env), *OVERRIDES, "-c", "core.hooksPath=" + _empty_hooks(), *args]
    try:
        done = subprocess.run(argv, cwd=root, env=env, input=stdin, capture_output=True,
                              timeout=timeout, check=False, shell=False,
                              stdin=None if stdin is not None else subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, "Git took too long and was stopped.") from exc
    except OSError as exc:
        raise HTTPException(502, "Git could not start.") from exc
    if len(done.stdout) > MAX_OUTPUT:
        done = subprocess.CompletedProcess(done.args, done.returncode, done.stdout[:MAX_OUTPUT], done.stderr)
    if check and done.returncode != 0:
        message = done.stderr.decode("utf-8", errors="replace").strip().splitlines()
        tail = "; ".join(x for x in message[-3:] if x)[:400] or "Git refused the operation."
        raise HTTPException(409, tail)
    return done


def _repo_state(root: Path) -> bool:
    dot = root / ".git"
    if dot.is_symlink():
        raise HTTPException(403, "This project's .git is a symbolic link, which is not allowed.")
    if dot.exists() and not dot.is_dir():
        raise HTTPException(403, "This folder is a Git worktree or submodule pointer. Open the main repository folder instead.")
    return dot.is_dir()


def _check_config(root: Path) -> None:
    config = root / ".git" / "config"
    if config.is_symlink():
        raise HTTPException(403, "Repository config cannot be a symbolic link.")
    done = _run(root, ["config", "--local", "--no-includes", "--name-only", "--list"], check=False)
    bad = sorted({line.strip() for line in done.stdout.decode("utf-8", errors="replace").splitlines()
                  if DANGEROUS_CONFIG.match(line.strip())})
    if bad:
        raise HTTPException(403, "This repository's settings run extra programs (" + ", ".join(bad[:4])
                            + "). " + brand.short() + " will not run Git here; use your own terminal.")


def _repo(project: str, *, trusted: bool = False, need_repo: bool = True) -> tuple[Path, bool]:
    root = studio._project(project)
    if trusted:
        adapters._trusted(root)
    exists = _repo_state(root)
    if need_repo and not exists:
        raise HTTPException(404, "This project is not a Git repository yet.")
    if exists:
        _check_config(root)
    return root, exists


def _rel(path: str) -> str:
    if (not path or len(path) > 1024 or "\x00" in path or "\\" in path or path.startswith("-")
            or path.startswith(":")):
        raise HTTPException(422, "Invalid file path.")
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in ("", ".", "..", ".git") for part in path.split("/")):
        raise HTTPException(403, "Path must stay inside the project.")
    return pure.as_posix()


def _secret(path: str) -> bool:
    return bool(SECRET_NAMES.search(path)) and not SAFE_ENV_FILES.search(path)


# --------------------------------------------------------------------------- status

XY = {"M": "modified", "A": "added", "D": "deleted", "R": "renamed", "C": "copied", "T": "type changed",
      "U": "conflict", ".": None}


def _status(root: Path) -> dict:
    done = _run(root, ["status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all",
                       "--ignore-submodules=all"])
    branch = {"head": None, "oid": None, "upstream": None, "ahead": 0, "behind": 0}
    files: list[dict] = []
    parts = done.stdout.decode("utf-8", errors="replace").split("\0")
    i = 0
    truncated = False
    while i < len(parts):
        item = parts[i]
        i += 1
        if not item:
            continue
        if item.startswith("# branch.head "):
            branch["head"] = item[14:]
        elif item.startswith("# branch.oid "):
            branch["oid"] = item[13:]
        elif item.startswith("# branch.upstream "):
            branch["upstream"] = item[18:]
        elif item.startswith("# branch.ab "):
            m = re.match(r"# branch\.ab \+(\d+) -(\d+)", item)
            if m:
                branch["ahead"], branch["behind"] = int(m.group(1)), int(m.group(2))
        elif item[:2] in ("1 ", "2 ", "u ", "? "):
            if len(files) >= MAX_FILES:
                truncated = True
                continue
            kind = item[0]
            if kind == "?":
                files.append({"path": item[2:], "index": None, "worktree": "untracked",
                              "staged": False, "unstaged": True, "conflict": False})
                continue
            fields = item.split(" ")
            xy = fields[1]
            if kind == "1":
                path = " ".join(fields[8:])
                orig = None
            elif kind == "2":
                path = " ".join(fields[9:])
                orig = parts[i]
                i += 1
            else:
                path = " ".join(fields[10:])
                orig = None
            conflict = kind == "u"
            files.append({"path": path, "from": orig,
                          "index": "conflict" if conflict else XY.get(xy[0]),
                          "worktree": "conflict" if conflict else XY.get(xy[1]),
                          "staged": not conflict and xy[0] != ".",
                          "unstaged": conflict or xy[1] != ".", "conflict": conflict})
    for f in files:
        f["secret_like"] = _secret(f["path"])
    detached = branch["head"] == "(detached)"
    merging = (root / ".git" / "MERGE_HEAD").is_file()
    rebasing = (root / ".git" / "rebase-merge").is_dir() or (root / ".git" / "rebase-apply").is_dir()
    return {"repository": True, "branch": None if detached else branch["head"], "detached": detached,
            "head": None if branch["oid"] in (None, "(initial)") else branch["oid"][:12],
            "initial": branch["oid"] == "(initial)", "upstream": branch["upstream"],
            "ahead": branch["ahead"], "behind": branch["behind"],
            "files": files, "truncated": truncated,
            "counts": {"staged": sum(f["staged"] for f in files),
                       "unstaged": sum(f["unstaged"] and not f["conflict"] for f in files),
                       "conflicts": sum(f["conflict"] for f in files)},
            "merging": merging, "rebasing": rebasing, "clean": not files,
            "push_supported": False, "network_allowed": False}


def _log(root: Path, limit: int = 15) -> list[dict]:
    done = _run(root, ["log", "-n", str(limit), "--no-show-signature", "--format=%h%x1f%an%x1f%ar%x1f%s%x1e"],
                check=False)
    if done.returncode != 0:
        return []
    out = []
    for rec in done.stdout.decode("utf-8", errors="replace").split("\x1e"):
        bits = rec.strip("\n").split("\x1f")
        if len(bits) == 4:
            out.append({"sha": bits[0], "author": bits[1], "when": bits[2], "subject": bits[3][:200]})
    return out


def _identity(root: Path) -> dict:
    name = _run(root, ["config", "--get", "user.name"], check=False).stdout.decode("utf-8", "replace").strip()
    email = _run(root, ["config", "--get", "user.email"], check=False).stdout.decode("utf-8", "replace").strip()
    return {"name": name or None, "email": email or None, "configured": bool(name and email)}


@router.get("/status")
def status(request: Request, project: str):
    studio._auth(request)
    root, exists = _repo(project, need_repo=False)
    if not exists:
        return {"version": VERSION, "repository": False, "push_supported": False, "network_allowed": False,
                "project": str(root)}
    with _lock(root):
        data = _status(root)
        data["recent"] = _log(root)
        data["identity"] = _identity(root)
    data.update({"version": VERSION, "project": str(root)})
    return data


@router.post("/init")
def init(request: Request, body: InitIn):
    studio._auth(request)
    root, exists = _repo(body.project, trusted=True, need_repo=False)
    if exists:
        raise HTTPException(409, "This project is already a Git repository.")
    with _lock(root):
        env = _env(root)
        env.pop("GIT_DIR", None)
        env.pop("GIT_WORK_TREE", None)
        subprocess.run([_git_binary(env), *OVERRIDES, "init", "-q", "-b", "main", str(root)], cwd=root, env=env,
                       capture_output=True, timeout=TIMEOUT, check=False, stdin=subprocess.DEVNULL)
        if not (root / ".git").is_dir():
            raise HTTPException(409, "Git could not create a repository here.")
        return _status(root) | {"recent": [], "identity": _identity(root)}


# --------------------------------------------------------------------------- branches

@router.get("/branches")
def branches(request: Request, project: str):
    studio._auth(request)
    root, _ = _repo(project)
    with _lock(root):
        done = _run(root, ["for-each-ref", "refs/heads", "--sort=-committerdate",
                           "--format=%(refname:short)%1f%(objectname:short)%1f%(committerdate:relative)%1f%(subject)%1f%(HEAD)"],
                    check=False)
    out = []
    for line in done.stdout.decode("utf-8", errors="replace").splitlines()[:200]:
        bits = line.split("\x1f")
        if len(bits) == 5:
            out.append({"name": bits[0], "sha": bits[1], "when": bits[2], "subject": bits[3][:200],
                        "current": bits[4].strip() == "*"})
    return {"branches": out, "remote_branches_shown": False}


def _branch_name(root: Path, name: str) -> str:
    if not BRANCH_RE.match(name) or name.endswith(".lock") or name == "HEAD":
        raise HTTPException(422, "Use letters, numbers, dots, dashes, underscores or slashes for branch names.")
    if _run(root, ["check-ref-format", "--branch", name], check=False).returncode != 0:
        raise HTTPException(422, "Git does not accept that branch name.")
    return name


@router.post("/branch")
def create_branch(request: Request, body: BranchIn):
    studio._auth(request)
    root, _ = _repo(body.project, trusted=True)
    with _lock(root):
        name = _branch_name(root, body.name)
        if body.switch:
            _run(root, ["switch", "-c", name])
        else:
            _run(root, ["branch", "--no-track", name])
        return _status(root)


@router.post("/switch")
def switch(request: Request, body: SwitchIn):
    studio._auth(request)
    root, _ = _repo(body.project, trusted=True)
    with _lock(root):
        name = _branch_name(root, body.name)
        if _run(root, ["show-ref", "--verify", "--quiet", "refs/heads/" + name], check=False).returncode != 0:
            raise HTTPException(404, "No local branch with that name.")
        # No --force / --discard-changes: Git refuses if uncommitted work would be lost.
        _run(root, ["switch", "--no-guess", name])
        return _status(root)


# --------------------------------------------------------------------------- stage / commit

@router.post("/stage")
def stage(request: Request, body: StageIn):
    studio._auth(request)
    root, _ = _repo(body.project, trusted=True)
    with _lock(root):
        current = {f["path"]: f for f in _status(root)["files"]}
        paths = []
        for raw in body.paths:
            path = _rel(raw)
            if path not in current:
                raise HTTPException(404, "Not a changed file: " + path)
            if body.stage and _secret(path):
                raise HTTPException(403, path + " looks like a secret (keys, tokens or .env). " + brand.short() + " will not stage it.")
            paths.append(path)
        if body.stage:
            _run(root, ["add", "--", *paths])
        elif _status(root)["initial"]:
            _run(root, ["rm", "--cached", "-q", "--", *paths])
        else:
            _run(root, ["restore", "--staged", "--", *paths])
        return _status(root)


@router.post("/commit")
def commit(request: Request, body: CommitIn):
    studio._auth(request)
    root, _ = _repo(body.project, trusted=True)
    message = body.message.replace("\r\n", "\n").strip()
    if not message:
        raise HTTPException(422, "Write a short commit message.")
    with _lock(root):
        state = _status(root)
        if state["counts"]["conflicts"]:
            raise HTTPException(409, "Resolve the conflicts before committing.")
        if not state["counts"]["staged"] and not state["merging"]:
            raise HTTPException(409, "Nothing is staged. Stage the files you want to commit first.")
        for f in state["files"]:
            if f["staged"] and f["secret_like"]:
                raise HTTPException(403, f["path"] + " looks like a secret. Unstage it before committing.")
        ident = []
        if body.author_name and body.author_email:
            ident = ["-c", "user.name=" + body.author_name.replace("\n", " "),
                     "-c", "user.email=" + body.author_email]
        elif not _identity(root)["configured"]:
            raise HTTPException(428, "Git needs your name and email for commits. Add them and try again.")
        _run(root, [*ident, "commit", "--no-verify", "--no-edit", "--cleanup=strip", "-F", "-"],
             stdin=message.encode("utf-8"))
        data = _status(root)
        data["recent"] = _log(root)
        data["identity"] = _identity(root)
        data["pushed"] = False
        return data


# --------------------------------------------------------------------------- diff

def _read_text(root: Path, path: str, limit: int) -> tuple[str, bytes]:
    file = studio._path(root, path) if not _secret(path) else None
    if file is None:
        raise HTTPException(403, "Secret-looking files are not shown.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(file, flags)
        with os.fdopen(fd, "rb") as stream:
            raw = stream.read(limit + 1)
    except OSError as exc:
        raise HTTPException(404, "File cannot be read.") from exc
    if len(raw) > limit:
        raise HTTPException(413, "File is too large to show here.")
    if b"\x00" in raw:
        raise HTTPException(415, "Binary file: no text diff.")
    return raw.decode("utf-8", errors="replace"), raw


@router.get("/diff")
def diff(request: Request, project: str, path: str, staged: bool = False):
    studio._auth(request)
    root, _ = _repo(project)
    rel = _rel(path)
    with _lock(root):
        current = {f["path"]: f for f in _status(root)["files"]}
        info = current.get(rel)
        if info is None:
            raise HTTPException(404, "That file has no changes.")
        if info["secret_like"]:
            return {"path": rel, "diff": "", "hidden": True, "reason": "Secret-looking file: contents hidden."}
        if info["worktree"] == "untracked":
            text, _ = _read_text(root, rel, MAX_DIFF)
            lines = text.splitlines()
            body = "\n".join("+" + x for x in lines)
            out = f"--- /dev/null\n+++ b/{rel}\n@@ -0,0 +1,{len(lines)} @@\n{body}"
            return {"path": rel, "diff": out, "untracked": True, "truncated": False}
        args = ["diff", "--no-color", "--no-ext-diff", "--no-textconv", "-M"]
        if staged:
            args.append("--cached")
        done = _run(root, [*args, "--", rel])
    text = done.stdout.decode("utf-8", errors="replace")
    truncated = len(text) > MAX_DIFF
    return {"path": rel, "diff": text[:MAX_DIFF], "staged": staged, "truncated": truncated}


# --------------------------------------------------------------------------- conflicts

def _join(lines: list[str]) -> str:
    return "\n".join(x[:-1] if x.endswith("\r") else x for x in lines)


def parse_conflicts(text: str) -> list[dict]:
    blocks, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        if lines[i].startswith("<<<<<<< "):
            start, ours, base, theirs = i, [], None, []
            ours_label = lines[i][8:].strip()
            i += 1
            while i < len(lines) and not lines[i].startswith(("=======", "||||||| ")):
                ours.append(lines[i]); i += 1
            if i < len(lines) and lines[i].startswith("||||||| "):
                base = []
                i += 1
                while i < len(lines) and not lines[i].startswith("======="):
                    base.append(lines[i]); i += 1
            i += 1
            while i < len(lines) and not lines[i].startswith(">>>>>>> "):
                theirs.append(lines[i]); i += 1
            if i >= len(lines):
                break
            blocks.append({"start_line": start + 1, "end_line": i + 1, "ours_label": ours_label,
                           "theirs_label": lines[i][8:].strip(), "ours": _join(ours),
                           "theirs": _join(theirs), "base": None if base is None else _join(base)})
        i += 1
    return blocks


def resolve_text(text: str, choices: list[str]) -> str:
    out, lines, i, n = [], text.split("\n"), 0, 0
    while i < len(lines):
        if lines[i].startswith("<<<<<<< "):
            ours, theirs = [], []
            i += 1
            while i < len(lines) and not lines[i].startswith(("=======", "||||||| ")):
                ours.append(lines[i]); i += 1
            if i < len(lines) and lines[i].startswith("||||||| "):
                while i < len(lines) and not lines[i].startswith("======="):
                    i += 1
            i += 1
            while i < len(lines) and not lines[i].startswith(">>>>>>> "):
                theirs.append(lines[i]); i += 1
            if i >= len(lines):
                raise HTTPException(422, "The conflict markers in this file are incomplete.")
            pick = choices[n] if n < len(choices) else choices[-1]
            out.extend(ours if pick == "ours" else theirs if pick == "theirs" else ours + theirs)
            n += 1
        else:
            out.append(lines[i])
        i += 1
    return "\n".join(out)


@router.get("/conflict")
def conflict(request: Request, project: str, path: str):
    studio._auth(request)
    root, _ = _repo(project)
    rel = _rel(path)
    with _lock(root):
        info = {f["path"]: f for f in _status(root)["files"]}.get(rel)
    if info is None or not info["conflict"]:
        raise HTTPException(404, "That file is not in conflict.")
    text, raw = _read_text(root, rel, MAX_CONFLICT_FILE)
    return {"path": rel, "blocks": parse_conflicts(text), "sha256": hashlib.sha256(raw).hexdigest(),
            "lines": text.count("\n") + 1}


@router.post("/resolve")
def resolve(request: Request, body: ResolveIn):
    studio._auth(request)
    root, _ = _repo(body.project, trusted=True)
    rel = _rel(body.path)
    choices = body.choices or ([body.choice] if body.choice else None)
    if not choices:
        raise HTTPException(422, "Choose mine, theirs or both.")
    with _lock(root):
        info = {f["path"]: f for f in _status(root)["files"]}.get(rel)
        if info is None or not info["conflict"]:
            raise HTTPException(404, "That file is not in conflict.")
        text, raw = _read_text(root, rel, MAX_CONFLICT_FILE)
        if hashlib.sha256(raw).hexdigest() != body.expected_sha256:
            raise HTTPException(409, "The file changed since you looked at it. Reload the conflict.")
        if not parse_conflicts(text):
            raise HTTPException(422, "No conflict markers found. Edit the file, then stage it.")
        resolved = resolve_text(text, list(choices))
        target = studio._path(root, rel)
        tmp = target.with_name("." + target.name + ".automoto-resolve")
        tmp.write_bytes(resolved.encode("utf-8"))
        os.replace(tmp, target)
        _run(root, ["add", "--", rel])
        return _status(root)
