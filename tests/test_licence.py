"""AGPL-3.0 relicensing: licence files, metadata and the web UI's "Source code" link (AGPL section 13)."""

import json
from pathlib import Path

from automoto import brand

ROOT = Path(__file__).resolve().parents[1]


def test_licence_files_and_metadata():
    lic = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert lic.lstrip().startswith("GNU AFFERO GENERAL PUBLIC LICENSE") and "Version 3, 19 November 2007" in lic
    assert "13. Remote Network Interaction; Use with the GNU General Public License." in lic
    assert (ROOT / "apps/vscode/LICENSE").read_text(encoding="utf-8") == lic
    assert "Copyright (C) 2025-2026 Yasin Mohammed Miah" in (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert 'license = "AGPL-3.0-only"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert json.loads((ROOT / "apps/vscode/package.json").read_text(encoding="utf-8"))["license"] == "AGPL-3.0-only"
    conf = json.loads((ROOT / "apps/desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    assert conf["bundle"]["license"] == "AGPL-3.0-only"
    assert 'license = "AGPL-3.0-only"' in (ROOT / "apps/desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8")


def test_source_url(monkeypatch):
    monkeypatch.delenv("AUTOMOTO_SOURCE_URL", raising=False)
    assert brand.source_url() == brand.REPO_URL
    monkeypatch.setenv("AUTOMOTO_SOURCE_URL", "https://git.example.org/me/automoto-fork")
    assert brand.source_url() == "https://git.example.org/me/automoto-fork"
    monkeypatch.setenv("AUTOMOTO_SOURCE_URL", "javascript:alert(1)")
    assert brand.source_url() == brand.REPO_URL
    monkeypatch.setenv("AUTOMOTO_SOURCE_URL", 'https://x.example/"><script>')
    assert '"><script>' not in brand.fill('<a href="__SOURCE_URL__">')


def test_web_pages_link_to_source():
    for page in ("index.html", "login.html"):
        html = (ROOT / "automoto/web" / page).read_text(encoding="utf-8")
        assert '<a href="__SOURCE_URL__"' in html and "Source code" in html
        assert "__SOURCE_URL__" not in brand.fill(html)
