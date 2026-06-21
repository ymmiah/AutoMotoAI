"""
Automated security update checker.

On application startup a background daemon thread queries the PyPI JSON
API for every package listed in requirements.txt.  Any package where:
  • the installed version is older than the latest PyPI release, OR
  • the package name appears in a hardcoded critical-security list

is flagged as "outdated" and reported via:
  • A log.warning() entry
  • The GET /api/security/status endpoint (server.py)

The check runs once on startup, then repeats every CHECK_INTERVAL_HOURS.
Results are stored in _report (thread-safe via a lock).

No packages are ever installed automatically — updates are reported only.
Users apply them manually:  pip install --upgrade <package>
"""
from __future__ import annotations

import importlib.metadata
import json
import logging
import os
import re
import threading
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

CHECK_INTERVAL_HOURS: float = float(os.getenv("SECURITY_CHECK_INTERVAL_HOURS", "24"))
_PYPI_API = "https://pypi.org/pypi/{package}/json"
_TIMEOUT  = 10   # seconds per PyPI request

# Packages we treat as security-critical even if a minor bump exists.
_CRITICAL = frozenset({
    "cryptography", "pyotp", "flask", "openai", "anthropic",
    "google-generativeai", "requests", "pillow", "fpdf2",
})

# ── shared state ──────────────────────────────────────────────────────────────

_lock   = threading.Lock()
_report: dict = {
    "last_checked":  None,
    "outdated":      [],    # list of {name, installed, latest, critical}
    "up_to_date":    [],    # list of names
    "errors":        [],    # list of {name, error}
    "check_status":  "pending",
}


def get_report() -> dict:
    with _lock:
        return dict(_report)


# ── version helpers ───────────────────────────────────────────────────────────

def _installed_version(pkg: str) -> str | None:
    try:
        return importlib.metadata.version(pkg)
    except importlib.metadata.PackageNotFoundError:
        return None


def _pypi_latest(pkg: str) -> str | None:
    url = _PYPI_API.format(package=pkg)
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read())
        return data["info"]["version"]
    except Exception as exc:
        logger.debug("PyPI lookup failed for %s: %s", pkg, exc)
        return None


def _parse_requirements(req_file: Path) -> list[str]:
    names: list[str] = []
    for line in req_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip version specifiers: flask>=3.0.0 → flask
        m = re.match(r"^([A-Za-z0-9_\-\.]+)", line)
        if m:
            names.append(m.group(1).lower())
    return names


def _version_tuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split(".")[:4])
    except ValueError:
        return (0,)


# ── check routine ─────────────────────────────────────────────────────────────

def _run_check() -> None:
    req_file = Path(__file__).resolve().parent.parent.parent / "requirements.txt"
    if not req_file.exists():
        with _lock:
            _report["check_status"] = "error"
            _report["errors"].append({"name": "requirements.txt", "error": "file not found"})
        return

    packages = _parse_requirements(req_file)
    outdated: list[dict]  = []
    up_to_date: list[str] = []
    errors: list[dict]    = []

    for pkg in packages:
        installed = _installed_version(pkg)
        if installed is None:
            errors.append({"name": pkg, "error": "not installed"})
            continue

        latest = _pypi_latest(pkg)
        if latest is None:
            errors.append({"name": pkg, "error": "PyPI lookup failed"})
            continue

        if _version_tuple(latest) > _version_tuple(installed):
            entry = {
                "name":      pkg,
                "installed": installed,
                "latest":    latest,
                "critical":  pkg in _CRITICAL,
            }
            outdated.append(entry)
            level = logging.WARNING if entry["critical"] else logging.INFO
            logger.log(level, "Package %s: %s → %s%s",
                       pkg, installed, latest,
                       " [CRITICAL]" if entry["critical"] else "")
        else:
            up_to_date.append(pkg)

    import datetime
    with _lock:
        _report["last_checked"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _report["outdated"]     = outdated
        _report["up_to_date"]   = up_to_date
        _report["errors"]       = errors
        _report["check_status"] = "ok"

    if outdated:
        logger.warning(
            "Security update check: %d package(s) have updates available "
            "(%d critical). Run: pip install --upgrade %s",
            len(outdated),
            sum(1 for e in outdated if e["critical"]),
            " ".join(e["name"] for e in outdated),
        )
    else:
        logger.info("Security update check: all packages up to date.")


def _loop() -> None:
    _run_check()
    while True:
        time.sleep(CHECK_INTERVAL_HOURS * 3600)
        _run_check()


# ── public API ────────────────────────────────────────────────────────────────

def start_background_check() -> None:
    """Spawn a daemon thread that checks for updates on startup and periodically."""
    t = threading.Thread(target=_loop, name="security-updater", daemon=True)
    t.start()
    logger.info("Security update checker started (interval: %.0fh)", CHECK_INTERVAL_HOURS)
