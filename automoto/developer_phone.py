"""Developer Studio phone control: an Android phone driven over adb.

The assistant reads the screen as text (the accessibility tree) and can tap, type,
scroll, press keys and open apps. Nothing is installed on the phone.

Safety:
* Local only. Hosted servers refuse every route.
* Control is off until the person presses "Turn on phone control" in the panel. The
  grant is for one phone, ends after ``GRANT_SECONDS``, and the assistant cannot press
  the button (agent calls never carry the approval header).
* adb comes from PATH, the Android SDK, or ``AUTOMOTO_ADB`` in the real environment
  (a project ``.env`` cannot point it elsewhere). It is never downloaded.
* Arguments are fixed lists, never a host shell. Typed text is quoted for the phone's
  shell. Typing into a password field is refused.
* Each action is one line in ``phone-audit.jsonl``; typed text is logged as a length.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Literal

from defusedxml import ElementTree as SafeXML
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from automoto import config

router = APIRouter(prefix="/api/developer/studio/phone", tags=["developer-phone"])

APPROVAL_HEADER = "X-Automoto-Phone-Approval"
GRANT_SECONDS = 30 * 60
TIMEOUT = 20
MAX_ELEMENTS = 150
MAX_TYPE = 500
DUMP = "/data/local/tmp/automoto-ui.xml"
SERIAL = r"^[A-Za-z0-9._:\-]{1,80}$"
PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")
BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
KEYS = {"back": 4, "home": 3, "recents": 187, "enter": 66, "delete": 67, "tab": 61}
ENV_KEEP = ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR",
            "ANDROID_HOME", "ANDROID_SDK_ROOT", "ANDROID_USER_HOME", "ADB_VENDOR_KEYS")

_LOCK = threading.Lock()
_grant: dict[str, Any] = {}
_last: dict[str, Any] = {}


class ConnectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    serial: str = Field(pattern=SERIAL)
    confirmed: Literal[True]
    understood_screen_access: Literal[True]


class TapIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(default="", max_length=200)
    element: int = Field(default=0, ge=0, le=MAX_ELEMENTS)
    x: int = Field(default=-1, ge=-1, le=20000)
    y: int = Field(default=-1, ge=-1, le=20000)


class TypeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=MAX_TYPE)


class ScrollIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: Literal["up", "down", "left", "right"]


class KeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: Literal["back", "home", "recents", "enter", "delete", "tab"]


class OpenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package: str = Field(min_length=3, max_length=200)


# -- plumbing ----------------------------------------------------------------------
def _auth(request: Request) -> None:
    from automoto import server
    server._authorise(request, local_only=True)


def _button_pressed(request: Request) -> bool:
    if getattr(request.state, "automoto_agent_call", False):
        return False
    return request.headers.get(APPROVAL_HEADER) == "1"


def adb_path() -> str:
    override = (config.env_trusted("AUTOMOTO_ADB") or "").strip()
    if override:
        return override
    found = shutil.which("adb")
    if found:
        return found
    exe = "adb.exe" if os.name == "nt" else "adb"
    for name in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        sdk = (os.environ.get(name) or "").strip()
        candidate = Path(sdk) / "platform-tools" / exe if sdk else None
        if candidate and candidate.is_file():
            return str(candidate)
    return ""


def _adb(args: list[str], serial: str = "", *, timeout: int = TIMEOUT) -> bytes:
    binary = adb_path()
    if not binary:
        raise HTTPException(409, "adb is not installed. Install Android SDK Platform-Tools, then press Refresh.")
    argv = [binary, *(["-s", serial] if serial else []), *args]
    env = {k: v for k, v in os.environ.items() if k.upper() in ENV_KEEP}
    try:
        done = subprocess.run(argv, capture_output=True, timeout=timeout, check=False, env=env,
                              stdin=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "The phone did not answer in time. Check the cable and that it is unlocked.") from None
    except OSError:
        raise HTTPException(409, "adb could not be started.") from None
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or b"").decode("utf-8", "replace").strip()[-300:]
        raise HTTPException(409, "The phone refused the command. " + tail)
    return done.stdout or b""


def _audit(action: str, **extra: Any) -> None:
    from automoto import home, redaction

    line = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "action": action,
            **{k: v for k, v in extra.items() if isinstance(v, (str, int, bool))}}
    try:
        path = home.home() / "phone-audit.jsonl"
        if path.exists() and path.stat().st_size > 2_000_000:
            os.replace(path, path.with_suffix(".jsonl.1"))
        with open(path, "a", encoding="utf-8") as f:
            f.write(redaction.redact(json.dumps(line, ensure_ascii=False)) + "\n")
    except OSError:
        pass


def list_devices() -> list[dict[str, str]]:
    out = _adb(["devices", "-l"]).decode("utf-8", "replace")
    found = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2 or not re.fullmatch(SERIAL, parts[0]):
            continue
        extra = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
        found.append({"serial": parts[0], "state": parts[1],
                      "model": extra.get("model", "").replace("_", " ")[:60]})
    return found


def _grant_state() -> dict[str, Any]:
    with _LOCK:
        if _grant and _grant["until"] <= time.time():
            _grant.clear()
            _last.clear()
        if not _grant:
            return {"on": False}
        return {"on": True, "serial": _grant["serial"], "model": _grant.get("model", ""),
                "minutes_left": max(1, int((_grant["until"] - time.time()) // 60))}


def active_serial() -> str:
    state = _grant_state()
    if not state["on"]:
        raise HTTPException(409, "Phone control is off. Ask the person to press Turn on phone control "
                                 "in Developer Studio. The assistant cannot turn it on.")
    return state["serial"]


# -- screen ------------------------------------------------------------------------
def parse_screen(xml: str) -> tuple[str, list[dict[str, Any]]]:
    try:
        root = SafeXML.fromstring(xml)
    except SafeXML.ParseError:
        raise HTTPException(502, "The phone sent an unreadable screen. Try again.") from None
    app, items = "", []
    for node in root.iter("node"):
        a = node.attrib
        app = app or a.get("package", "")
        box = BOUNDS.fullmatch(a.get("bounds", ""))
        if not box:
            continue
        x1, y1, x2, y2 = map(int, box.groups())
        if x2 <= x1 or y2 <= y1:
            continue
        label = (a.get("text") or a.get("content-desc") or "").strip().replace("\n", " ")[:120]
        kind = a.get("class", "").rsplit(".", 1)[-1]
        editable = "EditText" in kind
        clickable = a.get("clickable") == "true"
        scrollable = a.get("scrollable") == "true"
        if not label and not (clickable or editable or scrollable):
            continue
        if not label:
            label = a.get("resource-id", "").rsplit("/", 1)[-1][:60]
        items.append({"n": len(items) + 1, "label": label, "kind": kind,
                      "tap": clickable, "field": editable, "scroll": scrollable,
                      "password": a.get("password") == "true", "focused": a.get("focused") == "true",
                      "x": (x1 + x2) // 2, "y": (y1 + y2) // 2})
        if len(items) >= MAX_ELEMENTS:
            break
    return app, items


def _render(app: str, items: list[dict[str, Any]]) -> str:
    lines = [f"App: {app or 'unknown'}"]
    for it in items:
        tags = [t for t in ("tap", "field", "scroll", "password", "focused") if it[t]]
        lines.append(f'{it["n"]}. "{it["label"]}" {it["kind"]} [{", ".join(tags)}] at {it["x"]},{it["y"]}')
    return "\n".join(lines)


def _dump(serial: str) -> tuple[str, list[dict[str, Any]]]:
    raw = _adb(["exec-out", f"uiautomator dump {DUMP} >/dev/null && cat {DUMP}"], serial)
    text = raw.decode("utf-8", "replace")
    start = text.find("<?xml")
    app, items = parse_screen(text[start:] if start >= 0 else text)
    with _LOCK:
        _last.update({"serial": serial, "items": items})
    return app, items


def read_screen(serial: str) -> dict[str, Any]:
    app, items = _dump(serial)
    return {"app": app, "count": len(items), "screen": _render(app, items)}


def _find(items: list[dict[str, Any]], text: str) -> dict[str, Any]:
    want = text.strip().lower()
    exact = [it for it in items if it["label"].lower() == want]
    near = exact or [it for it in items if want in it["label"].lower()]
    if not near:
        raise HTTPException(404, f'"{text[:80]}" is not on the screen. Read the screen again.')
    return next((it for it in near if it["tap"]), near[0])


# -- actions -----------------------------------------------------------------------
def tap(body: TapIn) -> dict[str, Any]:
    serial = active_serial()
    if body.text:
        target = _find(_dump(serial)[1], body.text)
    elif body.element:
        with _LOCK:
            items = _last.get("items") if _last.get("serial") == serial else None
        if not items or body.element > len(items):
            raise HTTPException(409, "Read the screen first, then tap an element number from it.")
        target = items[body.element - 1]
    elif body.x >= 0 and body.y >= 0:
        target = {"label": "", "x": body.x, "y": body.y}
    else:
        raise HTTPException(422, "Give the text to tap, an element number, or x and y.")
    _adb(["shell", "input", "tap", str(target["x"]), str(target["y"])], serial)
    _audit("tap", serial=serial, x=target["x"], y=target["y"], label=target["label"][:60])
    return {"ok": True, "tapped": target["label"] or f'{target["x"]},{target["y"]}',
            "message": "Tapped. Read the screen to see what changed."}


def encode_text(text: str) -> str:
    if any(not (32 <= ord(ch) < 127) for ch in text):
        raise HTTPException(422, "Only plain English letters, numbers and symbols can be typed (no emoji or accents).")
    return shlex.quote(text.replace(" ", "%s"))


def type_text(body: TypeIn) -> dict[str, Any]:
    serial = active_serial()
    encoded = encode_text(body.text)
    focused = next((it for it in _dump(serial)[1] if it["focused"] and it["field"]), None)
    if focused is None:
        raise HTTPException(409, "No text box is selected. Tap the text box first.")
    if focused["password"]:
        raise HTTPException(403, "That is a password box. The person must type passwords themselves.")
    _adb(["shell", "input", "text", encoded], serial)
    _audit("type", serial=serial, field=focused["label"][:60], length=len(body.text))
    return {"ok": True, "typed_characters": len(body.text), "into": focused["label"]}


def _size(serial: str) -> tuple[int, int]:
    out = _adb(["shell", "wm", "size"], serial).decode("utf-8", "replace")
    sizes = re.findall(r"(\d+)x(\d+)", out)
    if not sizes:
        return 1080, 1920
    w, h = sizes[-1]  # an "Override size" line comes last and wins
    return int(w), int(h)


def scroll(body: ScrollIn) -> dict[str, Any]:
    serial = active_serial()
    w, h = _size(serial)
    cx, cy, dx, dy = w // 2, h // 2, w * 3 // 10, h * 3 // 10
    # "down" shows what is further down, so the finger moves up.
    moves = {"down": (cx, cy + dy, cx, cy - dy), "up": (cx, cy - dy, cx, cy + dy),
             "right": (cx + dx, cy, cx - dx, cy), "left": (cx - dx, cy, cx + dx, cy)}
    _adb(["shell", "input", "swipe", *map(str, moves[body.direction]), "300"], serial)
    _audit("scroll", serial=serial, direction=body.direction)
    return {"ok": True, "scrolled": body.direction}


def press_key(body: KeyIn) -> dict[str, Any]:
    serial = active_serial()
    _adb(["shell", "input", "keyevent", str(KEYS[body.key])], serial)
    _audit("key", serial=serial, key=body.key)
    return {"ok": True, "pressed": body.key}


def open_app(body: OpenIn) -> dict[str, Any]:
    serial = active_serial()
    if not PACKAGE.fullmatch(body.package):
        raise HTTPException(422, "Use the app's package name, for example com.android.settings.")
    out = _adb(["shell", "monkey", "-p", body.package, "-c", "android.intent.category.LAUNCHER", "1"], serial)
    if b"No activities found" in out:
        raise HTTPException(404, "That app is not installed or cannot be opened.")
    _audit("open", serial=serial, package=body.package)
    return {"ok": True, "opened": body.package}


def apps() -> dict[str, Any]:
    serial = active_serial()
    out = _adb(["shell", "pm", "list", "packages", "-3"], serial).decode("utf-8", "replace")
    names = sorted(line.removeprefix("package:").strip() for line in out.splitlines() if line.startswith("package:"))
    return {"apps": names[:300], "note": "Installed apps you added. System apps such as com.android.settings also open."}


def status() -> dict[str, Any]:
    binary = adb_path()
    devices = list_devices() if binary else []
    return {"adb": bool(binary), "devices": devices, "control": _grant_state(),
            "steps": ["On the phone, open Settings, About phone, and tap Build number 7 times.",
                      "Open Developer options and turn on USB debugging.",
                      "Plug the phone in, unlock it and tap Allow on the USB debugging prompt.",
                      "Press Refresh, tick the box and press Turn on phone control."]}


# -- routes ------------------------------------------------------------------------
@router.get("/status")
def status_route(request: Request):
    _auth(request)
    return status()


@router.post("/connect")
def connect(request: Request, body: ConnectIn):
    _auth(request)
    if not _button_pressed(request):
        raise HTTPException(403, "Phone control needs the button in Developer Studio. The assistant cannot press it.")
    device = next((d for d in list_devices() if d["serial"] == body.serial), None)
    if device is None or device["state"] != "device":
        raise HTTPException(409, "That phone is not ready. Unlock it and tap Allow on the USB debugging prompt.")
    with _LOCK:
        _grant.clear()
        _last.clear()
        _grant.update({"serial": body.serial, "model": device["model"], "until": time.time() + GRANT_SECONDS})
    _audit("control_on", serial=body.serial)
    return _grant_state()


@router.post("/disconnect")
def disconnect(request: Request):
    _auth(request)
    with _LOCK:
        serial = _grant.get("serial", "")
        _grant.clear()
        _last.clear()
    if serial:
        _audit("control_off", serial=serial)
    return {"on": False}


@router.get("/screen")
def screen_route(request: Request):
    _auth(request)
    return read_screen(active_serial())


@router.get("/screenshot")
def screenshot(request: Request):
    _auth(request)
    if getattr(request.state, "automoto_agent_call", False):
        raise HTTPException(403, "Screenshots are for the panel only.")
    png = _adb(["exec-out", "screencap", "-p"], active_serial())
    if not png.startswith(b"\x89PNG"):
        raise HTTPException(502, "The phone did not send a picture.")
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/apps")
def apps_route(request: Request):
    _auth(request)
    return apps()


@router.post("/tap")
def tap_route(request: Request, body: TapIn):
    _auth(request)
    return tap(body)


@router.post("/type")
def type_route(request: Request, body: TypeIn):
    _auth(request)
    return type_text(body)


@router.post("/scroll")
def scroll_route(request: Request, body: ScrollIn):
    _auth(request)
    return scroll(body)


@router.post("/key")
def key_route(request: Request, body: KeyIn):
    _auth(request)
    return press_key(body)


@router.post("/open")
def open_route(request: Request, body: OpenIn):
    _auth(request)
    return open_app(body)
