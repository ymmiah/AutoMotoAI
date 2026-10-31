"""Release file names and the "Which file do I need?" table (scripts/ci/release_notes.py)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_notes", ROOT / "scripts/ci/release_notes.py")
rn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rn)


def test_names_beta_and_stable():
    n = rn.names("5.6.0-beta.4")
    assert n["setup"] == "AutoMoto-AI-Setup-5.6.0-beta.4-Windows-x64.exe"
    assert n["msi"] == "AutoMoto-AI-5.6.0-beta.4-Windows-x64.msi"
    assert n["vsix"] == "AutoMoto-AI-5.6.0-beta.4-VSCode.vsix"
    assert n["wheel"] == "automoto_ai-5.6.0b4-py3-none-any.whl"
    assert rn.names("5.7.0")["sdist"] == "automoto_ai-5.7.0.tar.gz"
    for v in n.values():
        assert " " not in v  # GitHub would turn spaces into dots


def test_kind_old_and_new_names():
    assert rn.kind("AutoMoto-AI_5.6.0-beta.3_x64-setup.exe") == "setup"
    assert rn.kind("AutoMoto-AI-Setup-5.6.0-beta.4-Windows-x64.exe") == "setup"
    assert rn.kind("AutoMoto-AI-Setup-5.6.0-beta.4-Windows-x64.exe.sig") == "updater"
    assert rn.kind("latest.json") == "updater"
    assert rn.kind("automoto-ai-5.5.0.vsix") == "vsix"
    assert rn.kind("automoto_ai-5.5.0.tar.gz") == "sdist"
    assert rn.kind("SHA256SUMS.txt") == "sums"


def test_table_and_checksums():
    files = [{"name": x, "size": 1, "digest": "ab" * 32} for x in rn.names("5.6.0-beta.4").values()]
    files.append({"name": "AutoMoto-AI-Setup-5.6.0-beta.4-Windows-x64.exe.sig", "size": 1, "digest": "cd" * 32})
    t = rn.table("o/r", "v5.6.0-beta.4", files)
    assert t.startswith("## Which file do I need?")
    assert "releases/download/v5.6.0-beta.4/AutoMoto-AI-Setup-5.6.0-beta.4-Windows-x64.exe" in t
    assert "Windows-x64.msi" in t and "VSCode.vsix" in t and "pip install" in t and "START.html" in t
    c = rn.checksums(files)
    assert "ab" * 32 + "  AutoMoto-AI-5.6.0-beta.4-Windows-x64.msi" in c
    assert ".sig" not in c


def test_table_without_windows_app():
    t = rn.table("o/r", "v5.5.0", [{"name": "automoto_ai-5.5.0-py3-none-any.whl", "size": 1, "digest": ""}])
    assert "no Windows app in this version" in t


def test_changelog_section_found():
    text = rn.changelog("5.6.0-beta.3")
    assert text and "CHANGELOG" not in text[:40]


def test_branding_text_files_up_to_date():
    """installer-hooks.nsh and LICENSE-installer.txt come from brand.py."""
    import subprocess
    import sys

    import pytest

    pytest.importorskip("PIL")
    r = subprocess.run([sys.executable, "packaging/branding/generate.py", "--check"], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
