"""Developer Studio V43: device and simulator tools.

Diagnoses this computer for Android emulators, the iPhone Simulator, USB serial hardware
(microcontrollers and boards) and signing prerequisites, and verifies a development
device only when you ask, for one exact device.

Rules:
* Nothing is started, booted, flashed, installed, reset or signed. Serial ports are listed,
  never opened. Keystores and certificates are never read, only noticed.
* A device counts as verified only after a real answer from it (Android: adb state
  ``device``, matching properties and an echo round trip; Simulator: ``Booted`` in simctl).
* On a host that can't run a tool (the iPhone Simulator off macOS, the Android Emulator on
  Linux ARM) the answer is ``unsupported_host``, never success.
* Only fixed read-only commands run: ``adb devices``/``getprop``/``echo`` through the existing
  phone module, ``xcrun simctl list devices --json``, ``security find-identity -v -p
  codesigning`` (count only) and ``sysctl -n kern.hv_support``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_index as index
from automoto import developer_phone as phone
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/devices", tags=["developer-devices"])
VERSION = "1.0.0"
TIMEOUT = 15
KVM = Path("/dev/kvm")
XCRUN = "/usr/bin/xcrun"
SECURITY = "/usr/bin/security"
SYSCTL = "/usr/sbin/sysctl"
UDID = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")
MAX_GRADLE = 256 * 1024
VERIFIED: dict[tuple[str, str], dict] = {}
VERIFY_LOCK = threading.Lock()
KEYSTORE_SUFFIXES = (".jks", ".keystore", ".p12", ".pfx", ".mobileprovision", ".p8", ".cer", ".pem")
PASSWORD = re.compile(r"(?m)\b(storePassword|keyPassword)(?:\s*=\s*|\s*\(\s*|\s+)[\"']([^\"'$\n]{1,200})[\"']")


class VerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["android", "ios_simulator"]
    id: str = Field(min_length=1, max_length=80)


def _host() -> str:
    return "windows" if os.name == "nt" else "macos" if sys.platform == "darwin" else "linux"


def _arch() -> str:
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64", "armv8l"):
        return "arm64"
    if machine in ("x86_64", "amd64", "x64"):
        return "x86_64"
    return machine or "unknown"


def _fixed(argv: list[str]) -> str | None:
    """Run one fixed, read-only system command. Returns stdout, or None when unavailable."""
    if not Path(argv[0]).is_file():
        return None
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "DEVELOPER_DIR", "TMPDIR")}
    try:
        done = subprocess.run(argv, capture_output=True, timeout=TIMEOUT, check=False, env=env,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", "replace")[:512 * 1024]


def _item(status: str, title: str, text: str, fix: str | None = None, command: str | None = None,
          link: str | None = None, **extra) -> dict:
    return {"status": status, "title": title, "text": text, "fix": fix, "command": command,
            "link": link, **extra}


# ------------------------------------------------------------------ host diagnostics
def _virtualization(host: str, arch: str) -> dict:
    if host == "linux":
        if not KVM.exists():
            return _item("missing", "Hardware virtualization (KVM)",
                         "KVM isn't available, so Android emulators would be very slow or won't start.",
                         "Turn on virtualization (Intel VT-x or AMD-V) in your BIOS/UEFI settings. "
                         "On a cloud machine, nested virtualization must be enabled.")
        if not os.access(KVM, os.R_OK | os.W_OK):
            return _item("needs_permission", "Hardware virtualization (KVM)",
                         "KVM is there, but your user can't use it yet.",
                         "Add yourself to the kvm group, then sign out and back in.",
                         "sudo usermod -aG kvm $USER")
        return _item("ready", "Hardware virtualization (KVM)", "KVM is available to your user.")
    if host == "macos":
        if arch == "arm64":
            return _item("ready", "Hardware virtualization",
                         "Built into macOS on Apple silicon (Hypervisor framework).")
        value = _fixed([SYSCTL, "-n", "kern.hv_support"])
        if value is not None and value.strip() == "1":
            return _item("ready", "Hardware virtualization", "macOS reports Hypervisor support.")
        return _item("unknown", "Hardware virtualization", "macOS didn't confirm Hypervisor support.",
                     "Check that virtualization isn't disabled by a management profile.")
    return _item("not_checked", "Hardware virtualization",
                 "AutoMoto doesn't check this on Windows.",
                 "Open 'Turn Windows features on or off' and turn on Windows Hypervisor Platform, then restart.",
                 link="https://developer.android.com/studio/run/emulator-acceleration")


def _sdk_root(host: str) -> Path | None:
    candidates = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")]
    home = Path.home()
    candidates += {"linux": [str(home / "Android" / "Sdk")],
                   "macos": [str(home / "Library" / "Android" / "sdk")],
                   "windows": [str(Path(os.environ.get("LOCALAPPDATA", home)) / "Android" / "Sdk")]}[host]
    for raw in candidates:
        if raw and len(raw) < 2048 and Path(raw).is_absolute() and Path(raw).is_dir():
            return Path(raw)
    return None


def _android(host: str, arch: str, virtualization: dict) -> dict:
    sdk = _sdk_root(host)
    exe = ".exe" if host == "windows" else ""
    emulator = sdk / "emulator" / ("emulator" + exe) if sdk else None
    emulator_present = bool(emulator and emulator.is_file())
    adb = phone.adb_path()
    avd_home = Path(os.environ.get("ANDROID_AVD_HOME") or (Path.home() / ".android" / "avd"))
    avds = sorted(p.stem for p in avd_home.glob("*.ini"))[:30] if avd_home.is_dir() else []
    images = []
    if sdk and (sdk / "system-images").is_dir():
        for api in sorted((sdk / "system-images").iterdir())[:40]:
            if not api.is_dir():
                continue
            for flavour in sorted(api.iterdir())[:10]:
                for abi in sorted(flavour.iterdir())[:6] if flavour.is_dir() else []:
                    if abi.is_dir():
                        images.append({"image": f"{api.name}/{flavour.name}/{abi.name}", "abi": abi.name,
                                       "matches_host": (abi.name in ("x86_64", "x86")) == (arch == "x86_64")
                                       if arch in ("x86_64", "arm64") else None})
    images = images[:40]
    if host == "linux" and arch == "arm64":
        support = _item("unsupported_host", "Android Emulator on this computer",
                        "Google doesn't publish the Android Emulator for Linux on ARM, so it can't run here.",
                        "Use a real Android phone over USB, or an x86_64 Linux, Windows or Mac computer.")
    elif host == "windows" and arch == "arm64":
        support = _item("not_verified", "Android Emulator on this computer",
                        "AutoMoto hasn't verified the emulator on Windows on ARM.",
                        "Use a real Android phone over USB if the emulator doesn't start.")
    elif arch not in ("x86_64", "arm64"):
        support = _item("unsupported_host", "Android Emulator on this computer",
                        f"The emulator isn't published for this processor ({arch}).")
    elif not sdk:
        support = _item("missing", "Android Emulator on this computer", "The Android SDK wasn't found.",
                        "Install Android Studio, then open Device Manager once.",
                        link="https://developer.android.com/studio")
    elif not emulator_present:
        support = _item("missing", "Android Emulator on this computer",
                        "The Android SDK is installed, but the emulator package isn't.",
                        "In Android Studio, open SDK Manager → SDK Tools and tick Android Emulator.")
    elif not avds:
        support = _item("missing", "Android Emulator on this computer", "No virtual device has been created yet.",
                        "In Android Studio, open Device Manager and create a virtual device.")
    elif virtualization["status"] in ("missing", "needs_permission"):
        support = _item("needs_setup", "Android Emulator on this computer",
                        "The emulator is installed, but hardware virtualization isn't usable yet.",
                        virtualization.get("fix"), virtualization.get("command"))
    else:
        ready = virtualization["status"] == "ready"
        support = _item("ready" if ready else "probably_ready", "Android Emulator on this computer",
                        f"Emulator installed with {len(avds)} virtual device{'s' if len(avds) != 1 else ''}."
                        + ("" if ready else " Hardware virtualization wasn't checked."),
                        "Start it from Android Studio's Device Manager. AutoMoto doesn't start emulators.")
    if images and not any(i["matches_host"] for i in images if i["matches_host"] is not None):
        support["image_warning"] = ("None of the installed system images match this computer's processor; "
                                    "they would be very slow or won't start.")
    return {**support, "sdk_found": bool(sdk), "emulator_present": emulator_present,
            "adb_present": bool(adb), "virtual_devices": avds, "system_images": images,
            "emulator_started": False}


def _developer_dir() -> str | None:
    link = Path("/var/db/xcode_select_link")
    try:
        if link.is_symlink():
            return os.readlink(link)
    except OSError:
        pass
    for guess in ("/Applications/Xcode.app/Contents/Developer", "/Library/Developer/CommandLineTools"):
        if Path(guess).is_dir():
            return guess
    return None


def _ios(host: str) -> dict:
    if host != "macos":
        return _item("unsupported_host", "iPhone Simulator",
                     "The iPhone Simulator only runs on a Mac with Xcode. It can't run on this computer.",
                     "Use a Mac, or test on a real iPhone with Phone control.", booted=False)
    developer = _developer_dir()
    if not Path(XCRUN).is_file() or not developer:
        return _item("missing", "iPhone Simulator", "Xcode wasn't found.",
                     "Install Xcode from the Mac App Store, open it once, then press Check again.",
                     link="https://developer.apple.com/xcode/", booted=False)
    if "Xcode" not in developer:
        return _item("needs_setup", "iPhone Simulator",
                     "Only the Command Line Tools are selected. The Simulator needs full Xcode.",
                     "Point the tools at Xcode.", "sudo xcode-select -s /Applications/Xcode.app/Contents/Developer",
                     booted=False)
    return _item("ready", "iPhone Simulator", "Xcode is installed. Press Find devices to list simulators.",
                 developer_dir=developer, booted=False)


def _serial_ports(host: str) -> dict:
    ports = []
    if host == "windows":
        try:
            import winreg  # noqa: PLC0415
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as key:
                for i in range(64):
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    ports.append({"port": str(value)[:40], "description": str(name).rsplit("\\", 1)[-1][:80],
                                  "accessible": None})
        except (ImportError, OSError):
            pass
    else:
        patterns = (["/dev/ttyUSB*", "/dev/ttyACM*"] if host == "linux" else
                    ["/dev/cu.usbserial*", "/dev/cu.usbmodem*", "/dev/cu.SLAB_USBtoUART*", "/dev/cu.wchusbserial*"])
        names = {}
        by_id = Path("/dev/serial/by-id")
        if host == "linux" and by_id.is_dir():
            for link in by_id.iterdir():
                try:
                    names[str(link.resolve())] = link.name[:120]
                except OSError:
                    continue
        for pattern in patterns:
            for path in sorted(Path("/dev").glob(pattern[5:]))[:32]:
                ports.append({"port": path.as_posix(), "description": names.get(str(path), ""),
                              "accessible": os.access(path, os.R_OK | os.W_OK)})
    if not ports:
        status = _item("none", "USB boards and serial hardware",
                       "No USB serial device is plugged in (Arduino, ESP32, Raspberry Pi Pico and similar).",
                       "Plug the board in with a data cable (some cables only charge).")
    elif host == "linux" and any(p["accessible"] is False for p in ports):
        status = _item("needs_permission", "USB boards and serial hardware",
                       "A board is plugged in, but your user can't open it yet.",
                       "Add yourself to the dialout group (uucp on Arch), then sign out and back in.",
                       "sudo usermod -aG dialout $USER")
    else:
        status = _item("ready", "USB boards and serial hardware",
                       f"{len(ports)} serial device{'s' if len(ports) != 1 else ''} found.")
    return {**status, "ports": ports, "ports_opened": False}


def _signing(root: Path | None, host: str) -> list[dict]:
    items = []
    debug_keystore = Path.home() / ".android" / "debug.keystore"
    items.append(_item("ready" if debug_keystore.is_file() else "missing", "Android debug signing",
                       "Debug builds can be signed on this computer." if debug_keystore.is_file() else
                       "No Android debug key yet. Android Studio creates it on the first debug build.",
                       None if debug_keystore.is_file() else "Build and run any app once from Android Studio.",
                       platform="android", contents_read=False))
    if root is not None:
        keystores, hardcoded, signing_configs = [], [], False
        for name, warning in index._walk(root):
            if warning:
                continue
            leaf = name.rsplit("/", 1)[-1].lower()
            if leaf.endswith(KEYSTORE_SUFFIXES):
                keystores.append(name)
            elif leaf in ("build.gradle", "build.gradle.kts"):
                target = studio._path(root, name)
                try:
                    if target.is_symlink() or target.stat().st_size > MAX_GRADLE:
                        continue
                    text = target.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if "signingConfigs" in text:
                    signing_configs = True
                for match in PASSWORD.finditer(text):
                    hardcoded.append({"path": name, "line": text.count("\n", 0, match.start()) + 1,
                                      "setting": match.group(1)})
        if hardcoded:
            items.append(_item("problem", "Android release signing",
                               "A signing password is written straight into a Gradle file. The value is hidden here.",
                               "Read it from an environment variable or a keystore.properties file kept out of Git, "
                               "and change the password if the file was ever shared.",
                               platform="android", findings=hardcoded[:10], contents_read=False))
        elif signing_configs:
            items.append(_item("ready", "Android release signing",
                               "The project has a signing setup that doesn't hard-code passwords.",
                               platform="android", contents_read=False))
        else:
            items.append(_item("missing", "Android release signing",
                               "No release signing setup was found. You need one to publish on Google Play.",
                               "Create an upload key in Android Studio: Build → Generate Signed App Bundle.",
                               link="https://developer.android.com/studio/publish/app-signing",
                               platform="android", contents_read=False))
        if keystores:
            items.append(_item("warning", "Key and certificate files in the project",
                               f"{len(keystores)} key or certificate file{'s are' if len(keystores) != 1 else ' is'} "
                               "inside the project. They were not opened.",
                               "Keep them out of Git (add them to .gitignore) and back them up somewhere safe.",
                               platform="any", files=keystores[:20], contents_read=False))
    if host == "macos":
        profiles = 0
        for folder in (Path.home() / "Library" / "MobileDevice" / "Provisioning Profiles",
                       Path.home() / "Library" / "Developer" / "Xcode" / "UserData" / "Provisioning Profiles"):
            if folder.is_dir():
                profiles += sum(1 for _ in folder.glob("*.mobileprovision"))
        output = _fixed([SECURITY, "find-identity", "-v", "-p", "codesigning"])
        match = re.search(r"(\d+) valid identit", output or "")
        identities = int(match.group(1)) if match else None
        ready = bool(identities) and profiles > 0
        items.append(_item("ready" if ready else "missing", "Apple code signing",
                           f"{identities if identities is not None else 'Unknown number of'} signing "
                           f"identit{'y' if identities == 1 else 'ies'} and {profiles} provisioning "
                           f"profile{'s' if profiles != 1 else ''} found. Names are not shown.",
                           None if ready else "Sign in to your Apple account in Xcode → Settings → Accounts, "
                           "then let Xcode manage signing.", platform="apple",
                           identities=identities, provisioning_profiles=profiles, contents_read=False))
    else:
        items.append(_item("unsupported_host", "Apple code signing",
                           "Signing iPhone and Mac apps needs a Mac with Xcode.", platform="apple"))
    if host == "windows":
        kits = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"
        signtool = shutil.which("signtool")
        if not signtool and kits.is_dir():
            signtool = next((str(p) for p in sorted(kits.glob("*/x64/signtool.exe"), reverse=True)), None)
        items.append(_item("ready" if signtool else "missing", "Windows package signing (MSIX)",
                           ("signtool is installed for sideloaded packages." if signtool else
                            "signtool isn't installed. You only need it to sideload; the Microsoft Store signs "
                            "Store submissions for you."),
                           None if signtool else "Install the Windows SDK.",
                           link=None if signtool else "https://developer.microsoft.com/windows/downloads/windows-sdk/",
                           platform="windows"))
    return items


def _diagnose(root: Path | None) -> dict:
    host, arch = _host(), _arch()
    virtualization = _virtualization(host, arch)
    android = _android(host, arch, virtualization)
    ios = _ios(host)
    serial = _serial_ports(host)
    signing = _signing(root, host)
    return {"schema": VERSION, "host": {"os": host, "arch": arch, "release": platform.release()[:80]},
            "virtualization": virtualization, "android_emulator": android, "ios_simulator": ios,
            "serial_hardware": serial, "signing": signing,
            "anything_started": False, "devices_verified": False, "central_agent_studio": "developer",
            "limitations": ("Diagnostics read files and run a few fixed read-only commands. 'Ready' means "
                            "the pieces are present, not that a build will succeed. Devices are only "
                            "verified when you press Verify. Windows virtualization isn't checked.")}


# ------------------------------------------------------------------ devices
def _simulators() -> tuple[list[dict], str | None]:
    if _host() != "macos":
        return [], "The iPhone Simulator only runs on a Mac."
    raw = _fixed([XCRUN, "simctl", "list", "devices", "--json"])
    if raw is None:
        return [], "Xcode's simctl didn't answer. Is full Xcode installed and selected?"
    try:
        data = json.loads(raw)
    except ValueError:
        return [], "simctl returned something AutoMoto couldn't read."
    found = []
    for runtime, devices in (data.get("devices") or {}).items():
        label = runtime.rsplit(".", 1)[-1].replace("-", " ", 1).replace("-", ".")
        for device in devices or []:
            if not device.get("isAvailable", True) or not UDID.match(str(device.get("udid", ""))):
                continue
            found.append({"kind": "ios_simulator", "id": device["udid"], "name": str(device.get("name", ""))[:80],
                          "runtime": label[:40], "state": str(device.get("state", ""))[:20]})
            if len(found) >= 60:
                return found, None
    return found, None


def _devices() -> dict:
    android, android_error = [], None
    if not phone.adb_path():
        android_error = "adb isn't installed, so Android phones and emulators can't be listed."
    else:
        try:
            android = [{"kind": "iphone" if d.get("kind") != "android" else "android",
                        "id": d.get("serial", ""), "name": d.get("model") or d.get("serial", ""),
                        "state": d.get("state", "")} for d in phone.list_devices()]
        except HTTPException as exc:
            android_error = str(exc.detail)
    simulators, sim_error = _simulators()
    now = time.time()
    with VERIFY_LOCK:
        verified = {k: v for k, v in VERIFIED.items() if now - v["at"] < 3600}
    items = []
    for device in [*android, *simulators]:
        record = verified.get((device["kind"], device["id"]))
        items.append({**device, "verified": bool(record and record["verified"]),
                      "verified_details": record["details"] if record else None,
                      "status": "verified" if record and record["verified"] else "seen_not_verified"})
    return {"devices": items, "android_error": android_error, "simulator_error": sim_error,
            "host": _host(), "anything_started": False}


def _verify_android(serial: str) -> dict:
    if not re.fullmatch(phone.SERIAL, serial):
        raise HTTPException(422, "That isn't a valid device serial.")
    if not phone.adb_path():
        raise HTTPException(409, "adb isn't installed. Install Android SDK Platform-Tools first.")
    listed = next((d for d in phone.list_devices() if d.get("serial") == serial and d.get("kind") == "android"), None)
    if not listed:
        raise HTTPException(404, "That device isn't connected now. Press Find devices again.")
    state = listed.get("state")
    if state == "unauthorized":
        return {"verified": False, "status": "unauthorized",
                "text": "The phone hasn't allowed this computer yet.",
                "fix": "Unlock the phone and tap Allow on the 'Allow USB debugging?' message, then verify again."}
    if state != "device":
        return {"verified": False, "status": state or "unknown",
                "text": f"The device is {state or 'not ready'}.",
                "fix": "Unplug it and plug it back in, or restart adb.", "command": "adb kill-server"}
    details = {}
    for key, prop in (("model", "ro.product.model"), ("android_version", "ro.build.version.release"),
                      ("sdk", "ro.build.version.sdk"), ("abi", "ro.product.cpu.abi"),
                      ("emulator", "ro.kernel.qemu")):
        details[key] = phone._adb(["shell", "getprop", prop], serial).decode("utf-8", "replace").strip()[:60]
    nonce = "automoto-v43-" + secrets.token_hex(6)
    echoed = phone._adb(["shell", "echo", nonce], serial).decode("utf-8", "replace").strip()
    ok = echoed == nonce and bool(details["sdk"].isdigit())
    details["emulator"] = details["emulator"] == "1"
    return {"verified": ok, "status": "verified" if ok else "no_answer",
            "text": (f"{details['model'] or 'Device'} is ready for development: Android "
                     f"{details['android_version']} (API {details['sdk']}, {details['abi']})."
                     if ok else "The device didn't answer correctly."),
            "fix": None if ok else "Unplug it and plug it back in, then verify again.", "details": details}


def _verify_simulator(udid: str) -> dict:
    if _host() != "macos":
        raise HTTPException(409, "Unsupported host: the iPhone Simulator only runs on a Mac.")
    if not UDID.match(udid):
        raise HTTPException(422, "That isn't a valid simulator ID.")
    simulators, error = _simulators()
    if error:
        raise HTTPException(409, error)
    device = next((d for d in simulators if d["id"].lower() == udid.lower()), None)
    if not device:
        raise HTTPException(404, "That simulator wasn't found. Press Find devices again.")
    if device["state"] != "Booted":
        return {"verified": False, "status": "not_running",
                "text": f"{device['name']} ({device['runtime']}) exists but isn't running.",
                "fix": "Start it, then verify again. AutoMoto doesn't start simulators.",
                "command": f"xcrun simctl boot {device['id']} && open -a Simulator"}
    return {"verified": True, "status": "verified",
            "text": f"{device['name']} ({device['runtime']}) is running and ready.",
            "fix": None, "details": {"name": device["name"], "runtime": device["runtime"]}}


@router.get("/diagnose")
def diagnose(request: Request, project: str | None = None):
    studio._auth(request)
    return _diagnose(studio._project(project) if project else None)


@router.get("/list")
def list_devices(request: Request):
    studio._auth(request)
    return _devices()


@router.post("/verify")
def verify(request: Request, body: VerifyIn):
    studio._auth(request)
    result = _verify_android(body.id) if body.kind == "android" else _verify_simulator(body.id)
    with VERIFY_LOCK:
        VERIFIED[(body.kind, body.id)] = {"verified": bool(result["verified"]), "at": time.time(),
                                          "details": result.get("details")}
    return {"kind": body.kind, "id": body.id, **result, "verified_at": int(time.time()),
            "anything_started": False, "central_agent_studio": "developer"}
