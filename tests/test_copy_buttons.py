"""Shared, accessible copy button used across the whole app (automoto/web/static/copy.js)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "automoto" / "web"
STATIC = WEB / "static"


def test_copy_component_is_loaded_everywhere():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert '/static/copy.css?v=' in html
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'from "./copy.js"' in app and "installCopyButtons(document.body)" in app
    # Chat code blocks use the shared button, not their own markup.
    assert "copyButton({ getText: () => code.textContent" in app
    assert 'aria-label="Copy code" title="Copy">${icon("copy")}</button>' not in app


def test_only_the_shared_component_touches_the_clipboard():
    offenders = []
    for js in STATIC.glob("*.js"):
        if js.name == "copy.js":
            continue
        text = js.read_text(encoding="utf-8")
        if "clipboard.writeText" in text or 'execCommand("copy")' in text:
            offenders.append(js.name)
    assert offenders == []


def test_copy_button_accessibility_and_safety_rules():
    js = (STATIC / "copy.js").read_text(encoding="utf-8")
    css = (STATIC / "copy.css").read_text(encoding="utf-8")
    assert 'btn.type = "button"' in js and 'setAttribute("aria-label", "Copy " + label)' in js
    assert 'setAttribute("aria-live", "polite")' in js and '"Copied"' in js
    for skip in ("[data-sensitive]", "[data-no-copy]", "input", "textarea", "contenteditable"):
        assert skip in js
    assert "looksSecret(text)" in js
    # Always visible (no hover-only rule), keyboard focus ring, 44px touch targets, sticky in scrolling boxes.
    assert ":hover .copy-btn" not in css and "opacity:0" not in css.replace(" ", "")
    assert ".copy-btn:focus-visible" in css
    assert re.search(r"@media \(pointer:coarse\)\{[^}]*width:44px;height:44px", css)
    assert ".copy-anchor{position:sticky" in css


def test_paths_and_commands_are_marked_copyable():
    run = (STATIC / "developer-run.js").read_text(encoding="utf-8")
    assert 'command.dataset.copy=""' in run and "cmd.dataset.copy=run.command" in run and 'url.dataset.copy=""' in run
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert '<code data-copy="" data-copy-label="workspace folder path">' in app


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_secret_detection_and_copy_text(tmp_path):
    for name in ("copy.js", "icons.js"):
        (tmp_path / name).write_text((STATIC / name).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    secrets = [
        "ghp_" + "a" * 36, "github_pat_" + "B" * 40, "glpat-" + "c" * 20, "sk-" + "d" * 32, "sk-ant-" + "e" * 40,
        "sk_live_" + "f" * 24, "xoxb-" + "1" * 20, "AKIA" + "ABCDEFGHIJKLMNOP", "AIza" + "g" * 35, "hf_" + "h" * 34,
        "-----BEGIN OPENSSH PRIVATE KEY-----",
    ]
    safe = ["npm test", "python -m pytest -q", "C:\\Users\\me\\Documents", "sha256:" + "0" * 64,
            "550e8400-e29b-41d4-a716-446655440000", "git push origin main", "task-ask-prefix"]
    script = (
        f"import {{looksSecret, copyableText}} from {json.dumps((tmp_path / 'copy.js').as_uri())};"
        f"const s={json.dumps(secrets)}, k={json.dumps(safe)};"
        "console.log(JSON.stringify({secret:s.map(looksSecret), safe:k.map(looksSecret),"
        "trim:copyableText('a\\r\\nb\\n\\n'), prompt:copyableText('$ npm i\\n> npm test\\nPS C:\\\\x> dir',{prompt:true})}));"
    )
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60, check=True)
    got = json.loads(out.stdout)
    assert got["secret"] == [True] * len(secrets)
    assert got["safe"] == [False] * len(safe)
    assert got["trim"] == "a\nb"
    assert got["prompt"] == "npm i\nnpm test\ndir"
