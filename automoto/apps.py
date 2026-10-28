"""Local apps the agent can drive - only through each app's official automation route.

* **CLI apps** (ffmpeg, ImageMagick, Inkscape, LibreOffice headless, Tectonic/pdflatex, git,
  VS Code ``code`` …) run with ``run_app``: an argument list, never a shell, inside the
  working folder, with secret-free environment variables, a timeout, and path checks on every
  argument (sensitive paths and anything outside your allowed folders are refused).
* **GUI apps** (Photoshop, Illustrator, Premiere Pro, AutoCAD, GIMP, Blender …) can be opened
  with a file (``open_in_app``), and where the vendor supports scripting, run a script you can
  read first (``run_app_script``): Photoshop / Illustrator ExtendScript via COM (Windows) or
  AppleScript ``do javascript`` (macOS), AutoCAD ``accoreconsole`` with a ``.scr`` (Windows),
  Blender ``--background --python``, GIMP Script-Fu batch mode.
* Every call is **risky** (needs your approval). Nothing here bypasses licensing: apps must be
  installed and licensed by you, and AutoMoto only calls them the way their vendor documents.

``status`` says how well each route is verified: ``live`` (exercised on a real machine),
``unit`` (unit-tested with fakes) or ``untested`` (no licensed copy available to test with).
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from automoto import sandbox

OS = "windows" if sys.platform == "win32" else "macos" if sys.platform == "darwin" else "linux"


@dataclass
class App:
    id: str
    name: str
    category: str
    bins: dict[str, list[str]]  # os -> executable names (PATH) or glob paths
    cli: bool = True            # can run headless with run_app
    script: str = ""            # run_app_script route: jsx | acad | blender | gimp
    status: str = "unit"        # live | unit | untested
    note: str = ""
    deny: list[str] = field(default_factory=list)  # regexes for forbidden arguments

    def public(self, path: str | None) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "category": self.category, "installed": bool(path),
                "path": path, "cli": self.cli, "script": self.script or None, "status": self.status,
                "note": self.note}


_NET = r"^[a-z][a-z0-9+.-]*://"  # no network URLs: downloads go through fetch_url and the SSRF guard
PF = "C:/Program Files"

CATALOG: list[App] = [
    # -- media & design -------------------------------------------------------------------
    App("ffmpeg", "FFmpeg", "video/audio", {"*": ["ffmpeg"]}, status="live",
        note="trim, concat, resize, compress, subtitles, audio convert/normalise",
        deny=[_NET, r"^(tcp|udp|rtmp|rtp|srt|ftp|http|https|concat|subfile|pipe):", r"^-safe$"]),
    App("ffprobe", "FFprobe", "video/audio", {"*": ["ffprobe"]}, status="live", deny=[_NET]),
    App("sox", "SoX", "audio", {"*": ["sox"]}, status="unit", note="audio effects; ffmpeg covers most of it"),
    App("imagemagick", "ImageMagick", "graphics", {"windows": ["magick"], "*": ["magick", "convert"]}, status="live",
        note="resize, convert, compose, text", deny=[_NET, r"@", r"^(msl|ephemeral|mvg|url|text|label):"]),
    App("inkscape", "Inkscape", "graphics", {"*": ["inkscape"], "windows": ["inkscape", f"{PF}/Inkscape/bin/inkscape.exe"],
        "macos": ["inkscape", "/Applications/Inkscape.app/Contents/MacOS/inkscape"]}, status="unit",
        note="SVG → PNG/PDF export (inkscape in.svg --export-type=png)", deny=[_NET]),
    App("gimp", "GIMP", "graphics", {"linux": ["gimp-console", "gimp-console-2.10", "gimp", "gimp-2.10"],
        "windows": [f"{PF}/GIMP 2/bin/gimp-console-2.10.exe", f"{PF}/GIMP 3/bin/gimp-console-3.0.exe"],
        "macos": ["/Applications/GIMP*.app/Contents/MacOS/gimp"]}, script="gimp", status="untested",
        note="Script-Fu batch mode (gimp -i -b ...)"),
    App("blender", "Blender", "3d/video", {"*": ["blender"], "windows": ["blender", f"{PF}/Blender Foundation/Blender*/blender.exe"],
        "macos": ["blender", "/Applications/Blender.app/Contents/MacOS/Blender"]}, script="blender", status="untested",
        note="headless Python scripts (blender -b file.blend --python script.py)"),
    App("libreoffice", "LibreOffice", "documents", {"*": ["soffice", "libreoffice"],
        "windows": ["soffice", f"{PF}/LibreOffice/program/soffice.exe"],
        "macos": ["soffice", "/Applications/LibreOffice.app/Contents/MacOS/soffice"]}, status="live",
        note="headless convert: soffice --headless --convert-to pdf file.docx",
        deny=[_NET, r"^(macro|vnd\.sun\.star\.script):", r"^--accept", r"^-env:"]),
    App("pandoc", "Pandoc", "documents", {"*": ["pandoc"]}, status="unit", deny=[_NET, r"^--lua-filter", r"^--filter"]),
    App("tectonic", "Tectonic (LaTeX)", "documents", {"*": ["tectonic"]}, status="live",
        note="self-contained LaTeX engine; downloads packages on first use", deny=[r"^-Z\s*shell-escape", r"shell-escape"]),
    App("pdflatex", "pdfLaTeX", "documents", {"*": ["pdflatex"]}, status="unit", deny=[r"shell-escape", r"^-enable-write18"]),
    App("latexmk", "latexmk", "documents", {"*": ["latexmk"]}, status="unit", deny=[r"shell-escape", r"^-e$"]),
    # -- dev tools --------------------------------------------------------------------------
    App("vscode", "VS Code CLI", "dev", {"*": ["code", "code-insiders"],
        "macos": ["code", "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"],
        "windows": ["code", os.path.expandvars("%LOCALAPPDATA%/Programs/Microsoft VS Code/bin/code.cmd")]},
        status="unit", note="open files (code -g file:line), diff, list extensions",
        deny=[r"^--(un)?install-extension", r"^--(user-data|extensions)-dir", r"^(tunnel|serve-web)$", r"^--enable-proposed-api"]),
    App("git", "Git", "dev", {"*": ["git"]}, status="live", note="status, diff, log, add, commit, branch, push (with approval)",
        deny=[r"^-c$", r"^--config-env", r"^-c.+=", r"--upload-pack", r"--receive-pack", r"core\.sshCommand",
              r"^--(global|system)$", r"^credential", r"^config$", r"--exec(=|$)", r"^-u$"]),
    App("gh", "GitHub CLI", "dev", {"*": ["gh"]}, status="unit", deny=[r"^auth$", r"^secret$", r"^ssh-key$", r"^gpg-key$",
        r"^extension$", r"^codespace$", r"^alias$", r"^config$"]),
    App("glab", "GitLab CLI", "dev", {"*": ["glab"]}, status="unit", deny=[r"^auth$", r"^variable$", r"^ssh-key$", r"^config$"]),
    App("vercel", "Vercel CLI", "dev", {"*": ["vercel"]}, status="unit", deny=[r"^login$", r"^logout$", r"^env$", r"^--token"]),
    App("node", "Node.js", "dev", {"*": ["node"]}, status="live"),
    App("npm", "npm", "dev", {"*": ["npm"], "windows": ["npm.cmd", "npm"]}, status="live", deny=[r"^(adduser|login|publish|token|owner)$"]),
    App("python", "Python", "dev", {"windows": ["python", "py"], "*": ["python3", "python"]}, status="live"),
    App("go", "Go", "dev", {"*": ["go"]}, status="live"),
    App("cargo", "Rust (cargo)", "dev", {"*": ["cargo"]}, status="unit", deny=[r"^(login|publish|owner|yank)$"]),
    App("flutter", "Flutter", "dev", {"*": ["flutter"], "windows": ["flutter.bat", "flutter"]}, status="untested"),
    App("docker", "Docker", "dev", {"*": ["docker"]}, status="unit", deny=[r"^--privileged", r"^-v$", r"^--volume", r"^--mount",
        r"^(login|push|logout)$", r"^--pid=host", r"^--network=host", r"/var/run/docker\.sock"]),
    # -- licensed GUI apps (open + official scripting only) -----------------------------------
    App("photoshop", "Adobe Photoshop", "graphics", {
        "windows": [f"{PF}/Adobe/Adobe Photoshop*/Photoshop.exe"],
        "macos": ["/Applications/Adobe Photoshop*/Adobe Photoshop*.app"]}, cli=False, script="jsx", status="untested",
        note="ExtendScript (.jsx) via COM DoJavaScriptFile (Windows) or AppleScript do javascript (macOS)"),
    App("illustrator", "Adobe Illustrator", "graphics", {
        "windows": [f"{PF}/Adobe/Adobe Illustrator*/Support Files/Contents/Windows/Illustrator.exe"],
        "macos": ["/Applications/Adobe Illustrator*/Adobe Illustrator*.app"]}, cli=False, script="jsx", status="untested",
        note="ExtendScript (.jsx) via COM DoJavaScriptFile (Windows) or AppleScript do javascript (macOS)"),
    App("premiere", "Adobe Premiere Pro", "video", {
        "windows": [f"{PF}/Adobe/Adobe Premiere Pro*/Adobe Premiere Pro.exe"],
        "macos": ["/Applications/Adobe Premiere Pro*/Adobe Premiere Pro*.app"]}, cli=False, status="untested",
        note="open projects/media only. Premiere scripting needs a UXP/CEP panel inside the app, so it is not automated"),
    App("autocad", "AutoCAD", "cad", {
        "windows": [f"{PF}/Autodesk/AutoCAD*/acad.exe"],
        "macos": ["/Applications/Autodesk/AutoCAD*/AutoCAD*.app"]}, cli=False, script="acad", status="untested",
        note="Windows: accoreconsole.exe /i drawing.dwg /s script.scr (official core console). macOS: open only"),
    App("figma", "Figma desktop", "design", {"windows": [os.path.expandvars("%LOCALAPPDATA%/Figma/Figma.exe")],
        "macos": ["/Applications/Figma.app"]}, cli=False, status="untested", note="open only - use the Figma connector for data"),
    App("canva", "Canva desktop", "design", {"windows": [os.path.expandvars("%LOCALAPPDATA%/Programs/Canva/Canva.exe")],
        "macos": ["/Applications/Canva.app"]}, cli=False, status="untested", note="open only - use the Canva connector"),
]
BY_ID = {a.id: a for a in CATALOG}
_CACHE: dict[str, Any] = {"t": 0.0, "found": {}}


def _candidates(app: App) -> list[str]:
    return app.bins.get(OS) or app.bins.get("*", [])


def locate(app: App) -> str | None:
    for c in _candidates(app):
        if any(ch in c for ch in "/\\"):
            hits = sorted(glob.glob(os.path.expanduser(c)), reverse=True)  # newest version first
            if hits:
                return hits[0]
        else:
            w = shutil.which(c)
            if w:
                return w
    return None


def detect(refresh: bool = False) -> dict[str, str | None]:
    """{app id: path or None}, cached for a minute."""
    if refresh or time.time() - _CACHE["t"] > 60:
        _CACHE["found"] = {a.id: locate(a) for a in CATALOG}
        _CACHE["t"] = time.time()
    return dict(_CACHE["found"])


def available(app_id: str) -> bool:
    return bool(detect().get(app_id))


def listing() -> list[dict[str, Any]]:
    found = detect()
    return [a.public(found.get(a.id)) for a in CATALOG]


class AppError(Exception):
    pass


def _get(app_id: str) -> tuple[App, str]:
    app = BY_ID.get(str(app_id or "").lower())
    if not app:
        raise AppError(f"unknown app '{app_id}'. Known: {', '.join(BY_ID)}")
    path = detect().get(app.id)
    if not path:
        raise AppError(f"{app.name} is not installed on this computer (or not on PATH)")
    return app, path


_PATHISH = re.compile(r"^(~|/|\\\\|[A-Za-z]:[\\/]|\.\.?[\\/])|[\\/]")


def check_args(app: App, args: list[str]) -> list[str]:
    """Refuse forbidden flags and any path-like argument outside the allowed folders."""
    if not isinstance(args, list) or len(args) > 200:
        raise AppError("args must be a list of strings (max 200)")
    out: list[str] = []
    for a in args:
        a = str(a)
        if "\x00" in a or len(a) > 4000:
            raise AppError("bad argument")
        for rx in app.deny:
            if re.search(rx, a, re.I):
                raise AppError(f"argument '{a[:60]}' is not allowed for {app.name}")
        value = a.split("=", 1)[1] if a.startswith("-") and "=" in a else a
        for part in re.split(r"[;,]", value) if app.id == "ffmpeg" else [value]:
            part = part.strip().strip("'\"")
            part = re.sub(r"^[a-z_]+=", "", part)  # ffmpeg filter options like subtitles=subs.srt
            if part and _PATHISH.search(part) and "://" not in part and not part.startswith("-"):
                try:
                    sandbox.resolve(part, allow_outside=True)
                except sandbox.SandboxError as exc:
                    raise AppError(f"path argument refused: {exc}") from None
        out.append(a)
    return out


def _env() -> dict[str, str]:
    return sandbox.clean_env()


def _run(argv: list[str], timeout: int) -> str:
    kw: dict[str, Any] = {}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kw["start_new_session"] = True
    try:
        proc = subprocess.Popen(argv, cwd=str(sandbox.root()), env=_env(), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace", **kw)
    except OSError as exc:
        raise AppError(f"cannot start {Path(argv[0]).name}: {exc}") from None
    try:
        out, err = proc.communicate(timeout=timeout)
        code: int | None = proc.returncode
        note = ""
    except subprocess.TimeoutExpired:
        sandbox._kill_tree(proc)
        out, err = "", ""
        code, note = None, f"\n[timed out after {timeout}s - process killed]"
    text = ((out or "") + ("\n" + err if err else "")).strip()
    if len(text) > sandbox.MAX_OUTPUT:
        text = "[…truncated…]\n" + text[-sandbox.MAX_OUTPUT:]
    return f"exit {code}\n{text or '(no output)'}{note}"


def _timeout(t: int | None, default: int = 300) -> int:
    try:
        return max(1, min(1800, int(t or default)))
    except (TypeError, ValueError):
        return default


def run_app(app_id: str, args: list[str], timeout: int | None = None) -> str:
    app, path = _get(app_id)
    if not app.cli:
        raise AppError(f"{app.name} has no supported command line - use open_in_app or run_app_script")
    argv = [path, *check_args(app, args)]
    if sys.platform == "win32" and path.lower().endswith((".cmd", ".bat")):
        if any(re.search(r'[&|<>^%"]', a) for a in argv[1:]):
            raise AppError("arguments with & | < > ^ % or quotes can't be passed safely to a .cmd/.bat program")
        argv = ["cmd", "/c", *argv]
    return f"[{app.name}] " + _run(argv, _timeout(timeout))


def open_in_app(app_id: str, path: str) -> str:
    app, exe = _get(app_id)
    target = sandbox.resolve(path, allow_outside=True)
    if not target.exists():
        raise AppError(f"no such file: {path}")
    if OS == "macos" and exe.endswith(".app"):
        argv = ["open", "-a", exe, str(target)]
    elif app.id == "vscode":
        argv = [exe, "--goto", str(target)]
    else:
        argv = [exe, str(target)]
    if sys.platform == "win32" and exe.lower().endswith((".cmd", ".bat")):
        argv = ["cmd", "/c", *argv]
    try:
        subprocess.Popen(argv, cwd=str(sandbox.root()), env=_env(), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         **({"start_new_session": True} if sys.platform != "win32" else {}))
    except OSError as exc:
        raise AppError(f"cannot open {app.name}: {exc}") from None
    return f"opened {target.name} in {app.name}"


def script_argv(app: App, exe: str, script: Path, target: Path | None) -> list[str]:
    """The official command line for running ``script`` in ``app`` on this OS."""
    s = str(script)
    if app.script == "jsx":
        if OS == "windows":
            prog = {"photoshop": "Photoshop.Application", "illustrator": "Illustrator.Application"}[app.id]
            q = s.replace("'", "''")
            return ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                    f"$a = New-Object -ComObject {prog}; $a.DoJavaScriptFile('{q}') | Out-String"]
        if OS == "macos":
            bundle = {"photoshop": "com.adobe.Photoshop", "illustrator": "com.adobe.illustrator"}[app.id]
            return ["osascript", "-e", "on run argv", "-e",
                    f'tell application id "{bundle}" to do javascript file (POSIX file (item 1 of argv))',
                    "-e", "end run", s]
        raise AppError(f"{app.name} scripting is only available on Windows and macOS")
    if app.script == "acad":
        if OS != "windows":
            raise AppError("AutoCAD scripting (accoreconsole) is Windows-only; on macOS AutoMoto can only open drawings")
        core = str(Path(exe).with_name("accoreconsole.exe"))
        if not Path(core).exists():
            raise AppError("accoreconsole.exe not found next to acad.exe")
        if not target:
            raise AppError("AutoCAD scripts need a drawing: pass target=drawing.dwg")
        return [core, "/i", str(target), "/s", s, "/l", "en-US"]
    if app.script == "blender":
        return [exe, "-b", *([str(target)] if target else []), "--python", s]
    if app.script == "gimp":
        esc = s.replace("\\", "\\\\").replace('"', '\\"')
        return [exe, "-i", "-b", f'(load "{esc}")', "-b", "(gimp-quit 0)"]
    raise AppError(f"{app.name} has no supported scripting route")


def run_app_script(app_id: str, script: str, target: str | None = None, timeout: int | None = None) -> str:
    app, exe = _get(app_id)
    sp = sandbox.resolve(script, allow_outside=True)
    if not sp.is_file():
        raise AppError(f"no such script: {script}")
    tp = sandbox.resolve(target, allow_outside=True) if target else None
    if tp is not None and not tp.exists():
        raise AppError(f"no such file: {target}")
    return f"[{app.name} script] " + _run(script_argv(app, exe, sp, tp), _timeout(timeout, 600))
