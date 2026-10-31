"""GitHub Release notes and asset names, in one place.

    python scripts/ci/release_notes.py names VERSION              # the file names a release uses (JSON)
    python scripts/ci/release_notes.py notes --repo R --tag T [--out notes.md]   # full notes for a new release
    python scripts/ci/release_notes.py table --repo R --tag T     # only the "Which file do I need?" table
    python scripts/ci/release_notes.py ensure --repo R --tag T    # create the draft release if it's missing

``notes`` and ``table`` read the release's real asset list (and GitHub's SHA-256 digests) with the ``gh`` CLI,
so they also work for older releases with the old file names. Needs GH_TOKEN for ``gh``.
"""

from __future__ import annotations

import json
import re
import subprocess  # nosec B404 - only runs the gh CLI with fixed arguments
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from automoto import brand  # noqa: E402

SITE = brand.HOMEPAGE.rstrip("/")
SLUG = brand.DEFAULT_NAME.replace(" ", "-")  # "AutoMoto-AI"


def names(version: str) -> dict[str, str]:
    """Asset names for a new release. Python files keep the names pip needs."""
    py = re.sub(r"-beta\.(\d+)$", r"b\1", version)
    return {"setup": f"{SLUG}-Setup-{version}-Windows-x64.exe", "msi": f"{SLUG}-{version}-Windows-x64.msi",
            "vsix": f"{SLUG}-{version}-VSCode.vsix", "wheel": f"automoto_ai-{py}-py3-none-any.whl",
            "sdist": f"automoto_ai-{py}.tar.gz", "manifest": "latest.json", "sums": "SHA256SUMS.txt"}


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout  # nosec B603 B607


def assets(repo: str, tag: str) -> list[dict]:
    data = json.loads(gh("release", "view", tag, "--repo", repo, "--json", "assets"))  # also sees drafts
    return [{"name": a["name"], "size": a["size"], "digest": (a.get("digest") or "").removeprefix("sha256:")}
            for a in data.get("assets", [])]


def kind(name: str) -> str:
    n = name.lower()
    if n.endswith(".sig") or n == "latest.json":
        return "updater"
    if n.startswith("sha256sums"):
        return "sums"
    if n.endswith(".exe"):
        return "setup"
    for ext, k in ((".msi", "msi"), (".vsix", "vsix"), (".whl", "wheel"), (".tar.gz", "sdist")):
        if n.endswith(ext):
            return k
    return "other"


def table(repo: str, tag: str, files: list[dict]) -> str:
    by: dict[str, str] = {}
    for f in files:
        by.setdefault(kind(f["name"]), f["name"])
    url = lambda n: f"https://github.com/{repo}/releases/download/{tag}/{n}"  # noqa: E731
    link = lambda k: f"[`{by[k]}`]({url(by[k])})" if k in by else None  # noqa: E731
    rows = []
    rows.append(("**Windows 10/11** (most people)", link("setup") or
                 f"no Windows app in this version: see the [newer releases](https://github.com/{repo}/releases)",
                 "Double-click it. Installs just for you, no admin rights." if "setup" in by else
                 "Or use the Python file below with `scripts/install.ps1`."))
    if "msi" in by:
        rows.append(("**Windows, IT / company PCs** (Intune, Group Policy, all users)", link("msi"),
                     "`msiexec /i <file> /qn` for a silent install."))
    if "vsix" in by:
        rows.append(("**VS Code**", link("vsix"), "Extensions panel → `…` → *Install from VSIX…*"))
    if "wheel" in by:
        rows.append(("**Python 3.10+** (command line, any OS)", link("wheel"),
                     f"`pip install {url(by['wheel'])}`"))
    rows.append(("**Mac, Linux, phone or tablet**", f"[Start here: pick your device]({SITE}/START.html)",
                 "No download needed for phones: sign in from the browser."))
    out = ["## Which file do I need?", "", "| You have | Download | How |", "|---|---|---|"]
    out += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    extra = [n for n, k in ((by.get("sdist"), "the Python source package"), ) if n]
    out += ["", "You can ignore the other files: `.sig` files and `latest.json` are used by the app's automatic "
            "updates, `SHA256SUMS.txt` lists checksums" + (f", and `{extra[0]}` is the Python source package." if extra
                                                             else ".")]
    return "\n".join(out)


def changelog(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(version)}\b.*?$(.*?)(?=^## )", text, re.M | re.S)
    if not m:
        return "See the [CHANGELOG](https://github.com/{repo}/blob/main/CHANGELOG.md)."
    body = m.group(1).strip()
    return body.replace("### ", "#### ")


def checksums(files: list[dict]) -> str:
    rows = [f"{f['digest']}  {f['name']}" for f in sorted(files, key=lambda f: f["name"].lower())
            if f["digest"] and kind(f["name"]) not in ("updater",)]
    return "## Checksums (SHA-256)\n\n```\n" + "\n".join(rows) + "\n```" if rows else ""


def notes(repo: str, tag: str) -> str:
    version = tag.removeprefix("v")
    files = assets(repo, tag)
    beta = re.search(r"-beta\.(\d+)$", version)
    head = (f"**{brand.DEFAULT_NAME} {version}**" + (" is a **pre-release** for testers. The stable version stays the "
                                                     "latest release." if beta else "."))
    parts = [head, table(repo, tag, files), "## What's new", changelog(version).replace("{repo}", repo),
             checksums(files),
             f"Privacy policy: [{SITE}/PRIVACY.html]({SITE}/PRIVACY.html) · "
             f"Full history: [CHANGELOG](https://github.com/{repo}/blob/main/CHANGELOG.md)"]
    return "\n\n".join(p for p in parts if p) + "\n"


def ensure(repo: str, tag: str) -> None:
    """Create the release as a draft (a pre-release for -beta.N) unless it exists. Safe to run from two jobs."""
    version = tag.removeprefix("v")
    for attempt in range(3):
        if subprocess.run(["gh", "release", "view", tag, "--repo", repo], capture_output=True).returncode == 0:  # nosec
            return
        flags = ["--draft", "--verify-tag"]
        title = f"{brand.DEFAULT_NAME} {version}"
        m = re.search(r"^(.*)-beta\.(\d+)$", version)
        if m:
            flags += ["--prerelease", "--latest=false"]
            title = f"{brand.DEFAULT_NAME} {m.group(1)} Beta {m.group(2)}"
        r = subprocess.run(["gh", "release", "create", tag, "--repo", repo, *flags, "--title", title,  # nosec B603 B607
                            "--notes", f"{brand.DEFAULT_NAME} {version}. Files are being attached."],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return
        time.sleep(10 * (attempt + 1))  # the other workflow may be creating it right now
    raise SystemExit(f"could not create release {tag}")


def main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["names", "notes", "table", "ensure"])
    ap.add_argument("version", nargs="?")
    ap.add_argument("--repo")
    ap.add_argument("--tag")
    ap.add_argument("--out", help="write UTF-8 to this file instead of stdout (Windows consoles aren't UTF-8)")
    a = ap.parse_args(argv)
    if a.cmd == "ensure":
        ensure(a.repo, a.tag)
        return 0
    if a.cmd == "names":
        text = json.dumps(names(a.version)) + "\n"
    elif a.cmd == "table":
        text = table(a.repo, a.tag, assets(a.repo, a.tag)) + "\n"
    else:
        text = notes(a.repo, a.tag)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
