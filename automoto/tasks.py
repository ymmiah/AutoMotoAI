"""Background agent tasks: each run happens in its own thread so the chat stays responsive.

A task streams events (thinking, tool calls, results, approvals, final). When a risky
tool needs approval the task pauses in ``waiting_approval`` until someone calls
``approve(task_id, call_id, yes)`` (web UI card) or the approval times out (= denied).

BYOK keys passed to ``start`` live only on the running thread's stack and are dropped
when the run ends; they are never stored in the task record or its events.
"""

from __future__ import annotations

import contextvars
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from automoto import policy

APPROVAL_TIMEOUT_S = 600
MAX_TASKS = 100


@dataclass
class Task:
    id: str
    title: str
    source: str  # web | cli | routine
    status: str = "queued"  # queued | running | waiting_approval | done | error | cancelled
    created: float = field(default_factory=time.time)
    finished: float | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    pending: dict[str, Any] | None = None
    conversation_id: str | None = None
    owner: str | None = None  # hosted mode: the user id that started it
    cancel: threading.Event = field(default_factory=threading.Event)
    _answers: dict[str, bool] = field(default_factory=dict)
    _cv: threading.Condition = field(default_factory=threading.Condition)

    def summary(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "source": self.source, "status": self.status,
                "created": self.created, "finished": self.finished, "pending": self.pending,
                "steps": sum(1 for e in self.events if e.get("type") == "model"),
                "conversation_id": self.conversation_id,
                "result": self.result}


class TaskManager:
    def __init__(self, agent_factory: Callable[..., Any]):
        self.agent_factory = agent_factory
        self.tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    def start(self, messages: list[dict[str, Any]], *, title: str = "", source: str = "web",
              keys: dict[str, str] | None = None, prefer: str | None = None, max_steps: int | None = None,
              agent_kwargs: dict[str, Any] | None = None, auto_deny: bool = False,
              conversation_id: str | None = None, on_done: Callable[[Task], None] | None = None,
              owner: str | None = None) -> Task:
        last = next((m.get("content") for m in reversed(messages) if m.get("role") == "user"), "")
        text = last if isinstance(last, str) else " ".join(p.get("text", "") for p in last if isinstance(p, dict))
        task = Task(id=uuid.uuid4().hex[:10], title=(title or text or "task")[:120], source=source,
                    conversation_id=conversation_id, owner=owner)
        with self._lock:
            self.tasks[task.id] = task
            if len(self.tasks) > MAX_TASKS:
                for old in sorted(self.tasks.values(), key=lambda t: t.created)[: len(self.tasks) - MAX_TASKS]:
                    if old.status in ("done", "error", "cancelled"):
                        self.tasks.pop(old.id, None)

        def approver(call: dict[str, Any], decision: policy.Decision) -> bool:
            if auto_deny:
                return False
            with task._cv:
                task.pending = {"id": call["id"], "name": call["name"], "args": call["args"],
                                "reason": decision.reason, "level": decision.level}
                task.status = "waiting_approval"
                ok = task._cv.wait_for(lambda: call["id"] in task._answers or task.cancel.is_set(),
                                       timeout=APPROVAL_TIMEOUT_S)
                answer = bool(ok) and task._answers.pop(call["id"], False) and not task.cancel.is_set()
                task.pending = None
                task.status = "running"
                return answer

        def run(keys=keys) -> None:
            task.status = "running"
            try:
                agent = self.agent_factory(**(agent_kwargs or {}))
                res = agent.run(messages, approver=approver, on_event=task.events.append, keys=keys,
                                prefer=prefer, max_steps=max_steps, cancel=task.cancel)
                task.result = res.as_dict()
                task.status = "cancelled" if res.stopped == "cancelled" else (
                    "error" if res.stopped == "error" else "done")
            except Exception as exc:  # pragma: no cover - defensive
                task.result = {"text": f"✗ {exc.__class__.__name__}: {exc}"}
                task.status = "error"
            finally:
                keys = None  # noqa: F841 - drop BYOK keys as soon as the run ends
                if on_done:
                    try:
                        on_done(task)
                    except Exception:
                        pass
                task.finished = time.time()

        # the run keeps the caller's context (hosted mode: the user's tenant -> their own sandbox and memory)
        ctx = contextvars.copy_context()
        threading.Thread(target=ctx.run, args=(run,), name=f"automoto-task-{task.id}", daemon=True).start()
        return task

    def get(self, task_id: str, owner: str | None = None) -> Task | None:
        t = self.tasks.get(task_id)
        if t is not None and owner is not None and t.owner != owner:
            return None
        return t

    def list(self, owner: str | None = None) -> list[dict[str, Any]]:
        return [t.summary() for t in sorted(self.tasks.values(), key=lambda t: -t.created)
                if owner is None or t.owner == owner]

    def running(self, owner: str) -> int:
        return sum(1 for t in self.tasks.values() if t.owner == owner and t.status in ("queued", "running",
                                                                                         "waiting_approval"))

    def approve(self, task_id: str, call_id: str, yes: bool, owner: str | None = None) -> bool:
        task = self.get(task_id, owner)
        if not task or not task.pending or task.pending.get("id") != call_id:
            return False
        with task._cv:
            task._answers[call_id] = bool(yes)
            task._cv.notify_all()
        return True

    def cancel(self, task_id: str, owner: str | None = None) -> bool:
        task = self.get(task_id, owner)
        if not task:
            return False
        task.cancel.set()
        with task._cv:
            task._cv.notify_all()
        return True

    def wait(self, task_id: str, timeout: float = 30) -> Task | None:
        end = time.time() + timeout
        while time.time() < end:
            t = self.tasks.get(task_id)
            if t and t.status in ("done", "error", "cancelled"):
                return t
            time.sleep(0.02)
        return self.tasks.get(task_id)
