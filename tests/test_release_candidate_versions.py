"""Release candidate metadata validation without publishing side effects."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def _toml_version(path, prefix="version"):
    result = re.search(r"^" + re.escape(prefix) + r' = "([^"]+)"', _read(path), re.M)
    assert result, f"missing version from {path}"
    return result.group(1)


def test_release_desktop_engine_and_rust_lock_versions():
    app = json.loads(_read("apps/desktop/src-tauri/tauri.conf.json"))["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:-beta\.\d+)?", app)
    assert json.loads(_read("apps/desktop/package.json"))["version"] == app
    assert json.loads(_read("apps/desktop/package-lock.json"))["version"] == app
    assert json.loads(_read("apps/desktop/package-lock.json"))["packages"][""]["version"] == app
    assert _toml_version("apps/desktop/src-tauri/Cargo.toml") == app
    assert re.search(r'\[\[package\]\]\s+name = "automoto-desktop"\s+version = "' +
                     re.escape(app) + '"', _read("apps/desktop/src-tauri/Cargo.lock"))
    engine = app.replace("-beta.", "b")
    assert _toml_version("pyproject.toml") == engine
    assert _toml_version("automoto/__init__.py", "__version__") == engine


def test_vs_code_manifest_keeps_valid_extension_version_and_beta_asset_name():
    app = json.loads(_read("apps/desktop/src-tauri/tauri.conf.json"))["version"]
    manifest = json.loads(_read("apps/vscode/package.json"))
    lock = json.loads(_read("apps/vscode/package-lock.json"))
    # VS Code's manifest version stays plain semver. A beta app marks the VSIX pre-release.
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])
    assert lock["version"] == manifest["version"]
    assert lock["packages"][""]["version"] == manifest["version"]
    script = manifest["scripts"]["package"]
    if "-beta." in app:
        assert "--pre-release" in script and app in script
    else:
        assert "--pre-release" not in script and manifest["version"] in script
    assert lock["packages"][""]["license"] == manifest["license"]


def test_store_msix_version_mapping():
    import runpy
    app = json.loads(_read("apps/desktop/src-tauri/tauri.conf.json"))["version"]
    version_fn = runpy.run_path(str(ROOT / "packaging/msstore/msix.py"))["msix_version"]
    out = version_fn(app)
    parts = [int(x) for x in out.split(".")]
    assert len(parts) == 4 and parts[3] == 0
    assert parts[0] > 0 and all(0 <= x <= 65535 for x in parts)
