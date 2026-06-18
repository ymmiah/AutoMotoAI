"use strict";

/* ═══════════════════════════════════════════════════════════
   AutoMoto AI  ·  Frontend SPA
   ═══════════════════════════════════════════════════════════ */

const SESSION_ID = "s_" + Math.random().toString(36).slice(2);
let currentPath = null;
let selectedItem = null;
let allApps = [];

// ── DOM refs ──────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const chatHistory   = $("chatHistory");
const chatInput     = $("chatInput");
const providerSelect= $("providerSelect");
const statusBadge   = $("statusBadge");
const pathInput     = $("pathInput");
const fileList      = $("fileList");
const appList       = $("appList");
const appSearch     = $("appSearch");
const modal         = $("modal");
const modalPrompt   = $("modalPrompt");
const modalInput    = $("modalInput");

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

// ── Chat ──────────────────────────────────────────────────────────────────
function appendMsg(role, text) {
  const wrap = document.createElement("div");
  if (role === "user") {
    wrap.innerHTML = `<div class="msg-label" style="text-align:right">You</div>
                      <div class="msg msg-user">${escHtml(text)}</div>`;
    wrap.style.alignSelf = "flex-end";
    wrap.style.maxWidth  = "80%";
  } else if (role === "bot") {
    wrap.innerHTML = `<div class="msg-label">AutoMoto AI</div>
                      <div class="msg msg-bot">${escHtml(text)}</div>`;
    wrap.style.maxWidth = "80%";
  } else if (role === "system") {
    wrap.innerHTML = `<div class="msg msg-system">${escHtml(text)}</div>`;
    wrap.style.alignSelf = "center";
  } else if (role === "error") {
    wrap.innerHTML = `<div class="msg msg-error">⚠ ${escHtml(text)}</div>`;
  }
  chatHistory.appendChild(wrap);
  chatHistory.scrollTop = chatHistory.scrollHeight;
  return wrap;
}

function escHtml(str) {
  return str.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/\n/g,"<br>");
}

async function sendMessage() {
  const text = chatInput.value.trim();
  if (!text) return;
  chatInput.value = "";
  appendMsg("user", text);

  const thinkWrap = appendMsg("system", "");
  thinkWrap.querySelector(".msg-system").innerHTML =
    '<span class="thinking"><span class="spinner"></span> Thinking…</span>';
  chatInput.disabled = true;
  setStatus("Thinking…", "yellow");

  try {
    const data = await api("chat", {
      method: "POST",
      body: JSON.stringify({
        message: text,
        session_id: SESSION_ID,
        provider: providerSelect.value || null,
      }),
    });
    thinkWrap.remove();
    appendMsg("bot", data.reply);
    setStatus("Ready");
  } catch (err) {
    thinkWrap.remove();
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

  // ".." entry if not root
  const parent = getParent(currentPath);
  if (parent && parent !== currentPath) {
    const up = makeFileItem({ name: "..", is_dir: true, path: parent }, "⬆");
    fileList.appendChild(up);
  }

  for (const e of entries) {
    const icon = e.is_dir ? "📁" : extIcon(e.ext);
    fileList.appendChild(makeFileItem(e, icon));
  }
}

function makeFileItem(e, icon) {
  const div = document.createElement("div");
  div.className = "file-item";
  div.dataset.path = e.path;
  div.dataset.isDir = e.is_dir ? "1" : "0";
  div.innerHTML = `
    <span class="file-icon">${icon}</span>
    <span class="file-name">${escHtml(e.name)}</span>
    ${e.is_dir ? "" : `<span class="file-meta">${formatSize(e.size)}</span>`}
  `;
  div.addEventListener("click", () => selectItem(div, e));
  div.addEventListener("dblclick", () => {
    if (e.is_dir) navigateTo(e.path);
    else openFile(e);
  });
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
  const sep = path.includes("/") ? "/" : "\\";
  const parts = path.replace(/[/\\]+$/, "").split(sep);
  if (parts.length <= 1) return null;
  parts.pop();
  const parent = parts.join(sep) || sep;
  return parent || null;
}

function extIcon(ext) {
  const map = {
    ".py":".py📜", ".js":".js📜", ".ts":".ts📜",
    ".jpg":"🖼", ".jpeg":"🖼", ".png":"🖼", ".gif":"🖼", ".svg":"🖼",
    ".mp3":"🎵", ".mp4":"🎬", ".avi":"🎬", ".mkv":"🎬",
    ".pdf":"📕", ".doc":"📝", ".docx":"📝", ".txt":"📄",
    ".zip":"📦", ".rar":"📦", ".7z":"📦",
    ".exe":"⚙", ".msi":"⚙",
  };
  const e = ext.toLowerCase();
  for (const [k, v] of Object.entries(map)) {
    if (e === k) return v.length > 2 ? v.slice(-2) : v;
  }
  return "📄";
}

// ── Context menu ──────────────────────────────────────────────────────────
let ctxMenu = null;

function showContextMenu(ev, entry) {
  ev.preventDefault();
  removeCtxMenu();
  ctxMenu = document.createElement("div");
  ctxMenu.style.cssText = `
    position:fixed; left:${ev.clientX}px; top:${ev.clientY}px;
    background:var(--bg3); border:1px solid var(--border); border-radius:8px;
    padding:4px 0; z-index:200; min-width:160px; box-shadow:0 4px 20px rgba(0,0,0,.5);
  `;

  const items = [
    entry.is_dir
      ? ["Open",        () => navigateTo(entry.path)]
      : ["Open (select)", () => { appendMsg("system", `Selected file: ${entry.path}`); }],
    ["Open in Explorer", () => api("files/open-explorer", { method:"POST", body:JSON.stringify({ path:entry.path }) }).catch(e => appendMsg("error", e.message))],
    null,
    ["New File",   () => newFile()],
    ["New Folder", () => newFolder()],
    null,
    ["Copy Path",  () => navigator.clipboard.writeText(entry.path)],
    ["Delete",     () => deleteItem(entry)],
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
    btn.style.cssText = "display:block;width:100%;text-align:left;background:transparent;border:none;color:var(--fg);padding:6px 16px;cursor:pointer;font-size:13px;";
    btn.onmouseenter = () => btn.style.background = "var(--bg-hover)";
    btn.onmouseleave = () => btn.style.background = "transparent";
    btn.onclick = () => { removeCtxMenu(); item[1](); };
    ctxMenu.appendChild(btn);
  }
  document.body.appendChild(ctxMenu);
  document.addEventListener("click", removeCtxMenu, { once: true });
}

function removeCtxMenu() {
  ctxMenu?.remove();
  ctxMenu = null;
}

// ── File operations ────────────────────────────────────────────────────────
async function newFile() {
  const name = await prompt("New file name:", "untitled.txt");
  if (!name) return;
  const path = joinPath(currentPath, name);
  try {
    await api("files/create-file", { method:"POST", body:JSON.stringify({ path }) });
    navigateTo(currentPath);
  } catch(e) { appendMsg("error", e.message); }
}

async function newFolder() {
  const name = await prompt("New folder name:", "New Folder");
  if (!name) return;
  const path = joinPath(currentPath, name);
  try {
    await api("files/create-dir", { method:"POST", body:JSON.stringify({ path }) });
    navigateTo(currentPath);
  } catch(e) { appendMsg("error", e.message); }
}

async function deleteItem(entry) {
  if (!confirm(`Delete "${entry.name}"?`)) return;
  try {
    await api("files/delete", { method:"POST", body:JSON.stringify({ path:entry.path }) });
    navigateTo(currentPath);
  } catch(e) { appendMsg("error", e.message); }
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
        { name:"Notepad",       cmd:"notepad.exe"    },
        { name:"Calculator",    cmd:"calc.exe"       },
        { name:"Paint",         cmd:"mspaint.exe"    },
        { name:"File Explorer", cmd:"explorer.exe"   },
        { name:"Task Manager",  cmd:"taskmgr.exe"    },
        { name:"Command Prompt",cmd:"cmd.exe"        },
        { name:"PowerShell",    cmd:"powershell.exe" },
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

// ── Voice ─────────────────────────────────────────────────────────────────
let recognition = null;
const btnVoice = $("btnVoice");

function toggleVoice() {
  if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
    appendMsg("error", "Speech recognition not supported in this browser. Use Chrome.");
    return;
  }
  if (recognition) {
    recognition.stop();
    return;
  }
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRecognition();
  recognition.lang = "en-US";
  recognition.interimResults = false;
  recognition.onstart   = () => { btnVoice.textContent = "🔴"; setStatus("Listening…", "yellow"); };
  recognition.onresult  = e  => { chatInput.value = e.results[0][0].transcript; sendMessage(); };
  recognition.onerror   = e  => { appendMsg("error", "Voice error: " + e.error); };
  recognition.onend     = () => { recognition = null; btnVoice.textContent = "🎤"; setStatus("Ready"); };
  recognition.start();
}

// ── Init ──────────────────────────────────────────────────────────────────
async function init() {
  try {
    const info = await api("info");
    document.querySelector(".logo").textContent = `🤖 ${info.name}`;

    // Populate provider selector
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

    // Load file drives
    const drives = await api("files/drives");
    if (drives.length) navigateTo(drives[0]);
    else navigateTo("/");

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
$("btnHome").addEventListener("click",    () => navigateTo(navigator.platform.startsWith("Win") ? "C:\\" : "/home/" + (window.__username || "")));
$("btnRefresh").addEventListener("click", () => navigateTo(currentPath));
$("btnGo").addEventListener("click",      () => navigateTo(pathInput.value.trim()));
pathInput.addEventListener("keydown",    e => { if (e.key === "Enter") navigateTo(pathInput.value.trim()); });
$("btnNewFile").addEventListener("click", newFile);
$("btnNewDir").addEventListener("click",  newFolder);
$("btnOpenExp").addEventListener("click", () => {
  api("files/open-explorer", { method:"POST", body:JSON.stringify({ path:currentPath }) })
    .catch(e => appendMsg("error", e.message));
});

// Tabs
document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    tab.classList.add("active");
    $("tab" + tab.dataset.tab.charAt(0).toUpperCase() + tab.dataset.tab.slice(1)).classList.add("active");
  });
});

// App search
appSearch.addEventListener("input", () => {
  const q = appSearch.value.toLowerCase();
  renderApps(allApps.filter(a => a.name.toLowerCase().includes(q)));
});

init();
