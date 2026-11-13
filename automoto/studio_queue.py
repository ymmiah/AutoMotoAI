"""One studio task queue for Documents, Research, Spreadsheets, Visual and Developer.

A new task waits while another is running, then starts on its own. The list is
stored in this user's data folder, so leaving a studio does not drop it.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from typing import Any

from automoto import home

STUDIOS = frozenset({"documents", "research", "spreadsheets", "visual", "developer"})
_LOCK = threading.Lock()
_CACHE: dict[str, list[dict[str, Any]]] = {}


def _file():
    return home.home() / "studio-queue.json"


def _load() -> list[dict[str, Any]]:
    path = _file()
    key = str(path)
    if key in _CACHE:
        return _CACHE[key]
    jobs: list[dict[str, Any]] = []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            jobs = [row for row in raw if isinstance(row, dict) and isinstance(row.get("id"), str)]
    except (OSError, ValueError):
        jobs = []
    _CACHE[key] = jobs
    return jobs


def _save(jobs: list[dict[str, Any]]) -> None:
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    _CACHE[str(path)] = jobs


def reset_for_tests() -> None:
    """Drop the in-memory copy so the next read comes from disk."""
    _CACHE.pop(str(_file()), None)


def _promote(jobs: list[dict[str, Any]]) -> None:
    if any(job.get("status") == "running" for job in jobs):
        return
    for job in jobs:
        if job.get("status") == "queued":
            job["status"] = "running"
            job["progress"] = "Running"
            return


def _clean(title: str) -> str:
    text = " ".join(str(title or "").split())
    return (text or "Studio task")[:180]


def enqueue(studio: str, title: str) -> dict[str, Any]:
    if studio not in STUDIOS:
        raise ValueError("That studio is not in the queue.")
    with _LOCK:
        jobs = _load()
        job = {
            "id": secrets.token_hex(8),
            "studio": studio,
            "title": _clean(title),
            "status": "queued",
            "progress": "Waiting for the task ahead of it",
            "created": time.time(),
        }
        jobs.append(job)
        _promote(jobs)
        _save(jobs)
        return dict(job)


def jobs() -> list[dict[str, Any]]:
    with _LOCK:
        return [dict(job) for job in _load()]


def cancel(job_id: str) -> list[dict[str, Any]]:
    with _LOCK:
        rows = _load()
        for job in rows:
            if job.get("id") == job_id and job.get("status") in {"queued", "running"}:
                job["status"] = "cancelled"
                job["progress"] = "Cancelled"
        _promote(rows)
        _save(rows)
        return [dict(job) for job in rows]


def reorder(job_id: str, direction: str) -> list[dict[str, Any]]:
    if direction not in {"up", "down"}:
        raise ValueError("Reorder up or down.")
    with _LOCK:
        rows = _load()
        queued = [job for job in rows if job.get("status") == "queued"]
        index = next((i for i, job in enumerate(queued) if job.get("id") == job_id), None)
        if index is None:
            return [dict(job) for job in rows]
        swap = index - 1 if direction == "up" else index + 1
        if swap < 0 or swap >= len(queued):
            return [dict(job) for job in rows]
        first, second = queued[index], queued[swap]
        ia, ib = rows.index(first), rows.index(second)
        rows[ia], rows[ib] = rows[ib], rows[ia]
        _save(rows)
        return [dict(job) for job in rows]


def update(job_id: str, progress: str) -> dict[str, Any] | None:
    text = " ".join(str(progress or "").split())[:240]
    with _LOCK:
        rows = _load()
        found = None
        for job in rows:
            if job.get("id") == job_id and job.get("status") == "running":
                job["progress"] = text or job.get("progress") or "Running"
                found = dict(job)
        if found:
            _save(rows)
        return found


def finish(job_id: str, *, ok: bool, progress: str = "") -> list[dict[str, Any]]:
    text = " ".join(str(progress or "").split())[:240]
    with _LOCK:
        rows = _load()
        for job in rows:
            if job.get("id") == job_id and job.get("status") == "running":
                job["status"] = "done" if ok else "cancelled"
                job["progress"] = text or ("Done" if ok else "Stopped")
                break
        _promote(rows)
        _save(rows)
        return [dict(job) for job in rows]
