"""Developer Studio V41 + V44: real run and test results, and a live local preview.

Detection is inert: it only reads project manifests (package.json, pyproject.toml,
manage.py, go.mod, Cargo.toml, index.html) and proposes fixed command lists.
Nothing runs until the operator approves one exact command for a trusted project.

Safety model (read with docs/DEVELOPER-STUDIO-V41-V45.md):

* Approval-gated: ``/start`` needs ``approved: true`` and the ``command_sha256``
  the operator was shown; if the manifest changed in between, the run is refused.
* Loopback only: every app gets a free 127.0.0.1 port, HOST/PORT are set to
  loopback and known dev servers get explicit ``--host 127.0.0.1`` flags. While an
  app runs, a watchdog probes the port on this machine's network addresses; if the
  app is reachable from anything but loopback it is stopped immediately.
* Stoppable lifecycle: each run is its own process group with a hard time limit,
  can be stopped at any time, and every run is stopped when AutoMoto exits.
* Commands come only from the detected list. There is no free-form shell input.
"""
from __future__ import annotations

import atexit
import hashlib
import ipaddress
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import brand
from automoto import developer_adapters as adapters
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/run", tags=["developer-run"])
VERSION = "1.0.0"
MAX_LOG_BYTES = 256 * 1024
MAX_MANIFEST = 256 * 1024
APP_SECONDS = 60 * 60
TEST_SECONDS = 15 * 60
MAX_LIVE = 4
URL_RE = re.compile(r"https?://(127\.0\.0\.1|localhost|\[::1\]|0\.0\.0\.0|\[::\])(?::(\d{2,5}))?(/[^\s'\"<>\x1b]*)?")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
APP_SCRIPTS = ("dev", "start", "serve", "preview")
LOCK = threading.RLock()
RUNS: dict[str, "Run"] = {}


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    recipe: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9:_.-]+$")
    command_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    approved: Literal[True]


class StopIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    run_id: str = Field(min_length=1, max_length=40, pattern=r"^[a-f0-9]{8,40}$")


# --------------------------------------------------------------------------- detection

def _read(root: Path, name: str) -> str | None:
    file = root / name
    try:
        if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_MANIFEST:
            return None
        return file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _node_manager(root: Path) -> str:
    if (root / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (root / "yarn.lock").is_file():
        return "yarn"
    if (root / "bun.lockb").is_file() or (root / "bun.lock").is_file():
        return "bun"
    return "npm"


def _loopback_flags(script: str, manager: str) -> list[str]:
    """Extra args that pin well-known dev servers to 127.0.0.1 and our port ({port})."""
    low = script.casefold()
    extra: list[str] = []
    if re.search(r"\bvite\b", low) or "astro dev" in low or "svelte-kit dev" in low:
        extra = ["--host", "127.0.0.1", "--port", "{port}", "--strictPort"]
    elif re.search(r"\bnext (dev|start)\b", low):
        extra = ["-H", "127.0.0.1", "-p", "{port}"]
    elif re.search(r"\b(ng serve|angular)\b", low):
        extra = ["--host", "127.0.0.1", "--port", "{port}"]
    elif re.search(r"\bnuxt\b", low):
        extra = ["--host", "127.0.0.1", "--port", "{port}"]
    if extra and manager == "npm":
        return ["--", *extra]
    return extra


def _recipe(kind: str, rid: str, label: str, argv: list[str], source: str,
            preview: bool = False) -> dict:
    return {"id": rid, "kind": kind, "label": label, "argv": argv, "source": source,
            "preview": preview}


def _python_cmd() -> str:
    return "python" if os.name == "nt" else "python3"


def detect_recipes(root: Path) -> list[dict]:
    recipes: list[dict] = []
    package = _read(root, "package.json")
    if package is not None:
        try:
            data = json.loads(package)
            scripts = data.get("scripts") if isinstance(data, dict) else None
        except ValueError:
            scripts = None
        if isinstance(scripts, dict):
            manager = _node_manager(root)
            for name in APP_SCRIPTS:
                body = scripts.get(name)
                if isinstance(body, str) and body.strip():
                    argv = [manager, "run", name, *_loopback_flags(body, manager)]
                    recipes.append(_recipe("app", "node:" + name, f"{manager} run {name}", argv,
                                           f"package.json scripts.{name}: {body[:120]}", True))
            body = scripts.get("test")
            if isinstance(body, str) and body.strip() and "no test specified" not in body:
                recipes.append(_recipe("test", "node:test", f"{manager} test", [manager, "test"],
                                       f"package.json scripts.test: {body[:120]}"))
    py = _python_cmd()
    if (root / "manage.py").is_file():
        recipes.append(_recipe("app", "python:django", "Django dev server",
                               [py, "manage.py", "runserver", "127.0.0.1:{port}", "--noreload"],
                               "manage.py", True))
    pyproject = _read(root, "pyproject.toml") or ""
    tests_dir = root / "tests"
    py_tests = (any(root.glob("test_*.py")) or any(root.glob("*_test.py"))
                or (tests_dir.is_dir() and not tests_dir.is_symlink()
                    and any(tests_dir.glob("**/test_*.py"))))
    pytest_config = ("[tool.pytest" in pyproject or (root / "pytest.ini").is_file()
                     or (root / "conftest.py").is_file())
    if py_tests or pytest_config:
        recipes.append(_recipe("test", "python:pytest", "pytest", [py, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider"],
                               "pytest configuration or test_*.py files"))
    if (root / "go.mod").is_file():
        if (root / "main.go").is_file():
            recipes.append(_recipe("app", "go:run", "go run .", ["go", "run", "."], "go.mod + main.go", True))
        recipes.append(_recipe("test", "go:test", "go test", ["go", "test", "-v", "./..."], "go.mod"))
    if (root / "Cargo.toml").is_file():
        recipes.append(_recipe("app", "rust:run", "cargo run", ["cargo", "run"], "Cargo.toml", True))
        recipes.append(_recipe("test", "rust:test", "cargo test", ["cargo", "test"], "Cargo.toml"))
    if (root / "index.html").is_file() and package is None:
        recipes.append(_recipe("app", "static:serve", "Static site preview",
                               [py, "-m", "http.server", "{port}", "--bind", "127.0.0.1"],
                               "index.html", True))
    return recipes


def _command_sha(root: Path, recipe: dict) -> str:
    payload = json.dumps({"project": str(root), "id": recipe["id"], "argv": recipe["argv"],
                          "kind": recipe["kind"]}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _executable(name: str, env: dict) -> str | None:
    found = shutil.which(name, path=env.get("PATH", ""))
    if found is None and name in ("python", "python3") and sys.executable:
        found = sys.executable
    return found


def _public(root: Path, recipe: dict, env: dict) -> dict:
    exe = _executable(recipe["argv"][0], env)
    shown = " ".join(a.replace("{port}", "<port>") for a in recipe["argv"])
    return {**{k: recipe[k] for k in ("id", "kind", "label", "source", "preview")},
            "command": shown, "available": exe is not None,
            "missing": None if exe else recipe["argv"][0],
            "command_sha256": _command_sha(root, recipe)}


# --------------------------------------------------------------------------- test summaries

COUNT_RE = re.compile(r"\b(\d+)\s+(passed|failed|skipped|ignored|errors?|pending|todo|xfailed|xpassed|deselected)\b", re.I)


def parse_test_summary(text: str) -> dict:
    """Plain counts from pytest, Jest/Vitest, Mocha, Go and Cargo output."""
    clean = ANSI_RE.sub("", text)
    lines = clean.splitlines()
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    framework = "unknown"
    found = False
    for line in lines:
        low = line.strip()
        if low.startswith("test result:"):  # cargo, one per crate
            framework, found = "cargo", True
            for n, word in COUNT_RE.findall(low):
                key = {"ignored": "skipped"}.get(word.lower(), word.lower())
                if key in counts:
                    counts[key] += int(n)
    if not found:
        go_pass = sum(1 for x in lines if x.lstrip().startswith("--- PASS:"))
        go_fail = sum(1 for x in lines if x.lstrip().startswith("--- FAIL:"))
        go_skip = sum(1 for x in lines if x.lstrip().startswith("--- SKIP:"))
        if go_pass or go_fail or go_skip:
            framework, found = "go", True
            counts = {"passed": go_pass, "failed": go_fail, "skipped": go_skip}
    if not found:
        for line in reversed(lines):
            low = line.strip()
            if re.match(r"^=+ .*\b(passed|failed|error|skipped|no tests ran)\b.* =+$", low) or \
               re.match(r"^\d+ (passed|failed)", low):
                framework, found = "pytest", True
            elif low.startswith("Tests:") or re.match(r"^Tests\s+\d", low):
                framework, found = ("jest" if low.startswith("Tests:") else "vitest"), True
            elif re.match(r"^\d+ (passing|failing|pending)", low):
                framework, found = "mocha", True
                block = " ".join(x.strip() for x in lines[-12:])
                counts["passed"] = sum(int(n) for n in re.findall(r"(\d+) passing", block))
                counts["failed"] = sum(int(n) for n in re.findall(r"(\d+) failing", block))
                counts["skipped"] = sum(int(n) for n in re.findall(r"(\d+) pending", block))
                break
            if found:
                for n, word in COUNT_RE.findall(low):
                    w = word.lower()
                    key = "failed" if w.startswith("error") else "skipped" if w in ("ignored", "pending", "todo", "deselected", "xfailed") else w
                    if key == "xpassed":
                        key = "passed"
                    counts[key] = counts.get(key, 0) + int(n)
                break
    failures: list[str] = []
    for line in lines:
        s = line.strip()
        m = (re.match(r"^FAILED (\S+)", s) or re.match(r"^--- FAIL: (\S+)", s)
             or re.match(r"^(?:✕|×|✗)\s+(.+?)(?:\s+\(\d+\s*m?s\))?$", s)
             or re.match(r"^test (\S+) \.\.\. FAILED$", s) or re.match(r"^● (.+)$", s))
        if m and m.group(1) not in failures:
            failures.append(m.group(1)[:200])
        if len(failures) >= 30:
            break
    total = counts["passed"] + counts["failed"] + counts["skipped"]
    return {"framework": framework, "recognised": found, **counts, "total": total, "failures": failures}


# --------------------------------------------------------------------------- process lifecycle

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _non_loopback_addresses() -> list[str]:
    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    try:  # UDP "connect" picks the outbound interface without sending a packet.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            found.add(s.getsockname()[0])
    except OSError:
        pass
    def outside(addr: str) -> bool:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        return not (ip.is_loopback or ip.is_unspecified)
    return sorted(a for a in found if outside(a))


def _reachable(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None and os.name != "nt":
        try:  # children may still hold the group; ignore if gone
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            proc.kill()
        except OSError:
            pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        proc.wait(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        pass


class Run:
    def __init__(self, root: Path, recipe: dict, argv: list[str], port: int | None):
        self.id = uuid.uuid4().hex[:16]
        self.root = root
        self.recipe = recipe
        self.argv = argv
        self.port = port
        self.kind = recipe["kind"]
        self.status = "starting"
        self.exit_code: int | None = None
        self.started = time.time()
        self.ended: float | None = None
        self.url: str | None = None
        self.reason = ""
        self.log = bytearray()
        self.dropped = 0
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.stop_requested = False
        self.limit = APP_SECONDS if self.kind == "app" else TEST_SECONDS

    # -- output
    def _append(self, chunk: bytes) -> None:
        with self.lock:
            self.log.extend(chunk)
            over = len(self.log) - MAX_LOG_BYTES
            if over > 0:
                del self.log[:over]
                self.dropped += over

    def text(self) -> str:
        with self.lock:
            return ANSI_RE.sub("", self.log.decode("utf-8", errors="replace"))

    # -- lifecycle
    def start(self, env: dict) -> None:
        options = {"cwd": self.root, "shell": False, "env": env, "stdin": subprocess.DEVNULL,
                   "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}
        if os.name == "nt":
            options["creationflags"] = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                                        | getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            options["start_new_session"] = True
        try:
            self.proc = subprocess.Popen(self.argv, **options)
        except OSError as exc:
            self.status, self.reason, self.ended = "failed_to_start", str(exc)[:300], time.time()
            raise HTTPException(502, "The command could not start: " + str(exc)[:200]) from exc
        self.status = "running"
        threading.Thread(target=self._drain, daemon=True).start()
        threading.Thread(target=self._watch, daemon=True).start()

    def _drain(self) -> None:
        assert self.proc and self.proc.stdout
        try:
            while True:
                chunk = self.proc.stdout.read1(4096) if hasattr(self.proc.stdout, "read1") else self.proc.stdout.read(4096)
                if not chunk:
                    break
                self._append(chunk)
                if self.kind == "app" and self.url is None:
                    self._sniff_url(chunk.decode("utf-8", errors="replace"))
        except (OSError, ValueError):
            pass

    def _sniff_url(self, text: str) -> None:
        for match in URL_RE.finditer(ANSI_RE.sub("", text)):
            port = int(match.group(2) or 80)
            if 0 < port < 65536:
                self.sniffed_port = port
                if self.port is None:
                    self.port = port
                return

    def _watch(self) -> None:
        assert self.proc
        others = _non_loopback_addresses() if self.kind == "app" else []
        last_probe = 0.0
        while True:
            code = self.proc.poll()
            if code is not None:
                break
            now = time.time()
            if now - self.started > self.limit:
                self.reason = "Stopped after the time limit."
                self.status = "timed_out"
                _kill_tree(self.proc)
                break
            if self.kind == "app" and now - last_probe > 0.7:
                last_probe = now
                ports = {p for p in (self.port, getattr(self, "sniffed_port", None)) if p}
                for port in ports:
                    exposed = [a for a in others if _reachable(a, port)]
                    if exposed:
                        self.reason = ("Stopped: the app was reachable from your network (" + exposed[0] + ":"
                                       + str(port) + "). " + brand.short() + " previews only allow 127.0.0.1.")
                        self.status = "blocked_exposed"
                        self.url = None
                        _kill_tree(self.proc)
                        break
                    if self.url is None and _reachable("127.0.0.1", port):
                        self.url = f"http://127.0.0.1:{port}/"
                if self.status == "blocked_exposed":
                    break
            time.sleep(0.2)
        try:
            self.exit_code = self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _kill_tree(self.proc)
            self.exit_code = self.proc.poll()
        if os.name != "nt":
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)  # leftover children in the group
            except OSError:
                pass
        time.sleep(0.15)  # let the drain thread flush the tail
        self.ended = time.time()
        if self.status in ("running", "starting"):
            if self.stop_requested:
                self.status = "stopped"
            elif self.kind == "test":
                self.status = "passed" if self.exit_code == 0 else "failed"
            else:
                self.status = "exited"
        self.url = None if self.status != "running" else self.url

    def stop(self) -> None:
        self.stop_requested = True
        if self.proc is not None and self.proc.poll() is None:
            _kill_tree(self.proc)

    @property
    def live(self) -> bool:
        return self.proc is not None and self.ended is None

    def view(self, since: int = 0) -> dict:
        text = self.text()
        base = self.dropped
        start = max(since - base, 0)
        summary = parse_test_summary(text) if self.kind == "test" else None
        return {"run_id": self.id, "kind": self.kind, "recipe": self.recipe["id"],
                "label": self.recipe["label"],
                "command": " ".join(self.argv), "status": self.status, "live": self.live,
                "exit_code": self.exit_code, "reason": self.reason,
                "started": self.started, "ended": self.ended,
                "elapsed_ms": int(((self.ended or time.time()) - self.started) * 1000),
                "port": self.port, "bound_to": "127.0.0.1" if self.kind == "app" else None,
                "preview_url": self.url if self.status == "running" else None,
                "output": text[start:], "next": base + len(text), "truncated": self.dropped > 0,
                "summary": summary, "pushes_or_deploys": False, "network_exposure_allowed": False}


def _env(root: Path, kind: str, port: int | None) -> dict:
    env = adapters._environment(root)
    env.pop("AUTOMOTO_TOOLCHAIN_SDK", None)
    env.update({"NO_COLOR": "1", "FORCE_COLOR": "0", "BROWSER": "none", "CI": "true",
                "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
                "npm_config_update_notifier": "false"})
    if kind == "app" and port:
        env.update({"HOST": "127.0.0.1", "HOSTNAME": "127.0.0.1", "PORT": str(port),
                    "BIND": "127.0.0.1", "FLASK_RUN_HOST": "127.0.0.1", "FLASK_RUN_PORT": str(port)})
    return env


def stop_all() -> None:
    with LOCK:
        runs = list(RUNS.values())
    for run in runs:
        run.stop()


atexit.register(stop_all)


def _project_runs(root: Path) -> list[Run]:
    return [r for r in RUNS.values() if r.root == root]


# --------------------------------------------------------------------------- routes

@router.get("/detect")
def detect(request: Request, project: str):
    studio._auth(request)
    root = studio._project(project)
    env = _env(root, "test", None)
    recipes = [_public(root, r, env) for r in detect_recipes(root)]
    with studio.STATE_LOCK:
        trusted = studio._trusted(root, studio._load())
    return {"version": VERSION, "project": str(root), "trusted": trusted, "recipes": recipes,
            "commands_executed": False, "loopback_only": True, "approval_required": True,
            "runs": [r.view(10 ** 12) | {"output": ""} for r in _project_runs(root)][-6:]}


@router.post("/start")
def start(request: Request, body: StartIn):
    studio._auth(request)
    root = studio._project(body.project)
    adapters._trusted(root)
    recipe = next((r for r in detect_recipes(root) if r["id"] == body.recipe), None)
    if recipe is None:
        raise HTTPException(404, "That command is no longer offered for this project.")
    if _command_sha(root, recipe) != body.command_sha256:
        raise HTTPException(409, "The command changed since you approved it. Review it again.")
    with LOCK:
        live = [r for r in RUNS.values() if r.live]
        if any(r.root == root and r.kind == recipe["kind"] for r in live):
            raise HTTPException(429, "One is already running for this project. Stop it first.")
        if len(live) >= MAX_LIVE:
            raise HTTPException(429, "Too many runs at once. Stop one first.")
        port = _free_port() if recipe["kind"] == "app" else None
        env = _env(root, recipe["kind"], port)
        exe = _executable(recipe["argv"][0], env)
        if exe is None:
            raise HTTPException(424, f"{recipe['argv'][0]} is not installed or not on PATH.")
        argv = [exe, *[a.replace("{port}", str(port or "")) for a in recipe["argv"][1:]]]
        run = Run(root, recipe, argv, port)
        # forget finished runs beyond a small history
        for old in [r for r in RUNS.values() if not r.live][:-12]:
            RUNS.pop(old.id, None)
        RUNS[run.id] = run
    run.start(env)
    return run.view()


@router.get("/status")
def status(request: Request, project: str, run_id: str, since: int = 0):
    studio._auth(request)
    root = studio._project(project)
    run = RUNS.get(run_id)
    if run is None or run.root != root:
        raise HTTPException(404, "Run not found.")
    return run.view(max(since, 0))


@router.post("/stop")
def stop(request: Request, body: StopIn):
    studio._auth(request)
    root = studio._project(body.project)
    run = RUNS.get(body.run_id)
    if run is None or run.root != root:
        raise HTTPException(404, "Run not found.")
    run.stop()
    deadline = time.time() + 6
    while run.live and time.time() < deadline:
        time.sleep(0.05)
    return run.view(10 ** 12)
