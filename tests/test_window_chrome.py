"""The Windows caption bar keeps one size contract across Rust, CSS and the script copies."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_caption_metrics_match():
    rust = (ROOT / "apps/desktop/src-tauri/src/chrome.rs").read_text(encoding="utf-8")
    assert "CHROME_HEIGHT_PX: f32 = 40.0" in rust
    assert "CHROME_MENU_PX: f32 = 64.0" in rust
    assert "CHROME_BUTTON_PX: f32 = 46.0" in rust
    for css in (ROOT / "automoto/web/static/app.css", ROOT / "apps/desktop/dist/app.css"):
        text = css.read_text(encoding="utf-8")
        assert ".am-chrome" in text and "height: 40px;" in text
        assert ".am-menu { width: 64px;" in text
        assert ".am-controls button { width: 46px;" in text


def test_chrome_script_copies_match():
    source = (ROOT / "apps/desktop/src-tauri/src/chrome.js").read_bytes()
    assert source == (ROOT / "automoto/web/static/chrome.js").read_bytes()
    assert source == (ROOT / "apps/desktop/dist/chrome.js").read_bytes()


def test_settings_sections_are_in_the_interface():
    script = (ROOT / "automoto/web/static/app.js").read_text(encoding="utf-8")
    assert 'class="set-nav"' in script
    assert "You write the request" in script
    assert 'data-set="offline"' in script
    assert 'href="#/tools"' in script
