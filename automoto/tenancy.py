"""Hosted (multi-user) mode: who the current request or agent task belongs to.

Single-user local mode (the default) never sets a tenant, so nothing here changes it.
With ``AUTOMOTO_MODE=multiuser`` every authenticated request runs inside ``use(user)``:
``home.home()`` becomes that user's own folder (memory, chats, skills, settings) and the
sandbox root becomes their own workspace, so one user can never see another's files.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from automoto import config


@dataclass(frozen=True)
class Tenant:
    id: str
    username: str
    role: str  # "user" | "admin"
    home: Path

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


_CURRENT: contextvars.ContextVar[Tenant | None] = contextvars.ContextVar("automoto_tenant", default=None)


def multiuser() -> bool:
    return (config.env("AUTOMOTO_MODE", "") or "").strip().lower() in ("multiuser", "multi-user", "hosted")


def current() -> Tenant | None:
    return _CURRENT.get()


def set_current(t: Tenant | None) -> None:
    """Set the tenant for the rest of this context (a request's thread-pool context)."""
    _CURRENT.set(t)


@contextmanager
def use(t: Tenant | None) -> Iterator[Tenant | None]:
    tok = _CURRENT.set(t)
    try:
        yield t
    finally:
        _CURRENT.reset(tok)
