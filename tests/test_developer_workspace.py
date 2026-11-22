"""One workspace (Tools > Edit, test & share): static checks on the UI module.

It reuses the existing panels and engine APIs and adds no logic of its own: no HTML from data,
no browser storage, no new network calls, and the old cards still open (as tabs)."""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "automoto" / "web" / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_workspace_is_a_tools_card_and_old_cards_open_its_tabs():
    js = _read("developer-simple.js")
    assert '["workspace","Edit, test & share"' in js
    routes = re.search(r"const WORKSPACE_TAB=\{(.*?)\};", js).group(1)
    for card, tab in (("run", "test"), ("git", "share"), ("share", "share"), ("review", "share"), ("account", "share")):
        assert f'{card}:["{tab}"' in routes
    # Every original card is still there.
    for card in ("run", "git", "account", "share", "review"):
        assert f'["{card}",' in js


def test_workspace_moves_the_real_panels_and_adds_no_logic():
    js = _read("developer-workspace.js")
    for root in ("dsRunRoot", "dsGitRoot", "dsShareRoot", "dsReviewRoot", "dsAccountRoot", ".ds-columns"):
        assert f'"{root}"' in js
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js
    assert "localStorage" not in js and "sessionStorage" not in js
    assert "fetch(" not in js
    # The only engine call is the existing, local share status.
    assert re.findall(r'api\(BASE\+"([^"?]+)', js) == ["/remote/status"]
    # Tests only run from the runner's own approval-gated buttons.
    assert "runner.start" not in js and "runner.run" not in js
    assert "/share" not in js.replace("/remote/status", "")
    assert 'import {ring} from "./developer-beginner.js"' in js


def test_workspace_tabs_are_accessible():
    js = _read("developer-workspace.js")
    for attr in ('"role","tablist"', '"role","tab"', '"role","tabpanel"', '"aria-selected"', '"aria-controls"'):
        assert attr in js
    assert "ArrowRight" in js and "ArrowLeft" in js
