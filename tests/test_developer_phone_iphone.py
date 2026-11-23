"""Phone control, iPhone mode: a fake WebDriverAgent behind the same tools and grant."""

from __future__ import annotations

import base64
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from automoto import developer_phone, sandbox, server
from automoto import developer_phone_wda as wda
from automoto import phone_studio_tools as tools
from automoto.tools import ToolContext, ToolFailed

BASE = "/api/developer/studio/phone"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BUTTON = {**AUTH, developer_phone.APPROVAL_HEADER: "1"}
CTX = ToolContext()
PNG = b"\x89PNG\r\n\x1a\nfake"


def node(kind, label="", x=0, y=0, w=100, h=40, children=(), **extra):
    return {"type": f"XCUIElementType{kind}", "label": label, "rect": {"x": x, "y": y, "width": w, "height": h},
            "children": list(children), **extra}


TREE = node("Application", "Shop", 0, 0, 390, 844, [
    node("Window", "", 0, 0, 390, 844, [
        node("Other", "", 0, 0, 390, 844, [
            node("StaticText", "Welcome back", 20, 100, 350, 30),
            node("TextField", "Email", 20, 200, 350, 44),
            node("SecureTextField", "Password", 20, 260, 350, 44),
            node("Button", "Sign in", 20, 330, 350, 50),
            node("Button", "Hidden", 20, 400, 350, 50, isVisible="0"),
            node("Image", "", 0, 0, 10, 10),
        ]),
    ]),
])


class FakeWda:
    def __init__(self):
        self.calls: list[tuple[str, str, object]] = []
        self.active = {"type": "XCUIElementTypeTextField", "label": "Email"}
        self.sessions = 0
        self.expire_next = False

    def __call__(self, method, path, body=None, *, timeout=20):
        self.calls.append((method, path, body))
        if path == "/status":
            return {"value": {"os": {"name": "iOS", "version": "18.2"}, "device": "iphone",
                              "ios": {"simulatorVersion": "18.2"}}}
        if path == "/session":
            self.sessions += 1
            return {"value": {"sessionId": f"S{self.sessions}"}}
        if self.expire_next and path.startswith("/session/S1/"):
            self.expire_next = False
            raise HTTPException(404, "invalid session id")
        if path == "/source?format=json":
            return {"value": TREE}
        if path == "/screenshot":
            return {"value": base64.b64encode(PNG).decode()}
        if path.endswith("/element/active"):
            if not self.active:
                raise HTTPException(404, "no such element")
            return {"value": {"ELEMENT": "E-1"}}
        if path.endswith("/element/E-1/attribute/type"):
            return {"value": self.active["type"]}
        if path.endswith("/element/E-1/attribute/label"):
            return {"value": self.active["label"]}
        if path.endswith("/window/size"):
            return {"value": {"width": 390, "height": 844}}
        return {"value": None}

    def sent(self, suffix):
        return [body for _, path, body in self.calls if path.endswith(suffix)]


@pytest.fixture
def fake(monkeypatch, tmp_path):
    w = FakeWda()
    monkeypatch.setattr(wda, "_request", w)
    monkeypatch.setattr(developer_phone, "adb_path", lambda: "")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.delenv("AUTOMOTO_WDA_PORT", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(sandbox, "default_root", lambda: tmp_path / "work")
    developer_phone._grant.clear()
    developer_phone._last.clear()
    wda.reset()
    client = TestClient(server.app)
    r = client.post(BASE + "/connect", headers=BUTTON,
                    json={"serial": "iphone:8100", "confirmed": True, "understood_screen_access": True})
    assert r.status_code == 200, r.text
    w.client = client
    yield w
    developer_phone._grant.clear()
    wda.reset()


def taps(w):
    return [[(s["x"], s["y"]) for s in body["actions"][0]["actions"] if s["type"] == "pointerMove"]
            for body in w.sent("/actions")]


def test_status_lists_the_iphone_without_adb(fake):
    data = fake.client.get(BASE + "/status", headers=AUTH).json()
    assert data["adb"] is False
    assert data["devices"] == [{"serial": "iphone:8100", "state": "device", "kind": "iphone",
                                "model": "Iphone (iOS 18.2) Simulator"}]
    assert data["control"]["on"] and data["iphone_steps"]


def test_screen_reads_the_accessibility_tree(fake):
    data = json.loads(tools.phone_screen(CTX))
    assert data["screen"].splitlines() == [
        "App: Shop",
        '1. "Welcome back" StaticText [] at 195,115',
        '2. "Email" TextField [field] at 195,222',
        '3. "Password" SecureTextField [field, password] at 195,282',
        '4. "Sign in" Button [tap] at 195,355',
    ]


def test_tap_and_scroll_use_touch_actions(fake):
    assert '"tapped": "Sign in"' in tools.phone_tap(CTX, text="sign in")
    tools.phone_scroll(CTX, direction="down")
    assert taps(fake) == [[(195, 355)], [(195, 675), (195, 169)]]


def test_typing_allows_unicode_and_refuses_secure_or_missing_fields(fake):
    tools.phone_type(CTX, text="café ✓")
    assert fake.sent("/wda/keys") == [{"value": list("café ✓")}]
    fake.active = {"type": "XCUIElementTypeSecureTextField", "label": "Password"}
    with pytest.raises(ToolFailed, match="password"):
        tools.phone_type(CTX, text="hunter2")
    fake.active = None
    with pytest.raises(ToolFailed, match="Tap the text box"):
        tools.phone_type(CTX, text="hello")
    assert len(fake.sent("/wda/keys")) == 1


def test_keys_and_launch(fake):
    tools.phone_key(CTX, key="home")
    tools.phone_key(CTX, key="enter")
    assert fake.sent("/wda/homescreen") == [None] and fake.sent("/wda/keys") == [{"value": ["\n"]}]
    with pytest.raises(ToolFailed, match="no Back"):
        tools.phone_key(CTX, key="back")
    tools.phone_open(CTX, package="com.example.my-shop")
    assert fake.sent("/wda/apps/launch") == [{"bundleId": "com.example.my-shop"}]
    with pytest.raises(ToolFailed, match="bundle ID"):
        tools.phone_open(CTX, package="com.x/../../session")


def test_apps_lists_the_persons_iphone_projects(fake):
    from automoto import sandbox as sb

    project = sb.default_root() / "apps" / "my-shop"
    project.mkdir(parents=True)
    (project / "automoto-ios.yml").write_text("name: MyShop\nbundleID: com.ymm.MyShop\n", "utf-8")
    data = json.loads(tools.phone_apps(CTX))
    assert data["your_apps"] == ["com.ymm.MyShop"] and "com.apple.Preferences" in data["built_in"]


def test_a_restarted_agent_gets_a_new_session_once(fake):
    tools.phone_key(CTX, key="enter")
    fake.expire_next = True
    tools.phone_key(CTX, key="tab")
    assert fake.sessions == 2 and fake.sent("/wda/keys")[-1] == {"value": ["\t"]}


def test_screenshot_comes_back_as_png(fake):
    r = fake.client.get(BASE + "/screenshot", headers=AUTH)
    assert r.status_code == 200 and r.content == PNG


def test_tools_refuse_when_control_is_off(fake):
    fake.client.post(BASE + "/disconnect", headers=AUTH, json={})
    with pytest.raises(ToolFailed, match="Phone control is off"):
        tools.phone_tap(CTX, text="Sign in")
    assert fake.sent("/actions") == []


def test_port_only_from_the_real_environment(monkeypatch):
    monkeypatch.setenv("AUTOMOTO_WDA_PORT", "9100")
    assert wda.port() == 9100 and wda.serial() == "iphone:9100"
    for bad in ("80", "abc", "70000"):
        monkeypatch.setenv("AUTOMOTO_WDA_PORT", bad)
        assert wda.port() == 8100


def test_requests_only_go_to_loopback(monkeypatch):
    seen = []

    class Opener:
        def open(self, request, timeout):
            seen.append(request.full_url)
            raise OSError("down")

    monkeypatch.setattr(wda, "_NO_PROXY", Opener())
    assert wda.probe() is None
    assert seen == ["http://127.0.0.1:8100/status"]
