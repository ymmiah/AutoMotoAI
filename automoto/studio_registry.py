"""Studio plugin registry for the chat assistant.

Any later studio is picked up with no edit to ``tools.py`` or ``planner.py``:

* a module named ``automoto/*_studio_tools.py`` (or the same pattern on
  ``AUTOMOTO_STUDIO_PATH``)
* ``StudioSpec`` returned by a Python entry point in the group ``automoto.studios``
* ``register(spec)`` for tests and in-process plugins

Safety is applied here, not left to each studio. Mutating tools are approval-gated
(``risky``) even if a module marks them safe. Host program execution is omitted when
local apps are off (hosted multi-user servers). Online-only tools disappear in
offline mode. A studio that is not ``hosted_ok`` never joins the hosted tool set.
A broken module is logged and skipped.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("automoto.studio_registry")

_ID = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
# Names that change files, trust, or run a program. The registry will not let
# these stay "safe", so a new studio cannot skip the approval prompt.
_MUTATING = re.compile(
    r"(?:^|_)(save|edit|export|write|replace|delete|run|register|restore|trash|trust|create|revise|"
    r"decide|publish|apply|pdf)(?:$|_)"
)

_cache: dict[tuple[str, int], Any] = {}
_manual: list[StudioSpec] = []


def obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


S = {"type": "string"}
INT = {"type": "integer"}
OBJ = {"type": "object"}
ARR = {"type": "array", "items": S}


@dataclass(frozen=True)
class StudioSpec:
    """One studio the assistant can plan and call.

    ``approval`` is the floor for mutating tools. ``"safe"`` is ignored for those
    tools: writes, exports, trust changes and program runs stay ``risky``.
    ``hosted_ok`` must be set on purpose; otherwise hosted servers never see the
    studio. ``host_exec`` tools need the user's computer (``local_apps``).
    ``online_only`` tools need the network. ``local_only`` tools stay off hosted
    servers even when the rest of the studio is allowed (loopback models, for
    example). ``reads_only`` names a tool whose name looks mutating but only
    previews.
    """

    id: str
    name: str
    tools: tuple[Any, ...]
    words: str
    exts: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    how: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    fuzzy: tuple[str, ...] = ()
    hosted_ok: bool = False
    needs_local_apps: bool = False
    approval: str = "risky"
    host_exec: tuple[str, ...] = ()
    online_only: tuple[str, ...] = ()
    local_only: tuple[str, ...] = ()
    reads_only: tuple[str, ...] = ()

    def capability(self) -> Any:
        from automoto.planner import Capability

        return Capability(
            self.id, self.name, self.words, tuple(self.exts), tuple(t.name for t in self.tools),
            skills=tuple(self.skills), how=self.how,
        )


def register(spec: StudioSpec) -> StudioSpec:
    """Register a studio that is already imported (tests and embedded plugins)."""
    if not isinstance(spec, StudioSpec):
        raise TypeError("register() expects a StudioSpec")
    _manual.append(spec)
    return spec


def reset() -> None:
    """Drop discovery cache and in-process registrations. Package modules reload on the next scan."""
    _cache.clear()
    _manual.clear()


def studio_request(method: str = "POST") -> Any:
    """Loopback request carrying this process's session, for calling studio endpoints.

    On a hosted server the request is marked as an agent call. ``server._authorise``
    accepts that only when a signed-in tenant is already on this task, and still
    refuses ``local_only`` studios. The mark is not something an HTTP client can set.
    """
    from starlette.requests import Request

    from automoto.server import SESSION_TOKEN

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": (method or "POST").upper(),
        "scheme": "http",
        "path": "/internal/studio",
        "raw_path": b"/internal/studio",
        "query_string": b"",
        "headers": [(b"x-automoto-token", SESSION_TOKEN.encode("ascii"))],
        "client": ("127.0.0.1", 0),
        "server": ("127.0.0.1", 80),
    }
    request = Request(scope)
    request.state.automoto_agent_call = True
    return request


def call_studio(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    """Call a studio endpoint and turn its result or its HTTP error into tool text."""
    from fastapi import HTTPException
    from pydantic import ValidationError

    from automoto.tools import ToolFailed

    try:
        result = fn(*args, **kwargs)
    except ToolFailed:
        raise
    except HTTPException as exc:
        detail = exc.detail
        text = detail if isinstance(detail, str) else json.dumps(detail, default=str)
        raise ToolFailed(text[:1500]) from None
    except ValidationError as exc:
        msg = exc.errors()[0].get("msg", "invalid") if exc.errors() else "invalid"
        raise ToolFailed("studio rejected the request: " + str(msg)[:400]) from None
    if isinstance(result, str):
        return result[:20000]
    return json.dumps(result, default=str)[:20000]


def workspace_dir(raw: str) -> str:
    """Absolute project directory inside the sandbox, for Developer Studio roots."""
    from automoto import sandbox
    from automoto.tools import ToolFailed

    text = (raw or ".").strip() or "."
    try:
        path = sandbox.resolve(text, allow_outside=False)
    except sandbox.SandboxError as exc:
        raise ToolFailed(str(exc)) from None
    if not path.is_dir():
        raise ToolFailed(f"not a project folder: {text}")
    return str(path)


def load_studios() -> list[StudioSpec]:
    """Discover studio specs. Failures are logged; one bad module does not stop the rest."""
    found: dict[str, StudioSpec] = {}
    for path in [*_package_files(), *_env_files()]:
        spec = _cached(path, external=not _is_package_file(path))
        if spec is None:
            continue
        if spec.id in found:
            log.warning("duplicate studio id %s from %s; keeping the first", spec.id, path.name)
            continue
        found[spec.id] = spec
    for spec in _from_entry_points():
        if spec.id in found:
            log.warning("duplicate studio id %s from an entry point; keeping the file", spec.id)
            continue
        found[spec.id] = spec
    for spec in list(_manual):
        if spec.id not in found:
            found[spec.id] = spec
    return list(found.values())


def collect_tools(*, local_apps: bool = True, existing: set[str] | None = None) -> list[Any]:
    """Tools for ``tools.build``, after central safety filters."""
    from automoto import local_llm
    from automoto.tools import Tool

    offline = local_llm.offline()
    seen = set(existing or ())
    out: list[Any] = []
    for spec in load_studios():
        try:
            if spec.needs_local_apps and not local_apps:
                continue
            for tool in spec.tools:
                name = tool.name
                if name in spec.host_exec and not local_apps:
                    continue
                if name in spec.online_only and offline:
                    continue
                if name in seen:
                    log.warning("studio %s tool %s collides with an existing tool; skipped", spec.id, name)
                    continue
                level = _level(spec, tool)
                out.append(Tool(name, tool.description, tool.parameters, level, tool.fn, f"studio:{spec.id}", False))
                seen.add(name)
        except Exception:
            log.exception("skipping studio %s while building tools", getattr(spec, "id", "?"))
    return out


def hosted_groups() -> set[str]:
    """Tool groups a hosted server may expose. Studios must opt in with ``hosted_ok``."""
    groups = set()
    for spec in load_studios():
        if spec.hosted_ok and not spec.needs_local_apps:
            groups.add(f"studio:{spec.id}")
    return groups


def hosted_blocked() -> set[str]:
    """Tool names that stay off hosted servers even if the studio is otherwise allowed."""
    names: set[str] = set()
    for spec in load_studios():
        if not spec.hosted_ok or spec.needs_local_apps:
            names.update(t.name for t in spec.tools)
            continue
        names.update(spec.host_exec)
        names.update(spec.local_only)
    return names


def _level(spec: StudioSpec, tool: Any) -> str:
    level = tool.level if tool.level in ("safe", "risky", "blocked") else "risky"
    if tool.name in spec.host_exec and level == "safe":
        log.warning("studio %s tool %s runs a program; registry requires approval", spec.id, tool.name)
        level = "risky"
    mutating = bool(_MUTATING.search(tool.name)) and tool.name not in spec.reads_only
    if mutating and level == "safe":
        log.warning("studio %s tool %s changes data; registry requires approval", spec.id, tool.name)
        level = "risky"
    if spec.approval not in ("safe", "risky"):
        log.warning("studio %s has approval %r; mutating tools stay risky", spec.id, spec.approval)
    return level


def _package_files() -> list[Path]:
    root = Path(__file__).resolve().parent
    return sorted(p for p in root.glob("*_studio_tools.py") if p.is_file())


def _is_package_file(path: Path) -> bool:
    return path.resolve().parent == Path(__file__).resolve().parent


def _env_files() -> list[Path]:
    raw = os.environ.get("AUTOMOTO_STUDIO_PATH", "")
    found: list[Path] = []
    for part in raw.split(os.pathsep):
        if not part.strip():
            continue
        folder = Path(part).expanduser()
        if folder.is_dir():
            found.extend(sorted(p for p in folder.glob("*_studio_tools.py") if p.is_file()))
        elif folder.is_file() and folder.name.endswith("_studio_tools.py"):
            found.append(folder)
    return found


def _cached(path: Path, *, external: bool) -> StudioSpec | None:
    try:
        key = (str(path.resolve()), path.stat().st_mtime_ns)
    except OSError:
        log.warning("skipping studio module %s: unreadable", path)
        return None
    if key in _cache:
        return _cache[key]
    try:
        if external:
            mod = _load_external(path, key[1])
        else:
            mod = importlib.import_module("automoto." + path.stem)
        spec = _spec_from_module(mod)
        if spec is None:
            log.warning("skipping studio module %s: it does not define STUDIO", path.name)
            _cache[key] = None
            return None
        _validate(spec)
    except Exception:
        log.exception("skipping broken studio module %s", path.name)
        _cache[key] = None
        return None
    _cache[key] = spec
    return spec


def _load_external(path: Path, stamp: int) -> Any:
    name = f"automoto_ext_studio_{path.stem}_{stamp}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _spec_from_module(module: Any) -> StudioSpec | None:
    studio = getattr(module, "STUDIO", None)
    if callable(studio):
        studio = studio()
    return studio if isinstance(studio, StudioSpec) else None


def _validate(spec: StudioSpec) -> None:
    if not _ID.fullmatch(spec.id):
        raise ValueError(f"studio id {spec.id!r} must be a short lowercase slug")
    names = [t.name for t in spec.tools]
    if len(names) != len(set(names)):
        raise ValueError(f"studio {spec.id} repeats a tool name")
    re.compile(spec.words)


def _entry_point_objects() -> list[Any]:
    from importlib.metadata import entry_points

    try:
        return list(entry_points(group="automoto.studios"))
    except TypeError:  # pragma: no cover - importlib on very old interpreters
        return list(entry_points().get("automoto.studios", []))


def _from_entry_points() -> list[StudioSpec]:
    try:
        points = _entry_point_objects()
    except Exception:
        log.exception("skipping studio entry points")
        return []
    out: list[StudioSpec] = []
    for ep in points:
        try:
            loaded = ep.load()
            spec = loaded() if callable(loaded) else loaded
            if not isinstance(spec, StudioSpec):
                log.warning("skipping entry point %s: it did not return a StudioSpec", getattr(ep, "name", ep))
                continue
            _validate(spec)
            out.append(spec)
        except Exception:
            log.exception("skipping broken studio entry point %s", getattr(ep, "name", ep))
    return out
