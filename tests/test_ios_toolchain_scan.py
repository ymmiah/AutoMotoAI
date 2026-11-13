"""The vendored iPhone toolchain must not name hosts it used to contact."""

import subprocess
import sys
from pathlib import Path

from automoto.ios_toolchain_scan import ROOT, hits

NOTICE_MARKERS = (
    "xtool-org",
    "sidestore",
    "jkcoxson",
)


def test_vendored_tree_has_no_forbidden_hosts():
    assert ROOT.is_dir()
    assert hits(ROOT) == []


def test_notice_keeps_the_mit_attribution():
    text = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "MIT Licence" in text
    assert "Copyright (c) 2024 Kabir Oberai" in text
    for marker in NOTICE_MARKERS:
        assert marker in text


def test_support_files_are_not_downloaded_until_published():
    import json
    lock = json.loads((ROOT / "Artifacts.json").read_text(encoding="utf-8"))
    assert lock["base_url"].startswith("https://github.com/ymmiah/AutoMotoAI/")
    for name in ("darwin-tools-aarch64", "darwin-tools-x86_64",
                 "open-apple-macros-aarch64", "open-apple-macros-x86_64"):
        assert lock["artifacts"][name]["sha256"] == ""
    swift = (ROOT / "Sources" / "XToolSupport" / "AutomotoArtifacts.swift").read_text(encoding="utf-8")
    assert "will not download" in swift or "not published" in swift
    package = (ROOT / "Package.swift").read_text(encoding="utf-8")
    assert 'path: "Vendor/xtool-core"' in package
    assert 'name: "automoto-ios"' in package


def test_upstream_sync_is_disabled_and_does_not_merge():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "ios_toolchain_sync.py"
    text = script.read_text(encoding="utf-8")
    assert "never merges" in text
    assert "gh pr merge" not in text and "git merge" not in text
    completed = subprocess.run([sys.executable, str(script)], cwd=root, capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    assert "disabled" in completed.stdout
    assert "never merges" in completed.stdout


def test_a_planted_host_is_reported(tmp_path: Path):
    tree = tmp_path / "ios-toolchain"
    tree.mkdir()
    (tree / "NOTICE").write_text("xtool-org is allowed only here\n", encoding="utf-8")
    (tree / "App.swift").write_text("let host = \"mac-ani.jkcoxson.com\"\n", encoding="utf-8")
    found = hits(tree)
    assert len(found) == 1 and "App.swift:1" in found[0]
    assert hits(tree) and "NOTICE" not in found[0]
