// Applies the saved theme/accent before first paint (no flash). Not secret: theme only.
(function () {
  try {
    var t = localStorage.getItem("automoto_theme") || "dark";
    var a = localStorage.getItem("automoto_accent");
    var dark = t === "dark" || (t === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    if (a) document.documentElement.style.setProperty("--accent", a);
  } catch (e) {}
  // Same three-pane layout on every platform. The Windows app draws its own caption ("custom",
  // set by chrome.js); everywhere else (browser, server, macOS and Linux apps with their native
  // frame) the page shows the in-page top bar with the menus and no window controls ("bar").
  try {
    var d = document.documentElement, ua = navigator.userAgent || "", p = navigator.platform || "";
    d.dataset.os = /Mac|iPhone|iPad/.test(p + ua) ? "mac" : /Win/.test(p + ua) ? "windows" : /Android/.test(ua) ? "android" : "linux";
    if (window.__TAURI_INTERNALS__) d.dataset.native = "1";
    if (d.dataset.chromeFallback && !window.__AUTOMOTO_FORCE_CHROME__ && d.dataset.chrome !== "custom") d.dataset.chrome = d.dataset.chromeFallback;
  } catch (e) {}
})();
