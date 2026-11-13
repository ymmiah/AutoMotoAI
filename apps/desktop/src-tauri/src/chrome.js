// AutoMoto window frame. The Windows app injects this before every page
// (window.__AUTOMOTO_FORCE_CHROME__) and the sign-in page and engine UI also
// load it. Browser pages stay on the normal document chrome.
(function () {
  "use strict";

  var MARKUP = ''
    + '<header class="am-chrome" id="amChrome">'
    + '<button type="button" class="am-menu" data-chrome="menu" aria-haspopup="menu" aria-expanded="false" aria-controls="amAppMenu">Menu</button>'
    + '<div class="am-drag" data-tauri-drag-region>'
    + '<span class="am-mark" aria-hidden="true">A</span>'
    + '<span class="am-caption" id="amChromeTitle" data-tauri-drag-region>AutoMoto AI</span>'
    + '</div>'
    + '<div class="am-controls" role="toolbar" aria-label="Window">'
    + '<button type="button" data-chrome="min" aria-label="Minimize"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.5h10"/></svg></button>'
    + '<button type="button" data-chrome="max" aria-label="Maximize"><svg class="ico-max" viewBox="0 0 16 16" aria-hidden="true"><rect x="3.5" y="3.5" width="9" height="9" rx="1.5"/></svg><svg class="ico-restore" viewBox="0 0 16 16" aria-hidden="true"><rect x="4.8" y="3.2" width="7.2" height="7.2" rx="1.2"/><path d="M6.2 6.1H4.2A1.2 1.2 0 0 0 3 7.3v4.5A1.2 1.2 0 0 0 4.2 13h4.5a1.2 1.2 0 0 0 1.2-1.2V10"/></svg></button>'
    + '<button type="button" data-chrome="close" aria-label="Close"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 4.5 11.5 11.5M11.5 4.5 4.5 11.5"/></svg></button>'
    + '</div>'
    + '<div class="am-appmenu" id="amAppMenu" role="menu" hidden>'
    + '<button type="button" role="menuitem" data-chrome="act" data-action="home">Switch Local / Cloud / Server <span class="k">Ctrl+Shift+H</span></button>'
    + '<button type="button" role="menuitem" data-chrome="act" data-action="reload">Reload <span class="k">Ctrl+R</span></button>'
    + '<button type="button" role="menuitem" data-chrome="act" data-action="updates">Check for updates</button>'
    + '<button type="button" role="menuitem" data-chrome="act" data-action="signout">Sign out of this device</button>'
    + '<div role="separator"></div>'
    + '<button type="button" role="menuitem" data-chrome="act" data-action="guide">Step-by-step guide <span class="k">F1</span></button>'
    + '<button type="button" role="menuitem" data-chrome="act" data-action="store">Get it from Microsoft</button>'
    + '<button type="button" role="menuitem" data-chrome="act" data-action="releases">Advanced: GitHub installers</button>'
    + '<button type="button" role="menuitem" data-chrome="act" data-action="log">Open the local engine log</button>'
    + '<button type="button" role="menuitem" data-chrome="act" data-action="about">About AutoMoto AI</button>'
    + '<div role="separator"></div>'
    + '<button type="button" role="menuitem" data-chrome="act" data-action="quit">Quit <span class="k">Ctrl+Q</span></button>'
    + '</div></header>';

  // Used only when a page has no caption stylesheet (an older account server).
  // Sizes match chrome.rs: 40px bar, 64px menu, 46px buttons.
  var FALLBACK_CSS = ''
    + '.am-chrome{position:fixed;top:0;left:0;right:0;height:40px;z-index:80;display:none;align-items:stretch;'
    + 'background:#0c1017;color:#edf1f7;border-bottom:1px solid #2a3544;font:13px/1 Segoe UI,system-ui,sans-serif;user-select:none}'
    + 'html[data-chrome="custom"] .am-chrome{display:flex}'
    + '.am-menu{width:64px;height:40px;border:0;background:transparent;color:inherit;font:inherit}'
    + '.am-drag{flex:1;display:flex;align-items:center;gap:8px;min-width:0;padding-left:4px}'
    + '.am-mark{width:18px;height:18px;border-radius:5px;background:#b9ef75;color:#16210c;display:grid;place-items:center;font-size:11px;font-weight:800}'
    + '.am-caption{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}'
    + '.am-controls{display:flex}'
    + '.am-controls button{width:46px;height:40px;border:0;background:transparent;color:inherit;display:grid;place-items:center}'
    + '.am-controls svg{width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:1.4;stroke-linecap:round;stroke-linejoin:round}'
    + '.am-controls .ico-restore{display:none}.am-controls button.is-restore .ico-max{display:none}.am-controls button.is-restore .ico-restore{display:block}'
    + '.am-appmenu{position:absolute;top:100%;left:8px;min-width:260px;padding:6px;background:#131a24;border:1px solid #2a3544;border-radius:12px}'
    + '.am-appmenu button{display:flex;width:100%;text-align:left;border:0;background:transparent;color:inherit;padding:8px 10px;font:inherit}'
    + '.am-appmenu .k{margin-left:auto;opacity:.7;font-size:11px}';

  function call(cmd, args) {
    try {
      var api = window.__TAURI_INTERNALS__;
      if (!api || typeof api.invoke !== "function") return Promise.resolve(null);
      return Promise.resolve(api.invoke(cmd, args || {})).catch(function () { return null; });
    } catch (e) {
      return Promise.resolve(null);
    }
  }

  function ensure() {
    var bar = document.getElementById("amChrome");
    if (!bar) {
      document.body.insertAdjacentHTML("afterbegin", MARKUP);
      bar = document.getElementById("amChrome");
    }
    if (bar && getComputedStyle(bar).position !== "fixed" && !document.getElementById("amChromeFallback")) {
      var style = document.createElement("style");
      style.id = "amChromeFallback";
      style.textContent = FALLBACK_CSS;
      document.head.appendChild(style);
    }
    return bar;
  }

  function boot() {
    if (window.__AUTOMOTO_FORCE_CHROME__) document.documentElement.dataset.chrome = "custom";
    if (document.documentElement.dataset.chrome !== "custom" || !document.body) return;
    var bar = ensure();
    if (!bar || bar.dataset.wired === "1") return;
    bar.dataset.wired = "1";
    var menuBtn = bar.querySelector("[data-chrome='menu']");
    var menu = document.getElementById("amAppMenu");
    var maxBtn = bar.querySelector("[data-chrome='max']");

    function syncTitle() {
      var el = document.getElementById("amChromeTitle");
      if (!el) return;
      var title = (document.title || "AutoMoto AI").replace(/\s+/g, " ").trim();
      if (title) el.textContent = title;
    }
    syncTitle();
    var titleNode = document.querySelector("title");
    if (titleNode && window.MutationObserver) {
      new MutationObserver(syncTitle).observe(titleNode, { childList: true, characterData: true, subtree: true });
    }

    function syncMax() {
      call("plugin:window|is_maximized").then(function (on) {
        if (!maxBtn) return;
        var maximized = on === true;
        maxBtn.classList.toggle("is-restore", maximized);
        maxBtn.setAttribute("aria-label", maximized ? "Restore" : "Maximize");
      });
    }
    window.addEventListener("resize", syncMax);
    syncMax();

    var minBtn = bar.querySelector("[data-chrome='min']");
    var closeBtn = bar.querySelector("[data-chrome='close']");
    if (minBtn) minBtn.addEventListener("click", function () { call("plugin:window|minimize"); });
    if (maxBtn) maxBtn.addEventListener("click", function () { call("plugin:window|toggle_maximize").then(syncMax); });
    if (closeBtn) closeBtn.addEventListener("click", function () { call("plugin:window|close"); });

    function items() {
      return menu ? Array.prototype.slice.call(menu.querySelectorAll("[role='menuitem']")) : [];
    }
    function openMenu() {
      if (!menu || !menuBtn) return;
      menu.hidden = false;
      menuBtn.setAttribute("aria-expanded", "true");
      var list = items();
      if (list[0]) list[0].focus();
    }
    function closeMenu(focusBtn) {
      if (!menu || !menuBtn) return;
      menu.hidden = true;
      menuBtn.setAttribute("aria-expanded", "false");
      if (focusBtn) menuBtn.focus();
    }
    if (menuBtn) {
      menuBtn.addEventListener("click", function () {
        if (!menu || menu.hidden) openMenu();
        else closeMenu(true);
      });
    }
    if (menu) {
      menu.addEventListener("keydown", function (e) {
        var list = items();
        if (!list.length) return;
        var i = list.indexOf(document.activeElement);
        if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Home" || e.key === "End") {
          e.preventDefault();
          var next = e.key === "Home" ? 0 : e.key === "End" ? list.length - 1 : (i + (e.key === "ArrowDown" ? 1 : -1) + list.length) % list.length;
          list[next].focus();
        } else if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          closeMenu(true);
        }
      });
      menu.addEventListener("click", function (e) {
        var item = e.target.closest("[data-action]");
        if (!item) return;
        var action = item.getAttribute("data-action");
        closeMenu(false);
        if (action === "guide" && document.getElementById("view")) { location.hash = "#/help"; return; }
        call("chrome_action", { action: action });
      });
    }
    document.addEventListener("mousedown", function (e) {
      if (!menu || menu.hidden || bar.contains(e.target)) return;
      closeMenu(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && menu && !menu.hidden) {
        e.preventDefault();
        e.stopPropagation();
        closeMenu(true);
      }
    }, true);
  }

  window.__automotoChromeBoot = boot;
  if (window.__AUTOMOTO_FORCE_CHROME__) document.documentElement.dataset.chrome = "custom";
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
