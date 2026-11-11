"""iPhone apps inside Developer Studio.

A person describes an app or hands over a ZIP. This module writes the project,
asks the in-house toolchain to build and install it, drafts the App Store
page, and talks to Apple only after the on-screen button for that exact draft.

The toolchain sources live in ``third_party/ios-toolchain``. This module does
not contact that project's old hosts. Apple SDKs are never downloaded from us.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import shutil
import stat
import subprocess
import threading
import zipfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import brand, config, home, sandbox

log = logging.getLogger("automoto.developer_ios")
router = APIRouter(prefix="/api/developer/studio/ios", tags=["developer-ios"])

APPLE_API = "https://api.appstoreconnect.apple.com"
ANISETTE_DEFAULT = "http://127.0.0.1:6969"
# Hosts the forked toolchain used to contact. A configured URL that contains
# one of these is refused, even if a remote helper is explicitly allowed.
FORBIDDEN_HOSTS = ("xtool-org", "sidestore", "jkcoxson")
SECRET_NAMES = ("AUTOMOTO_ASC_KEY_ID", "AUTOMOTO_ASC_ISSUER_ID", "AUTOMOTO_ASC_KEY_PATH", "AUTOMOTO_APPLE_ID")
SECRET_ENV_HIDDEN = {"AUTOMOTO_ASC_KEY_ID", "AUTOMOTO_ASC_ISSUER_ID", "AUTOMOTO_APPLE_PASSWORD"}
APPROVAL_HEADER = "x-automoto-ios-approval"
MAX_ZIP_BYTES = 30 * 1024 * 1024
MAX_FILES = 400
MAX_UNPACKED = 80 * 1024 * 1024
_LOCK = threading.Lock()
_SLUG = re.compile(r"[^a-z0-9]+")
_BUNDLE = re.compile(r"^bundleID:\s*([A-Za-z0-9.-]+)\s*$", re.M)

SCREENSHOTS = (
    {"id": "iphone-6-7", "label": "A picture of the app on a 6.7 inch iPhone", "done": False},
    {"id": "iphone-6-5", "label": "A picture of the app on a 6.5 inch iPhone", "done": False},
)


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)


class CreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(default="", max_length=4000)
    project: str = Field(default="", max_length=1024)
    zip_path: str = Field(default="", max_length=1024)


class SetupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    xcode_xip: str = Field(default="", max_length=1024)


class ListingIn(ProjectIn):
    name: str = Field(min_length=1, max_length=30)
    subtitle: str = Field(default="", max_length=30)
    description: str = Field(min_length=1, max_length=4000)
    keywords: str = Field(default="", max_length=100)
    privacy: str = Field(min_length=1, max_length=2000)
    support_url: str = Field(default="", max_length=300)
    version: str = Field(default="1.0", pattern=r"^[0-9]+(\.[0-9]+){0,2}$")
    build_number: str = Field(default="1", pattern=r"^[0-9]{1,8}$")


class ApproveIn(ProjectIn):
    confirmed: bool
    screenshots_acknowledged: bool
    listing_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class SubmitIn(ProjectIn):
    listing_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class SecretIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=1024)

    def __repr__(self) -> str:  # pragma: no cover - never log the value
        return "SecretIn(redacted)"


def _auth(request: Request) -> None:
    from automoto import server
    server._authorise(request, local_only=True)


def _offline() -> bool:
    from automoto import local_llm
    return local_llm.offline()


def _fail(message: str) -> None:
    raise HTTPException(409, message)


def toolchain_root() -> Path:
    here = Path(__file__).resolve().parents[1] / "third_party" / "ios-toolchain"
    override = (config.env("AUTOMOTO_IOS_TOOLCHAIN_ROOT") or "").strip()
    return Path(override).expanduser() if override else here


def _lockfile() -> dict[str, Any]:
    path = toolchain_root() / "Artifacts.json"
    if not path.is_file():
        return {"base_url": "", "artifacts": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def host_blocked(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(part in host for part in FORBIDDEN_HOSTS)


def anisette_url() -> str:
    raw = (config.env("AUTOMOTO_ANISETTE_URL") or ANISETTE_DEFAULT).strip()
    if host_blocked(raw):
        _fail("That provisioning server is not used. Leave it empty to stay on this computer.")
    host = (urlparse(raw).hostname or "").lower()
    loopback = host in {"127.0.0.1", "localhost", "::1"}
    if not loopback and (config.env("AUTOMOTO_ANISETTE_ALLOW_REMOTE") or "") != "1":
        _fail("The provisioning helper stays on this computer unless you turn on one you run yourself.")
    return raw


def _binary() -> str:
    override = (config.env("AUTOMOTO_IOS_TOOLCHAIN_BIN") or "").strip()
    if override:
        return override
    found = shutil.which("automoto-ios")
    return found or ""


def current_facts() -> dict[str, Any]:
    system = platform.system()
    package = (config.env("AUTOMOTO_DESKTOP_PACKAGE") or "").strip().lower()
    return {
        "system": system,
        "package": package,
        "wsl": system == "Windows" and shutil.which("wsl") is not None,
        "offline": _offline(),
        "binary": _binary(),
        "mode": (config.env("AUTOMOTO_IOS_TOOLCHAIN") or "").strip().lower(),
    }


def deployment_message(facts: dict[str, Any] | None = None) -> dict[str, Any]:
    """Plain-language reason this computer can or cannot build for an iPhone."""
    facts = facts or current_facts()
    who = brand.short()
    if facts["package"] == "msix":
        return {"ok": False, "code": "msix", "message": (
            f"This copy of {who} came from the Microsoft Store. That package cannot "
            "put an app on an iPhone or start the iPhone tools. Install the engine "
            "on a Windows PC that has WSL, or use a Mac or a Linux computer."
        )}
    if facts["system"] == "Windows" and not facts["wsl"]:
        return {"ok": False, "code": "wsl", "message": (
            "This Windows PC needs WSL (a small Linux inside Windows) before it can "
            "build an iPhone app. Install WSL, then come back. A Store copy of the "
            "app cannot do this step."
        )}
    if facts["system"] not in {"Windows", "Linux", "Darwin"}:
        return {"ok": False, "code": "os", "message": f"{who} cannot build an iPhone app on this kind of computer."}
    if facts["mode"] == "fake":
        return {"ok": True, "code": "fake", "message": (
            "A test stand-in is being used instead of the real iPhone tools. "
            "It does not talk to a real iPhone or to Apple."
        )}
    if not facts["binary"]:
        where = "inside WSL" if facts["system"] == "Windows" else "on this computer"
        return {"ok": False, "code": "binary", "message": (
            f"The iPhone tools are not built {where} yet. The source is in this "
            "project. Building it needs Swift 6.2. Nothing was downloaded."
        )}
    ready = "WSL on this Windows PC" if facts["system"] == "Windows" else "this computer"
    return {"ok": True, "code": "ready", "message": f"The iPhone tools can run on {ready}. A real iPhone is still required. There is no simulator."}


def wizard_steps(facts: dict[str, Any] | None = None) -> list[dict[str, str]]:
    facts = facts or current_facts()
    place = deployment_message(facts)["message"]
    who = brand.short()
    return [
        {"n": "1", "title": "This computer", "text": place},
        {"n": "2", "title": "Xcode, from Apple", "text": (
            "Download Xcode.xip once from Apple's developer downloads. "
            f"{who} does not keep a copy and will not fetch one for you."
        )},
        {"n": "3", "title": "Your iPhone", "text": (
            "Plug in the iPhone. On the phone, turn on Developer Mode "
            "(Settings, Privacy & Security, Developer Mode) and tap Trust for this computer. "
            "Windows and Linux have no iPhone simulator."
        )},
        {"n": "4", "title": "Your Apple account", "text": (
            "A paid Apple Developer account is needed for the App Store, and to stop "
            "a test install expiring after 7 days."
        )},
        {"n": "5", "title": "An App Store key", "text": (
            "In App Store Connect, create an API key once. Put the .p8 file in the "
            "secrets folder and tell this page the path. Do not paste the key into the chat."
        )},
        {"n": "6", "title": "The app", "text": (
            "Describe the app, or give a ZIP of a project. You will not be shown the "
            "source unless you ask."
        )},
        {"n": "7", "title": "Sending it to Apple", "text": (
            "Read the App Store page, tick the box, and press Send to Apple. "
            "Nothing is uploaded before that button."
        )},
    ]


def _env_path() -> Path:
    return home.base() / ".env"


def _secrets_dir() -> Path:
    path = home.home() / "secrets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def store_secret(name: str, value: str) -> dict[str, Any]:
    """Write one secret into the existing .env. The value is not returned or logged."""
    if name not in SECRET_NAMES:
        _fail("That is not an iPhone setting this app stores.")
    if "\n" in value or "\r" in value or "-----BEGIN" in value:
        _fail("Do not paste a key here. Put the .p8 file in the secrets folder and store the path.")
    value = value.strip()
    if not value:
        _fail("That value is empty.")
    if name == "AUTOMOTO_ASC_KEY_PATH":
        file = Path(value).expanduser()
        try:
            file.resolve().relative_to(_secrets_dir().resolve())
        except ValueError:
            _fail("Put the key file in the secrets folder, not in a project.")
        if not file.is_file():
            _fail("That key file is not there yet.")
        if os.name == "posix":
            mode = stat.S_IMODE(file.stat().st_mode)
            if mode & 0o077:
                _fail("The key file must be readable only by you.")
    path = _env_path()
    lines: list[str] = []
    found = False
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.startswith(name + "="):
                lines.append(f"{name}={value}")
                found = True
            else:
                lines.append(raw)
    if not found:
        lines.append(f"{name}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    if os.name == "posix":
        os.chmod(path, 0o600)
    os.environ[name] = value
    log.info("stored iPhone setting %s", name)
    return {"stored": name, "present": True}


def secret_status() -> dict[str, bool]:
    return {name: bool(config.env(name)) for name in SECRET_NAMES}


def child_env() -> dict[str, str]:
    """Environment for the toolchain. Key material stays out of it."""
    env = {key: value for key, value in os.environ.items() if key not in SECRET_ENV_HIDDEN}
    env["AUTOMOTO_ANISETTE_URL"] = anisette_url() if _anisette_safe() else ANISETTE_DEFAULT
    return env


def _anisette_safe() -> bool:
    try:
        anisette_url()
    except HTTPException:
        return False
    return True


def artifact_report() -> dict[str, Any]:
    lock = _lockfile()
    waiting = [key for key, entry in lock.get("artifacts", {}).items()
               if key.startswith(("darwin-tools", "open-apple-macros")) and not entry.get("sha256")]
    return {"published": not waiting, "waiting": waiting,
            "message": ("Support files for Linux and Windows builds are not published yet, so nothing was downloaded."
                        if waiting else "Support files are pinned and can be checked before use.")}


def fetch_artifact(key: str, dest: Path, *, opener: Callable[..., Any] | None = None) -> Path:
    """Download one support file from our releases, or refuse when it has no checksum."""
    entry = _lockfile().get("artifacts", {}).get(key)
    if not entry:
        _fail(f"There is no support file named {key}.")
    sha = str(entry.get("sha256") or "")
    if not re.fullmatch(r"[a-f0-9]{64}", sha):
        _fail(f"The support file {key} is not published yet, so nothing was downloaded.")
    if dest.is_file() and hashlib.sha256(dest.read_bytes()).hexdigest() == sha:
        return dest
    base = (config.env("AUTOMOTO_IOS_ARTIFACT_BASE") or _lockfile().get("base_url") or "").strip()
    if not base or host_blocked(base):
        _fail("Support files are only fetched from this project's own releases.")
    host = (urlparse(base).hostname or "").lower()
    if host != "github.com":
        _fail("Support files are only fetched from this project's GitHub releases.")
    url = base.rstrip("/") + "/" + str(entry["file"])
    if host_blocked(url):
        _fail("That download address is not allowed.")
    blob = _read_url(url, opener)
    digest = hashlib.sha256(blob).hexdigest()
    if digest != sha:
        _fail("The support file did not match its checksum, so it was not kept.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
    return dest


def _read_url(url: str, opener: Callable[..., Any] | None) -> bytes:
    if opener is not None:
        return opener(url)
    import urllib.request
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310  # nosec B310 - host checked by the caller
        return response.read()


def _slug(prompt: str) -> str:
    words = _SLUG.sub("-", prompt.lower()).strip("-")
    slug = "-".join(part for part in words.split("-") if part)[:40].strip("-")
    return slug or "my-app"


def _app_name(prompt: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", prompt)[:3]
    name = "".join(part[:12].capitalize() for part in parts)[:30]
    return name or "MyApp"


def _project_dir(raw: str, slug: str) -> Path:
    if raw.strip():
        try:
            path = sandbox.resolve(raw.strip(), allow_outside=False)
        except sandbox.SandboxError as exc:
            _fail(str(exc))
        path.mkdir(parents=True, exist_ok=True)
        return path
    dest = sandbox.default_root() / "apps" / slug
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def _scaffold(dest: Path, prompt: str) -> None:
    name = _app_name(prompt)
    title = (prompt.strip() or name)[:80].replace("\\", " ").replace('"', "'")
    sources = dest / "Sources" / name
    sources.mkdir(parents=True, exist_ok=True)
    (dest / "Package.swift").write_text(
        "// swift-tools-version: 6.0\n\nimport PackageDescription\n\n"
        "let package = Package(\n"
        f'    name: "{name}",\n'
        "    platforms: [.iOS(.v17)],\n"
        "    products: [.library(name: \"" + name + "\", targets: [\"" + name + "\"])],\n"
        "    targets: [.target(name: \"" + name + "\")]\n)\n",
        encoding="utf-8", newline="\n")
    (sources / f"{name}App.swift").write_text(
        "import SwiftUI\n\n@main struct " + name + "App: App {\n"
        "    var body: some Scene {\n        WindowGroup { ContentView() }\n    }\n}\n\n"
        "private struct ContentView: View {\n    var body: some View {\n"
        f'        Text("{title}")\n            .padding()\n    }}\n',
        encoding="utf-8", newline="\n")
    slug = dest.name
    (dest / "automoto-ios.yml").write_text(
        f"version: 1\nbundleID: app.local.{slug}\n",
        encoding="utf-8", newline="\n")
    (dest / "AppStore").mkdir(exist_ok=True)
    (dest / "AppStore" / "prompt.txt").write_text(prompt.strip() + "\n", encoding="utf-8", newline="\n")


def _unpack_zip(zip_path: str, dest: Path) -> None:
    try:
        archive = sandbox.resolve(zip_path, allow_outside=False)
    except sandbox.SandboxError as exc:
        _fail(str(exc))
    if not archive.is_file() or archive.stat().st_size > MAX_ZIP_BYTES:
        _fail("That ZIP is missing or larger than 30 MB.")
    try:
        zf = zipfile.ZipFile(archive)
    except zipfile.BadZipFile:
        _fail("That file is not a ZIP of an app project.")
    total = 0
    names = [info for info in zf.infolist() if not info.is_dir()]
    if len(names) > MAX_FILES:
        _fail("That ZIP has too many files.")
    for info in names:
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/") or name.split("/")[-1].startswith(".env"):
            _fail("That ZIP has a file this app will not unpack.")
        total += info.file_size
        if total > MAX_UNPACKED:
            _fail("That ZIP unpacks to more than 80 MB.")
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(info))


def create_app(request: Request, body: CreateIn) -> dict[str, Any]:
    _auth(request)
    if not body.prompt.strip() and not body.zip_path.strip():
        _fail("Describe the app or give a ZIP.")
    slug = _slug(body.prompt or Path(body.zip_path).stem)
    dest = _project_dir(body.project, slug)
    if body.zip_path.strip():
        _unpack_zip(body.zip_path.strip(), dest)
        if body.prompt.strip() and not (dest / "AppStore" / "prompt.txt").exists():
            (dest / "AppStore").mkdir(exist_ok=True)
            (dest / "AppStore" / "prompt.txt").write_text(body.prompt.strip() + "\n", encoding="utf-8", newline="\n")
    else:
        _scaffold(dest, body.prompt)
    names = sorted(p.name for p in dest.iterdir())
    return {"project": str(dest), "files": names,
            "summary": f"Created an iPhone app called {dest.name}. It is ready to build. The source stays in the project folder."}


def _toolchain():
    if current_facts()["mode"] == "fake":
        return _FakeToolchain()
    return _SubprocessToolchain()


def build_app(request: Request, body: ProjectIn) -> dict[str, Any]:
    _auth(request)
    _need_host()
    project = _existing_project(body.project)
    return _toolchain().build(project)


def install_app(request: Request, body: ProjectIn) -> dict[str, Any]:
    _auth(request)
    _need_host()
    project = _existing_project(body.project)
    return _toolchain().install(project)


def devices(request: Request) -> dict[str, Any]:
    _auth(request)
    _need_host()
    return _toolchain().devices()


def _need_host() -> None:
    message = deployment_message()
    if not message["ok"]:
        _fail(message["message"])


def _existing_project(raw: str) -> Path:
    try:
        path = sandbox.resolve(raw, allow_outside=False)
    except sandbox.SandboxError as exc:
        _fail(str(exc))
    if not path.is_dir():
        _fail("That project folder is not there.")
    return path


def setup(request: Request, body: SetupIn) -> dict[str, Any]:
    _auth(request)
    report = deployment_message()
    xip = ""
    if body.xcode_xip.strip():
        file = Path(body.xcode_xip).expanduser()
        if not file.is_file():
            xip = "That Xcode file is not there. Download Xcode.xip from Apple and choose the file."
        else:
            with file.open("rb") as handle:
                magic = handle.read(4)
            xip = "" if magic == b"xar!" else "That file is not an Xcode.xip from Apple."
    return {"deployment": report, "xcode_xip": xip, "artifacts": artifact_report(),
            "secrets": secret_status(), "anisette": ANISETTE_DEFAULT}


def _listing_path(project: Path) -> Path:
    return project / "AppStore" / "listing.json"


def listing_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def listing_sha(data: dict[str, Any]) -> str:
    return hashlib.sha256(listing_bytes(data)).hexdigest()


def prepare_listing(request: Request, body: ListingIn) -> dict[str, Any]:
    _auth(request)
    project = _existing_project(body.project)
    data = body.model_dump()
    data["screenshots"] = [dict(item) for item in SCREENSHOTS]
    data["screenshots_acknowledged"] = False
    path = _listing_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(listing_bytes(data))
    _clear_approval(project)
    sha = listing_sha(data)
    return {"project": str(project), "listing_sha256": sha, "listing": data,
            "summary": "Wrote the App Store page as a draft. Nothing was sent. Read it, then press Send to Apple."}


def _approval_path() -> Path:
    return home.home() / "ios-approvals.json"


def _load_approvals() -> dict[str, Any]:
    path = _approval_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_approvals(data: dict[str, Any]) -> None:
    path = _approval_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8", newline="\n")


def _clear_approval(project: Path) -> None:
    with _LOCK:
        data = _load_approvals()
        data.pop(str(project), None)
        _save_approvals(data)


def _button_pressed(request: Request) -> bool:
    if getattr(request.state, "automoto_agent_call", False):
        return False
    return request.headers.get(APPROVAL_HEADER) == "1"


def approve_listing(request: Request, body: ApproveIn) -> dict[str, Any]:
    _auth(request)
    if not _button_pressed(request):
        _fail("Sending to Apple needs the button in the iPhone panel. The assistant cannot press it.")
    if body.confirmed is not True or body.screenshots_acknowledged is not True:
        _fail("Tick the box that you have read the page and you want Apple to receive it.")
    project = _existing_project(body.project)
    current = _read_listing(project)
    if listing_sha(current) != body.listing_sha256:
        _fail("The App Store page changed. Read it again, then press the button.")
    with _LOCK:
        data = _load_approvals()
        data[str(project)] = {"sha256": body.listing_sha256, "consumed": False}
        _save_approvals(data)
    return {"approved": True, "listing_sha256": body.listing_sha256,
            "summary": "Apple can receive this exact page when you send it. Editing the page cancels this."}


def _read_listing(project: Path) -> dict[str, Any]:
    path = _listing_path(project)
    if not path.is_file():
        _fail("Write the App Store page first.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _fail("The App Store page could not be read.")
    if not isinstance(data, dict):
        _fail("The App Store page could not be read.")
    return data


def _take_approval(project: Path, sha: str) -> None:
    with _LOCK:
        data = _load_approvals()
        row = data.get(str(project)) or {}
        if row.get("sha256") != sha or row.get("consumed"):
            _fail("Apple has not been sent anything. Press Send to Apple on this exact page.")
        row["consumed"] = True
        data[str(project)] = row
        _save_approvals(data)


def submit_app(request: Request, body: SubmitIn) -> dict[str, Any]:
    _auth(request)
    if _offline():
        _fail("Sending to Apple needs the internet. Offline mode left this step out.")
    project = _existing_project(body.project)
    listing = _read_listing(project)
    if listing_sha(listing) != body.listing_sha256:
        _fail("The App Store page changed. Read it again, then press the button.")
    if not all(config.env(name) for name in ("AUTOMOTO_ASC_KEY_ID", "AUTOMOTO_ASC_ISSUER_ID", "AUTOMOTO_ASC_KEY_PATH")):
        _fail("Add the App Store Connect key id, issuer id, and key file path first. Nothing was sent.")
    signed = _toolchain().sign(project)
    if signed.get("test_double") and (config.env("AUTOMOTO_IOS_ALLOW_TEST_DOUBLE") or "") != "1":
        _fail("This computer has not signed the app for the App Store, so it was not sent.")
    if not signed.get("ok"):
        _fail(signed.get("message") or "The app was not signed for the App Store.")
    token = apple_token()
    _take_approval(project, body.listing_sha256)
    ipa = Path(signed["ipa"])
    result = upload_to_apple(
        ipa, listing, bundle_id=_bundle_id(project), token=token, http=_HTTP or _urlopen_json,
    )
    result["apple_signature"] = False if signed.get("test_double") else True
    result["test_double"] = bool(signed.get("test_double"))
    log.info("app store submit project=%s stopped=%s", project.name, result.get("stopped"))
    return result


def _bundle_id(project: Path) -> str:
    for name in ("automoto-ios.yml", "xtool.yml"):
        file = project / name
        if not file.is_file():
            continue
        match = _BUNDLE.search(file.read_text(encoding="utf-8"))
        if match:
            return match.group(1)
    _fail("This project has no bundle id yet.")
    return ""


def apple_token() -> str:
    """ES256 JWT for App Store Connect. The private key is never logged."""
    key_id = config.env("AUTOMOTO_ASC_KEY_ID") or ""
    issuer = config.env("AUTOMOTO_ASC_ISSUER_ID") or ""
    path = config.env("AUTOMOTO_ASC_KEY_PATH") or ""
    if not key_id or not issuer or not path:
        _fail("Add the App Store Connect key id, issuer id, and key file path in the secrets folder first.")
    file = Path(path)
    try:
        pem = file.read_bytes()
    except OSError:
        _fail("The App Store key file could not be read.")
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        key = serialization.load_pem_private_key(pem, password=None)
        header = _b64(json.dumps({"alg": "ES256", "kid": key_id, "typ": "JWT"}, separators=(",", ":")).encode())
        import time
        now = int(time.time())
        payload = _b64(json.dumps({
            "iss": issuer, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1",
        }, separators=(",", ":")).encode())
        signing = f"{header}.{payload}".encode()
        signature = key.sign(signing, ec.ECDSA(hashes.SHA256()))
        raw_r, raw_s = decode_dss_signature(signature)
        joined = raw_r.to_bytes(32, "big") + raw_s.to_bytes(32, "big")
        return signing.decode("ascii") + "." + _b64(joined)
    except HTTPException:
        raise
    except Exception:
        log.info("app store token could not be built")
        _fail("The App Store key could not be used. Check the .p8 file, the key id, and the issuer id.")
    return ""


def _b64(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


HttpFunc = Callable[[str, str, dict[str, str], bytes | None], tuple[int, dict[str, str], Any]]
# Tests replace this. Production leaves it empty and uses App Store Connect directly.
_HTTP: HttpFunc | None = None


def upload_to_apple(ipa: Path, listing: dict[str, Any], *, bundle_id: str, token: str, http: HttpFunc) -> dict[str, Any]:
    """Upload one IPA and submit the approved page. Talks only to Apple."""
    apps = _apple(http, "GET", f"/v1/apps?filter[bundleId]={bundle_id}", token)
    rows = (apps or {}).get("data") or []
    if not rows:
        return {"stopped": True, "submitted": False, "message": (
            "Apple does not have an app with this id yet. Create the app once on the "
            "App Store Connect website, then press Send to Apple again. Nothing was uploaded."
        )}
    app_id = rows[0]["id"]
    version = str(listing.get("version") or "1.0")
    build_no = str(listing.get("build_number") or "1")
    upload = _apple(http, "POST", "/v1/buildUploads", token, {
        "data": {"type": "buildUploads", "attributes": {
            "cfBundleShortVersionString": version, "cfBundleVersion": build_no, "platform": "IOS",
        }, "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}}}
    )
    upload_id = (upload or {}).get("data", {}).get("id")
    blob = ipa.read_bytes()
    file_body = _apple(http, "POST", "/v1/buildUploadFiles", token, {
        "data": {"type": "buildUploadFiles", "attributes": {
            "fileName": ipa.name, "fileSize": len(blob), "uti": "com.apple.ipa", "assetType": "ASSET",
        }, "relationships": {"buildUpload": {"data": {"type": "buildUploads", "id": upload_id}}}}}
    )
    file_id = (file_body or {}).get("data", {}).get("id")
    ops = ((file_body or {}).get("data") or {}).get("attributes", {}).get("uploadOperations") or []
    for op in ops:
        _put_part(http, op, blob)
    digest = hashlib.sha256(blob).hexdigest()
    _apple(http, "PATCH", f"/v1/buildUploadFiles/{file_id}", token, {
        "data": {"type": "buildUploadFiles", "id": file_id, "attributes": {
            "uploaded": True, "sourceFileChecksums": {"file": {"hash": digest, "algorithm": "SHA_256"}},
        }}}
    )
    created = _apple(http, "POST", "/v1/appStoreVersions", token, {
        "data": {"type": "appStoreVersions", "attributes": {"platform": "IOS", "versionString": version},
                 "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}}}
    )
    version_id = (created or {}).get("data", {}).get("id")
    _apple(http, "POST", "/v1/appStoreVersionLocalizations", token, {
        "data": {"type": "appStoreVersionLocalizations", "attributes": {
            "locale": "en-US", "description": listing.get("description") or "",
            "keywords": listing.get("keywords") or "", "subtitle": listing.get("subtitle") or "",
        }, "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": version_id}}}}}
    )
    submission = _apple(http, "POST", "/v1/reviewSubmissions", token, {
        "data": {"type": "reviewSubmissions", "attributes": {"platform": "IOS"},
                 "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}}}
    )
    submission_id = (submission or {}).get("data", {}).get("id")
    _apple(http, "POST", "/v1/reviewSubmissionItems", token, {
        "data": {"type": "reviewSubmissionItems", "relationships": {
            "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": submission_id}},
            "appStoreVersion": {"data": {"type": "appStoreVersions", "id": version_id}},
        }}}
    )
    _apple(http, "PATCH", f"/v1/reviewSubmissions/{submission_id}", token, {
        "data": {"type": "reviewSubmissions", "id": submission_id, "attributes": {"submitted": True}}
    })
    return {"stopped": False, "submitted": True, "app_id": app_id, "upload_id": upload_id,
            "message": "Apple has the app and the page you approved. Apple still has to review it."}


def _apple(http: HttpFunc, method: str, path: str, token: str, body: dict[str, Any] | None = None) -> Any:
    url = APPLE_API + path
    if urlparse(url).hostname != "api.appstoreconnect.apple.com":
        _fail("Refusing to contact a server that is not App Store Connect.")
    raw = None if body is None else json.dumps(body).encode("utf-8")
    status, _headers, payload = http(method, url, {
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
    }, raw)
    if status >= 400:
        _fail("App Store Connect did not accept that step. Nothing else was sent.")
    return payload


def _put_part(http: HttpFunc, op: dict[str, Any], blob: bytes) -> None:
    url = str(op.get("url") or "")
    host = (urlparse(url).hostname or "").lower()
    if not host.endswith(".apple.com") or host_blocked(url):
        _fail("The file upload address from Apple was not an Apple address, so the file was not sent.")
    offset = int(op.get("offset") or 0)
    length = int(op.get("length") or len(blob))
    headers = {item["name"]: item["value"] for item in op.get("requestHeaders") or [] if "name" in item}
    headers.pop("Authorization", None)
    status, _headers, _payload = http("PUT", url, headers, blob[offset:offset + length])
    if status >= 400:
        _fail("Apple did not accept the app file.")


def _urlopen_json(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, dict[str, str], Any]:
    import urllib.request
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310  # nosec B310 - caller checked the host
            raw = response.read()
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            return response.status, dict(response.headers), payload
    except Exception:
        log.info("app store request failed method=%s", method)
        _fail("App Store Connect could not be reached. Nothing else was sent.")
    return 0, {}, {}


def sign_argv(binary: str, ipa: str, certificate: str, key: str, *, windows: bool) -> list[str]:
    cmd = [binary, "sign-appstore", "--ipa", ipa, "--certificate", certificate, "--key", key]
    return ["wsl", "-e", *cmd] if windows else cmd


def devices_argv(binary: str, *, windows: bool) -> list[str]:
    cmd = [binary, "devices", "--no-wait"]
    return ["wsl", "-e", *cmd] if windows else cmd


def build_argv(binary: str, *, windows: bool) -> list[str]:
    cmd = [binary, "dev", "build"]
    return ["wsl", "-e", *cmd] if windows else cmd


class _FakeToolchain:
    def build(self, project: Path) -> dict[str, Any]:
        out = project / "AppStore" / "app.ipa"
        out.parent.mkdir(exist_ok=True)
        out.write_bytes(b"IPA-TEST-DOUBLE")
        return {"ok": True, "test_double": True, "ipa": str(out),
                "message": "A test stand-in built a pretend app. A real iPhone was not used."}

    def install(self, project: Path) -> dict[str, Any]:
        return {"ok": True, "test_double": True, "real_iphone": False,
                "message": "A test stand-in did not install anything on a real iPhone."}

    def devices(self) -> dict[str, Any]:
        return {"devices": [{"name": "Test stand-in", "udid": "FAKE", "connection": "none", "real_iphone": False}],
                "message": "No real iPhone was checked."}

    def sign(self, project: Path) -> dict[str, Any]:
        ipa = project / "AppStore" / "app.ipa"
        if not ipa.is_file():
            ipa.parent.mkdir(exist_ok=True)
            ipa.write_bytes(b"IPA-TEST-DOUBLE")
        return {"ok": True, "test_double": True, "ipa": str(ipa), "apple_signature": False,
                "message": "A test stand-in did not sign this with Apple."}


class _SubprocessToolchain:
    def build(self, project: Path) -> dict[str, Any]:
        return self._run(build_argv(self._bin(), windows=platform.system() == "Windows"), project, "build")

    def install(self, project: Path) -> dict[str, Any]:
        ipa = project / "AppStore" / "app.ipa"
        argv = ["install", str(ipa)]
        binary = self._bin()
        cmd = ["wsl", "-e", binary, *argv] if platform.system() == "Windows" else [binary, *argv]
        return self._run(cmd, project, "install")

    def devices(self) -> dict[str, Any]:
        result = self._run(devices_argv(self._bin(), windows=platform.system() == "Windows"), None, "devices")
        devices = []
        for line in (result.get("output") or "").splitlines():
            if "[" in line and "]" in line:
                devices.append({"name": line.split("[", 1)[0].strip(), "raw": line.strip(), "real_iphone": True})
        result["devices"] = devices
        if not devices:
            result["message"] = "No iPhone is connected. Plug it in, unlock it, and tap Trust."
        return result

    def sign(self, project: Path) -> dict[str, Any]:
        ipa = project / "AppStore" / "app.ipa"
        cert = config.env("AUTOMOTO_ASC_CERT_PATH") or ""
        key = config.env("AUTOMOTO_ASC_KEY_PATH") or ""
        if not cert or not key:
            return {"ok": False, "test_double": False, "message": (
                "Add the App Store certificate file and the key path before signing. Nothing was signed."
            )}
        argv = sign_argv(self._bin(), str(ipa), cert, key, windows=platform.system() == "Windows")
        ran = self._run(argv, project, "sign")
        ran["ipa"] = str(ipa)
        ran["test_double"] = False
        ran["apple_signature"] = bool(ran.get("ok"))
        return ran

    def _bin(self) -> str:
        binary = _binary()
        if not binary:
            _fail(deployment_message()["message"])
        return binary

    def _run(self, argv: list[str], cwd: Path | None, kind: str) -> dict[str, Any]:
        try:
            env = child_env()
            completed = subprocess.run(
                argv, cwd=str(cwd) if cwd else None, env=env, capture_output=True,
                timeout=120, check=False, text=True,
            )
        except (OSError, subprocess.TimeoutExpired):
            log.info("iPhone tool %s did not finish", kind)
            return {"ok": False, "message": "The iPhone tools did not finish. Nothing was sent to Apple."}
        output = (completed.stdout or "")[-2000:]
        if completed.returncode != 0:
            return {"ok": False, "output": output, "message": "The iPhone tools reported a problem. Nothing was sent to Apple."}
        return {"ok": True, "output": output, "message": "The iPhone tools finished this step."}


@router.get("/wizard")
def wizard(request: Request):
    _auth(request)
    return {"steps": wizard_steps(), "deployment": deployment_message()}


@router.get("/status")
def status(request: Request):
    _auth(request)
    return {"deployment": deployment_message(), "artifacts": artifact_report(), "secrets": secret_status()}


@router.post("/secrets")
def secrets(request: Request, body: SecretIn):
    _auth(request)
    return store_secret(body.name, body.value)


@router.post("/setup")
def setup_route(request: Request, body: SetupIn):
    return setup(request, body)


@router.post("/create")
def create_route(request: Request, body: CreateIn):
    return create_app(request, body)


@router.post("/build")
def build_route(request: Request, body: ProjectIn):
    return build_app(request, body)


@router.post("/install")
def install_route(request: Request, body: ProjectIn):
    return install_app(request, body)


@router.get("/devices")
def devices_route(request: Request):
    return devices(request)


@router.post("/listing")
def listing_route(request: Request, body: ListingIn):
    return prepare_listing(request, body)


@router.get("/listing")
def listing_get(request: Request, project: str):
    _auth(request)
    folder = _existing_project(project)
    data = _read_listing(folder)
    return {"listing": data, "listing_sha256": listing_sha(data)}


@router.post("/approve")
def approve_route(request: Request, body: ApproveIn):
    return approve_listing(request, body)


@router.post("/submit")
def submit_route(request: Request, body: SubmitIn):
    return submit_app(request, body)
