"""Routines: agent prompts that run on a schedule while ``python -m automoto serve`` is up
(or on demand with ``python -m automoto routines run <name>``).

Schedules:
  * interval - ``every 30m``, ``every 2h``, ``every 1d`` (minimum 1 minute)
  * cron     - five fields ``min hour day month weekday`` with ``*``, ``a,b``, ``a-b``, ``*/n``
               (weekday 0 = Sunday ... 6 = Saturday), local time

Routines run unattended, so risky tools are auto-denied unless listed in
``AUTOMOTO_AUTO_APPROVE`` (or AUTOMOTO_APPROVAL=auto). Results go to
``~/.automoto/routines.log`` and the memory journal.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from automoto import home

INTERVAL_RE = re.compile(r"^\s*every\s+(\d+)\s*(m|min|mins|minutes?|h|hrs?|hours?|d|days?)\s*$", re.I)
_LOCK = threading.Lock()


class ScheduleError(ValueError):
    pass


def parse_interval(spec: str) -> int | None:
    m = INTERVAL_RE.match(spec or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()[0]
    secs = n * {"m": 60, "h": 3600, "d": 86400}[unit]
    if secs < 60:
        raise ScheduleError("minimum interval is 1 minute")
    return secs


def _field(expr: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in expr.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
            if step < 1:
                raise ScheduleError("bad step")
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
        else:
            a = b = int(part)
        if a < lo or b > hi or a > b:
            raise ScheduleError(f"value out of range {lo}-{hi}")
        out.update(range(a, b + 1, step))
    return out


def parse_cron(spec: str) -> list[set[int]]:
    parts = (spec or "").split()
    if len(parts) != 5:
        raise ScheduleError("cron needs 5 fields: min hour day month weekday")
    try:
        f = [_field(parts[0], 0, 59), _field(parts[1], 0, 23), _field(parts[2], 1, 31),
             _field(parts[3], 1, 12), {d % 7 for d in _field(parts[4], 0, 7)}]
    except ValueError as exc:
        raise ScheduleError(str(exc)) from None
    return f


def cron_matches(spec: str, when: datetime) -> bool:
    mi, hr, dom, mon, dow = parse_cron(spec)
    wd = (when.weekday() + 1) % 7  # python Monday=0 -> cron Sunday=0
    return when.minute in mi and when.hour in hr and when.day in dom and when.month in mon and wd in dow


def validate(schedule: str) -> str:
    if parse_interval(schedule) is not None:
        return "interval"
    parse_cron(schedule)
    return "cron"


@dataclass
class Routine:
    name: str
    schedule: str
    prompt: str
    enabled: bool = True
    last_run: float | None = None
    last_status: str = ""
    last_result: str = ""

    def is_due(self, now: float) -> bool:
        if not self.enabled:
            return False
        secs = parse_interval(self.schedule)
        if secs is not None:
            return self.last_run is None or now - self.last_run >= secs
        when = datetime.fromtimestamp(now).replace(second=0, microsecond=0)
        if self.last_run and datetime.fromtimestamp(self.last_run).replace(second=0, microsecond=0) == when:
            return False  # already ran this minute
        return cron_matches(self.schedule, when)


class RoutineStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or home.routines_file())

    def load(self) -> dict[str, Routine]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {r["name"]: Routine(**{k: v for k, v in r.items() if k in Routine.__dataclass_fields__})
                for r in data.get("routines", [])}

    def save(self, routines: dict[str, Routine]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"routines": [asdict(r) for r in routines.values()]}, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, name: str, schedule: str, prompt: str) -> Routine:
        name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name.strip())[:60]
        if not name or not prompt.strip():
            raise ScheduleError("routine needs a name and a prompt")
        validate(schedule)
        with _LOCK:
            rs = self.load()
            rs[name] = Routine(name=name, schedule=schedule.strip(), prompt=prompt.strip())
            self.save(rs)
        return rs[name]

    def update(self, name: str, *, schedule: str | None = None, prompt: str | None = None,
               enabled: bool | None = None) -> Routine:
        with _LOCK:
            rs = self.load()
            if name not in rs:
                raise KeyError(name)
            r = rs[name]
            if schedule is not None:
                validate(schedule)
                r.schedule = schedule.strip()
            if prompt is not None:
                if not prompt.strip():
                    raise ScheduleError("prompt is empty")
                r.prompt = prompt.strip()
            if enabled is not None:
                r.enabled = bool(enabled)
            self.save(rs)
            return r

    def remove(self, name: str) -> bool:
        with _LOCK:
            rs = self.load()
            if rs.pop(name, None) is None:
                return False
            self.save(rs)
        return True

    def record(self, name: str, status: str, result: str, when: float) -> None:
        with _LOCK:
            rs = self.load()
            if name in rs:
                rs[name].last_run, rs[name].last_status, rs[name].last_result = when, status, result[:500]
                self.save(rs)


def run_routine(r: Routine, runner: Callable[[str], dict[str, Any]], store: RoutineStore | None = None,
                log_path: Path | None = None) -> dict[str, Any]:
    store = store or RoutineStore()
    started = time.time()
    store.record(r.name, "running", "", started)
    try:
        res = runner(r.prompt)
        status, text = res.get("stopped", "done"), res.get("text", "")
    except Exception as exc:
        status, text = "error", f"{exc.__class__.__name__}: {exc}"
    store.record(r.name, status, text, started)
    line = {"ts": datetime.fromtimestamp(started).isoformat(timespec="seconds"), "routine": r.name,
            "status": status, "result": text[:2000]}
    lp = Path(log_path or home.routines_log())
    with _LOCK, lp.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")
    return line


class Scheduler:
    """Checks routines every ``tick`` seconds in a daemon thread."""

    def __init__(self, runner: Callable[[str], dict[str, Any]], store: RoutineStore | None = None, tick: float = 20):
        self.runner, self.store, self.tick = runner, store or RoutineStore(), tick
        self._stop = threading.Event()
        self._busy: set[str] = set()
        self.thread: threading.Thread | None = None

    def due(self, now: float | None = None) -> list[Routine]:
        now = now or time.time()
        return [r for r in self.store.load().values() if r.name not in self._busy and r.is_due(now)]

    def run_due(self, now: float | None = None) -> list[str]:
        started = []
        for r in self.due(now):
            self._busy.add(r.name)
            started.append(r.name)

            def go(r=r):
                try:
                    run_routine(r, self.runner, self.store)
                finally:
                    self._busy.discard(r.name)
            threading.Thread(target=go, name=f"automoto-routine-{r.name}", daemon=True).start()
        return started

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return

        def loop():
            while not self._stop.wait(self.tick):
                try:
                    self.run_due()
                except Exception:
                    pass
        self.thread = threading.Thread(target=loop, name="automoto-scheduler", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()
