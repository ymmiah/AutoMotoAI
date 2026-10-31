"""Microsoft Store package: version mapping, AppxManifest.xml and the images it references (packaging/msstore)."""

import importlib.util
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("msix", ROOT / "packaging/msstore/msix.py")
msix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(msix)
NS = {"m": "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
      "uap": "http://schemas.microsoft.com/appx/manifest/uap/windows10",
      "rescap": "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"}


def test_version_mapping():
    assert msix.msix_version("5.6.0-beta.3") == "5.6.3.0"
    assert msix.msix_version("5.6.0") == "5.6.99.0"
    assert msix.msix_version("5.6.1-beta.1") == "5.6.101.0"
    assert msix.msix_version("5.6.1") == "5.6.199.0"
    order = ["5.6.0-beta.1", "5.6.0-beta.3", "5.6.0", "5.6.1-beta.1", "5.6.1", "5.7.0-beta.1", "6.0.0"]
    nums = [tuple(map(int, msix.msix_version(v).split("."))) for v in order]
    assert nums == sorted(nums) and len(set(nums)) == len(nums)
    for bad in ("5.6", "5.6.0-rc.1", "0.1.0", "5.6.0-beta.99"):
        with pytest.raises(ValueError):
            msix.msix_version(bad)


def test_current_app_version_maps_with_last_part_zero():
    v = json.loads((ROOT / "apps/desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))["version"]
    parts = msix.msix_version(v).split(".")
    assert len(parts) == 4 and parts[-1] == "0" and all(0 <= int(p) <= 65535 for p in parts) and parts[0] != "0"


def test_manifest_placeholder_and_variables():
    root = ET.fromstring(msix.manifest("5.6.0-beta.3", env={}).encode())
    ident = root.find("m:Identity", NS)
    assert ident.get("Version") == "5.6.3.0" and ident.get("ProcessorArchitecture") == "x64"
    assert ident.get("Publisher").startswith("CN=")
    assert "Beta" in root.find("m:Properties/m:DisplayName", NS).text
    app = root.find("m:Applications/m:Application", NS)
    assert app.get("Executable") == "AutoMoto AI.exe" and app.get("EntryPoint") == "Windows.FullTrustApplication"
    caps = [c.get("Name") for c in root.find("m:Capabilities", NS)]
    assert caps == ["internetClient", "runFullTrust"]
    env = {"MSSTORE_IDENTITY_NAME": "12345YasinMohammedMiah.AutoMotoAIBeta", "MSSTORE_PUBLISHER": "CN=ABCD-1234",
           "MSSTORE_PUBLISHER_DISPLAY_NAME": "Yasin Mohammed Miah", "MSSTORE_DISPLAY_NAME": "AutoMoto AI (Beta)"}
    root = ET.fromstring(msix.manifest("5.6.0-beta.3", env=env).encode())
    assert root.find("m:Identity", NS).get("Name") == env["MSSTORE_IDENTITY_NAME"]
    assert root.find("m:Identity", NS).get("Publisher") == "CN=ABCD-1234"
    assert not msix.is_placeholder(env) and msix.is_placeholder({})
    with pytest.raises(ValueError):
        msix.manifest("5.6.0-beta.3", env={**env, "MSSTORE_PUBLISHER": "Yasin"})
    with pytest.raises(ValueError):
        msix.manifest("5.6.0-beta.3", env={**env, "MSSTORE_IDENTITY_NAME": 'x"><evil'})


def test_every_referenced_image_exists_with_the_right_size():
    from PIL import Image

    text = msix.manifest("5.6.0-beta.3", env={})
    refs = set(re.findall(r'Assets\\([A-Za-z0-9]+)\.png', text))
    assert refs >= {"StoreLogo", "Square44x44Logo", "Square150x150Logo", "Wide310x150Logo", "SplashScreen"}
    sizes = {"StoreLogo": (50, 50), "Square44x44Logo": (44, 44), "Square71x71Logo": (71, 71),
             "Square150x150Logo": (150, 150), "Square310x310Logo": (310, 310), "Wide310x150Logo": (310, 150),
             "SplashScreen": (620, 300)}
    out = ROOT / "packaging/branding/out/msix"
    for ref in refs:
        assert Image.open(out / f"{ref}.png").size == sizes[ref]
        assert Image.open(out / f"{ref}.scale-200.png").size == tuple(2 * v for v in sizes[ref])
    assert Image.open(out / "Square44x44Logo.targetsize-256_altform-unplated.png").size == (256, 256)


def test_store_screenshots_are_big_enough():
    from PIL import Image

    shots = sorted((ROOT / "packaging/msstore/screenshots").glob("*.png"))
    assert 1 <= len(shots) <= 10
    for s in shots:
        w, h = Image.open(s).size
        assert w >= 1366 and h >= 768
