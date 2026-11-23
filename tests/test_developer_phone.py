"""Phone control: button-only grant, screen reading, actions and their refusals, with a fake adb."""

from __future__ import annotations

import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from automoto import developer_phone, loop, planner, server, studio_registry, tenancy
from automoto import phone_studio_tools as tools
from automoto.tools import ToolContext, ToolFailed

BASE = "/api/developer/studio/phone"
AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BUTTON = {**AUTH, developer_phone.APPROVAL_HEADER: "1"}
CTX = ToolContext()
SCREEN = """UI hierchary dumped to: /data/local/tmp/automoto-ui.xml<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
 <node text="" class="android.widget.FrameLayout" package="com.example.chat" clickable="false" bounds="[0,0][1080,2400]">
  <node text="Hello &amp; welcome" class="android.widget.TextView" package="com.example.chat" bounds="[40,200][1040,300]" />
  <node text="Send" class="android.widget.Button" package="com.example.chat" clickable="true" bounds="[880,2200][1040,2300]" />
  <node text="" content-desc="Attach" class="android.widget.ImageButton" package="com.example.chat" clickable="true" bounds="[40,2200][140,2300]" />
  <node text="Message" class="android.widget.EditText" package="com.example.chat" clickable="true" focused="FOCUS" password="PASS" bounds="[160,2200][860,2300]" />
  <node text="" class="android.view.View" package="com.example.chat" bounds="[0,0][10,10]" />
 </node>
</hierarchy>"""


class FakeAdb:
    def __init__(self):
        self.calls: list[list[str]] = []
        self.devices = "List of devices attached\nR58N123 device product:x model:Pixel_8 device:y\nEMU1 unauthorized\n"
        self.focused, self.password = "true", "false"

    def __call__(self, argv, **kwargs):
        args = argv[3:] if argv[1:2] == ["-s"] else argv[1:]
        self.calls.append(args)
        out = b""
        if args[:1] == ["devices"]:
            out = self.devices.encode()
        elif args[:1] == ["exec-out"] and "uiautomator" in args[1]:
            out = SCREEN.replace("FOCUS", self.focused).replace("PASS", self.password).encode()
        elif args[:1] == ["exec-out"]:
            out = b"\x89PNG fake"
        elif args[:3] == ["shell", "wm", "size"]:
            out = b"Physical size: 1080x2400\n"
        elif args[:3] == ["shell", "pm", "list"]:
            out = b"package:com.zeta\npackage:com.alpha\n"
        elif args[:2] == ["shell", "monkey"] and args[3] == "com.missing.app":
            out = b"** No activities found to run, monkey aborted."
        return subprocess.CompletedProcess(argv, 0, out, b"")

    def actions(self):
        return [c for c in self.calls if c[:2] == ["shell", "input"] or c[:2] == ["shell", "monkey"]]


@pytest.fixture
def adb(monkeypatch):
    fake = FakeAdb()
    monkeypatch.setenv("AUTOMOTO_ADB", "adb-fake")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.setattr(developer_phone.subprocess, "run", fake)
    monkeypatch.setattr(developer_phone.wda, "probe", lambda: None)
    developer_phone._grant.clear()
    developer_phone._last.clear()
    yield fake
    developer_phone._grant.clear()
    developer_phone._last.clear()


@pytest.fixture
def client(adb, tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(tmp_path / "data"))
    return TestClient(server.app)


def _on(client, serial="R58N123"):
    r = client.post(BASE + "/connect", headers=BUTTON,
                    json={"serial": serial, "confirmed": True, "understood_screen_access": True})
    assert r.status_code == 200, r.text
    return r.json()


def test_status_lists_phones_and_control_is_off(client):
    data = client.get(BASE + "/status", headers=AUTH).json()
    assert data["adb"] is True and data["control"] == {"on": False}
    assert [(d["serial"], d["state"], d["model"]) for d in data["devices"]] == [
        ("R58N123", "device", "Pixel 8"), ("EMU1", "unauthorized", "")]


def test_tools_refuse_until_the_person_presses_the_button(client, adb):
    with pytest.raises(ToolFailed, match="Turn on phone control"):
        tools.phone_screen(CTX)
    with pytest.raises(ToolFailed, match="Turn on phone control"):
        tools.phone_tap(CTX, text="Send")
    assert adb.actions() == []


def test_connect_needs_the_button_header_and_a_ready_phone(client):
    body = {"serial": "R58N123", "confirmed": True, "understood_screen_access": True}
    assert client.post(BASE + "/connect", headers=AUTH, json=body).status_code == 403
    assert client.post(BASE + "/connect", headers=BUTTON, json={**body, "serial": "EMU1"}).status_code == 409
    assert client.post(BASE + "/connect", headers=BUTTON, json={**body, "confirmed": False}).status_code == 422


def test_agent_call_cannot_press_the_button(client):
    request = studio_registry.studio_request("POST")
    request.scope["headers"].append((developer_phone.APPROVAL_HEADER.lower().encode(), b"1"))
    body = developer_phone.ConnectIn(serial="R58N123", confirmed=True, understood_screen_access=True)
    with pytest.raises(ToolFailed, match="cannot press"):
        studio_registry.call_studio(developer_phone.connect, request, body)


def test_screen_is_read_as_numbered_text(client):
    state = _on(client)
    assert state["on"] and state["model"] == "Pixel 8"
    data = json.loads(tools.phone_screen(CTX))
    screen = data["screen"]
    assert data["count"] == 4 and "App: com.example.chat" in screen
    assert '"Hello & welcome" TextView' in screen
    assert '"Send" Button [tap] at 960,2250' in screen
    assert '"Attach" ImageButton [tap]' in screen
    assert "View" not in screen.replace("TextView", "")  # empty, non-interactive nodes are dropped


def test_tap_by_text_element_and_position(client, adb):
    _on(client)
    assert '"tapped": "Send"' in tools.phone_tap(CTX, text="send")
    tools.phone_screen(CTX)
    assert '"tapped": "Attach"' in tools.phone_tap(CTX, element=3)
    tools.phone_tap(CTX, x=5, y=6)
    assert adb.actions() == [["shell", "input", "tap", "960", "2250"],
                             ["shell", "input", "tap", "90", "2250"],
                             ["shell", "input", "tap", "5", "6"]]
    with pytest.raises(ToolFailed, match="not on the screen"):
        tools.phone_tap(CTX, text="Delete account")


def test_typed_text_is_quoted_for_the_phone_shell(client, adb):
    _on(client)
    tools.phone_type(CTX, text="hi there; rm -rf / $(id)")
    assert adb.actions()[-1] == ["shell", "input", "text", "'hi%sthere;%srm%s-rf%s/%s$(id)'"]
    assert developer_phone.encode_text("it's") == "'it'\"'\"'s'"
    with pytest.raises(ToolFailed, match="plain English"):
        tools.phone_type(CTX, text="café")


def test_typing_refuses_password_boxes_and_needs_a_selected_box(client, adb):
    _on(client)
    adb.password = "true"
    with pytest.raises(ToolFailed, match="password"):
        tools.phone_type(CTX, text="hunter2")
    adb.password, adb.focused = "false", "false"
    with pytest.raises(ToolFailed, match="Tap the text box"):
        tools.phone_type(CTX, text="hello")
    assert not any(c[:3] == ["shell", "input", "text"] for c in adb.calls)


def test_scroll_keys_apps_and_open(client, adb):
    _on(client)
    tools.phone_scroll(CTX, direction="down")
    tools.phone_key(CTX, key="back")
    assert '"apps": ["com.alpha", "com.zeta"]' in tools.phone_apps(CTX)
    tools.phone_open(CTX, package="com.android.settings")
    assert adb.actions() == [
        ["shell", "input", "swipe", "540", "1920", "540", "480", "300"],
        ["shell", "input", "keyevent", "4"],
        ["shell", "monkey", "-p", "com.android.settings", "-c", "android.intent.category.LAUNCHER", "1"]]
    with pytest.raises(ToolFailed, match="package name"):
        tools.phone_open(CTX, package="com.x; reboot")
    with pytest.raises(ToolFailed, match="not installed"):
        tools.phone_open(CTX, package="com.missing.app")


def test_stop_and_expiry_turn_control_off(client, monkeypatch):
    _on(client)
    assert client.post(BASE + "/disconnect", headers=AUTH, json={}).json() == {"on": False}
    with pytest.raises(ToolFailed, match="Phone control is off"):
        tools.phone_key(CTX, key="home")
    _on(client)
    developer_phone._grant["until"] = 0
    with pytest.raises(ToolFailed, match="Phone control is off"):
        tools.phone_screen(CTX)


def test_screenshot_is_for_the_panel_only(client):
    _on(client)
    r = client.get(BASE + "/screenshot", headers=AUTH)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    with pytest.raises(ToolFailed, match="panel only"):
        studio_registry.call_studio(developer_phone.screenshot, studio_registry.studio_request("GET"))


def test_audit_never_logs_typed_text(client, tmp_path):
    from automoto import home

    _on(client)
    tools.phone_type(CTX, text="secret plan")
    log = (home.home() / "phone-audit.jsonl").read_text("utf-8")
    assert '"action": "type"' in log and '"length": 11' in log and "secret" not in log


def test_hosted_server_refuses_phone_control(client, monkeypatch):
    from automoto import hosted

    assert not {n for n in hosted.hosted_tools() if n.startswith("phone_")}
    monkeypatch.setattr(tenancy, "multiuser", lambda: True)
    assert client.get(BASE + "/status", headers=AUTH).status_code in (403, 404)
    with pytest.raises(ToolFailed, match="hosted"):
        tools.phone_status(CTX)


def test_registry_levels_planner_and_untrusted_output():
    studio_registry.reset()
    levels = {t.name: t.level for t in studio_registry.collect_tools() if t.group == "studio:phone"}
    assert levels == {"phone_status": "safe", "phone_screen": "safe", "phone_apps": "safe",
                      "phone_tap": "risky", "phone_type": "risky", "phone_scroll": "risky",
                      "phone_key": "risky", "phone_open": "risky"}
    assert not [t for t in studio_registry.collect_tools(local_apps=False) if t.group == "studio:phone"]
    assert "phone_tap" in studio_registry.hosted_blocked()
    assert "phone" in planner.classify("open whatsapp on my phone and read the last message")
    tool = next(t for t in studio_registry.collect_tools() if t.name == "phone_screen")
    assert loop.is_untrusted(tool)
