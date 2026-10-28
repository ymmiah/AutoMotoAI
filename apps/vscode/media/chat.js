// AutoMoto chat webview. Everything is rendered with textContent - model output is never HTML.
(function () {
  const vscode = acquireVsCodeApi();
  const log = document.getElementById("log");
  const form = document.getElementById("f");
  const ta = document.getElementById("t");
  const ws = document.getElementById("ws");
  const stop = document.getElementById("stop");
  const send = document.getElementById("send");
  const saved = vscode.getState() || { items: [], ws: false };
  ws.checked = !!saved.ws;

  function add(kind, text, meta) {
    const el = document.createElement("div");
    el.className = "msg " + kind;
    const body = document.createElement("div");
    body.className = "body";
    body.textContent = text;
    el.appendChild(body);
    if (meta) {
      const m = document.createElement("div");
      m.className = "meta";
      m.textContent = meta;
      el.appendChild(m);
    }
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }
  function remember(kind, text, meta) {
    saved.items.push({ kind, text, meta });
    saved.items = saved.items.slice(-80);
    vscode.setState(saved);
  }
  saved.items.forEach((i) => add(i.kind, i.text, i.meta));

  function busy(b) {
    stop.hidden = !b;
    send.disabled = b;
  }
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = ta.value.trim();
    if (!text) return;
    vscode.postMessage({ type: "send", text, workspace: ws.checked });
    ta.value = "";
  });
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
  ws.addEventListener("change", () => {
    saved.ws = ws.checked;
    vscode.setState(saved);
  });
  stop.addEventListener("click", () => vscode.postMessage({ type: "stop" }));

  window.addEventListener("message", (e) => {
    const m = e.data || {};
    if (m.type === "user" || m.type === "bot" || m.type === "error") {
      add(m.type, String(m.text || ""), m.meta);
      remember(m.type, String(m.text || ""), m.meta);
    } else if (m.type === "step") {
      add("step", String(m.text || ""));
    } else if (m.type === "busy") {
      busy(!!m.value);
    } else if (m.type === "clear") {
      log.textContent = "";
      saved.items = [];
      vscode.setState(saved);
    }
  });
  vscode.postMessage({ type: "ready" });
})();
