"use strict";

/* ═══════════════════════════════════════════════════════════
   AutoMoto AI  ·  Frontend SPA
   ═══════════════════════════════════════════════════════════ */

const SESSION_ID = "s_" + Math.random().toString(36).slice(2);
let currentPath  = null;
let selectedItem = null;
let allApps      = [];

// ── DOM refs ──────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const chatHistory    = $("chatHistory");
const chatInput      = $("chatInput");
const providerSelect = $("providerSelect");
const statusBadge    = $("statusBadge");
const pathInput      = $("pathInput");
const fileList       = $("fileList");
const appList        = $("appList");
const appSearch      = $("appSearch");
const modal          = $("modal");
const modalPrompt    = $("modalPrompt");
const modalInput     = $("modalInput");
const toolsToggle    = $("toolsToggle");

// ── Helpers ───────────────────────────────────────────────────────────────
async function api(endpoint, options = {}) {
  const res = await fetch(`/api/${endpoint}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const json = await res.json();
  if (!json.ok) throw new Error(json.error || "API error");
  return json.data;
}

function setStatus(text, type = "green") {
  statusBadge.textContent = text;
  statusBadge.className = `badge badge-${type}`;
}

function prompt(question, defaultVal = "") {
  return new Promise(resolve => {
    modalPrompt.textContent = question;
    modalInput.value = defaultVal;
    modal.classList.remove("hidden");
    modalInput.focus();
    const ok = () => {
      modal.classList.add("hidden");
      resolve(modalInput.value.trim() || null);
    };
    const cancel = () => {
      modal.classList.add("hidden");
      resolve(null);
    };
    $("modalOk").onclick     = ok;
    $("modalCancel").onclick = cancel;
    modalInput.onkeydown = e => { if (e.key === "Enter") ok(); if (e.key === "Escape") cancel(); };
  });
}

function formatSize(bytes) {
  if (bytes === 0) return "";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 ** 2) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1024 ** 2).toFixed(1) + " MB";
}

function formatRate(bps) {
  if (bps < 1024)       return bps + " B/s";
  if (bps < 1024 ** 2)  return (bps / 1024).toFixed(1) + " KB/s";
  return (bps / 1024 ** 2).toFixed(1) + " MB/s";
}

function escHtml(str) {
  return String(str)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
    .replace(/\n/g,"<br>");
}

// ── Command history ───────────────────────────────────────────────────────
const cmdHistory = [];
let   histIdx    = -1;

function pushHistory(text) {
  if (cmdHistory.at(-1) !== text) cmdHistory.push(text);
  if (cmdHistory.length > 200) cmdHistory.shift();
  histIdx = -1;
}

chatInput.addEventListener("keydown", e => {
  if (e.key === "ArrowUp") {
    e.preventDefault();
    if (!cmdHistory.length) return;
    histIdx = histIdx < 0 ? cmdHistory.length - 1 : Math.max(0, histIdx - 1);
    chatInput.value = cmdHistory[histIdx];
  } else if (e.key === "ArrowDown") {
    e.preventDefault();
    if (histIdx < 0) return;
    histIdx++;
    chatInput.value = histIdx >= cmdHistory.length ? (histIdx = -1, "") : cmdHistory[histIdx];
  }
});

// ── Chat ──────────────────────────────────────────────────────────────────
function appendMsg(role, text) {
  const wrap = document.createElement("div");
  wrap.style.display = "flex";
  wrap.style.flexDirection = "column";

  if (role === "user") {
    wrap.style.alignItems = "flex-end";
    wrap.innerHTML =
      `<div class="msg-label" style="text-align:right">You</div>` +
      `<div class="msg msg-user">${escHtml(text)}</div>`;
  } else if (role === "bot") {
    wrap.style.alignItems = "flex-start";
    wrap.innerHTML =
      `<div class="msg-label">AutoMoto AI</div>` +
      `<div class="msg msg-bot">${escHtml(text)}</div>`;
  } else if (role === "system") {
    wrap.style.alignItems = "center";
    wrap.innerHTML = `<div class="msg msg-system">${escHtml(text)}</div>`;
  } else if (role === "error") {
    wrap.style.alignItems = "flex-start";
    wrap.innerHTML = `<div class="msg msg-error">⚠ ${escHtml(text)}</div>`;
  }
  chatHistory.appendChild(wrap);
  chatHistory.scrollTop = chatHistory.scrollHeight;
  return wrap;
}

function appendToolCall(name, args) {
  const wrap = document.createElement("div");
  wrap.style.cssText = "display:flex;flex-direction:column;align-items:flex-start;";
  const argsStr = Object.keys(args).length
    ? JSON.stringify(args, null, 0).slice(0, 120)
    : "";
  wrap.innerHTML =
    `<div class="tool-call-card">` +
    `<span class="tool-name">🔧 ${escHtml(name)}</span>` +
    (argsStr ? `<div class="tool-args">${escHtml(argsStr)}</div>` : "") +
    `</div>`;
  chatHistory.appendChild(wrap);
  chatHistory.scrollTop = chatHistory.scrollHeight;
  return wrap;
}

function appendToolResult(name, result, success) {
  const wrap = document.createElement("div");
  wrap.style.cssText = "display:flex;flex-direction:column;align-items:flex-start;";
  const cls   = success ? "ok" : "err";
  const icon  = success ? "✅" : "❌";
  const prev  = result.slice(0, 160).replace(/\n/g, " ") + (result.length > 160 ? "…" : "");
  wrap.innerHTML =
    `<div class="tool-result-card ${cls}">${icon} ${escHtml(name)}: ${escHtml(prev)}</div>`;
  chatHistory.appendChild(wrap);
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

let _streaming = false;
let _botWrap   = null;
let _botMsgEl  = null;

function beginBotStream() {
  _botWrap = document.createElement("div");
  _botWrap.style.cssText = "display:flex;flex-direction:column;align-items:flex-start;";
  _botWrap.innerHTML = `<div class="msg-label">AutoMoto AI</div><div class="msg msg-bot streaming"></div>`;
  _botMsgEl = _botWrap.querySelector(".msg-bot");
  chatHistory.appendChild(_botWrap);
  _streaming = true;
}

function appendToken(text) {
  if (!_botMsgEl) beginBotStream();
  _botMsgEl.textContent += text;
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

function endBotStream() {
  if (_botMsgEl) _botMsgEl.classList.remove("streaming");
  _botMsgEl = null;
  _botWrap  = null;
  _streaming = false;
}

async function sendMessage() {
  const text = chatInput.value.trim();
  if (!text || _streaming) return;
  chatInput.value = "";
  pushHistory(text);
  appendMsg("user", text);

  chatInput.disabled = true;
  setStatus("Thinking…", "yellow");

  const useTools = toolsToggle.checked;

  // SSE streaming path
  beginBotStream();

  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message:    text,
        session_id: SESSION_ID,
        provider:   providerSelect.value || null,
        use_tools:  useTools,
      }),
    });

    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let   buf     = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      // Parse SSE frames (may be multiple per chunk)
      const frames = buf.split("\n\n");
      buf = frames.pop();   // last (potentially incomplete) frame stays in buf

      for (const frame of frames) {
        if (!frame.trim()) continue;
        let eventType = "message";
        let dataStr   = "";
        for (const line of frame.split("\n")) {
          if (line.startsWith("event: "))      eventType = line.slice(7).trim();
          else if (line.startsWith("data: "))  dataStr   = line.slice(6);
        }
        let payload;
        try { payload = JSON.parse(dataStr); } catch { continue; }

        if (eventType === "token") {
          appendToken(payload.text);
        } else if (eventType === "tool_call") {
          endBotStream();
          appendToolCall(payload.name, payload.args || {});
          beginBotStream();
        } else if (eventType === "tool_result") {
          appendToolResult(payload.name, payload.result, payload.success);
        } else if (eventType === "error") {
          endBotStream();
          appendMsg("error", payload.message);
        } else if (eventType === "done") {
          endBotStream();
        }
      }
    }
    endBotStream();
    setStatus("Ready");
  } catch (err) {
    endBotStream();
    appendMsg("error", err.message);
    setStatus("Error", "red");
  } finally {
    chatInput.disabled = false;
    chatInput.focus();
  }
}

async function clearChat() {
  await api("chat/clear", { method: "POST", body: JSON.stringify({ session_id: SESSION_ID }) });
  chatHistory.innerHTML = "";
  appendMsg("system", "Conversation cleared.");
}

// ── File browser ──────────────────────────────────────────────────────────
async function navigateTo(path) {
  fileList.innerHTML = '<div class="msg-system" style="padding:16px">Loading…</div>';
  try {
    const entries = await api("files/list?path=" + encodeURIComponent(path));
    currentPath = path;
    pathInput.value = path;
    renderFileList(entries);
  } catch (err) {
    fileList.innerHTML = `<div class="msg-system" style="color:var(--red);padding:12px">⚠ ${escHtml(err.message)}</div>`;
  }
}

function renderFileList(entries) {
  fileList.innerHTML = "";

  const parent = getParent(currentPath);
  if (parent && parent !== currentPath) {
    fileList.appendChild(makeFileItem({ name: "..", is_dir: true, path: parent }, "⬆"));
  }

  for (const e of entries) {
    const icon = e.is_dir ? "📁" : extIcon(e.ext);
    fileList.appendChild(makeFileItem(e, icon));
  }
}

function makeFileItem(e, icon) {
  const div = document.createElement("div");
  div.className = "file-item";
  div.dataset.path  = e.path;
  div.dataset.isDir = e.is_dir ? "1" : "0";
  div.innerHTML =
    `<span class="file-icon">${icon}</span>` +
    `<span class="file-name">${escHtml(e.name)}</span>` +
    (e.is_dir ? "" : `<span class="file-meta">${formatSize(e.size)}</span>`);
  div.addEventListener("click",       () => selectItem(div, e));
  div.addEventListener("dblclick",    () => { if (e.is_dir) navigateTo(e.path); else openFile(e); });
  div.addEventListener("contextmenu", ev => showContextMenu(ev, e));
  return div;
}

function selectItem(div, entry) {
  document.querySelectorAll(".file-item.selected").forEach(el => el.classList.remove("selected"));
  div.classList.add("selected");
  selectedItem = entry;
}

function openFile(entry) {
  appendMsg("system", `Selected: ${entry.path}`);
}

function getParent(path) {
  if (!path) return null;
  const sep   = path.includes("/") ? "/" : "\\";
  const parts = path.replace(/[/\\]+$/, "").split(sep);
  if (parts.length <= 1) return null;
  parts.pop();
  return parts.join(sep) || sep;
}

function extIcon(ext) {
  const map = {
    ".py":"📜", ".js":"📜", ".ts":"📜",
    ".jpg":"🖼", ".jpeg":"🖼", ".png":"🖼", ".gif":"🖼", ".svg":"🖼",
    ".mp3":"🎵", ".mp4":"🎬", ".avi":"🎬", ".mkv":"🎬",
    ".pdf":"📕", ".doc":"📝", ".docx":"📝", ".txt":"📄",
    ".zip":"📦", ".rar":"📦", ".7z":"📦",
    ".exe":"⚙",  ".msi":"⚙",
  };
  return map[ext.toLowerCase()] ?? "📄";
}

// ── Context menu ──────────────────────────────────────────────────────────
let ctxMenu = null;

function showContextMenu(ev, entry) {
  ev.preventDefault();
  removeCtxMenu();
  ctxMenu = document.createElement("div");
  ctxMenu.style.cssText =
    `position:fixed;left:${ev.clientX}px;top:${ev.clientY}px;` +
    `background:var(--bg3);border:1px solid var(--border);border-radius:8px;` +
    `padding:4px 0;z-index:200;min-width:160px;box-shadow:0 4px 20px rgba(0,0,0,.5);`;

  const items = [
    entry.is_dir
      ? ["Open",            () => navigateTo(entry.path)]
      : ["Open (select)",   () => appendMsg("system", `Selected file: ${entry.path}`)],
    ["Open in Explorer",    () => api("files/open-explorer", { method:"POST", body:JSON.stringify({ path:entry.path }) }).catch(e => appendMsg("error", e.message))],
    null,
    ["New File",    () => newFile()],
    ["New Folder",  () => newFolder()],
    null,
    ["Copy Path",   () => navigator.clipboard.writeText(entry.path)],
    ["Delete",      () => deleteItem(entry)],
  ];

  for (const item of items) {
    if (!item) {
      const sep = document.createElement("hr");
      sep.style.cssText = "border:none;border-top:1px solid var(--border);margin:4px 0;";
      ctxMenu.appendChild(sep);
      continue;
    }
    const btn = document.createElement("button");
    btn.textContent = item[0];
    btn.style.cssText =
      "display:block;width:100%;text-align:left;background:transparent;border:none;" +
      "color:var(--fg);padding:6px 16px;cursor:pointer;font-size:13px;";
    btn.onmouseenter = () => btn.style.background = "var(--bg-hover)";
    btn.onmouseleave = () => btn.style.background = "transparent";
    btn.onclick = () => { removeCtxMenu(); item[1](); };
    ctxMenu.appendChild(btn);
  }
  document.body.appendChild(ctxMenu);
  document.addEventListener("click", removeCtxMenu, { once: true });
}

function removeCtxMenu() { ctxMenu?.remove(); ctxMenu = null; }

// ── File operations ────────────────────────────────────────────────────────
async function newFile() {
  const name = await prompt("New file name:", "untitled.txt");
  if (!name) return;
  const path = joinPath(currentPath, name);
  try   { await api("files/create-file", { method:"POST", body:JSON.stringify({ path }) }); navigateTo(currentPath); }
  catch (e) { appendMsg("error", e.message); }
}

async function newFolder() {
  const name = await prompt("New folder name:", "New Folder");
  if (!name) return;
  const path = joinPath(currentPath, name);
  try   { await api("files/create-dir", { method:"POST", body:JSON.stringify({ path }) }); navigateTo(currentPath); }
  catch (e) { appendMsg("error", e.message); }
}

async function deleteItem(entry) {
  if (!confirm(`Delete "${entry.name}"?`)) return;
  try   { await api("files/delete", { method:"POST", body:JSON.stringify({ path:entry.path }) }); navigateTo(currentPath); }
  catch (e) { appendMsg("error", e.message); }
}

function joinPath(base, name) {
  const sep = base.includes("/") ? "/" : "\\";
  return base.replace(/[/\\]+$/, "") + sep + name;
}

// ── App launcher ──────────────────────────────────────────────────────────
async function loadApps() {
  appList.innerHTML = '<div class="msg-system" style="padding:12px">Loading…</div>';
  try {
    allApps = await api("apps/list");
    if (!allApps.length) {
      allApps = [
        { name:"Notepad",        cmd:"notepad.exe"    },
        { name:"Calculator",     cmd:"calc.exe"       },
        { name:"Paint",          cmd:"mspaint.exe"    },
        { name:"File Explorer",  cmd:"explorer.exe"   },
        { name:"Task Manager",   cmd:"taskmgr.exe"    },
        { name:"Command Prompt", cmd:"cmd.exe"        },
        { name:"PowerShell",     cmd:"powershell.exe" },
      ];
    }
    renderApps(allApps);
  } catch(e) {
    appList.innerHTML = `<div class="msg-system" style="color:var(--red)">⚠ ${escHtml(e.message)}</div>`;
  }
}

function renderApps(apps) {
  appList.innerHTML = "";
  for (const app of apps) {
    const div = document.createElement("div");
    div.className = "file-item";
    div.innerHTML = `<span class="file-icon">🚀</span><span class="file-name">${escHtml(app.name)}</span>`;
    div.addEventListener("dblclick", () => launchApp(app));
    div.addEventListener("click", () => {
      document.querySelectorAll(".file-item.selected").forEach(el => el.classList.remove("selected"));
      div.classList.add("selected");
    });
    appList.appendChild(div);
  }
}

async function launchApp(app) {
  try {
    await api("apps/launch", { method:"POST", body:JSON.stringify({ cmd: app.cmd }) });
    appendMsg("system", `Launched: ${app.name}`);
    setStatus(`Launched ${app.name}`);
  } catch(e) { appendMsg("error", e.message); }
}

// ── System Monitor ────────────────────────────────────────────────────────
let monitorInterval = null;
let allProcs        = [];
let selectedPid     = null;

function setBar(barId, valId, percent, detail) {
  const bar = $(barId);
  const val = $(valId);
  bar.style.width = Math.min(percent, 100) + "%";
  bar.className = "metric-fill" +
    (percent >= 90 ? " crit" : percent >= 70 ? " warn" : "");
  val.textContent = `${percent.toFixed(0)}%  ${detail}`;
}

async function refreshMonitor() {
  try {
    const snap = await api("monitor/snapshot");
    const cpu  = snap.cpu   || {};
    const ram  = snap.ram   || {};
    const disk = snap.disk  || {};
    const net  = snap.network || {};

    setBar("barCpu",  "valCpu",
      cpu.percent  || 0, `${cpu.count || ""} cores`);
    setBar("barRam",  "valRam",
      ram.percent  || 0, `${(ram.used_gb||0).toFixed(1)}/${(ram.total_gb||0).toFixed(1)} GB`);
    setBar("barDisk", "valDisk",
      disk.percent || 0, `${(disk.used_gb||0).toFixed(0)}/${(disk.total_gb||0).toFixed(0)} GB`);

    $("netUp").textContent = formatRate(net.bytes_sent_rate || 0);
    $("netDn").textContent = formatRate(net.bytes_recv_rate || 0);
  } catch { /* psutil not available or server error — silently skip */ }

  try {
    const procs = await api("monitor/processes?limit=50");
    allProcs = procs;
    filterProcs();
  } catch { /* silently skip */ }
}

function filterProcs() {
  const q    = ($("procSearch").value || "").toLowerCase();
  const rows = allProcs.filter(p => p.name.toLowerCase().includes(q));
  const tbody = $("procBody");
  tbody.innerHTML = "";
  for (const p of rows) {
    const tr = document.createElement("tr");
    tr.dataset.pid = p.pid;
    if (p.pid === selectedPid) tr.classList.add("selected");
    tr.innerHTML =
      `<td class="col-name" title="${escHtml(p.name)}">${escHtml(p.name)}</td>` +
      `<td class="col-num">${p.pid}</td>` +
      `<td class="col-num">${p.cpu.toFixed(1)}</td>` +
      `<td class="col-num">${p.mem.toFixed(1)}</td>` +
      `<td class="col-status">${escHtml(p.status)}</td>`;
    tr.addEventListener("click", () => {
      document.querySelectorAll("#procBody tr.selected").forEach(r => r.classList.remove("selected"));
      tr.classList.add("selected");
      selectedPid = p.pid;
    });
    tbody.appendChild(tr);
  }
}

async function killSelected() {
  if (selectedPid == null) return;
  const proc = allProcs.find(p => p.pid === selectedPid);
  const name = proc ? proc.name : `PID ${selectedPid}`;
  if (!confirm(`Kill "${name}" (PID ${selectedPid})?`)) return;
  try {
    const msg = await api("monitor/kill", { method:"POST", body:JSON.stringify({ pid: selectedPid }) });
    appendMsg("system", msg || `Killed PID ${selectedPid}`);
    selectedPid = null;
    refreshMonitor();
  } catch(e) { appendMsg("error", e.message); }
}

function startMonitor() {
  if (monitorInterval) return;
  refreshMonitor();
  monitorInterval = setInterval(refreshMonitor, 2000);
}

function stopMonitor() {
  if (monitorInterval) { clearInterval(monitorInterval); monitorInterval = null; }
}

// ── Voice ─────────────────────────────────────────────────────────────────
let recognition = null;
const btnVoice  = $("btnVoice");

function toggleVoice() {
  if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
    appendMsg("error", "Speech recognition not supported. Use Chrome.");
    return;
  }
  if (recognition) { recognition.stop(); return; }
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SR();
  recognition.lang = "en-US";
  recognition.interimResults = false;
  recognition.onstart  = () => { btnVoice.textContent = "🔴"; setStatus("Listening…", "yellow"); };
  recognition.onresult = e  => { chatInput.value = e.results[0][0].transcript; sendMessage(); };
  recognition.onerror  = e  => appendMsg("error", "Voice error: " + e.error);
  recognition.onend    = () => { recognition = null; btnVoice.textContent = "🎤"; setStatus("Ready"); };
  recognition.start();
}

// ── Init ──────────────────────────────────────────────────────────────────
async function init() {
  try {
    const info = await api("info");
    document.querySelector(".logo").textContent = `🤖 ${info.name}`;

    for (const p of info.providers) {
      const opt = document.createElement("option");
      opt.value = p;
      opt.textContent = p.charAt(0).toUpperCase() + p.slice(1);
      if (p === info.default_provider) opt.selected = true;
      providerSelect.appendChild(opt);
    }
    if (!info.providers.length) {
      appendMsg("error", "No AI provider configured — add an API key to .env");
    }

    const drives = await api("files/drives");
    navigateTo(drives.length ? drives[0] : "/");
    loadApps();
    appendMsg("system", `${info.name} v${info.version} ready.`);
    setStatus("Ready");
  } catch(e) {
    appendMsg("error", "Init failed: " + e.message);
  }
}

// ── Event bindings ─────────────────────────────────────────────────────────
$("btnSend").addEventListener("click",   sendMessage);
chatInput.addEventListener("keydown",    e => { if (e.key === "Enter") sendMessage(); });
$("btnClear").addEventListener("click",  clearChat);
$("btnVoice").addEventListener("click",  toggleVoice);
$("btnScreenshot").addEventListener("click", async () => {
  try {
    const path = await api("screenshot", { method:"POST" });
    appendMsg("system", `Screenshot saved: ${path}`);
  } catch(e) { appendMsg("error", e.message); }
});

// File browser toolbar
$("btnUp").addEventListener("click",      () => { const p = getParent(currentPath); if (p) navigateTo(p); });
$("btnHome").addEventListener("click",    () => navigateTo(navigator.platform.startsWith("Win") ? "C:\\" : "/home"));
$("btnRefresh").addEventListener("click", () => { if (currentPath) navigateTo(currentPath); });
$("btnGo").addEventListener("click",      () => navigateTo(pathInput.value.trim()));
pathInput.addEventListener("keydown",    e => { if (e.key === "Enter") navigateTo(pathInput.value.trim()); });
$("btnNewFile").addEventListener("click", newFile);
$("btnNewDir").addEventListener("click",  newFolder);
$("btnOpenExp").addEventListener("click", () =>
  api("files/open-explorer", { method:"POST", body:JSON.stringify({ path:currentPath }) })
    .catch(e => appendMsg("error", e.message)));

// Tabs — start/stop monitor on tab switch
document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    tab.classList.add("active");
    const tabName = tab.dataset.tab;
    $("tab" + tabName.charAt(0).toUpperCase() + tabName.slice(1)).classList.add("active");
    if (tabName === "monitor") startMonitor(); else stopMonitor();
  });
});

// App search
appSearch.addEventListener("input", () => {
  const q = appSearch.value.toLowerCase();
  renderApps(allApps.filter(a => a.name.toLowerCase().includes(q)));
});

// Process filter + kill
$("procSearch").addEventListener("input", filterProcs);
$("btnProcKill").addEventListener("click", killSelected);

init();
