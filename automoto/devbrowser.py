"""Look at the user's OWN local dev site in a headless browser (DOM, computed CSS, screenshot, CSS preview).

Folded in from the reviewed "Engineering Studio" overlay (its native_browser.py, kept almost as-is):
* only exact loopback origins listed in ``AUTOMOTO_BROWSER_ORIGINS`` (default: none = off);
* a fresh browser context per call, GET/HEAD only, WebSockets and popups closed, no downloads;
* risky level, so every call asks first; disabled in hosted mode;
* nothing on disk changes except a screenshot in scratch/. Needs ``pip install playwright`` +
  ``python -m playwright install chromium`` (not a default dependency).
Rejected from the overlay: the long-lived browser pool (``AUTOMOTO_CHROMIUM_PATH`` let an env var pick any
executable to launch, and it allowed clicks), the separate /studio page and its direct "apply source edit" API.
"""

from __future__ import annotations

import ipaddress
import json
import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from automoto import config, sandbox, tenancy
from automoto.tools import Tool, ToolContext, ToolFailed

_MAX_CSS = 20_000
_MAX_SELECTOR = 300


def _origin(url: str) -> str:
    """Canonicalise an explicitly local origin. Reject credentials and deceptive hosts."""
    try:
        u = urlsplit(url.strip())
        port = u.port if u.port is not None else (443 if u.scheme == "https" else 80)
    except (ValueError, AttributeError) as exc:
        raise ToolFailed(f"invalid browser URL: {exc}") from None
    if u.scheme not in ("http", "https") or not u.hostname or u.username is not None or u.password is not None:
        raise ToolFailed("browser URL must be an http(s) URL without credentials")
    host = u.hostname.lower()
    if host != "localhost":
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ToolFailed("page_inspect only opens localhost or a loopback IP")
        except ValueError:
            raise ToolFailed("page_inspect only opens localhost or a loopback IP") from None
    if not 1 <= port <= 65535:
        raise ToolFailed("invalid browser port")
    host_part = f"[{host}]" if ":" in host else host
    return f"{u.scheme}://{host_part}:{port}"


def _allowed_origins() -> set[str]:
    allowed = set()
    for raw in (config.env("AUTOMOTO_BROWSER_ORIGINS", "") or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        origin = _origin(raw)
        u = urlsplit(raw)
        if u.path not in ("", "/") or u.query or u.fragment:
            raise ToolFailed("AUTOMOTO_BROWSER_ORIGINS must contain origins, not full URLs")
        allowed.add(origin)
    return allowed


def authorise(url: str) -> str:
    if tenancy.multiuser():
        raise ToolFailed("native browser tools are disabled in hosted/multi-user mode")
    origin = _origin(url)
    allowed = _allowed_origins()
    if not allowed:
        raise ToolFailed("No approved origin. Set AUTOMOTO_BROWSER_ORIGINS=http://127.0.0.1:3000")
    if origin not in allowed:
        raise ToolFailed(f"browser origin {origin} is not in AUTOMOTO_BROWSER_ORIGINS")
    return origin


def _session(url: str, selector: str, css: str = "", screenshot: bool = False) -> str:
    origin = authorise(url)
    selector = (selector or "body").strip()
    if not selector or len(selector) > _MAX_SELECTOR:
        raise ToolFailed("selector must be 1-300 characters")
    if len(css) > _MAX_CSS:
        raise ToolFailed("CSS preview exceeds 20,000 characters")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ToolFailed('Install browser support: pip install -e ".[browser]" && python -m playwright install chromium') from None

    # Fresh, disposable context for every inspection. No persisted cookies or credentials.
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(accept_downloads=False, service_workers="block",
                                              ignore_https_errors=False)
                try:
                    def restrict(route):
                        req = route.request
                        try:
                            if req.method not in ("GET", "HEAD") or authorise(req.url) != origin:
                                route.abort()
                                return
                        except (ToolFailed, ValueError):
                            route.abort()
                            return
                        route.continue_()

                    context.route("**/*", restrict)
                    # In this MVP, WebSockets are not needed for inspection and must not
                    # bypass the request-origin filter (live-reload may be unavailable).
                    if hasattr(context, "route_web_socket"):
                        context.route_web_socket("**/*", lambda ws: ws.close())
                    page = context.new_page()
                    context.on("page", lambda popup: popup.close() if popup != page else None)
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    if authorise(page.url) != origin:
                        raise ToolFailed("navigation left the approved origin")
                    target = page.locator(selector).first
                    if target.count() == 0:
                        raise ToolFailed(f"no element matched: {selector}")
                    if css:
                        page.add_style_tag(content=css)
                    info = target.evaluate("""el => {
                      const s = getComputedStyle(el);
                      return {tag: el.tagName.toLowerCase(), id: el.id,
                        classes: Array.from(el.classList).slice(0,20),
                        text: (el.innerText || '').slice(0,2500),
                        html: el.outerHTML.slice(0,4000),
                        styles: {display:s.display, color:s.color, background:s.backgroundColor,
                          fontSize:s.fontSize, width:s.width, height:s.height,
                          margin:s.margin, padding:s.padding, position:s.position}};
                    }""")
                    result = {"url": page.url, "title": page.title()[:200], "selector": selector,
                              "element": info, "preview_only": bool(css)}
                    if screenshot:
                        name = f"native-browser-{uuid.uuid4().hex[:10]}.png"
                        out = sandbox.resolve(f"scratch/{name}")
                        out.parent.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(out), full_page=False, timeout=10000)
                        result["screenshot"] = sandbox.rel(out)
                    if css:
                        result["next_step"] = "Temporary CSS only. For a permanent change, inspect project files and use edit_file with approval, then rerun this inspection."
                    return json.dumps(result, ensure_ascii=False)
                finally:
                    context.close()
            finally:
                browser.close()
    except ToolFailed:
        raise
    except Exception as exc:
        raise ToolFailed(f"browser inspection failed ({exc.__class__.__name__}): {str(exc)[:350]}") from None


def browser_inspect(ctx: ToolContext, url: str, selector: str = "body", screenshot: bool = False) -> str:
    return _session(url, selector, screenshot=screenshot)


def browser_preview_css(ctx: ToolContext, url: str, css: str, selector: str = "body",
                        screenshot: bool = True) -> str:
    if not css.strip():
        raise ToolFailed("CSS must not be empty")
    return _session(url, selector, css=css, screenshot=screenshot)


S = {"type": "string"}


def page_inspect(ctx: ToolContext, url: str, selector: str = "body", css: str = "", screenshot: bool = False) -> str:
    """One tool: inspect (and optionally preview CSS on) the user's local dev page."""
    if css.strip():
        return browser_preview_css(ctx, url, css, selector, screenshot if screenshot is not None else True)
    return browser_inspect(ctx, url, selector, screenshot)


TOOLS = [
    Tool("page_inspect",
         "Open the user's OWN local dev site (an origin they allowed, e.g. http://127.0.0.1:3000) in a headless "
         "browser: element text/HTML, computed CSS, optional screenshot (scratch/), and css= to preview a style "
         "change that vanishes on reload. Never changes files; edit the source with edit_file afterwards.",
         {"type": "object", "properties": {"url": S, "selector": S, "css": S, "screenshot": {"type": "boolean"}},
          "required": ["url"]}, "risky", page_inspect, "code"),
]
