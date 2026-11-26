"""Developer Studio V42: debugger and profiling host.

A small Debug Adapter Protocol (DAP) client that drives real debuggers:
* Python through debugpy (``python -m debugpy.adapter``);
* native C, C++, Rust or Go binaries through GDB 14+ (``gdb --interpreter=dap``) or lldb-dap.

It sets breakpoints, shows the call stack, local variables and watch values, steps,
continues, pauses and stops. When the debugger itself crashes, the session is marked
``adapter_crashed``, the debugger and the program are stopped, and the same session can be
restarted with its breakpoints. A Python speed check (cProfile) and a crash explainer that
reads pasted error output are included.

Safety: starting anything needs a trusted project, an explicit confirmation, the exact
debugger bytes (SHA-256) and the exact target file bytes. Watch expressions are limited
to names, attributes and simple indexes, so the watch box cannot run arbitrary code.
The debugger and your program are NOT OS-sandboxed: debugging runs your program.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_adapters as adapters
from automoto import developer_index as index
from automoto import developer_native as native
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/debug", tags=["developer-debug"])
VERSION = "1.0.0"
MAX_SESSIONS = 2
SESSION_SECONDS = 30 * 60
REQUEST_TIMEOUT = 15.0
START_TIMEOUT = 25.0
MAX_FRAME = 2 * 1024 * 1024
MAX_HEADERS = 4096
MAX_OUTPUT = 64 * 1024
MAX_TARGET = 256 * 1024 * 1024
MAX_SOURCE = 512 * 1024
MAX_FRAMES = 25
MAX_VARIABLES = 60
MAX_VALUE = 240
MAX_BREAKPOINTS = 40
MAX_WATCHES = 12
PROFILE_TIMEOUT = 120
MAX_CRASH_TEXT = 64 * 1024
WATCH = re.compile(r"^[A-Za-z_]\w{0,63}(?:\.[A-Za-z_]\w{0,63}|\[\d{1,6}\]|\[(?:'[\w .-]{0,40}'|\"[\w .-]{0,40}\")\]|->[A-Za-z_]\w{0,63}){0,6}$")
PROFILE_MARKER = "AUTOMOTO_V42_PROFILE "
NOT_SUPPORTED = (".NET (netcoredbg)", "Java and Kotlin (JDWP)", "Node.js", "Go with Delve",
                 "attaching to a running process", "remote debugging")

DEBUGGERS = {
    "debugpy": {
        "kind": "python", "label": "Python (debugpy)",
        "names": ("python", "python3") if os.name == "nt" else ("python3", "python"),
        "args": ["-m", "debugpy.adapter"],
        "install": {"windows": "python -m pip install debugpy", "macos": "python3 -m pip install debugpy",
                    "linux": "python3 -m pip install debugpy"},
        "ci_verified_hosts": ["linux", "macos", "windows"],
    },
    "gdb": {
        "kind": "native", "label": "GDB (C, C++, Rust, Go programs)", "names": ("gdb",),
        # -nx: never read .gdbinit files (a project .gdbinit could run commands).
        "args": ["--interpreter=dap", "-q", "-nx", "-iex", "set auto-load local-gdbinit off"],
        "needs": "GDB 14 or newer (it added the DAP interpreter).",
        "install": {"windows": "https://www.msys2.org/",
                    "macos": "brew install gdb", "linux": "sudo apt install gdb"},
        "ci_verified_hosts": ["linux"],
    },
    "lldb-dap": {
        "kind": "native", "label": "LLDB (C, C++, Swift, Rust programs)", "names": ("lldb-dap", "lldb-vscode"),
        "args": [],
        "install": {"windows": "https://github.com/llvm/llvm-project/releases",
                    "macos": "xcode-select --install", "linux": "sudo apt install lldb"},
        "ci_verified_hosts": [],
    },
}
LLDB_CANDIDATES = ("/Library/Developer/CommandLineTools/usr/bin/lldb-dap",
                   "/Applications/Xcode.app/Contents/Developer/usr/bin/lldb-dap")
PROFILE_SCRIPT = r"""
import cProfile, json, os, pstats, runpy, sys
target = sys.argv[1]
sys.argv = [target]
sys.path.insert(0, os.path.dirname(target))
prof = cProfile.Profile()
code = 0
prof.enable()
try:
    runpy.run_path(target, run_name="__main__")
except SystemExit as exc:
    code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
finally:
    prof.disable()
stats = pstats.Stats(prof)
rows = []
total = 0.0
for (filename, line, name), (cc, nc, tt, ct, callers) in stats.stats.items():
    total += tt
    rows.append({"file": filename, "line": line, "function": name, "calls": nc,
                 "own_seconds": round(tt, 6), "total_seconds": round(ct, 6)})
rows.sort(key=lambda r: r["total_seconds"], reverse=True)
sys.stdout.flush()
print("AUTOMOTO_V42_PROFILE " + json.dumps({"rows": rows[:25], "own_total_seconds": round(total, 6),
                                             "exit_code": code}))
"""

SESSIONS: dict[str, "Session"] = {}
SESSIONS_LOCK = threading.Lock()
PROFILE_LOCK = threading.Lock()


class Breakpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)
    line: int = Field(ge=1, le=10_000_000)


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    debugger: str = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9-]{1,31}$")
    target: str = Field(min_length=1, max_length=1024)
    expected_target_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    breakpoints: list[Breakpoint] = Field(default_factory=list, max_length=MAX_BREAKPOINTS)
    stop_on_uncaught: bool = True
    confirmed: Literal[True]
    accept_unsandboxed_execution: Literal[True]


class SessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{16,64}$")


class ControlIn(SessionIn):
    action: Literal["continue", "next", "stepIn", "stepOut", "pause"]


class BreakpointsIn(SessionIn):
    path: str = Field(min_length=1, max_length=1024)
    lines: list[int] = Field(max_length=MAX_BREAKPOINTS)


class WatchIn(SessionIn):
    expressions: list[str] = Field(max_length=MAX_WATCHES)


class RestartIn(SessionIn):
    confirmed: Literal[True]


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    target: str = Field(min_length=1, max_length=1024)
    expected_target_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_execution: Literal[True]


class CrashIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    text: str = Field(min_length=1, max_length=MAX_CRASH_TEXT)
    exit_code: int | None = Field(default=None, ge=-(2**31), le=2**32)


# ------------------------------------------------------------------ helpers
def _host() -> str:
    return "windows" if os.name == "nt" else "macos" if sys.platform == "darwin" else "linux"


def _locate(spec: dict) -> str | None:
    for name in spec["names"]:
        found = shutil.which(name)
        if found:
            return found
    if spec is DEBUGGERS.get("lldb-dap") and sys.platform == "darwin":
        return next((c for c in LLDB_CANDIDATES if Path(c).is_file()), None)
    return None


def _debuggers(root: Path) -> dict:
    host = _host()
    out = {}
    for name, spec in DEBUGGERS.items():
        binary = _locate(spec)
        if not binary:
            item = {"status": "unavailable"}
        elif Path(binary).suffix.lower() in (".cmd", ".bat", ".ps1"):
            item = {"status": "shell_wrapper_blocked"}
        else:
            try:
                item = {"status": "installed_not_executed",
                        **adapters._fingerprint(str(Path(binary).absolute()), root)}
                # Run through the PATH entry (a virtual environment's python only finds its
                # packages that way); spawn re-checks that it still resolves to these bytes.
                item["launch_path"] = str(Path(binary).absolute())
            except HTTPException:
                item = {"status": "untrusted_executable"}
        out[name] = {"name": name, "kind": spec["kind"], "label": spec["label"],
                     "needs": spec.get("needs"), "install_hint": spec["install"][host],
                     "ci_verified_hosts": spec["ci_verified_hosts"],
                     "verified_on_this_host_by_ci": host in spec["ci_verified_hosts"], **item}
    return out


def _launch_path(config: dict) -> str:
    try:
        if str(Path(config["launch_path"]).resolve(strict=True)) != config["executable"]:
            raise HTTPException(409, "The debugger program moved since you approved it. Check again.")
    except OSError as exc:
        raise HTTPException(409, "The debugger program is gone. Check again.") from exc
    return config["launch_path"]


def _sha_file(path: Path, limit: int) -> tuple[str, int]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            meta = os.fstat(stream.fileno())
            if not stat.S_ISREG(meta.st_mode):
                raise HTTPException(403, "Only regular files can be debugged.")
            if meta.st_size > limit:
                raise HTTPException(413, "The file is larger than the debugger limit.")
            digest = hashlib.sha256()
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
            return digest.hexdigest(), meta.st_size
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(403, "The file cannot be read safely.") from exc


def _native_magic(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            head = handle.read(4)
    except OSError:
        return None
    if head == b"\x7fELF":
        return "elf"
    if head[:2] == b"MZ":
        return "pe"
    if head in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe",
                b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
        return "mach-o"
    return None


def _target(root: Path, relative: str, kind: str) -> Path:
    path = studio._path(root, relative)
    if path.is_symlink() or not path.is_file():
        raise HTTPException(403, "Choose a regular file inside the project.")
    if kind == "python":
        if path.suffix.lower() not in (".py", ".pyw"):
            raise HTTPException(422, "The Python debugger needs a .py file.")
    else:
        if not _native_magic(path):
            raise HTTPException(422, "This isn't a compiled program (ELF, Mach-O or Windows .exe).")
        if os.name != "nt" and not os.access(path, os.X_OK):
            raise HTTPException(422, "This program isn't marked as executable.")
    return path


def _relative(root: Path, raw: str | None) -> tuple[str | None, bool]:
    if not raw:
        return None, False
    try:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve()
        if resolved.is_relative_to(root):
            return resolved.relative_to(root).as_posix(), resolved.is_file()
    except (OSError, ValueError):
        pass
    return Path(raw).name or raw[:120], False


def _kill_tree(proc: subprocess.Popen, extra_pids: set[int]) -> None:
    sid = None
    if os.name != "nt":
        try:
            sid = os.getsid(proc.pid)
        except OSError:
            sid = None
    if os.name == "nt":
        for pid in {proc.pid, *extra_pids}:
            try:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=10, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        for pid in extra_pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        # Programs a debugger started may sit in their own process group (GDB job control)
        # but stay in the debugger's session. Sweep that session on Linux.
        if sid and sid != os.getsid(0) and Path("/proc").is_dir():
            for entry in Path("/proc").iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                    if int(fields[3]) == sid:
                        os.kill(int(entry.name), signal.SIGKILL)
                except (OSError, ValueError, IndexError):
                    continue
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _read_frame(stream) -> dict:
    size, length = 0, None
    while True:
        line = stream.readline(MAX_HEADERS + 1)
        if not line:
            raise EOFError("debugger closed the connection")
        size += len(line)
        if size > MAX_HEADERS:
            raise ValueError("DAP headers too large")
        if line in (b"\r\n", b"\n"):
            if length is None:
                continue
            break
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
    if not 0 <= length <= MAX_FRAME:
        raise ValueError("DAP message too large")
    raw = stream.read(length)
    if len(raw) != length:
        raise EOFError("incomplete DAP message")
    message = json.loads(raw.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("DAP message is not an object")
    return message


# ------------------------------------------------------------------ session
class Session:
    def __init__(self, root: Path, config: dict):
        self.id = secrets.token_urlsafe(18)
        self.root = root
        self.config = config
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.seq = 0
        self.pending: dict[int, tuple[threading.Event, list]] = {}
        self.initialized = threading.Event()
        self.status = "starting"
        self.output = ""
        self.output_truncated = False
        self.stop: dict | None = None
        self.frames: list[dict] = []
        self.variables: list[dict] = []
        self.watch_values: list[dict] = []
        self.watches: list[str] = []
        self.exception: dict | None = None
        self.exit_code: int | None = None
        self.error: str | None = None
        self.breakpoints: dict[str, list[int]] = {}
        self.breakpoint_results: dict[str, list[dict]] = {}
        self.capabilities: dict = {}
        self.debuggee_pids: set[int] = set()
        self.started = time.monotonic()
        self.user_stopped = False
        self.temp = tempfile.TemporaryDirectory(prefix="automoto-v42-")
        self.proc: subprocess.Popen | None = None
        self.restarts = 0
        self.stderr_tail = ""

    # -- transport
    def spawn(self) -> None:
        spec = DEBUGGERS[self.config["debugger"]]
        env = adapters._environment(self.root)
        env.update({"PYTHONSAFEPATH": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
                    "NO_COLOR": "1"})
        command = [_launch_path(self.config), *spec["args"]]
        options = {"cwd": self.temp.name, "env": env, "shell": False, "stdin": subprocess.PIPE,
                   "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
        if os.name == "nt":
            options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            options["start_new_session"] = True
        try:
            self.proc = subprocess.Popen(command, **options)
        except OSError as exc:
            raise HTTPException(502, "The debugger could not start.") from exc
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._stderr, daemon=True).start()

    def _stderr(self) -> None:
        try:
            while chunk := self.proc.stderr.read(2048):
                with self.lock:
                    self.stderr_tail = (self.stderr_tail + chunk.decode("utf-8", "replace"))[-2000:]
        except (OSError, ValueError):
            pass

    def _write(self, message: dict) -> None:
        body = json.dumps(message, separators=(",", ":")).encode("utf-8")
        with self.write_lock:
            if not self.proc or not self.proc.stdin:
                raise OSError("debugger is not running")
            self.proc.stdin.write(b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            self.proc.stdin.flush()

    def request(self, command: str, arguments: dict | None = None, *, wait: bool = True,
                timeout: float = REQUEST_TIMEOUT) -> dict | tuple:
        with self.lock:
            self.seq += 1
            seq = self.seq
            holder: list = []
            event = threading.Event()
            self.pending[seq] = (event, holder)
        try:
            self._write({"seq": seq, "type": "request", "command": command, "arguments": arguments or {}})
        except (OSError, ValueError) as exc:
            self.pending.pop(seq, None)
            raise HTTPException(409, "The debugger is no longer running.") from exc
        if not wait:
            return (event, holder)
        return self._await(command, event, holder, timeout)

    def _await(self, command: str, event: threading.Event, holder: list, timeout: float) -> dict:
        if not event.wait(timeout):
            raise HTTPException(504, f"The debugger didn't answer '{command}' in time.")
        response = holder[0] if holder else {}
        if response.get("_eof"):
            raise HTTPException(409, "The debugger stopped unexpectedly.")
        if response.get("success") is not True:
            message = str(response.get("message") or "")[:300]
            body = response.get("body") or {}
            detail = body.get("error", {}).get("format") if isinstance(body.get("error"), dict) else None
            raise HTTPException(409, f"The debugger refused '{command}': {detail or message or 'no reason given'}")
        return response.get("body") or {}

    def _append_output(self, text: str) -> None:
        with self.lock:
            room = MAX_OUTPUT - len(self.output)
            if room <= 0:
                self.output_truncated = True
                return
            self.output += text[:room]
            if len(text) > room:
                self.output_truncated = True

    def _reader(self) -> None:
        stream = self.proc.stdout
        try:
            while True:
                message = _read_frame(stream)
                kind = message.get("type")
                if kind == "response":
                    entry = self.pending.pop(message.get("request_seq"), None)
                    if entry:
                        entry[1].append(message)
                        entry[0].set()
                elif kind == "event":
                    self._event(message.get("event"), message.get("body") or {})
                elif kind == "request":
                    # Reverse requests (runInTerminal, startDebugging) are refused.
                    self._write({"seq": 0, "type": "response", "request_seq": message.get("seq"),
                                 "command": message.get("command"), "success": False,
                                 "message": "Not supported by AutoMoto."})
        except (EOFError, OSError, ValueError, UnicodeError, TypeError, json.JSONDecodeError):
            pass
        with self.lock:
            for event, holder in list(self.pending.values()):
                holder.append({"_eof": True})
                event.set()
            self.pending.clear()
            if self.status not in ("exited", "terminated", "stopped_by_user", "timed_out", "failed"):
                self.status = "adapter_crashed"
                self.error = ("The debugger itself stopped unexpectedly. Your program was stopped too. "
                              "Press Restart to try again with the same stop points.")
                time.sleep(0.2)
                if "No module named debugpy" in self.stderr_tail:
                    self.error = ("debugpy isn't installed for this Python. Install it, then press Restart: "
                                  + DEBUGGERS["debugpy"]["install"][_host()])
                elif "dap" in self.stderr_tail.lower() and "interpreter" in self.stderr_tail.lower():
                    self.error = "This GDB is too old for debugging from AutoMoto. GDB 14 or newer is needed."
        self.cleanup()

    def _event(self, name: str, body: dict) -> None:
        if name == "initialized":
            self.initialized.set()
        elif name == "output":
            if body.get("category") in ("stdout", "stderr", "console", None):
                self._append_output(str(body.get("output", "")))
        elif name == "process":
            pid = body.get("systemProcessId")
            if isinstance(pid, int) and pid > 0:
                self.debuggee_pids.add(pid)
        elif name == "stopped":
            with self.lock:
                self.status = "stopped"
                self.stop = {"reason": body.get("reason"), "thread_id": body.get("threadId"),
                             "description": str(body.get("description") or "")[:300],
                             "text": str(body.get("text") or "")[:500], "inspecting": True}
            threading.Thread(target=self._inspect_stop, daemon=True).start()
        elif name == "continued":
            with self.lock:
                if self.status == "stopped":
                    self.status = "running"
                    self.stop = None
        elif name == "exited":
            with self.lock:
                self.exit_code = body.get("exitCode")
        elif name == "terminated":
            with self.lock:
                if self.status not in ("adapter_crashed", "stopped_by_user", "timed_out"):
                    self.status = "exited"
            threading.Thread(target=self._finish, daemon=True).start()

    def _finish(self) -> None:
        try:
            self.request("disconnect", {"terminateDebuggee": True}, timeout=3)
        except HTTPException:
            pass
        self.cleanup()

    def _value(self, raw) -> str:
        text = str(raw if raw is not None else "")
        return text if len(text) <= MAX_VALUE else text[:MAX_VALUE] + "…"

    def _inspect_stop(self) -> None:
        try:
            thread = self.stop.get("thread_id") if self.stop else None
            if thread is None:
                threads = self.request("threads").get("threads") or []
                thread = threads[0]["id"] if threads else None
                with self.lock:
                    if self.stop is not None:
                        self.stop["thread_id"] = thread
            trace = self.request("stackTrace", {"threadId": thread, "startFrame": 0, "levels": MAX_FRAMES})
            frames = []
            for frame in (trace.get("stackFrames") or [])[:MAX_FRAMES]:
                source = frame.get("source") or {}
                path, exists = _relative(self.root, source.get("path"))
                frames.append({"id": frame.get("id"), "name": str(frame.get("name", ""))[:160],
                               "path": path, "line": frame.get("line"), "column": frame.get("column"),
                               "in_project": exists})
            variables = []
            top = frames[0]["id"] if frames else None
            if top is not None:
                scopes = self.request("scopes", {"frameId": top}).get("scopes") or []
                # Arguments and locals; GDB splits them into two scopes. Globals and registers are skipped.
                wanted = [s for s in scopes if not s.get("expensive") and s.get("variablesReference")
                          and str(s.get("name", "")).lower() not in ("globals", "global", "registers", "statics")][:3]
                for scope in wanted:
                    found = self.request("variables", {"variablesReference": scope["variablesReference"],
                                                       "start": 0, "count": MAX_VARIABLES}).get("variables") or []
                    for item in found[:MAX_VARIABLES]:
                        name = str(item.get("name", ""))
                        if name.startswith("__") or name in ("special variables", "function variables"):
                            continue
                        if len(variables) < MAX_VARIABLES:
                            variables.append({"name": name[:80], "value": self._value(item.get("value")),
                                              "type": str(item.get("type") or "")[:80]})
            exception = None
            if self.stop and self.stop.get("reason") == "exception" and self.capabilities.get("supportsExceptionInfoRequest"):
                try:
                    info = self.request("exceptionInfo", {"threadId": thread})
                    exception = {"id": str(info.get("exceptionId", ""))[:120],
                                 "description": str(info.get("description", ""))[:500]}
                except HTTPException:
                    exception = None
            # Watches are evaluated before anything is published, so a paused state never shows
            # the new stack with an empty or stale watch list.
            watch_values = self._watch_values(frames[0]["id"] if frames else None)
            with self.lock:
                self.frames, self.variables, self.exception = frames, variables, exception
                self.watch_values = watch_values
        except HTTPException as exc:
            with self.lock:
                self.error = str(exc.detail)
        finally:
            with self.lock:
                if self.stop is not None:
                    self.stop["inspecting"] = False

    def _evaluate_watches(self) -> None:
        values = self._watch_values(self.frames[0]["id"] if self.frames else None)
        with self.lock:
            self.watch_values = values

    def _watch_values(self, frame) -> list[dict]:
        values = []
        for expression in list(self.watches):
            if frame is None:
                values.append({"expression": expression, "value": None, "error": "Not paused"})
                continue
            try:
                body = self.request("evaluate", {"expression": expression, "frameId": frame, "context": "watch"},
                                    timeout=5)
                values.append({"expression": expression, "value": self._value(body.get("result")),
                               "type": str(body.get("type") or "")[:80], "error": None})
            except HTTPException as exc:
                values.append({"expression": expression, "value": None, "error": str(exc.detail)[:200]})
        return values

    def set_breakpoints(self, path: str, lines: list[int]) -> list[dict]:
        absolute = studio._path(self.root, path)
        if absolute.is_symlink() or not absolute.is_file():
            raise HTTPException(403, "Stop points must be in regular project files.")
        lines = sorted(set(lines))[:MAX_BREAKPOINTS]
        body = self.request("setBreakpoints", {"source": {"path": str(absolute), "name": absolute.name},
                                               "breakpoints": [{"line": n} for n in lines],
                                               "sourceModified": False})
        results = [{"line": bp.get("line") or lines[i] if i < len(lines) else bp.get("line"),
                    "verified": bool(bp.get("verified")), "message": str(bp.get("message") or "")[:200]}
                   for i, bp in enumerate(body.get("breakpoints") or [])]
        with self.lock:
            self.breakpoints[path] = lines
            self.breakpoint_results[path] = results
        return results

    def launch(self) -> None:
        spec = DEBUGGERS[self.config["debugger"]]
        init = self.request("initialize", {
            "clientID": "automoto", "clientName": "AutoMoto Developer Studio",
            "adapterID": self.config["debugger"], "pathFormat": "path", "linesStartAt1": True,
            "columnsStartAt1": True, "supportsVariableType": True, "supportsRunInTerminalRequest": False,
            "supportsStartDebuggingRequest": False, "locale": "en"})
        self.capabilities = {k: v for k, v in init.items() if isinstance(v, bool)}
        filters = [f.get("filter") for f in (init.get("exceptionBreakpointFilters") or []) if isinstance(f, dict)]
        target = str(self.config["target_path"])
        if spec["kind"] == "python":
            arguments = {"type": "python", "request": "launch", "name": "AutoMoto", "program": target,
                         "cwd": str(self.root), "console": "internalConsole", "justMyCode": True,
                         "stopOnEntry": False, "redirectOutput": True,
                         "python": [self.config["executable"]]}
        else:
            arguments = {"program": target, "cwd": str(self.root), "args": [], "stopOnEntry": False}
        pending = self.request("launch", arguments, wait=False)
        deadline = time.monotonic() + START_TIMEOUT
        while not self.initialized.wait(0.2):
            if pending[0].is_set():
                # Some adapters answer launch before 'initialized'; a failure ends here.
                self._await("launch", *pending, timeout=0.1)
            if time.monotonic() > deadline or self.status == "adapter_crashed":
                raise HTTPException(504, "The debugger didn't get ready in time.")
        for path, lines in self.config["breakpoints"].items():
            self.set_breakpoints(path, lines)
        wanted = [f for f in ("uncaught",) if f in filters] if self.config["stop_on_uncaught"] else []
        if filters:
            self.request("setExceptionBreakpoints", {"filters": wanted})
        if self.capabilities.get("supportsConfigurationDoneRequest", True):
            self.request("configurationDone")
        self._await("launch", *pending, timeout=START_TIMEOUT)
        with self.lock:
            if self.status == "starting":
                self.status = "running"

    def cleanup(self) -> None:
        if self.proc:
            _kill_tree(self.proc, self.debuggee_pids)
            for handle in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                try:
                    if handle:
                        handle.close()
                except OSError:
                    pass
        self.temp.cleanup()

    def snapshot(self) -> dict:
        with self.lock:
            alive = bool(self.proc and self.proc.poll() is None)
            return {
                "session_id": self.id, "status": self.status, "debugger": self.config["debugger"],
                "target": self.config["target"], "stop": dict(self.stop) if self.stop else None,
                "frames": [{k: v for k, v in f.items() if k != "id"} for f in self.frames]
                if self.status == "stopped" else [],
                "variables": list(self.variables) if self.status == "stopped" else [],
                "watches": list(self.watch_values) if self.status == "stopped" else
                [{"expression": w, "value": None, "error": None} for w in self.watches],
                "exception": self.exception if self.status == "stopped" else None,
                "breakpoints": {p: self.breakpoint_results.get(p, [{"line": n, "verified": False, "message": ""}
                                                                    for n in lines])
                                for p, lines in self.breakpoints.items()},
                "output": self.output, "output_truncated": self.output_truncated,
                "exit_code": self.exit_code, "error": self.error, "debugger_running": alive,
                "restart_available": self.status in ("adapter_crashed", "exited", "stopped_by_user",
                                                     "timed_out", "failed"),
                "elapsed_seconds": int(time.monotonic() - self.started), "restarts": self.restarts,
                "debugger_messages": self.stderr_tail[-600:] if self.status in ("adapter_crashed", "failed") else "",
                "external_code_unsandboxed": True, "central_agent_studio": "developer",
            }


def _session(session_id: str) -> Session:
    with SESSIONS_LOCK:
        found = SESSIONS.get(session_id)
    if not found:
        raise HTTPException(404, "That debug session has ended. Start a new one.")
    if time.monotonic() - found.started > SESSION_SECONDS and found.status not in ("exited", "adapter_crashed"):
        found.status = "timed_out"
        found.error = "The session reached its 30-minute limit and was stopped."
        found.cleanup()
    return found


def _prune() -> None:
    with SESSIONS_LOCK:
        finished = [k for k, s in SESSIONS.items()
                    if s.status in ("exited", "adapter_crashed", "stopped_by_user", "timed_out", "failed")
                    and not (s.proc and s.proc.poll() is None)]
        # Keep finished sessions readable (for Restart) until the limit forces them out.
        while len(SESSIONS) >= MAX_SESSIONS and finished:
            SESSIONS.pop(finished.pop(0), None)


def _verified_config(root: Path, debugger: str, target: str, target_sha: str, exe: str, exe_sha: str,
                     breakpoints: dict, stop_on_uncaught: bool) -> dict:
    adapters._trusted(root)
    if debugger not in DEBUGGERS:
        raise HTTPException(422, "Unknown debugger.")
    found = _debuggers(root)[debugger]
    if found["status"] != "installed_not_executed":
        raise HTTPException(409, f"{DEBUGGERS[debugger]['label']} is not installed. {found['install_hint']}")
    if found.get("executable") != exe or found.get("sha256") != exe_sha:
        raise HTTPException(409, "The debugger program changed since you approved it. Check again.")
    path = _target(root, target, DEBUGGERS[debugger]["kind"])
    digest, _ = _sha_file(path, MAX_TARGET)
    if digest != target_sha:
        raise HTTPException(409, "The program changed since you chose it. Check again.")
    clean = {}
    for rel, lines in breakpoints.items():
        source = studio._path(root, rel)
        if source.is_symlink() or not source.is_file():
            raise HTTPException(403, "Stop points must be in regular project files.")
        clean[rel] = sorted(set(lines))[:MAX_BREAKPOINTS]
    return {"debugger": debugger, "executable": exe, "sha256": exe_sha, "launch_path": found["launch_path"],
            "target": target,
            "target_path": path, "target_sha256": digest, "breakpoints": clean,
            "stop_on_uncaught": stop_on_uncaught}


def _start(root: Path, config: dict, watches: list[str] | None = None, restarts: int = 0) -> Session:
    _prune()
    with SESSIONS_LOCK:
        live = [s for s in SESSIONS.values() if s.proc and s.proc.poll() is None]
        if len(live) >= MAX_SESSIONS:
            raise HTTPException(429, "Two debug sessions are already running. Stop one first.")
        session = Session(root, config)
        session.watches = list(watches or [])
        session.restarts = restarts
        SESSIONS[session.id] = session
    try:
        session.spawn()
        session.launch()
    except HTTPException as exc:
        with session.lock:
            if session.status != "adapter_crashed":
                session.status = "failed"
            session.error = (session.error or str(exc.detail))
        session.cleanup()
    return session


# ------------------------------------------------------------------ detection
def _detect(root: Path) -> dict:
    debuggers = _debuggers(root)
    python_targets, native_targets, incomplete = [], [], False
    preferred = ("main.py", "app.py", "__main__.py", "run.py", "cli.py")
    for name, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        leaf = name.rsplit("/", 1)[-1]
        path = root / name
        if leaf.endswith(".py") and len(python_targets) < 60:
            if not leaf.startswith("test_") and leaf != "conftest.py":
                python_targets.append(name)
            continue
        if len(native_targets) >= 20 or "." in leaf and not leaf.lower().endswith(".exe"):
            continue
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_TARGET:
                continue
        except OSError:
            continue
        if _native_magic(path) and (os.name == "nt" or os.access(path, os.X_OK)):
            native_targets.append(name)
    python_targets.sort(key=lambda p: (p.rsplit("/", 1)[-1] not in preferred, p.count("/"), p))
    targets = []
    for kind, names in (("python", python_targets[:30]), ("native", native_targets)):
        for name in names:
            try:
                digest, size = _sha_file(studio._path(root, name), MAX_TARGET)
            except HTTPException:
                continue
            targets.append({"path": name, "kind": kind, "sha256": digest, "bytes": size})
    return {"schema": VERSION, "host": _host(), "debuggers": list(debuggers.values()),
            "targets": targets, "scan_incomplete": incomplete,
            "project_trusted": studio._trusted(root, studio._load()),
            "not_supported_yet": list(NOT_SUPPORTED), "program_started": False,
            "central_agent_studio": "developer",
            "limitations": ("Debugging runs your program for real, without an OS sandbox. Watch "
                            "expressions are limited to names, attributes and simple indexes. "
                            "Only the main file's bytes are pinned; files it imports are not. "
                            "Python profiling only; native profiling is not offered.")}


# ------------------------------------------------------------------ crash explainer
SIGNALS = {4: "SIGILL (illegal instruction)", 6: "SIGABRT (the program aborted itself)",
           7: "SIGBUS (bad memory access)", 8: "SIGFPE (arithmetic error, often divide by zero)",
           9: "SIGKILL (killed from outside, often out of memory)",
           11: "SIGSEGV (segmentation fault: bad memory access)", 15: "SIGTERM (asked to stop)"}
WINDOWS_CODES = {0xC0000005: "access violation (bad memory access)", 0xC00000FD: "stack overflow (often endless recursion)",
                 0xC0000094: "integer divide by zero", 0xC0000409: "stack buffer overrun / fail-fast",
                 0xC000001D: "illegal instruction", 0xC0000374: "heap corruption"}
FRAME_PATTERNS = (
    ("python", re.compile(r'File "([^"\n]{1,500})", line (\d{1,8})(?:, in ([^\n]{1,120}))?')),
    ("rust", re.compile(r"panicked at ([^\s:]{1,500}):(\d{1,8}):\d{1,6}")),
    ("go", re.compile(r"^\s+(/[^\s:]{1,500}\.go):(\d{1,8})", re.M)),
    ("javascript", re.compile(r"at (?:([^\s(]{1,120}) \()?([^\s()]{1,500}\.(?:js|mjs|cjs|ts)):(\d{1,8}):\d{1,6}\)?")),
    ("java", re.compile(r"at ([\w$.<>]{1,200})\(([\w$]{1,120}\.(?:java|kt)):(\d{1,8})\)")),
    ("dotnet", re.compile(r"at ([^\n]{1,200}) in ([^\n]{1,500}):line (\d{1,8})")),
    ("native", re.compile(r"(?:#\d+\s+0x[0-9a-f]+ in |\bat )?([\w:~<>]{1,120}) (?:\([^)]*\) )?(?:at )?([^\s:]{1,500}\.(?:c|cc|cpp|cxx|h|hpp|rs|zig|swift)):(\d{1,8})")),
)


def _crash(root: Path, text: str, exit_code: int | None) -> dict:
    text = text[:MAX_CRASH_TEXT]
    frames, language = [], None
    for lang, pattern in FRAME_PATTERNS:
        for match in pattern.finditer(text):
            groups = match.groups()
            if lang == "python":
                path, line, func = groups
            elif lang in ("rust", "go"):
                (path, line), func = groups, None
            elif lang == "javascript":
                func, path, line = groups
            else:
                func, path, line = groups
            rel, exists = _relative(root, path)
            frames.append({"path": rel, "line": int(line), "function": func, "in_project": exists})
            if len(frames) >= 40:
                break
        if frames:
            language = lang
            break
    error = None
    if language == "python":
        tail = [l for l in text.strip().splitlines() if l.strip()]
        error = tail[-1].strip()[:300] if tail else None
        frames.reverse()  # innermost first
    else:
        for pattern in (r"(?m)^(panic: [^\n]{1,300})", r"(?m)^(thread '[^\n]{1,80}' panicked[^\n]{0,200})",
                        r"(?m)^((?:Uncaught )?\w*(?:Error|Exception)[:\s][^\n]{0,300})",
                        r"(ERROR: AddressSanitizer: [^\n]{1,200})", r"(Segmentation fault[^\n]{0,80})"):
            match = re.search(pattern, text)
            if match:
                error = match.group(1).strip()
                break
    signal_name = None
    if exit_code is not None:
        code = exit_code
        if code < 0 and -code in SIGNALS:
            signal_name = SIGNALS[-code]
        elif 128 < code < 160 and code - 128 in SIGNALS:
            signal_name = SIGNALS[code - 128]
        elif (code & 0xFFFFFFFF) in WINDOWS_CODES:
            signal_name = WINDOWS_CODES[code & 0xFFFFFFFF]
    if not signal_name:
        for number, label in SIGNALS.items():
            if re.search(r"\b" + label.split(" ")[0] + r"\b", text):
                signal_name = label
                break
    first = next((f for f in frames if f["in_project"]), frames[0] if frames else None)
    if error and first:
        summary = f"It crashed with {error} at {first['path']} line {first['line']}."
    elif error:
        summary = f"It crashed with {error}."
    elif signal_name:
        summary = f"The program was stopped by {signal_name}."
    elif first:
        summary = f"The last place in your code was {first['path']} line {first['line']}."
    else:
        summary = "AutoMoto couldn't find a crash pattern in this text."
    tips = []
    if signal_name and ("SIGSEGV" in signal_name or "access violation" in signal_name or "SIGBUS" in signal_name):
        tips.append("Build with debug info (-g) and run it under the debugger to see the exact line.")
        tips.append("Build with -fsanitize=address to catch the bad memory access where it happens.")
    if signal_name and "stack overflow" in signal_name:
        tips.append("Look for a function that calls itself without stopping.")
    if first and first["in_project"]:
        tips.append(f"Set a stop point at {first['path']} line {first['line']} and start the debugger.")
    return {"summary": summary, "language": language, "error": error, "signal": signal_name,
            "frames": frames, "first_project_frame": first, "tips": tips,
            "program_started": False, "text_stored": False, "central_agent_studio": "developer"}


# ------------------------------------------------------------------ profiling
def _profile(root: Path, body: ProfileIn) -> dict:
    config = _verified_config(root, "debugpy", body.target, body.expected_target_sha256,
                              body.expected_executable, body.expected_sha256, {}, False)
    with tempfile.TemporaryDirectory(prefix="automoto-v42-profile-") as directory:
        env = adapters._environment(root)
        env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", "NO_COLOR": "1",
                    "TMPDIR": directory, "TEMP": directory, "TMP": directory})
        command = [_launch_path(config), "-c", PROFILE_SCRIPT, str(config["target_path"])]
        output = native._execute(root, command, env, timeout=PROFILE_TIMEOUT)
    text = output["output"]
    marker = text.rfind(PROFILE_MARKER)
    rows, own_total, code = [], None, output["exit_code"]
    program_output = text if marker < 0 else text[:marker]
    if marker >= 0:
        try:
            data = json.loads(text[marker + len(PROFILE_MARKER):].splitlines()[0])
            own_total, code = data.get("own_total_seconds"), data.get("exit_code")
            for row in data.get("rows", [])[:25]:
                rel, exists = _relative(root, str(row.get("file", "")))
                rows.append({"function": str(row.get("function", ""))[:120], "path": rel,
                             "line": row.get("line"), "calls": row.get("calls"),
                             "own_seconds": row.get("own_seconds"), "total_seconds": row.get("total_seconds"),
                             "in_project": exists})
        except (ValueError, IndexError, TypeError):
            rows = []
    project_rows = [r for r in rows if r["in_project"]]
    return {"status": "completed" if rows else output["status"], "rows": rows,
            "slowest_in_project": project_rows[:5], "own_total_seconds": own_total,
            "program_exit_code": code, "program_output": program_output[-8000:],
            "elapsed_ms": output["elapsed_ms"], "timed_out": output["timed_out"],
            "profiler": "cProfile", "external_code_unsandboxed": True,
            "central_agent_studio": "developer"}


# ------------------------------------------------------------------ routes
@router.get("/detect")
def detect(request: Request, project: str):
    studio._auth(request)
    return _detect(studio._project(project))


@router.post("/start")
def start(request: Request, body: StartIn):
    studio._auth(request)
    root = studio._project(body.project)
    grouped: dict[str, list[int]] = {}
    for bp in body.breakpoints:
        grouped.setdefault(bp.path, []).append(bp.line)
    config = _verified_config(root, body.debugger, body.target, body.expected_target_sha256,
                              body.expected_executable, body.expected_sha256, grouped, body.stop_on_uncaught)
    return _start(root, config).snapshot()


@router.get("/state")
def state(request: Request, session_id: str):
    studio._auth(request)
    return _session(SessionIn(session_id=session_id).session_id).snapshot()


@router.post("/control")
def control(request: Request, body: ControlIn):
    studio._auth(request)
    session = _session(body.session_id)
    if body.action == "pause":
        if session.status != "running":
            raise HTTPException(409, "The program isn't running.")
        threads = session.request("threads").get("threads") or []
        if not threads:
            raise HTTPException(409, "No running thread to pause.")
        session.request("pause", {"threadId": threads[0]["id"]})
        return session.snapshot()
    if session.status != "stopped" or not session.stop:
        raise HTTPException(409, "The program isn't paused.")
    thread = session.stop.get("thread_id")
    with session.lock:
        session.status = "running"
        session.stop = None
        session.frames, session.variables, session.watch_values = [], [], []
    session.request(body.action, {"threadId": thread})
    return session.snapshot()


@router.post("/breakpoints")
def breakpoints(request: Request, body: BreakpointsIn):
    studio._auth(request)
    session = _session(body.session_id)
    if session.status not in ("running", "stopped"):
        raise HTTPException(409, "The session isn't active.")
    if any(n < 1 or n > 10_000_000 for n in body.lines):
        raise HTTPException(422, "Line numbers must be positive.")
    session.set_breakpoints(body.path, body.lines)
    return session.snapshot()


@router.post("/watch")
def watch(request: Request, body: WatchIn):
    studio._auth(request)
    session = _session(body.session_id)
    cleaned = []
    for expression in body.expressions:
        expression = expression.strip()
        if not WATCH.match(expression):
            raise HTTPException(422, "Watch a name like total, user.name or items[0]. Calls and operators aren't allowed.")
        cleaned.append(expression)
    with session.lock:
        session.watches = cleaned
    if session.status == "stopped":
        session._evaluate_watches()
    return session.snapshot()


@router.post("/stop")
def stop(request: Request, body: SessionIn):
    studio._auth(request)
    session = _session(body.session_id)
    with session.lock:
        if session.status in ("running", "stopped", "starting"):
            session.status = "stopped_by_user"
    try:
        session.request("disconnect", {"terminateDebuggee": True}, timeout=3)
    except HTTPException:
        pass
    session.cleanup()
    return session.snapshot()


@router.post("/restart")
def restart(request: Request, body: RestartIn):
    studio._auth(request)
    old = _session(body.session_id)
    if old.status not in ("adapter_crashed", "exited", "stopped_by_user", "timed_out", "failed"):
        raise HTTPException(409, "Stop the session before restarting it.")
    cfg = old.config
    config = _verified_config(old.root, cfg["debugger"], cfg["target"], cfg["target_sha256"],
                              cfg["executable"], cfg["sha256"], dict(old.breakpoints), cfg["stop_on_uncaught"])
    with SESSIONS_LOCK:
        SESSIONS.pop(old.id, None)
    return _start(old.root, config, old.watches, old.restarts + 1).snapshot()


@router.post("/profile")
def profile(request: Request, body: ProfileIn):
    studio._auth(request)
    if not PROFILE_LOCK.acquire(blocking=False):
        raise HTTPException(429, "A speed check is already running.")
    try:
        return _profile(studio._project(body.project), body)
    finally:
        PROFILE_LOCK.release()


@router.post("/crash")
def crash(request: Request, body: CrashIn):
    studio._auth(request)
    return _crash(studio._project(body.project), body.text, body.exit_code)


def shutdown() -> None:
    with SESSIONS_LOCK:
        sessions = list(SESSIONS.values())
        SESSIONS.clear()
    for session in sessions:
        session.cleanup()


atexit.register(shutdown)
