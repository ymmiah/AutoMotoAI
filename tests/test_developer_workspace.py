"""Edit, test & share (Tools > Edit, test & share): static checks on the chat-first UI module.

It reuses the Developer chat and the existing panels and engine APIs: no HTML from data, no browser
storage, no direct fetch, only the existing engine endpoints, and every run, apply and send waits for
the user's click on an inline confirm card."""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "automoto" / "web" / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_workspace_is_a_tools_card_and_old_cards_open_its_live_panel():
    js = _read("developer-simple.js")
    assert '["workspace","Edit, test & share"' in js
    routes = re.search(r"const WORKSPACE_TAB=\{(.*?)\};", js).group(1)
    for card, mode in (("run", "test"), ("git", "share"), ("share", "share"), ("review", "share"), ("account", "share")):
        assert f'{card}:["{mode}"' in routes
    for card in ("run", "git", "account", "share", "review"):
        assert f'["{card}",' in js


def test_workspace_reuses_the_developer_chat_not_a_new_bot():
    js = _read("developer-workspace.js")
    assert 'put("dsxChat",chatSlot)' in js
    for root in ("dsRunRoot", "dsGitRoot", "dsShareRoot", "dsReviewRoot", "dsAccountRoot", "dsPolyglotRoot", ".ds-columns"):
        assert f'"{root}"' in js
    # No model or agent calls of its own: AI requests go through the existing chat submit.
    assert "/api/agent" not in js and "/api/conversations" not in js and "/api/chat" not in js
    assert "chat.submit(" in js
    simple = _read("developer-simple.js")
    assert "workspace.handle(note)" in simple and "approvalCard(entry" in simple


def test_workspace_is_safe_by_construction():
    js = _read("developer-workspace.js")
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "outerHTML" not in js
    assert "localStorage" not in js and "sessionStorage" not in js and "indexedDB" not in js
    assert "fetch(" not in js and "eval(" not in js and "new Function" not in js
    # Only the existing engine endpoints.
    calls = set(re.findall(r'api\((?:BASE\+)?"([^"?]+)', js)) | set(re.findall(r'api\(R\+"([^"?]+)', js))
    assert calls <= {"/remote/status", "/remote/plan", "/remote/share", "/remote/fallback", "/preview", "/open",
                     "/remote/review/checks", "/polyglot/map", "/api/developer/studio/file"}, calls
    # Links from the website are https only and never pass the opener.
    assert 'rel="noopener noreferrer"' in js and r"/^https:\/\/" in js


def test_every_action_waits_for_a_click_on_an_inline_card():
    js = _read("developer-workspace.js")
    # The runner only starts from the card's own button, with the exact command shown.
    start = js.index("runner.start(r,{confirmed:true})")
    assert js.rfind("go.onclick", 0, start) > js.rfind("function runFlow", 0, start)
    # Share and review send confirmed:true only from inside a click handler with the plan's hash.
    for call in ('api(BASE+"/remote/share"', 'api(R+"/open"'):
        i = js.index(call)
        assert js.rfind("go.onclick", 0, i) > js.rfind("async function", 0, i)
        assert "action_sha256" in js[i:i + 260] and "confirmed:true" in js[i:i + 260]
    # Assistant edits and commands: Apply / Run once decide the waiting task.
    assert '"Apply"' in js and '"Run once"' in js and "decide(allow)" in js
    # The runner keeps its dialog for every other caller.
    run = _read("developer-run.js")
    assert "if(!confirmed&&!window.confirm(" in run


def test_beginner_copy_and_chips():
    js = _read("developer-workspace.js")
    assert "Hi! What do you want to build or fix today?" in js
    for chip in ("Explain my project", "Fix the error", "Test my app", "Share to GitHub", "Ask for a review", "Map my project"):
        assert f'"{chip}"' in js
    assert "ChatGPT" not in js


def test_header_buttons_live_in_the_page_menu_and_the_strip_waits_for_activity():
    js = _read("developer-workspace.js")
    assert '"#convMore"' in js and '"Manual controls"' in js and '"All tools"' in js
    assert "dswManual" not in js and "dswBack" not in js
    assert 'strip.hidden=true' in js and "strip.hidden=!active" in js
    for words in ("All saved", "Changes not saved", "Tests passed", "Not tested yet", "Not shared yet", "Everything shared"):
        assert f'"{words}"' in js
    css = _read("developer-studio.css")
    assert ".dsx[data-ws] #dsxCompProject{display:none}" in css
