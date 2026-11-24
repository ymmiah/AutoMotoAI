"""V43 device and simulator tools: honest host diagnostics, explicit device verification, signing prerequisites."""
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from automoto import developer_devices as devices
from automoto import developer_phone as phone
from automoto import sandbox, server

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
URL = "/api/developer/studio/devices"
UDID = "0F1E2D3C-4B5A-6978-8796-A5B4C3D2E1F0"


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "userhome"
    home.mkdir()
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    for name in ("ANDROID_HOME", "ANDROID_SDK_ROOT", "ANDROID_AVD_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(phone, "adb_path", lambda: None)
    monkeypatch.setattr(devices, "_fixed", lambda argv: None)
    devices.VERIFIED.clear()
    root = sandbox.default_root() / "v43-app"
    root.mkdir(parents=True)
    return TestClient(server.app), root, home, monkeypatch


def host(monkeypatch, os_name, arch):
    monkeypatch.setattr(devices, "_host", lambda: os_name)
    monkeypatch.setattr(devices, "_arch", lambda: arch)


def make_sdk(home, abi="x86_64"):
    sdk = home / "Android" / "Sdk"
    (sdk / "emulator").mkdir(parents=True)
    (sdk / "emulator" / "emulator").write_text("")
    (sdk / "system-images" / "android-35" / "google_apis" / abi).mkdir(parents=True)
    (home / ".android" / "avd").mkdir(parents=True)
    (home / ".android" / "avd" / "Pixel_8.ini").write_text("")
    return sdk


def diagnose(client, root=None):
    params = {"project": str(root)} if root else {}
    response = client.get(URL + "/diagnose", params=params, headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()


def test_requires_session_token(env):
    client, *_ = env
    assert client.get(URL + "/diagnose").status_code in (401, 403)


def test_linux_arm64_emulator_is_unsupported_even_with_sdk(env):
    client, root, home, mp = env
    host(mp, "linux", "arm64")
    make_sdk(home, "arm64-v8a")
    data = diagnose(client)
    assert data["android_emulator"]["status"] == "unsupported_host"
    assert data["ios_simulator"]["status"] == "unsupported_host"
    assert data["anything_started"] is False and data["android_emulator"]["emulator_started"] is False


def test_windows_arm64_not_verified_and_windows_virtualization_not_checked(env):
    client, root, home, mp = env
    host(mp, "windows", "arm64")
    mp.setenv("LOCALAPPDATA", str(home))
    data = diagnose(client)
    assert data["android_emulator"]["status"] == "not_verified"
    assert data["virtualization"]["status"] == "not_checked"
    assert any(i["title"].startswith("Windows package signing") for i in data["signing"])


@pytest.mark.parametrize("make,expected", [(False, "missing"), (True, None)])
def test_linux_x86_emulator_never_ready_without_pieces_or_kvm(env, tmp_path, make, expected):
    client, root, home, mp = env
    host(mp, "linux", "x86_64")
    mp.setattr(devices, "KVM", tmp_path / "no-kvm")
    if make:
        make_sdk(home)
    data = diagnose(client)
    assert data["virtualization"]["status"] == "missing"
    if expected:
        assert data["android_emulator"]["status"] == "missing"
    else:
        assert data["android_emulator"]["status"] == "needs_setup"
        assert data["android_emulator"]["virtual_devices"] == ["Pixel_8"]
    assert data["android_emulator"]["status"] not in ("ready", "probably_ready")


def test_kvm_permission_gives_copyable_fix(env, tmp_path):
    client, root, home, mp = env
    host(mp, "linux", "x86_64")
    kvm = tmp_path / "kvm"
    kvm.write_text("")
    mp.setattr(devices, "KVM", kvm)
    mp.setattr(devices.os, "access", lambda path, mode: False if Path(path) == kvm else True)
    data = diagnose(client)
    assert data["virtualization"]["status"] == "needs_permission"
    assert data["virtualization"]["command"] == "sudo usermod -aG kvm $USER"


def test_emulator_ready_with_matching_image_and_warns_on_mismatch(env, tmp_path):
    client, root, home, mp = env
    host(mp, "linux", "x86_64")
    kvm = tmp_path / "kvm"
    kvm.write_text("")
    mp.setattr(devices, "KVM", kvm)
    mp.setattr(devices.os, "access", lambda path, mode: True)
    make_sdk(home, "x86_64")
    assert diagnose(client)["android_emulator"]["status"] == "ready"
    sdk = home / "Android" / "Sdk"
    (sdk / "system-images" / "android-35" / "google_apis" / "x86_64").rmdir()
    (sdk / "system-images" / "android-35" / "google_apis" / "arm64-v8a").mkdir()
    assert "image_warning" in diagnose(client)["android_emulator"]


def test_macos_without_xcode_is_missing_not_ready(env):
    client, root, home, mp = env
    host(mp, "macos", "arm64")
    mp.setattr(devices, "_developer_dir", lambda: None)
    data = diagnose(client)
    assert data["ios_simulator"]["status"] == "missing"
    assert data["virtualization"]["status"] == "ready"
    apple = next(i for i in data["signing"] if i["platform"] == "apple")
    assert apple["status"] == "missing"


def test_signing_hides_passwords_and_flags_keystores(env):
    client, root, home, mp = env
    host(mp, "linux", "x86_64")
    app = root / "app"
    app.mkdir()
    (app / "build.gradle.kts").write_text('android {\n  signingConfigs {\n    create("release") {\n'
                                          '      storePassword = "hunter2-secret"\n      keyPassword = System.getenv("KP")\n'
                                          '    }\n  }\n}\n')
    (app / "build.gradle").write_text("signingConfigs { release { keyPassword 'groovy-secret' } }\n")
    (app / "upload.jks").write_bytes(b"\x00binary")
    data = diagnose(client, root)
    text = str(data)
    assert "hunter2-secret" not in text and "groovy-secret" not in text
    release = next(i for i in data["signing"] if i["title"] == "Android release signing")
    assert release["status"] == "problem"
    assert {(f["path"], f["line"], f["setting"]) for f in release["findings"]} == {
        ("app/build.gradle.kts", 4, "storePassword"), ("app/build.gradle", 1, "keyPassword")}
    keys = next(i for i in data["signing"] if i["title"].startswith("Key and certificate"))
    assert keys["files"] == ["app/upload.jks"] and keys["contents_read"] is False


def test_signing_setup_without_hardcoded_password_is_ready(env):
    client, root, home, mp = env
    host(mp, "linux", "x86_64")
    (root / "build.gradle.kts").write_text('signingConfigs { create("release") { storePassword = System.getenv("SP") } }\n')
    (home / ".android").mkdir()
    (home / ".android" / "debug.keystore").write_bytes(b"x")
    data = diagnose(client, root)
    statuses = {i["title"]: i["status"] for i in data["signing"]}
    assert statuses["Android release signing"] == "ready" and statuses["Android debug signing"] == "ready"


def test_serial_ports_listed_never_opened(env, monkeypatch):
    client, root, home, mp = env
    host(mp, "linux", "x86_64")
    fake = [Path("/dev/ttyUSB0")]

    def glob(self, pattern):
        if self == Path("/dev"):
            return list(fake) if pattern == "ttyUSB*" else []
        return _orig_glob(self, pattern)
    mp.setattr(devices.Path, "glob", glob)
    mp.setattr(devices.os, "access", lambda path, mode: Path(path).as_posix() != "/dev/ttyUSB0")
    data = diagnose(client)
    serial = data["serial_hardware"]
    assert serial["ports"][0]["port"] == "/dev/ttyUSB0" and serial["ports_opened"] is False
    assert serial["status"] == "needs_permission" and "dialout" in serial["command"]


_orig_glob = Path.glob


def android_phone(mp, state="device", answers=None):
    mp.setattr(phone, "adb_path", lambda: "/usr/bin/adb")
    mp.setattr(phone, "list_devices", lambda: [{"kind": "android", "serial": "emulator-5554", "state": state,
                                                "model": "sdk_gphone64"}])
    answers = answers or {}

    def adb(args, serial=None):
        assert serial == "emulator-5554"
        assert args[0] == "shell" and args[1] in ("getprop", "echo"), args
        if args[1] == "echo":
            return (answers.get("echo", args[2]) + "\n").encode()
        return (answers.get(args[2], {"ro.product.model": "sdk_gphone64", "ro.build.version.release": "15",
                                      "ro.build.version.sdk": "35", "ro.product.cpu.abi": "x86_64",
                                      "ro.kernel.qemu": "1"}[args[2]]) + "\n").encode()
    mp.setattr(phone, "_adb", adb)


def test_android_verify_records_and_list_shows_verified(env):
    client, root, home, mp = env
    host(mp, "linux", "x86_64")
    android_phone(mp)
    listed = client.get(URL + "/list", headers=AUTH).json()
    assert listed["devices"][0]["status"] == "seen_not_verified" and listed["anything_started"] is False
    result = client.post(URL + "/verify", json={"kind": "android", "id": "emulator-5554"}, headers=AUTH).json()
    assert result["verified"] is True and result["details"]["sdk"] == "35" and result["details"]["emulator"] is True
    assert client.get(URL + "/list", headers=AUTH).json()["devices"][0]["status"] == "verified"


def test_android_verify_fails_on_wrong_echo(env):
    client, root, home, mp = env
    android_phone(mp, answers={"echo": "something-else"})
    result = client.post(URL + "/verify", json={"kind": "android", "id": "emulator-5554"}, headers=AUTH).json()
    assert result["verified"] is False and result["status"] == "no_answer"


def test_android_unauthorized_and_offline(env):
    client, root, home, mp = env
    android_phone(mp, state="unauthorized")
    result = client.post(URL + "/verify", json={"kind": "android", "id": "emulator-5554"}, headers=AUTH).json()
    assert result["verified"] is False and result["status"] == "unauthorized"
    android_phone(mp, state="offline")
    result = client.post(URL + "/verify", json={"kind": "android", "id": "emulator-5554"}, headers=AUTH).json()
    assert result["verified"] is False and result["command"] == "adb kill-server"


def test_android_verify_refusals(env):
    client, root, home, mp = env
    assert client.post(URL + "/verify", json={"kind": "android", "id": "emulator-5554"}, headers=AUTH).status_code == 409
    android_phone(mp)
    assert client.post(URL + "/verify", json={"kind": "android", "id": "other-1"}, headers=AUTH).status_code == 404
    assert client.post(URL + "/verify", json={"kind": "android", "id": "x; rm -rf /"}, headers=AUTH).status_code == 422
    assert client.post(URL + "/verify", json={"kind": "usb", "id": "x"}, headers=AUTH).status_code == 422


def test_simulator_refused_off_mac(env):
    client, root, home, mp = env
    host(mp, "linux", "x86_64")
    response = client.post(URL + "/verify", json={"kind": "ios_simulator", "id": UDID}, headers=AUTH)
    assert response.status_code == 409 and "Mac" in response.json()["detail"]
    assert client.get(URL + "/list", headers=AUTH).json()["simulator_error"]


def test_simulator_booted_vs_shutdown_on_mac(env):
    client, root, home, mp = env
    host(mp, "macos", "arm64")
    other = UDID[:-1] + "1"
    payload = ('{"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-18-2": ['
               f'{{"udid": "{UDID}", "name": "iPhone 16", "state": "Booted", "isAvailable": true}},'
               f'{{"udid": "{other}", "name": "iPhone SE", "state": "Shutdown", "isAvailable": true}}]}}}}')
    mp.setattr(devices, "_fixed", lambda argv: payload if argv[1:3] == ["simctl", "list"] else None)
    booted = client.post(URL + "/verify", json={"kind": "ios_simulator", "id": UDID}, headers=AUTH).json()
    assert booted["verified"] is True and booted["details"]["runtime"] == "iOS 18.2"
    off = client.post(URL + "/verify", json={"kind": "ios_simulator", "id": other}, headers=AUTH).json()
    assert off["verified"] is False and off["command"] == f"xcrun simctl boot {other} && open -a Simulator"
    assert client.post(URL + "/verify", json={"kind": "ios_simulator", "id": "not-a-udid"}, headers=AUTH).status_code == 422


def test_real_host_diagnosis_is_honest(tmp_path, monkeypatch):
    """No mocks: whatever this host is, nothing is started and unsupported pieces are never 'ready'."""
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    data = TestClient(server.app).get(URL + "/diagnose", headers=AUTH).json()
    assert data["anything_started"] is False
    if data["host"]["os"] != "macos":
        assert data["ios_simulator"]["status"] == "unsupported_host"
    if data["host"]["os"] == "linux" and data["host"]["arch"] == "arm64":
        assert data["android_emulator"]["status"] == "unsupported_host"
    assert data["android_emulator"]["status"] != "ready" or data["android_emulator"]["virtual_devices"]
