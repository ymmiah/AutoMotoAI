"use strict";
/* ═══════════════════════════════════════════════════════════
   AutoMoto AI  ·  Open-Source AI Assistant  ·  Frontend SPA
   ═══════════════════════════════════════════════════════════ */

// ── Constants ────────────────────────────────────────────────────────────────
const CSRF_HEADER = { "X-Requested-With": "XMLHttpRequest" };
const JSON_HEADERS = { "Content-Type": "application/json", ...CSRF_HEADER };

// Server-issued session token (stored in sessionStorage so it lives for the tab)
let SESSION_TOKEN = sessionStorage.getItem("amAiSession") || null;

// ── DOM refs ──────────────────────────────────────────────────────────────────
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
const welcomeScreen  = $("welcomeScreen");

// ── Conversations (local state) ───────────────────────────────────────────────
const conversations = {};   // id → { title, msgs }
let activeConvId = null;
let convCounter  = 0;

function newConversation() {
  const id = "c" + (++convCounter) + "_" + Date.now();
  conversations[id] = { title: "New conversation", msgs: [] };
  activeConvId = id;
  chatHistory.innerHTML = "";
  chatHistory.appendChild(welcomeScreen);
  welcomeScreen.style.display = "";
  $("topbarTitle").textContent = "New conversation";
  renderConvList();
  clearServer();
  return id;
}

function renderConvList() {
  const list = $("convList");
  list.innerHTML = "";
  const ids = Object.keys(conversations).reverse();
  for (const id of ids) {
    const item = document.createElement("div");
    item.className = "conv-item" + (id === activeConvId ? " active" : "");
    item.innerHTML =
      `<span class="conv-icon">💬</span>` +
      `<span class="conv-label">${escHtml(conversations[id].title)}</span>`;
    item.addEventListener("click", () => switchConv(id));
    list.appendChild(item);
  }
}

function switchConv(id) {
  activeConvId = id;
  const conv = conversations[id];
  chatHistory.innerHTML = "";
  if (!conv.msgs.length) {
    chatHistory.appendChild(welcomeScreen);
    welcomeScreen.style.display = "";
  }
  conv.msgs.forEach(m => renderPersistedMsg(m));
  $("topbarTitle").textContent = conv.title;
  renderConvList();
}

function renderPersistedMsg(m) {
  if (m.type === "user")       appendMsg("user", m.text);
  else if (m.type === "bot")   appendMsg("bot",  m.text);
  else if (m.type === "system") appendMsg("system", m.text);
}

async function clearServer() {
  if (!SESSION_TOKEN) return;
  try {
    await fetch("/api/chat/clear", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ session_token: SESSION_TOKEN }),
    });
  } catch { /* silent */ }
}

// ── Session init ─────────────────────────────────────────────────────────────
async function initSession() {
  try {
    const res = await fetch("/api/session/new", { method: "POST", headers: CSRF_HEADER });
    const j = await res.json();
    if (j.ok && j.data) {
      SESSION_TOKEN = j.data.token;
      sessionStorage.setItem("amAiSession", SESSION_TOKEN);
    }
  } catch { /* server may not have session endpoint yet — fall back */ }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
async function api(endpoint, options = {}) {
  const headers = { ...JSON_HEADERS, ...(options.headers || {}) };
  const res = await fetch(`/api/${endpoint}`, { ...options, headers });
  const json = await res.json();
  if (!json.ok) throw new Error(json.error || "API error");
  return json.data;
}

function setStatus(text, type = "green") {
  statusBadge.textContent = text;
  statusBadge.className = `badge badge-${type}`;
}

function modalPromptBox(question, defaultVal = "") {
  return new Promise(resolve => {
    modalPrompt.textContent = question;
    modalInput.value = defaultVal;
    modal.classList.remove("hidden");
    modalInput.focus();
    const ok = () => { modal.classList.add("hidden"); resolve(modalInput.value.trim() || null); };
    const cancel = () => { modal.classList.add("hidden"); resolve(null); };
    $("modalOk").onclick     = ok;
    $("modalCancel").onclick = cancel;
    modalInput.onkeydown = e => {
      if (e.key === "Enter")  ok();
      if (e.key === "Escape") cancel();
    };
  });
}

function formatSize(bytes) {
  if (!bytes) return "";
  if (bytes < 1024)       return bytes + " B";
  if (bytes < 1024 ** 2) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1024 ** 2).toFixed(1) + " MB";
}

function formatRate(bps) {
  if (bps < 1024)      return bps + " B/s";
  if (bps < 1024 ** 2) return (bps / 1024).toFixed(1) + " KB/s";
  return (bps / 1024 ** 2).toFixed(1) + " MB/s";
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Markdown-lite renderer ────────────────────────────────────────────────────
function renderMarkdown(raw) {
  const lines = raw.split("\n");
  let html = "";
  let inCode = false;
  let codeLang = "";
  let codeBuf  = "";

  for (const line of lines) {
    if (!inCode && (line.startsWith("```") || line.startsWith("~~~"))) {
      inCode = true;
      codeLang = line.slice(3).trim();
      codeBuf  = "";
      continue;
    }
    if (inCode && (line.startsWith("```") || line.startsWith("~~~"))) {
      inCode = false;
      const esc = escHtml(codeBuf);
      html +=
        `<pre><button class="pre-copy" onclick="copyCode(this)">Copy</button>` +
        (codeLang ? `<span class="code-lang">${escHtml(codeLang)}</span>` : "") +
        `<code>${esc}</code></pre>`;
      codeBuf = "";
      continue;
    }
    if (inCode) { codeBuf += line + "\n"; continue; }

    let l = escHtml(line);
    // headings
    if (l.startsWith("### ")) { html += `<h3>${l.slice(4)}</h3>`; continue; }
    if (l.startsWith("## "))  { html += `<h2>${l.slice(3)}</h2>`; continue; }
    if (l.startsWith("# "))   { html += `<h1>${l.slice(2)}</h1>`; continue; }
    // hr
    if (/^---+$/.test(l.trim()) || /^===+$/.test(l.trim())) { html += "<hr>"; continue; }
    // bullet
    if (l.startsWith("- ") || l.startsWith("* ")) {
      html += `<li>${inlineMarkdown(l.slice(2))}</li>`; continue;
    }
    // blank line
    if (!l.trim()) { html += "<br>"; continue; }
    html += `<p>${inlineMarkdown(l)}</p>`;
  }
  if (inCode) html += `<pre><code>${escHtml(codeBuf)}</code></pre>`;
  return html;
}

function inlineMarkdown(str) {
  return str
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}

window.copyCode = function(btn) {
  const code = btn.parentElement.querySelector("code");
  if (!code) return;
  navigator.clipboard.writeText(code.textContent).then(() => {
    btn.textContent = "Copied!";
    setTimeout(() => btn.textContent = "Copy", 1500);
  });
};

// ── Command history ───────────────────────────────────────────────────────────
const cmdHistory = [];
let   histIdx    = -1;

function pushHistory(text) {
  if (cmdHistory.at(-1) !== text) cmdHistory.push(text);
  if (cmdHistory.length > 200) cmdHistory.shift();
  histIdx = -1;
}

chatInput.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); return; }
  if (e.key === "ArrowUp") {
    if (!cmdHistory.length) return;
    e.preventDefault();
    histIdx = histIdx < 0 ? cmdHistory.length - 1 : Math.max(0, histIdx - 1);
    chatInput.value = cmdHistory[histIdx];
    autoResize(chatInput);
  } else if (e.key === "ArrowDown") {
    if (histIdx < 0) return;
    e.preventDefault();
    histIdx++;
    chatInput.value = histIdx >= cmdHistory.length ? (histIdx = -1, "") : cmdHistory[histIdx];
    autoResize(chatInput);
  }
});

function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 180) + "px";
}
chatInput.addEventListener("input", () => autoResize(chatInput));

// ── Chat rendering ────────────────────────────────────────────────────────────
let msgGroup = null;

function ensureGroup() {
  if (!msgGroup) {
    msgGroup = document.createElement("div");
    msgGroup.className = "msg-group";
    chatHistory.appendChild(msgGroup);
  }
}

function appendMsg(role, text) {
  welcomeScreen.style.display = "none";
  ensureGroup();

  const wrap = document.createElement("div");
  wrap.className = `msg-wrap ${role === "user" ? "user" : role === "bot" ? "bot" : "system-msg"}`;

  if (role === "user") {
    wrap.innerHTML =
      `<div class="msg-label">You</div>` +
      `<div class="msg user">${escHtml(text)}</div>`;
  } else if (role === "bot") {
    wrap.innerHTML =
      `<div class="msg-label">AutoMoto AI</div>` +
      `<div class="msg bot">${renderMarkdown(text)}</div>`;
  } else if (role === "system") {
    wrap.innerHTML = `<div class="msg system">${escHtml(text)}</div>`;
  } else if (role === "error") {
    wrap.innerHTML = `<div class="msg error">⚠ ${escHtml(text)}</div>`;
  }
  msgGroup.appendChild(wrap);
  chatHistory.scrollTop = chatHistory.scrollHeight;

  if (activeConvId && conversations[activeConvId]) {
    if (role === "user" || role === "bot") {
      conversations[activeConvId].msgs.push({ type: role, text });
    }
  }
  return wrap;
}

function appendToolCardWrap() {
  const wrap = document.createElement("div");
  wrap.className = "tool-card-wrap";
  msgGroup.appendChild(wrap);
  chatHistory.scrollTop = chatHistory.scrollHeight;
  return wrap;
}

function appendToolCall(name, args) {
  const wrap = appendToolCardWrap();
  const argsStr = Object.keys(args).length
    ? JSON.stringify(args, null, 0).slice(0, 120)
    : "";
  wrap.innerHTML =
    `<div class="tool-call-card">` +
    `<span class="tool-name">🔧 ${escHtml(name)}</span>` +
    (argsStr ? `<span class="tool-args">${escHtml(argsStr)}</span>` : "") +
    `</div>`;
}

function appendToolResult(name, result, success) {
  const wrap = appendToolCardWrap();
  const cls  = success ? "ok" : "err";
  const icon = success ? "✅" : "❌";
  const prev = result.slice(0, 200).replace(/\n/g, " ") + (result.length > 200 ? "…" : "");
  wrap.innerHTML =
    `<div class="tool-result-card ${cls}">${icon} <strong>${escHtml(name)}</strong>: ${escHtml(prev)}</div>`;
}

// ── Streaming bot message ─────────────────────────────────────────────────────
let _streaming  = false;
let _botMsgEl   = null;
let _botRawText = "";

function beginBotStream() {
  welcomeScreen.style.display = "none";
  ensureGroup();
  const wrap = document.createElement("div");
  wrap.className = "msg-wrap bot";
  wrap.innerHTML = `<div class="msg-label">AutoMoto AI</div><div class="msg bot streaming"></div>`;
  _botMsgEl = wrap.querySelector(".msg.bot");
  msgGroup.appendChild(wrap);
  _botRawText = "";
  _streaming = true;
}

function appendToken(text) {
  if (!_botMsgEl) beginBotStream();
  _botRawText += text;
  _botMsgEl.innerHTML = renderMarkdown(_botRawText);
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

function endBotStream(fullText) {
  if (_botMsgEl) {
    _botMsgEl.classList.remove("streaming");
    if (fullText) _botMsgEl.innerHTML = renderMarkdown(fullText);
  }
  if (activeConvId && fullText && conversations[activeConvId]) {
    conversations[activeConvId].msgs.push({ type: "bot", text: fullText });
    if (conversations[activeConvId].msgs.length === 2) {
      const firstUserMsg = conversations[activeConvId].msgs.find(m => m.type === "user");
      if (firstUserMsg) {
        conversations[activeConvId].title = firstUserMsg.text.slice(0, 40) +
          (firstUserMsg.text.length > 40 ? "…" : "");
        $("topbarTitle").textContent = conversations[activeConvId].title;
        renderConvList();
      }
    }
  }
  _botMsgEl   = null;
  _botRawText = "";
  _streaming  = false;
}

// ── File attach ───────────────────────────────────────────────────────────────
const attachedFiles = [];   // { name, content (string) }
const attachChips   = $("attachChips");
const fileInput     = $("fileInput");

function refreshChips() {
  attachChips.innerHTML = "";
  if (!attachedFiles.length) { attachChips.classList.add("hidden"); return; }
  attachChips.classList.remove("hidden");
  attachedFiles.forEach((f, i) => {
    const chip = document.createElement("div");
    chip.className = "attach-chip";
    chip.innerHTML =
      `<span>📄 ${escHtml(f.name)}</span>` +
      `<button title="Remove" onclick="removeChip(${i})">✕</button>`;
    attachChips.appendChild(chip);
  });
}

window.removeChip = function(idx) { attachedFiles.splice(idx, 1); refreshChips(); };

$("btnAttach").addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", () => {
  const readers = [];
  for (const file of fileInput.files) {
    if (attachedFiles.find(a => a.name === file.name)) continue;
    readers.push(new Promise(resolve => {
      const reader = new FileReader();
      reader.onload  = e => resolve({ name: file.name, content: e.target.result });
      reader.onerror = ()  => resolve({ name: file.name, content: `[Could not read: ${file.name}]` });
      reader.readAsText(file);
    }));
  }
  Promise.all(readers).then(results => {
    results.forEach(r => attachedFiles.push(r));
    refreshChips();
  });
  fileInput.value = "";
});

function buildAttachContext() {
  if (!attachedFiles.length) return "";
  const parts = attachedFiles.map(f =>
    `=== ${f.name} ===\n\n${f.content.slice(0, 40000)}` +
    (f.content.length > 40000 ? "\n… (truncated)" : "")
  );
  return `[${attachedFiles.length} file(s) attached]\n\n${parts.join("\n\n---\n\n")}`;
}

// ── Send message ──────────────────────────────────────────────────────────────
async function sendMessage() {
  const text = chatInput.value.trim();
  if (!text || _streaming) return;

  chatInput.value = "";
  autoResize(chatInput);
  pushHistory(text);

  const fileCtx = buildAttachContext();
  if (attachedFiles.length) {
    appendMsg("system", `Attached: ${attachedFiles.map(f => f.name).join(", ")}`);
    attachedFiles.length = 0;
    refreshChips();
  }

  const msgContent = fileCtx ? `${fileCtx}\n\nUser request: ${text}` : text;
  appendMsg("user", text);

  chatInput.disabled = true;
  $("btnSend").disabled = true;
  setStatus("Thinking…", "yellow");

  beginBotStream();

  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({
        message:       msgContent,
        session_token: SESSION_TOKEN,
        provider:      providerSelect.value || null,
        use_tools:     toolsToggle.checked,
      }),
    });

    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let   buf     = "";
    let   fullReply = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      const frames = buf.split("\n\n");
      buf = frames.pop();

      for (const frame of frames) {
        if (!frame.trim()) continue;
        let eventType = "message";
        let dataStr   = "";
        for (const line of frame.split("\n")) {
          if (line.startsWith("event: "))     eventType = line.slice(7).trim();
          else if (line.startsWith("data: ")) dataStr   = line.slice(6);
        }
        let payload;
        try { payload = JSON.parse(dataStr); } catch { continue; }

        if (eventType === "token") {
          fullReply += payload.text;
          appendToken(payload.text);
        } else if (eventType === "tool_call") {
          appendToolCall(payload.name, payload.args || {});
          beginBotStream();
        } else if (eventType === "tool_result") {
          appendToolResult(payload.name, payload.result, payload.success);
        } else if (eventType === "error") {
          endBotStream(fullReply || "");
          appendMsg("error", payload.message);
        } else if (eventType === "done") {
          endBotStream(payload.full_reply || fullReply);
        }
      }
    }
    endBotStream(fullReply);
    setStatus("Ready");
  } catch (err) {
    endBotStream("");
    appendMsg("error", err.message);
    setStatus("Error", "red");
  } finally {
    chatInput.disabled = false;
    $("btnSend").disabled = false;
    chatInput.focus();
  }
}

async function clearChat() {
  if (!activeConvId) return;
  conversations[activeConvId].msgs = [];
  await clearServer();
  chatHistory.innerHTML = "";
  chatHistory.appendChild(welcomeScreen);
  welcomeScreen.style.display = "";
  msgGroup = null;
  appendMsg("system", "Conversation cleared.");
}

// ── File browser ──────────────────────────────────────────────────────────────
let currentPath  = null;
let selectedItem = null;

async function navigateTo(path) {
  fileList.innerHTML = '<div class="msg system" style="margin:16px auto;font-size:12px">Loading…</div>';
  try {
    const entries = await api("files/list?path=" + encodeURIComponent(path));
    currentPath = path;
    pathInput.value = path;
    renderFileList(entries);
  } catch (err) {
    fileList.innerHTML = `<div class="file-item" style="color:var(--red)">⚠ ${escHtml(err.message)}</div>`;
  }
}

function renderFileList(entries) {
  fileList.innerHTML = "";
  const parent = getParent(currentPath);
  if (parent && parent !== currentPath)
    fileList.appendChild(makeFileItem({ name: "..", is_dir: true, path: parent }, "⬆"));
  for (const e of entries)
    fileList.appendChild(makeFileItem(e, e.is_dir ? "📁" : extIcon(e.ext)));
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

function openFile(entry) { appendMsg("system", `Selected: ${entry.path}`); }

function getParent(path) {
  if (!path) return null;
  const sep   = path.includes("/") ? "/" : "\\";
  const parts = path.replace(/[/\\]+$/, "").split(sep);
  if (parts.length <= 1) return null;
  parts.pop();
  return parts.join(sep) || sep;
}

function extIcon(ext) {
  const m = {
    ".py":"📜", ".js":"📜", ".ts":"📜", ".jsx":"📜", ".tsx":"📜",
    ".jpg":"🖼", ".jpeg":"🖼", ".png":"🖼", ".gif":"🖼", ".svg":"🖼",
    ".mp3":"🎵", ".mp4":"🎬", ".avi":"🎬", ".mkv":"🎬",
    ".pdf":"📕", ".doc":"📝", ".docx":"📝", ".pptx":"📊", ".xlsx":"📊",
    ".txt":"📄", ".md":"📄", ".csv":"📊",
    ".zip":"📦", ".rar":"📦", ".7z":"📦",
    ".exe":"⚙", ".msi":"⚙",
  };
  return m[(ext||"").toLowerCase()] ?? "📄";
}

// ── Context menu ──────────────────────────────────────────────────────────────
let ctxMenu = null;

function showContextMenu(ev, entry) {
  ev.preventDefault();
  removeCtxMenu();
  ctxMenu = document.createElement("div");
  ctxMenu.className = "ctx-menu";
  ctxMenu.style.left = ev.clientX + "px";
  ctxMenu.style.top  = ev.clientY + "px";

  const items = [
    entry.is_dir
      ? ["📂 Open",          () => navigateTo(entry.path)]
      : ["📄 Select",        () => appendMsg("system", `Selected: ${entry.path}`)],
    ["🗂 Open in Explorer", () => api("files/open-explorer", { method: "POST", body: JSON.stringify({ path: entry.path }) }).catch(e => appendMsg("error", e.message))],
    null,
    ["+ New File",   () => newFile()],
    ["+ New Folder", () => newFolder()],
    null,
    ["📋 Copy path", () => navigator.clipboard.writeText(entry.path)],
    ["🗑 Delete",    () => deleteItem(entry)],
  ];

  for (const item of items) {
    if (!item) {
      const sep = document.createElement("hr");
      sep.className = "ctx-sep";
      ctxMenu.appendChild(sep);
      continue;
    }
    const btn = document.createElement("button");
    btn.className   = "ctx-item";
    btn.textContent = item[0];
    btn.onclick     = () => { removeCtxMenu(); item[1](); };
    ctxMenu.appendChild(btn);
  }
  document.body.appendChild(ctxMenu);
  document.addEventListener("click", removeCtxMenu, { once: true });
}

function removeCtxMenu() { ctxMenu?.remove(); ctxMenu = null; }

// ── File operations ────────────────────────────────────────────────────────────
async function newFile() {
  const name = await modalPromptBox("New file name:", "untitled.txt");
  if (!name) return;
  try {
    await api("files/create-file", { method: "POST", body: JSON.stringify({ path: joinPath(currentPath, name) }) });
    navigateTo(currentPath);
  } catch (e) { appendMsg("error", e.message); }
}

async function newFolder() {
  const name = await modalPromptBox("New folder name:", "New Folder");
  if (!name) return;
  try {
    await api("files/create-dir", { method: "POST", body: JSON.stringify({ path: joinPath(currentPath, name) }) });
    navigateTo(currentPath);
  } catch (e) { appendMsg("error", e.message); }
}

async function deleteItem(entry) {
  if (!confirm(`Delete "${entry.name}"?`)) return;
  try {
    await api("files/delete", { method: "POST", body: JSON.stringify({ path: entry.path }) });
    navigateTo(currentPath);
  } catch (e) { appendMsg("error", e.message); }
}

function joinPath(base, name) {
  const sep = (base || "").includes("/") ? "/" : "\\";
  return (base || "").replace(/[/\\]+$/, "") + sep + name;
}

// ── App launcher ──────────────────────────────────────────────────────────────
let allApps = [];

async function loadApps() {
  appList.innerHTML = '<div class="file-item">Loading…</div>';
  try {
    allApps = await api("apps/list");
    if (!allApps.length) allApps = [
      { name: "Notepad",        cmd: "notepad.exe"    },
      { name: "Calculator",     cmd: "calc.exe"       },
      { name: "Paint",          cmd: "mspaint.exe"    },
      { name: "File Explorer",  cmd: "explorer.exe"   },
      { name: "Task Manager",   cmd: "taskmgr.exe"    },
      { name: "Command Prompt", cmd: "cmd.exe"        },
      { name: "PowerShell",     cmd: "powershell.exe" },
    ];
    renderApps(allApps);
  } catch (e) {
    appList.innerHTML = `<div class="file-item" style="color:var(--red)">⚠ ${escHtml(e.message)}</div>`;
  }
}

function renderApps(apps) {
  appList.innerHTML = "";
  for (const a of apps) {
    const div = document.createElement("div");
    div.className = "file-item";
    div.innerHTML = `<span class="file-icon">🚀</span><span class="file-name">${escHtml(a.name)}</span>`;
    div.addEventListener("dblclick", () => launchApp(a));
    div.addEventListener("click", () => {
      document.querySelectorAll(".file-item.selected").forEach(el => el.classList.remove("selected"));
      div.classList.add("selected");
    });
    appList.appendChild(div);
  }
}

async function launchApp(a) {
  try {
    await api("apps/launch", { method: "POST", body: JSON.stringify({ cmd: a.cmd }) });
    appendMsg("system", `Launched: ${a.name}`);
  } catch (e) { appendMsg("error", e.message); }
}

// ── System monitor ────────────────────────────────────────────────────────────
let monitorInterval = null;
let allProcs = [];
let selectedPid = null;

function setBar(barId, valId, percent, detail) {
  const bar = $(barId);
  const val = $(valId);
  if (!bar || !val) return;
  bar.style.width  = Math.min(percent, 100) + "%";
  bar.className    = "metric-fill" + (percent >= 90 ? " crit" : percent >= 70 ? " warn" : "");
  val.textContent  = `${percent.toFixed(0)}%  ${detail}`;
}

async function refreshMonitor() {
  try {
    const snap = await api("monitor/snapshot");
    const cpu  = snap.cpu   || {};
    const ram  = snap.ram   || {};
    const disk = snap.disk  || {};
    const net  = snap.network || {};
    setBar("barCpu",  "valCpu",  cpu.percent  || 0, `${cpu.count || ""}c`);
    setBar("barRam",  "valRam",  ram.percent  || 0, `${(ram.used_gb||0).toFixed(1)}/${(ram.total_gb||0).toFixed(1)}GB`);
    setBar("barDisk", "valDisk", disk.percent || 0, `${(disk.used_gb||0).toFixed(0)}/${(disk.total_gb||0).toFixed(0)}GB`);
    $("netUp").textContent = formatRate(net.bytes_sent_rate || 0);
    $("netDn").textContent = formatRate(net.bytes_recv_rate || 0);
  } catch { /* psutil not available — silently skip */ }

  try {
    allProcs = await api("monitor/processes?limit=50");
    filterProcs();
  } catch { /* silently skip */ }
}

function filterProcs() {
  const q = ($("procSearch").value || "").toLowerCase();
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
  if (!confirm(`Kill "${name}" (PID ${selectedPid})?\n\nThis will forcefully terminate the process.`)) return;
  try {
    const msg = await api("monitor/kill", { method: "POST", body: JSON.stringify({ pid: selectedPid }) });
    appendMsg("system", msg || `Killed PID ${selectedPid}`);
    selectedPid = null;
    refreshMonitor();
  } catch (e) { appendMsg("error", e.message); }
}

function startMonitor() {
  if (monitorInterval) return;
  refreshMonitor();
  monitorInterval = setInterval(refreshMonitor, 2000);
}

function stopMonitor() {
  if (monitorInterval) { clearInterval(monitorInterval); monitorInterval = null; }
}

// ── Voice ─────────────────────────────────────────────────────────────────────
let recognition = null;
const btnVoice  = $("btnVoice");

function toggleVoice() {
  if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
    appendMsg("error", "Speech recognition not supported — use Chrome or Edge.");
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

// ── Theme ─────────────────────────────────────────────────────────────────────
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem("amAiTheme", t);
  $("btnTheme").textContent = t === "dark" ? "🌙" : "☀";
}

$("btnTheme").addEventListener("click", () => {
  const cur = document.documentElement.dataset.theme || "dark";
  applyTheme(cur === "dark" ? "light" : "dark");
});

// ── Settings modal ────────────────────────────────────────────────────────────
$("btnSettings").addEventListener("click", () => {
  $("settingsModal").classList.remove("hidden");
  const curTheme = document.documentElement.dataset.theme || "dark";
  $("settingTheme").value = curTheme;
  $("settingTools").checked = toolsToggle.checked;
  // Populate provider options if needed
  const settingProv = $("settingProvider");
  settingProv.innerHTML = providerSelect.innerHTML;
  settingProv.value = providerSelect.value;
});

$("btnCloseSettings").addEventListener("click", () => $("settingsModal").classList.add("hidden"));

$("btnSaveSettings").addEventListener("click", () => {
  applyTheme($("settingTheme").value);
  document.body.style.fontSize = $("settingFontSize").value + "px";
  toolsToggle.checked = $("settingTools").checked;
  providerSelect.value = $("settingProvider").value;
  $("settingsModal").classList.add("hidden");
});

// ── Tools panel ───────────────────────────────────────────────────────────────
$("btnOpenTools").addEventListener("click", () => {
  $("toolsPanel").classList.toggle("hidden");
  loadApps();
});
$("btnCloseTools").addEventListener("click", () => $("toolsPanel").classList.add("hidden"));

// Tabs in tools panel
document.querySelectorAll("#toolsPanel .tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll("#toolsPanel .tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll("#toolsPanel .tab-panel").forEach(p => p.classList.remove("active"));
    tab.classList.add("active");
    const id = "tab" + tab.dataset.tab.charAt(0).toUpperCase() + tab.dataset.tab.slice(1);
    $(id)?.classList.add("active");
    if (tab.dataset.tab === "mon") startMonitor(); else stopMonitor();
  });
});

// ── Sidebar toggle ────────────────────────────────────────────────────────────
$("btnToggleSidebar").addEventListener("click", () => {
  $("sidebar").classList.toggle("collapsed");
});

// ── Welcome card clicks ───────────────────────────────────────────────────────
document.querySelectorAll(".welcome-card").forEach(card => {
  card.addEventListener("click", () => {
    const prompt = card.dataset.prompt;
    if (!prompt) return;
    chatInput.value = prompt;
    autoResize(chatInput);
    chatInput.focus();
  });
});

// ── File browser bindings ─────────────────────────────────────────────────────
$("btnUp").addEventListener("click",      () => { const p = getParent(currentPath); if (p) navigateTo(p); });
$("btnHome").addEventListener("click",    () => navigateTo(navigator.platform.startsWith("Win") ? "C:\\" : (localStorage.getItem("amAiHome") || "/home")));
$("btnRefresh").addEventListener("click", () => { if (currentPath) navigateTo(currentPath); });
$("btnGo").addEventListener("click",      () => navigateTo(pathInput.value.trim()));
pathInput.addEventListener("keydown",    e => { if (e.key === "Enter") navigateTo(pathInput.value.trim()); });
$("btnNewFile").addEventListener("click", newFile);
$("btnNewDir").addEventListener("click",  newFolder);
$("btnOpenExp").addEventListener("click", () =>
  api("files/open-explorer", { method: "POST", body: JSON.stringify({ path: currentPath }) })
    .catch(e => appendMsg("error", e.message))
);

// App search
appSearch.addEventListener("input", () => {
  const q = appSearch.value.toLowerCase();
  renderApps(allApps.filter(a => a.name.toLowerCase().includes(q)));
});

// Process filter + kill
$("procSearch").addEventListener("input", filterProcs);
$("btnProcKill").addEventListener("click", killSelected);

// ── Sidebar new chat / input send ─────────────────────────────────────────────
$("btnNewChat").addEventListener("click", () => { newConversation(); });
$("btnSend").addEventListener("click", sendMessage);
$("btnClear").addEventListener("click", clearChat);
$("btnVoice").addEventListener("click", toggleVoice);
$("btnScreenshot").addEventListener("click", async () => {
  try {
    const path = await api("screenshot", { method: "POST" });
    appendMsg("system", `Screenshot saved: ${path}`);
  } catch (e) { appendMsg("error", e.message); }
});

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  // Restore theme
  const savedTheme = localStorage.getItem("amAiTheme") || "dark";
  applyTheme(savedTheme);

  // Get server session token
  await initSession();

  try {
    const info = await api("info");
    document.querySelector(".brand-name").textContent = info.name;
    $("footerVersion").textContent = info.version;

    for (const p of info.providers) {
      const opt = document.createElement("option");
      opt.value = p;
      opt.textContent = p.charAt(0).toUpperCase() + p.slice(1);
      if (p === info.default_provider) opt.selected = true;
      providerSelect.appendChild(opt);
    }

    if (!info.providers.length) {
      appendMsg("error",
        "No AI provider configured — add an API key to your .env file " +
        "(OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY)."
      );
    }

    // Load initial drive/directory
    try {
      const drives = await api("files/drives");
      const startPath = drives.length
        ? drives[0]
        : (navigator.platform.startsWith("Win") ? "C:\\" : "/home");
      navigateTo(startPath);
    } catch { /* silently skip file browser init */ }

    setStatus("Ready");
    appendMsg("system", `${info.name} v${info.version} · Open source AI assistant`);

  } catch (e) {
    appendMsg("error", "Initialisation failed: " + e.message);
  }

  // Create first conversation slot
  newConversation();
}

init();
