"""iPhone mode for phone control: a WebDriverAgent (WDA) server on this computer.

WDA is the helper app iPhone test tools use. The person starts it, either in the iOS
Simulator or on a USB iPhone with port 8100 forwarded, and AutoMoto talks to it over
HTTP. The host is always 127.0.0.1. Only the port can change, through
``AUTOMOTO_WDA_PORT`` in the real environment, so nothing here can reach another
machine. The safety rules and grant in ``developer_phone`` apply unchanged.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from typing import Any

from fastapi import HTTPException

from automoto import config

PREFIX = "iphone:"
TIMEOUT = 20
BUNDLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]*(?:\.[A-Za-z0-9][A-Za-z0-9\-]*)+$")
TAPPABLE = {"Button", "Cell", "Link", "Switch", "Tab", "MenuItem", "Icon", "SegmentedControl", "Key"}
FIELDS = {"TextField", "SecureTextField", "SearchField", "TextView"}
SCROLLS = {"ScrollView", "Table", "CollectionView"}
SKIP = {"Application", "Window", "Other", "Group"}
KEYS = {"enter": "\n", "delete": "\b", "tab": "\t"}
BUILT_IN = ["com.apple.Preferences", "com.apple.mobilesafari", "com.apple.MobileSMS", "com.apple.mobilemail",
            "com.apple.mobilecal", "com.apple.camera", "com.apple.mobileslideshow", "com.apple.Maps"]
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_session: dict[str, str] = {}


def port() -> int:
    raw = (config.env_trusted("AUTOMOTO_WDA_PORT") or "8100").strip()
    value = int(raw) if raw.isdigit() else 8100
    return value if 1024 <= value <= 65535 else 8100


def serial() -> str:
    return f"{PREFIX}{port()}"


def is_iphone(device: str) -> bool:
    return device.startswith(PREFIX)


def _request(method: str, path: str, body: Any = None, *, timeout: float = TIMEOUT) -> Any:
    url = f"http://127.0.0.1:{port()}{path}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with _NO_PROXY.open(request, timeout=timeout) as response:  # nosec B310 - fixed loopback host
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            detail = json.loads(raw or b"{}").get("value", {})
        except (ValueError, AttributeError):
            detail = {}
        message = (detail.get("message") or detail.get("error") or "") if isinstance(detail, dict) else ""
        raise HTTPException(409 if exc.code != 404 else 404, "The iPhone refused the command. " + str(message)[:300]) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise HTTPException(409, "WebDriverAgent is not answering. Start it again, then press Refresh.") from None
    try:
        return json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(502, "WebDriverAgent sent an unreadable answer.") from None


def probe() -> dict[str, str] | None:
    """The iPhone or Simulator behind WDA, or None. Called by every status check, so it is quick."""
    try:
        value = _request("GET", "/status", timeout=1.5).get("value") or {}
    except HTTPException:
        return None
    os_info = value.get("os") or {}
    device = str(value.get("device") or "iphone").replace("_", " ")
    model = f"{device[:1].upper()}{device[1:]} (iOS {os_info.get('version', '?')})"
    if os_info.get("name") and os_info["name"] != "iOS":
        model = f"{device} ({os_info['name']} {os_info.get('version', '')})".strip()
    if (value.get("ios") or {}).get("simulatorVersion"):
        model += " Simulator"
    return {"serial": serial(), "state": "device", "model": model[:60], "kind": "iphone"}


def _sid(fresh: bool = False) -> str:
    if fresh or "id" not in _session:
        reply = _request("POST", "/session", {"capabilities": {"alwaysMatch": {}}})
        sid = reply.get("sessionId") or (reply.get("value") or {}).get("sessionId")
        if not sid or not re.fullmatch(r"[A-Za-z0-9\-]{1,80}", str(sid)):
            raise HTTPException(502, "WebDriverAgent did not start a session.")
        _session["id"] = str(sid)
    return _session["id"]


def _call(method: str, path: str, body: Any = None) -> Any:
    """A session call. A stale session (WDA restarted) is replaced once."""
    try:
        return _request(method, f"/session/{_sid()}{path}", body)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return _request(method, f"/session/{_sid(fresh=True)}{path}", body)


def reset() -> None:
    _session.clear()


# -- screen ------------------------------------------------------------------------
def parse_source(tree: dict[str, Any], limit: int) -> tuple[str, list[dict[str, Any]]]:
    app = str(tree.get("label") or tree.get("name") or "")
    items: list[dict[str, Any]] = []
    stack = [tree]
    while stack and len(items) < limit:
        node = stack.pop()
        stack.extend(reversed(node.get("children") or []))
        kind = str(node.get("type", "")).removeprefix("XCUIElementType")
        rect = node.get("rect") or {}
        try:
            x, y, w, h = (int(float(rect.get(k, 0))) for k in ("x", "y", "width", "height"))
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0 or str(node.get("isVisible", "1")) in ("0", "False", "false"):
            continue
        label = str(node.get("label") or node.get("name") or node.get("value") or "").strip().replace("\n", " ")[:120]
        tap, field, scroll = kind in TAPPABLE, kind in FIELDS, kind in SCROLLS
        if kind in SKIP or not (label or tap or field or scroll):
            continue
        items.append({"n": len(items) + 1, "label": label, "kind": kind, "tap": tap, "field": field,
                      "scroll": scroll, "password": kind == "SecureTextField", "focused": False,
                      "x": x + w // 2, "y": y + h // 2})
    return app, items


def dump(limit: int) -> tuple[str, list[dict[str, Any]]]:
    tree = _request("GET", "/source?format=json").get("value")
    if not isinstance(tree, dict):
        raise HTTPException(502, "The iPhone sent an unreadable screen. Try again.")
    return parse_source(tree, limit)


def active_field() -> dict[str, str] | None:
    """The selected text box (``kind``, ``label``) or None when nothing is selected."""
    try:
        value = _call("GET", "/element/active").get("value") or {}
    except HTTPException:
        return None
    element = value.get("ELEMENT") or next((v for k, v in value.items() if k.startswith("element-")), "")
    if not element or not re.fullmatch(r"[A-Za-z0-9\-]{1,80}", str(element)):
        return None
    kind = str(_call("GET", f"/element/{element}/attribute/type").get("value") or "").removeprefix("XCUIElementType")
    label = str(_call("GET", f"/element/{element}/attribute/label").get("value") or "")
    return {"kind": kind, "label": label[:60]} if kind in FIELDS else None


# -- actions -----------------------------------------------------------------------
def _touch(*moves: tuple[int, int, int]) -> None:
    (x0, y0, _), *rest = moves
    steps: list[dict[str, Any]] = [{"type": "pointerMove", "duration": 0, "x": x0, "y": y0},
                                   {"type": "pointerDown", "button": 0}]
    steps += [{"type": "pointerMove", "duration": ms, "x": x, "y": y} for x, y, ms in rest] or [{"type": "pause", "duration": 80}]
    steps.append({"type": "pointerUp", "button": 0})
    _call("POST", "/actions", {"actions": [{"type": "pointer", "id": "finger1",
                                            "parameters": {"pointerType": "touch"}, "actions": steps}]})


def tap(x: int, y: int) -> None:
    _touch((x, y, 0))


def swipe(x1: int, y1: int, x2: int, y2: int) -> None:
    _touch((x1, y1, 0), (x2, y2, 300))


def size() -> tuple[int, int]:
    value = _call("GET", "/window/size").get("value") or {}
    return int(value.get("width") or 390), int(value.get("height") or 844)


def type_text(text: str) -> None:
    _call("POST", "/wda/keys", {"value": list(text)})


def key(name: str) -> None:
    if name == "home":
        _request("POST", "/wda/homescreen")
    elif name in KEYS:
        type_text(KEYS[name])
    else:
        raise HTTPException(422, "iPhones have no Back or Recents button. Tap Back on the screen, or press home.")


def launch(bundle_id: str) -> None:
    if not BUNDLE.fullmatch(bundle_id):
        raise HTTPException(422, "Use the app's bundle ID, for example com.apple.Preferences.")
    _call("POST", "/wda/apps/launch", {"bundleId": bundle_id})


def screenshot() -> bytes:
    data = _request("GET", "/screenshot").get("value") or ""
    try:
        png = base64.b64decode(data, validate=True)
    except ValueError:
        png = b""
    if not png.startswith(b"\x89PNG"):
        raise HTTPException(502, "The iPhone did not send a picture.")
    return png


def apps() -> dict[str, Any]:
    from automoto import developer_ios, sandbox

    mine = []
    for project in sorted((sandbox.default_root() / "apps").glob("*")):
        for name in ("automoto-ios.yml", "xtool.yml"):
            file = project / name
            match = developer_ios._BUNDLE.search(file.read_text("utf-8")) if file.is_file() else None
            if match:
                mine.append(match.group(1))
                break
    return {"your_apps": mine[:50], "built_in": BUILT_IN,
            "note": "iPhones do not share the full app list. Use a bundle ID from here, or the one in Xcode under Signing."}
