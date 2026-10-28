// Applies the saved theme/accent before first paint (no flash). Not secret: theme only.
(function () {
  try {
    var t = localStorage.getItem("automoto_theme") || "dark";
    var a = localStorage.getItem("automoto_accent");
    var dark = t === "dark" || (t === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    if (a) document.documentElement.style.setProperty("--accent", a);
  } catch (e) {}
})();
