"""Product display name in ONE place ("AutoMoto" is a temporary name).

Change the defaults here, or set ``AUTOMOTO_BRAND_NAME`` / ``AUTOMOTO_BRAND_SHORT`` in the environment
or .env, and every new UI string, page title, prompt and doc snippet follows. The Python package, the
``automoto`` command, env-var prefixes, installers and bundle IDs are deliberately NOT renamed by this.
"""

from __future__ import annotations

import html
import os

DEFAULT_NAME = "AutoMoto AI"
DEFAULT_SHORT = "AutoMoto"

# Installer / Windows app branding (packaging/branding/generate.py reads these; re-run it after a change)
PUBLISHER = "Yasin Mohammed Miah"
CREDIT = "Yasin Mohammed Miah, Student of BCU, BSc Computing Top-Up (Hons)"
TAGLINE = "The AI agent that does the work, and asks before anything risky"
HOMEPAGE = "https://ymmiah.github.io/AutoMotoAI/"
REPO_URL = "https://github.com/ymmiah/AutoMotoAI"
SUPPORT_URL = REPO_URL + "/issues"
COLORS = {"bg": "#0a0d12", "bg2": "#0e1219", "panel": "#131922", "line": "#222c39", "text": "#e8edf3",
          "dim": "#93a0ae", "accent": "#38f2a5", "accent2": "#7c5cff", "on_accent": "#04110b"}


def name() -> str:
    """Full display name, e.g. 'AutoMoto AI'."""
    return (os.getenv("AUTOMOTO_BRAND_NAME") or "").strip()[:60] or DEFAULT_NAME


def short() -> str:
    """Short name used in sentences, e.g. 'AutoMoto can make mistakes'."""
    v = (os.getenv("AUTOMOTO_BRAND_SHORT") or "").strip()[:40]
    if v:
        return v
    n = name()
    return DEFAULT_SHORT if n == DEFAULT_NAME else n


def fill(text: str, *, escape: bool = True) -> str:
    """Replace ``__BRAND__`` / ``__BRAND_SHORT__`` placeholders (HTML-escaped by default)."""
    f = html.escape if escape else (lambda s: s)
    return text.replace("__BRAND_SHORT__", f(short())).replace("__BRAND__", f(name()))
