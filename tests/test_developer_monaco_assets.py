"""Offline Monaco packaging checks for Developer Studio V2 completion.

The editor must be available from local installed Python static resources. We
never substitute a CDN download in a production runtime.
"""
from __future__ import annotations

import hashlib
import json
from importlib.resources import files

import pytest

from automoto import developer_studio

MONACO = files("automoto").joinpath("web/static/vendor/monaco")
REQUIRED = (
    "monaco.js", "monaco.css", "editor.worker.js", "ts.worker.js",
    "json.worker.js", "css.worker.js", "html.worker.js", "MONACO-LICENSE.txt", "DOMPURIFY-LICENSE.txt",
)


def test_vendor_manifest_integrity():
    manifest_file = MONACO.joinpath("manifest.json")
    assert manifest_file.is_file(), "Offline Monaco not bundled in installed package"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["version"] == "0.57.0"
    assert manifest["sanitizer"] == "dompurify@3.4.17", "Unpatched vulnerable DOMPurify must not ship"
    assert manifest["format"] == "esm"
    listed = manifest["files"]
    for name in REQUIRED:
        assert name in listed, f"{name} missing in Monaco manifest"
    for name, record in listed.items():
        assert not name.startswith("/") and ".." not in name.split("/")
        asset = MONACO.joinpath(name)
        assert asset.is_file(), f"Offline Monaco missing asset {name}"
        data = asset.read_bytes()
        assert len(data) == record["size"]
        assert hashlib.sha256(data).hexdigest() == record["sha256"]
    assert "MIT" in MONACO.joinpath("MONACO-LICENSE.txt").read_text(encoding="utf-8")
    assert "Apache License" in MONACO.joinpath("DOMPURIFY-LICENSE.txt").read_text(encoding="utf-8")
    assert len(MONACO.joinpath("monaco.js").read_bytes()) > 100_000


def test_monaco_only_served_as_local_static_assets():
    web = files("automoto").joinpath("web")
    wrapper = web.joinpath("static/developer-monaco.js").read_text(encoding="utf-8")
    boot = web.joinpath("index.html").read_text(encoding="utf-8")
    entry = web.joinpath("static/developer-editor.js").read_text(encoding="utf-8")
    assert 'import("/static/vendor/monaco/monaco.js")' in wrapper
    assert '/static/vendor/monaco/monaco.css' in boot
    assert 'import("./developer-monaco.js")' in entry
    assert "unpkg.com" not in wrapper and "jsdelivr.net" not in wrapper
    assert "new Worker(root + entry" not in wrapper  # workers belong inside vendored ESM
    assert developer_studio.MAX_PREVIEW == 128 * 1024


def test_monaco_worker_entries_are_bundled_locally():
    source = files("automoto").joinpath("web/static/vendor/monaco/monaco.js").read_text(encoding="utf-8")
    # Minified ESM must use the same-origin worker directory.
    assert "/static/vendor/monaco/" in source
    assert "ts.worker.js" in source and "editor.worker.js" in source
