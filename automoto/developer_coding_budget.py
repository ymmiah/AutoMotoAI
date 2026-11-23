"""V52: per-run, local-only coding budgets and forced human tool approvals.

These budgets are monotonic and scoped to one agent task. They are cooperative:
an already-running provider or external process cannot be forcibly killed by
a Python check, but no *subsequent* tool can start after the deadline.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

# Only explicitly audited read-only operations are automatic in a bounded run.
# Even if Settings chooses auto approval, every other tool must ask the user.
READ_ONLY = frozenset({
    "read_file", "list_dir", "search_files", "project_inspect",
    "developer_open", "developer_read", "developer_search",
    "developer_sources", "developer_symbols", "developer_languages",
    "developer_lsp", "developer_diff",
})

MAX_STEPS = 12
MAX_OPERATIONS = 30
MAX_SECONDS = 600


@dataclass
class CodingBudget:
    max_steps: int = 8
    max_operations: int = 20
    max_seconds: int = 300
    _started: float | None = field(default=None, init=False, repr=False)
    _operations: int = field(default=0, init=False, repr=False)
    _reason: str = field(default="", init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self):
        if (type(self.max_steps) is not int or not 1 <= self.max_steps <= MAX_STEPS or
            type(self.max_operations) is not int or not 1 <= self.max_operations <= MAX_OPERATIONS or
            type(self.max_seconds) is not int or not 30 <= self.max_seconds <= MAX_SECONDS):
            raise ValueError("Invalid bounded coding limits")

    def start(self):
        with self._lock:
            if self._started is None:
                self._started = time.monotonic()

    def _remaining_unlocked(self):
        if self._started is None:
            return float(self.max_seconds)
        return max(0.0, self.max_seconds - (time.monotonic() - self._started))

    def remaining(self) -> float:
        with self._lock:
            return self._remaining_unlocked()

    def check(self) -> str | None:
        with self._lock:
            if self._remaining_unlocked() <= 0:
                self._reason = "time"
            return self._reason or None

    def consume_operation(self) -> str | None:
        """Reserve one tool-call slot *before* any tool side effect or approval."""
        with self._lock:
            if self._remaining_unlocked() <= 0:
                self._reason = "time"
            elif self._operations >= self.max_operations:
                self._reason = "operations"
            if self._reason:
                return self._reason
            self._operations += 1
            return None

    def mark_steps(self):
        with self._lock:
            self._reason = self._reason or "steps"

    def snapshot(self) -> dict:
        with self._lock:
            remaining = self._remaining_unlocked()
            if remaining <= 0:
                self._reason = self._reason or "time"
            return {
                "max_steps": self.max_steps,
                "max_operations": self.max_operations,
                "max_seconds": self.max_seconds,
                "operations_used": self._operations,
                "seconds_remaining": round(remaining, 1),
                "limit_reason": self._reason or None,
                "requires_approval": True,
                "cooperative_deadline": True,
            }
