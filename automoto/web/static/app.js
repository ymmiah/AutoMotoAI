// AutoMoto AI GUI - vanilla ES module, no build step, no CDN.
import { icon, hydrateIcons, TOOL_ICONS } from "./icons.js";

// Auth: the HttpOnly session cookie set by the one-time launch link (the page never sees a token).
const TOKEN = document.querySelector('meta[name="automoto-token"]')?.content || "";
const VERSION = document.querySelector('meta[name="automoto-version"]').content;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const isMac = /Mac|iPhone|iPad/.test(navigator.platform);
const MAX_IMAGES = 4;

const state = {
  convs: [], cur: null, mode: localStorage.getItem("automoto_mode") || "agent",
  providers: [], desktop: false, settings: null, attachments: [], files: [], running: new Map(),
  route: "", pageTimer: null, busy: false,
};

const keys = () => { try { return JSON.parse(sessionStorage.getItem("automoto_keys") || "{}"); } catch { return {}; } };
async function api(path, body, method) {
  const r = await fetch(path, {
    method: method || (body !== undefined ? "POST" : "GET"),
    headers: { "Content-Type": "application/json", ...(TOKEN ? { "X-AutoMoto-Token": TOKEN } : {}) },
    credentials: "same-origin",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;
    const msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => x.msg).join("; ") : data.error || r.statusText;
    throw Object.assign(new Error(msg), { data, status: r.status });
  }
  return data;
}

// ---------------------------------------------------------------- ui helpers
function toast(msg, kind = "") {
  const t = document.createElement("div");
  t.className = "toast " + kind;
  t.setAttribute("role", kind === "bad" ? "alert" : "status");
  t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 300); }, kind === "bad" ? 5200 : 3000);
}
function openModal(html, { onMount, label = "Dialog" } = {}) {
  const m = $("#modal");
  const prev = document.activeElement;
  m.innerHTML = `<div class="modal-box">${html}</div>`;
  m.setAttribute("aria-label", label);
  m.hidden = false;
  hydrateIcons(m);
  const close = () => { m.hidden = true; m.innerHTML = ""; prev?.focus?.(); };
  m.onclick = (e) => { if (e.target === m) close(); };
  m.onkeydown = (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
  onMount?.(m, close);
  ($("input, textarea, select, button.primary", m) || $("button", m))?.focus();
  return close;
}
function confirmDialog(text, { ok = "Delete", danger = true } = {}) {
  return new Promise((res) => {
    openModal(`<h3>${esc(text)}</h3><div class="row"><button class="btn" data-a="no">Cancel</button><button class="btn ${danger ? "danger" : "primary"}" data-a="yes">${esc(ok)}</button></div>`, {
      label: text,
      onMount: (m, close) => {
        $('[data-a="no"]', m).onclick = () => { close(); res(false); };
        $('[data-a="yes"]', m).onclick = () => { close(); res(true); };
        $('[data-a="yes"]', m).focus();
      },
    });
  });
}
function promptDialog(title, value = "", { ok = "Save" } = {}) {
  return new Promise((res) => {
    openModal(`<h3>${esc(title)}</h3><form><input class="input" name="v" value="${esc(value)}" aria-label="${esc(title)}" maxlength="120"><div class="row"><button type="button" class="btn" data-a="no">Cancel</button><button class="btn primary">${esc(ok)}</button></div></form>`, {
      label: title,
      onMount: (m, close) => {
        const inp = $("input", m); inp.select();
        $('[data-a="no"]', m).onclick = () => { close(); res(null); };
        $("form", m).onsubmit = (e) => { e.preventDefault(); const v = inp.value.trim(); close(); res(v || null); };
      },
    });
  });
}
function timeAgo(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(ts * 1000).toLocaleDateString();
}
const fmtTime = (ts) => new Date(ts * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- markdown
if (window.DOMPurify) {
  DOMPurify.addHook("afterSanitizeAttributes", (n) => {
    if (n.tagName === "A") { n.setAttribute("target", "_blank"); n.setAttribute("rel", "noopener noreferrer"); }
  });
}
function renderMarkdown(text) {
  const raw = window.marked ? marked.parse(String(text || ""), { gfm: true, breaks: true }) : esc(text);
  const html = window.DOMPurify ? DOMPurify.sanitize(raw, { FORBID_TAGS: ["style", "form", "input"], FORBID_ATTR: ["style"] }) : esc(text);
  const div = document.createElement("div");
  div.className = "md";
  div.innerHTML = html;
  $$("pre > code", div).forEach((code) => {
    const lang = ([...code.classList].find((c) => c.startsWith("language-")) || "").replace("language-", "");
    const pre = code.parentElement;
    const wrap = document.createElement("div");
    wrap.className = "code";
    wrap.innerHTML = `<div class="code-head"><span>${esc(lang || "code")}</span><button class="icon-btn sm" aria-label="Copy code" title="Copy">${icon("copy")}</button></div>`;
    pre.replaceWith(wrap);
    wrap.appendChild(pre);
    try {
      if (window.hljs) {
        if (lang && hljs.getLanguage(lang)) hljs.highlightElement(code);
        else { code.innerHTML = hljs.highlightAuto(code.textContent).value; code.classList.add("hljs"); }
      }
    } catch { /* plain text is fine */ }
    $("button", wrap).onclick = (e) => copyText(code.textContent, e.currentTarget);
  });
  return div;
}
async function copyText(text, btn) {
  try { await navigator.clipboard.writeText(text); } catch {
    const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }
  if (btn) { const old = btn.innerHTML; btn.innerHTML = icon("check"); setTimeout(() => (btn.innerHTML = old), 1200); }
  else toast("Copied");
}

// ---------------------------------------------------------------- theme
function applyTheme(theme, accent) {
  const dark = theme === "dark" || (theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  $("#hljsTheme").href = `/static/vendor/hljs-${dark ? "dark" : "light"}.css`;
  localStorage.setItem("automoto_theme", theme);
  if (accent) { document.documentElement.style.setProperty("--accent", accent); localStorage.setItem("automoto_accent", accent); }
}
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if ((localStorage.getItem("automoto_theme") || "dark") === "system") applyTheme("system");
});
async function saveSetting(patch) {
  try { state.settings = await api("/api/settings", patch, "PUT"); return true; }
  catch (e) { toast(e.message, "bad"); return false; }
}

// ---------------------------------------------------------------- providers
async function refreshStatus() {
  const [st, full] = await Promise.all([api("/api/status", { keys: keys() }), api("/api/status")]);
  state.providers = st.providers; state.desktop = full.desktop;
  const pick = $("#providerPick");
  const saved = localStorage.getItem("automoto_prefer") || "auto";
  pick.innerHTML = `<option value="auto">Auto · best available</option>` + st.providers.map((p) =>
    `<option value="${p.id}" ${p.configured ? "" : "disabled"}>${esc(p.label)}${p.supports_vision ? " 👁" : ""}${p.configured ? "" : " (no key)"}</option>`).join("");
  pick.value = st.providers.some((p) => p.id === saved && p.configured) ? saved : "auto";
  pick.title = st.providers.filter((p) => p.configured).map((p) => `${p.label}: ${p.agent_model}`).join("\n") || "No keys yet";
  return st;
}
$("#providerPick").addEventListener("change", (e) => localStorage.setItem("automoto_prefer", e.target.value));

// ---------------------------------------------------------------- sidebar
async function loadConvs() {
  const q = $("#convSearch").value.trim();
  try { state.convs = (await api(`/api/conversations?q=${encodeURIComponent(q)}`)).conversations; }
  catch { state.convs = []; }
  renderConvs();
}
function renderConvs() {
  const list = $("#convList");
  if (!state.convs.length) {
    list.innerHTML = `<div class="empty-list">${$("#convSearch").value ? "No chats match." : "No chats yet. Start one!"}</div>`;
    return;
  }
  const now = new Date(); const day = 86400;
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
  const group = (t) => t >= start ? "Today" : t >= start - day ? "Yesterday" : t >= start - 7 * day ? "Previous 7 days" : "Older";
  let last = "", html = "";
  for (const c of state.convs) {
    const g = group(c.updated);
    if (g !== last) { html += `<div class="group-label">${g}</div>`; last = g; }
    const active = state.cur?.id === c.id ? " active" : "";
    html += `<div class="conv${active}" role="listitem" tabindex="0" data-id="${c.id}" title="${esc(c.title)}">
      ${state.running.has(c.id) ? '<span class="running" aria-label="running"></span>' : icon(c.mode === "chat" ? "chat" : "bolt")}
      <span class="t">${esc(c.title)}</span>
      <span class="acts"><button class="icon-btn sm" data-act="rename" aria-label="Rename chat">${icon("edit")}</button><button class="icon-btn sm" data-act="delete" aria-label="Delete chat">${icon("trash")}</button></span></div>`;
  }
  list.innerHTML = html;
}
$("#convList").addEventListener("click", (e) => {
  const row = e.target.closest(".conv"); if (!row) return;
  const id = row.dataset.id, act = e.target.closest("[data-act]")?.dataset.act;
  if (act === "rename") return renameConv(id);
  if (act === "delete") return deleteConv(id);
  location.hash = `#/c/${id}`;
  closeSidebarMobile();
});
$("#convList").addEventListener("keydown", (e) => {
  const row = e.target.closest(".conv");
  if (!row || e.target !== row) return;
  if (e.key === "Enter") { location.hash = `#/c/${row.dataset.id}`; closeSidebarMobile(); }
  if (e.key === "Delete") deleteConv(row.dataset.id);
});
let searchTimer;
$("#convSearch").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(loadConvs, 180); });
async function renameConv(id) {
  const c = state.convs.find((x) => x.id === id) || state.cur;
  const v = await promptDialog("Rename chat", c?.title || "");
  if (!v) return;
  try {
    await api(`/api/conversations/${id}`, { title: v }, "PATCH");
    if (state.cur?.id === id) { state.cur.title = v; renderTitle(); }
    loadConvs(); toast("Renamed");
  } catch (e) { toast(e.message, "bad"); }
}
async function deleteConv(id) {
  if (!(await confirmDialog("Delete this chat?"))) return;
  try {
    await api(`/api/conversations/${id}`, undefined, "DELETE");
    if (state.cur?.id === id) location.hash = "#/new";
    loadConvs(); toast("Chat deleted");
  } catch (e) { toast(e.message, "bad"); }
}

const app = $("#app");
const mobile = () => matchMedia("(max-width: 760px)").matches;
function toggleSidebar() {
  if (mobile()) {
    const open = !app.classList.contains("side-open");
    app.classList.toggle("side-open", open); $("#scrim").hidden = !open;
    if (open) $("#convSearch").focus();
  } else app.classList.toggle("side-collapsed");
}
function closeSidebarMobile() { app.classList.remove("side-open"); $("#scrim").hidden = true; }
$("#toggleSide").onclick = toggleSidebar;
$("#closeSide").onclick = closeSidebarMobile;
$("#scrim").onclick = closeSidebarMobile;
$("#toggleInfo").onclick = () => { $("#info").hidden = !$("#info").hidden; localStorage.setItem("automoto_info", $("#info").hidden ? "0" : "1"); };
$("#closeInfo").onclick = () => { $("#info").hidden = true; localStorage.setItem("automoto_info", "0"); };
$("#newChat").onclick = () => newChat();
function newChat() { closeSidebarMobile(); if (location.hash === "#/new") renderRoute(); else location.hash = "#/new"; }

function setMode(m, persist = true) {
  state.mode = m;
  $$("#modeSeg button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.mode === m)));
  if (persist) localStorage.setItem("automoto_mode", m);
  const ta = $("#composerInput");
  if (ta) ta.placeholder = m === "agent" ? "Give AutoMoto a goal…" : "Message AutoMoto…";
  if (persist && state.cur?.id) api(`/api/conversations/${state.cur.id}`, { mode: m }, "PATCH").catch(() => {});
}
$("#modeSeg").addEventListener("click", (e) => { const b = e.target.closest("button[data-mode]"); if (b) setMode(b.dataset.mode); });
$("#modeSeg").addEventListener("keydown", (e) => {
  if (["ArrowLeft", "ArrowRight"].includes(e.key)) { setMode(state.mode === "agent" ? "chat" : "agent"); $(`#modeSeg [data-mode="${state.mode}"]`).focus(); }
});

// ---------------------------------------------------------------- router
window.addEventListener("hashchange", renderRoute);
async function renderRoute() {
  clearInterval(state.pageTimer);
  const h = location.hash || "#/new";
  state.route = h;
  const [, pg, id] = h.split("/");
  $$(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === pg));
  const chatish = pg === "c" || pg === "new" || !PAGES[pg];
  $("#modeSeg").style.visibility = chatish ? "" : "hidden";
  $(".picker").style.visibility = chatish ? "" : "hidden";
  closeSidebarMobile();
  if (pg === "c" && id) return openConv(id);
  state.cur = null; renderConvs();
  if (PAGES[pg]) return PAGES[pg]();
  return renderChat(null);
}

// ---------------------------------------------------------------- chat view
const SUGGESTIONS = [
  { i: "globe", t: "Research with sources", s: "What's new with NVIDIA NIM this month? 5 bullets with links.", p: "Search the web for what's new with NVIDIA NIM this month and give me 5 bullets with links." },
  { i: "terminal", t: "Build & test", s: "A tiny Python CLI with a test, run in the sandbox.", p: "Create a tiny Python project in scratch/hello-cli with a README and a pytest test, then run the test and show me the result." },
  { i: "brain", t: "Remember me", s: "Save a preference for every future chat.", p: "Remember that I prefer concise answers with bullet points." },
  { i: "image", t: "Read an image", s: "Attach a screenshot and ask what it shows.", p: "Describe this image and point out anything I should fix.", attach: true },
];
async function openConv(id) {
  try {
    const conv = await api(`/api/conversations/${id}`);
    state.cur = conv;
    setMode(conv.mode || state.mode, false);
    renderConvs();
    renderChat(conv);
    const t = (await api("/api/tasks")).tasks.find((x) => x.conversation_id === id && ["running", "waiting_approval", "queued"].includes(x.status));
    if (t && state.cur?.id === id) { state.running.set(id, t.id); streamTask(t.id, addBot(), id); }
  } catch (e) {
    toast(e.status === 404 ? "That chat no longer exists" : e.message, "bad");
    location.hash = "#/new";
  }
}
function renderTitle() {
  if (!state.cur) { $("#pageTitle").textContent = "New chat"; return; }
  const c = state.convs.find((x) => x.id === state.cur.id); if (c) state.cur.title = c.title;
  $("#pageTitle").innerHTML = `<button class="btn ghost sm" id="titleBtn" title="Rename chat" style="font-size:15px;font-weight:600;max-width:100%;overflow:hidden;text-overflow:ellipsis">${esc(state.cur.title)}</button>`;
  $("#titleBtn").onclick = () => renameConv(state.cur.id);
}
function renderChat(conv) {
  renderTitle();
  $("#view").innerHTML = `<div class="chat">
    <div class="messages" id="msgs" role="log" aria-live="polite" aria-label="Conversation"><div class="thread" id="thread"></div></div>
    <div class="composer-wrap">
      <form class="composer" id="composer" aria-label="Message composer">
        <div class="attachments" id="attachments" aria-label="Attachments"></div>
        <label class="sr" for="composerInput">Message</label>
        <textarea id="composerInput" rows="1" placeholder="${state.mode === "agent" ? "Give AutoMoto a goal…" : "Message AutoMoto…"}"></textarea>
        <div class="bar">
          <input type="file" id="fileInput" accept="image/*,.docx,.doc,.odt,.rtf,.xlsx,.xls,.ods,.csv,.tsv,.pptx,.ppt,.odp,.pdf,.md,.txt,.log,.json,.jsonl,.yaml,.yml,.toml,.xml,.parquet,.sqlite,.db,.zip,.tar,.gz,.tgz,.bz2,.xz,.7z,.rar" multiple hidden>
          <button type="button" class="icon-btn" id="attachBtn" aria-label="Attach image or file" title="Attach an image, Word, Excel, PowerPoint or PDF file (or paste / drop)">${icon("clip")}</button>
          <span class="hint">Enter to send · Shift+Enter new line · ${isMac ? "⌘" : "Ctrl"}+K commands</span>
          <span class="spacer"></span>
          <button class="send" id="sendBtn" aria-label="Send message" title="Send">${icon("send")}</button>
        </div>
      </form>
      <div class="footer-note">AutoMoto can make mistakes. Risky actions always ask you first.</div>
    </div></div>`;
  const thread = $("#thread");
  if (!conv || !conv.messages?.length) {
    $("#msgs").innerHTML = `<div class="hero"><div class="logo" aria-hidden="true">A</div><h2>Hey, cousin 👋</h2>
      <p>Give me a goal. I'll search the web, work in my sandbox, run commands after you approve, remember what matters and report back.</p>
      <div class="chips">${SUGGESTIONS.map((s, i) => `<button type="button" class="chip" data-i="${i}">${icon(s.i)}<span><b>${esc(s.t)}</b><small>${esc(s.s)}</small></span></button>`).join("")}</div></div>`;
    $$(".chip").forEach((b) => b.onclick = () => {
      const s = SUGGESTIONS[b.dataset.i];
      $("#composerInput").value = s.p; autosize();
      if (s.attach) $("#fileInput").click(); else $("#composerInput").focus();
    });
    $("#infoBody").innerHTML = '<p class="muted">Start an agent run to see the provider, model and every step here.</p>';
  } else {
    for (const m of conv.messages) m.role === "user" ? addUser(m.content, thread) : renderSavedBot(m, thread);
    updateInfoFromConv(conv);
  }
  wireComposer();
  renderAttachments();
  scrollDown(true);
  if (!mobile()) $("#composerInput").focus();
}
function scrollDown(force) {
  const m = $("#msgs"); if (!m) return;
  if (force || m.scrollHeight - m.scrollTop - m.clientHeight < 260) m.scrollTop = m.scrollHeight;
}
function ensureThread() {
  if (!$("#thread")) $("#msgs").innerHTML = '<div class="thread" id="thread"></div>';
  return $("#thread");
}
function addUser(content, thread = ensureThread()) {
  const text = typeof content === "string" ? content : content.filter((p) => p.type === "text").map((p) => p.text).join("\n");
  const imgs = Array.isArray(content) ? content.filter((p) => p.type === "image_url").map((p) => p.image_url.url) : [];
  const d = document.createElement("div");
  d.className = "msg user";
  d.innerHTML = `<div><div class="bubble">${esc(text)}</div>${imgs.length ? `<div class="imgs">${imgs.map((u) => `<img src="${esc(u)}" alt="attached image">`).join("")}</div>` : ""}</div>`;
  thread.appendChild(d);
  scrollDown(true);
  return d;
}
function addBot(thread = ensureThread()) {
  const d = document.createElement("div");
  d.className = "msg bot";
  d.innerHTML = `<div class="avatar" aria-hidden="true">A</div><div class="content"><div class="steps"></div><div class="answer"><div class="status-line"><span class="typing" aria-label="working"><i></i><i></i><i></i></span><span class="st-text">Thinking…</span></div></div><div class="meta"></div></div>`;
  thread.appendChild(d);
  scrollDown(true);
  return d;
}

// ---------------------------------------------------------------- run rendering
const argSummary = (args) => {
  if (!args || typeof args !== "object") return "";
  const v = args.command || args.query || args.url || args.path || args.text || args.name || Object.values(args)[0];
  return typeof v === "string" ? v : JSON.stringify(args);
};
const pretty = (o) => { try { return typeof o === "string" ? o : JSON.stringify(o, null, 2); } catch { return String(o); } };
function stepCard(ev) {
  const d = document.createElement("details");
  d.className = "step run";
  d.dataset.id = ev.id;
  d.innerHTML = `<summary><span class="ico">${icon(TOOL_ICONS[ev.name] || "wrench")}</span><span class="nm">${esc(ev.name)}</span>
    <span class="arg">${esc(argSummary(ev.args))}</span><span class="st"><span class="spin" aria-label="running"></span></span><span class="chev">${icon("chev")}</span></summary>
    <div class="body"><div class="lab">Arguments</div><pre>${esc(pretty(ev.args))}</pre><div class="out"></div></div>`;
  return d;
}
function setStepStatus(card, cls, html) {
  card.classList.remove("run", "ok", "bad", "wait"); card.classList.add(cls);
  $(".st", card).innerHTML = html;
}
// ctx: { el, tid, live, steps:[], provider, model, switched:[] }
function renderEvent(ctx, ev) {
  const steps = $(".steps", ctx.el), st = $(".st-text", ctx.el);
  const card = () => ev.id && $$(".step", steps).find((c) => c.dataset.id === ev.id);
  switch (ev.type) {
    case "thinking": if (st) st.textContent = ev.step > 1 ? `Thinking · step ${ev.step}` : "Thinking…"; break;
    case "model":
      ctx.provider = ev.provider; ctx.model = ev.model; ctx.step = ev.step;
      if (ev.switched?.length) ctx.switched.push(...ev.switched);
      break;
    case "say": {
      const n = document.createElement("div"); n.className = "note"; n.appendChild(renderMarkdown(ev.text)); steps.appendChild(n); break;
    }
    case "tool_call": {
      const c = stepCard(ev); steps.appendChild(c);
      ctx.steps.push({ id: ev.id, name: ev.name, cls: "run" });
      if (st) st.textContent = `Running ${ev.name}…`;
      break;
    }
    case "approval_needed": {
      const c = card(); if (c) setStepStatus(c, "wait", `<span class="pill waiting_approval">needs approval</span>`);
      const s = ctx.steps.find((x) => x.id === ev.id); if (s) s.cls = "wait";
      const a = document.createElement("div");
      a.className = "approve"; a.dataset.id = ev.id;
      a.setAttribute("role", "group"); a.setAttribute("aria-label", `Approve ${ev.name}?`);
      a.innerHTML = `<div class="ah">${icon("shield")} Allow <code>${esc(ev.name)}</code>?</div>
        <div class="why">${esc(ev.reason || "This action is marked risky.")}</div><pre>${esc(pretty(ev.args))}</pre>
        <div class="row">${ctx.live ? `<button class="btn primary" data-ok="1">${icon("check")} Approve</button><button class="btn" data-ok="0">${icon("x")} Deny</button><span class="muted" style="font-size:12px">or press A / D</span>` : '<span class="muted">Waiting…</span>'}</div>`;
      steps.appendChild(a);
      if (ctx.live) {
        $$("button", a).forEach((b) => b.onclick = () => answerApproval(ctx, ev.id, b.dataset.ok === "1", a));
        $("button.primary", a).focus({ preventScroll: true });
      }
      if (st) st.textContent = "Waiting for your approval";
      updateInfo(ctx, "waiting_approval");
      break;
    }
    case "approval": {
      const a = $$(".approve", steps).find((x) => x.dataset.id === ev.id);
      if (a) { a.classList.add("done"); $(".row", a).innerHTML = ev.approved ? `<span class="pill done">approved</span>` : `<span class="pill error">denied</span>`; }
      const c = card(); if (c && ev.approved) setStepStatus(c, "run", '<span class="spin"></span>');
      if (st) st.textContent = ev.approved ? "Approved, running…" : "Denied";
      break;
    }
    case "tool_result": {
      let c = card();
      if (!c) { c = stepCard({ id: ev.id, name: ev.name, args: {} }); steps.appendChild(c); }
      setStepStatus(c, ev.ok ? "ok" : "bad", `${ev.ms != null ? `<span class="muted" style="font-size:11px">${ev.ms < 1000 ? ev.ms + "ms" : (ev.ms / 1000).toFixed(1) + "s"}</span>` : ""}${icon(ev.ok ? "check" : "alert")}`);
      $(".out", c).innerHTML = `<div class="lab">${ev.ok ? "Result" : "Error"}</div><pre>${esc(ev.output || "")}</pre>`;
      const s = ctx.steps.find((x) => x.id === ev.id); if (s) s.cls = ev.ok ? "ok" : "bad";
      else ctx.steps.push({ id: ev.id, name: ev.name, cls: ev.ok ? "ok" : "bad" });
      if (st) st.textContent = "Thinking…";
      break;
    }
    case "max_steps": { const n = document.createElement("div"); n.className = "note warn"; n.innerHTML = `${icon("alert")} Step limit reached, summarising.`; steps.appendChild(n); break; }
    case "cancelled": { const n = document.createElement("div"); n.className = "note warn"; n.innerHTML = `${icon("stop")} Stopped by you.`; steps.appendChild(n); break; }
    case "error": ctx.error = ev.error; break;
  }
  if (ctx.live) updateInfo(ctx);
  scrollDown();
}
function metaHtml(m) {
  const bits = [];
  if (m.provider) bits.push(`<span title="${esc(m.model || "")}">${esc(m.provider)}${m.model ? ` · ${esc(String(m.model).split("/").pop())}` : ""}</span>`);
  if (m.steps) bits.push(`<span>${m.steps} step${m.steps === 1 ? "" : "s"}</span>`);
  const fails = m.switched?.length || (m.tried || []).filter((t) => !t.ok).length;
  if (fails) bits.push(`<span class="failover" title="${esc((m.switched || (m.tried || []).filter((t) => !t.ok).map((t) => `${t.provider}: ${t.error || ""}`)).join("\n"))}">failover ×${fails}</span>`);
  if (m.mode) bits.push(`<span>${m.mode === "chat" ? "chat" : "agent"}</span>`);
  return bits.join('<span class="sep">·</span>');
}
function finishBot(el, text, meta = {}, { error = false } = {}) {
  const ans = $(".answer", el);
  ans.innerHTML = "";
  ans.appendChild(renderMarkdown(text || "(no answer)"));
  if (error) el.classList.add("error");
  const m = $(".meta", el);
  m.innerHTML = metaHtml(meta) + `<span class="msg-actions"><button class="icon-btn sm" aria-label="Copy answer" title="Copy">${icon("copy")}</button></span>`;
  $(".msg-actions button", m).onclick = (e) => copyText(text || "", e.currentTarget);
  scrollDown();
}
function renderSavedBot(msg, thread) {
  const el = addBot(thread);
  const meta = msg.meta || {};
  const ctx = { el, live: false, steps: [], switched: [] };
  for (const ev of meta.events || []) if (ev.type !== "approval_needed" || (meta.events || []).some((x) => x.type === "approval" && x.id === ev.id)) renderEvent(ctx, ev);
  const text = typeof msg.content === "string" ? msg.content : (msg.content || []).map((p) => p.text || "").join("\n");
  finishBot(el, text, { ...meta, switched: ctx.switched.length ? ctx.switched : undefined }, { error: meta.stopped === "error" });
  if (meta.actions?.length) renderActions(el, meta.actions);
  $$(".step", el).forEach((d) => d.open = false);
  return el;
}
function renderActions(el, actions) {
  if (!state.desktop) return;
  for (const a of actions) {
    const box = document.createElement("div");
    box.className = "action-card";
    box.innerHTML = `${icon("monitor")}<b>${esc(a.tool)}</b><code>${esc(JSON.stringify(a.args))}</code><span class="muted">${esc(a.why || "")}</span><span class="spacer" style="flex:1"></span><button class="btn sm primary">${icon("play")} Run</button><button class="btn sm">Skip</button>`;
    const [run, skip] = $$("button", box);
    run.onclick = async () => {
      if (a.risk !== "safe" && !(await confirmDialog(`Run ${a.tool} on your computer?`, { ok: "Run", danger: false }))) return;
      try { const r = await api("/api/actions/execute", { action: a, confirmed: true }); box.innerHTML = `${icon(r.ok ? "check" : "alert")} ${esc(a.tool)}: ${esc(r.output || r.error || (r.ok ? "done" : "failed"))}`; }
      catch (e) { toast(e.message, "bad"); }
    };
    skip.onclick = () => box.remove();
    $(".content", el).appendChild(box);
  }
}

// ---------------------------------------------------------------- live task streaming
let activeCtx = null;
async function streamTask(tid, el, convId) {
  const ctx = { el, tid, live: true, steps: [], switched: [], convId };
  activeCtx = ctx;
  setBusy(true);
  let since = 0, misses = 0, t;
  while (true) {
    try { t = await api(`/api/tasks/${tid}?since=${since}`); misses = 0; }
    catch (e) {
      if (e.status === 404 || ++misses > 8) { finishBot(el, "✗ Lost track of this run (the server may have restarted).", {}, { error: true }); break; }
      await sleep(1200); continue;
    }
    for (const ev of t.events) renderEvent(ctx, ev);
    since = t.next;
    updateInfo(ctx, t.status);
    if (!["running", "queued", "waiting_approval"].includes(t.status)) break;
    if (!el.isConnected && activeCtx !== ctx) return; // user navigated away; openConv will resume
    await sleep(t.status === "waiting_approval" ? 700 : 450);
  }
  const r = t?.result || {};
  if (t) finishBot(el, r.text || (t.status === "cancelled" ? "Stopped." : "(no answer)"),
    { provider: r.provider, model: r.model, steps: r.steps, switched: ctx.switched, mode: "agent" }, { error: t.status === "error" });
  $$(".approve:not(.done) .row", el).forEach((row) => row.innerHTML = '<span class="pill">expired</span>');
  if (convId) state.running.delete(convId);
  if (activeCtx === ctx) { activeCtx = null; setBusy(false); }
  if (t?.status === "done" && document.hidden) document.title = "✓ AutoMoto AI";
  loadConvs(); refreshBadge();
}
async function answerApproval(ctx, callId, ok, card) {
  $$("button", card).forEach((b) => b.disabled = true);
  try { await api(`/api/tasks/${ctx.tid}/approve`, { call_id: callId, approve: ok }); }
  catch (e) { toast(e.message, "bad"); $$("button", card).forEach((b) => b.disabled = false); }
}
function updateInfo(ctx, status) {
  if (status) ctx.status = status;
  if (activeCtx && ctx !== activeCtx) return;
  const s = ctx.status || "running";
  $("#infoBody").innerHTML = `<dl class="kv"><dt>Status</dt><dd><span class="pill ${esc(s)}">${esc(s.replace("_", " "))}</span></dd>
    <dt>Provider</dt><dd>${esc(ctx.provider || "…")}</dd><dt>Model</dt><dd>${esc(ctx.model || "…")}</dd>
    <dt>Step</dt><dd>${ctx.step || 0}</dd>${ctx.tid ? `<dt>Task</dt><dd><code>${esc(ctx.tid)}</code></dd>` : ""}
    ${ctx.switched.length ? `<dt>Failover</dt><dd class="failover">${ctx.switched.map(esc).join("<br>")}</dd>` : ""}</dl>
    <b>Steps</b><ul class="mini-steps">${ctx.steps.map((x) => `<li class="${x.cls}"><span class="dot"></span><code>${esc(x.name)}</code></li>`).join("") || '<li class="muted">No tools used yet</li>'}</ul>`;
}
function updateInfoFromConv(conv) {
  const last = [...conv.messages].reverse().find((m) => m.role === "assistant");
  if (!last) return;
  const m = last.meta || {};
  const ctx = { live: false, steps: [], switched: [], provider: m.provider, model: m.model, step: m.steps, tid: m.task_id, status: m.stopped === "error" ? "error" : "done" };
  for (const ev of m.events || []) {
    if (ev.type === "tool_result") ctx.steps.push({ name: ev.name, cls: ev.ok ? "ok" : "bad" });
    if (ev.type === "model" && ev.switched?.length) ctx.switched.push(...ev.switched);
  }
  const prev = activeCtx; activeCtx = null; updateInfo(ctx); activeCtx = prev;
}

// ---------------------------------------------------------------- composer
function autosize() { const ta = $("#composerInput"); if (!ta) return; ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 220) + "px"; }
function setBusy(b) {
  state.busy = b;
  const btn = $("#sendBtn"); if (!btn) return;
  btn.classList.toggle("stop", b);
  btn.innerHTML = icon(b ? "stop" : "send");
  btn.setAttribute("aria-label", b ? "Stop" : "Send message");
  btn.title = b ? "Stop (Esc)" : "Send";
  btn.disabled = false;
}
function wireComposer() {
  const ta = $("#composerInput"), form = $("#composer");
  ta.addEventListener("input", autosize);
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!state.busy) send(); }
  });
  form.addEventListener("submit", (e) => { e.preventDefault(); state.busy ? stopRun() : send(); });
  $("#attachBtn").onclick = () => $("#fileInput").click();
  $("#fileInput").onchange = (e) => { addFiles(e.target.files); e.target.value = ""; };
  ta.addEventListener("paste", (e) => {
    const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith("image/"));
    if (files.length) { e.preventDefault(); addFiles(files); }
  });
  const chat = $(".chat");
  chat.addEventListener("dragover", (e) => { if ([...e.dataTransfer.types].includes("Files")) { e.preventDefault(); form.classList.add("drop"); } });
  chat.addEventListener("dragleave", (e) => { if (!chat.contains(e.relatedTarget)) form.classList.remove("drop"); });
  chat.addEventListener("drop", (e) => { e.preventDefault(); form.classList.remove("drop"); addFiles(e.dataTransfer.files); });
  setBusy(!!activeCtx && activeCtx.el.isConnected);
}
function readAsDataURL(file) {
  return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file); });
}
async function shrink(dataUrl) {
  if (dataUrl.length < 900 * 1024) return dataUrl;
  const img = new Image(); img.src = dataUrl; await img.decode();
  const scale = Math.min(1, 1600 / Math.max(img.width, img.height));
  const c = document.createElement("canvas"); c.width = Math.round(img.width * scale); c.height = Math.round(img.height * scale);
  c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.85);
}
const MAX_UPLOAD_MB = 50;
async function uploadFile(f, dir = "uploads") {
  if (f.size > MAX_UPLOAD_MB * 1048576) throw new Error(`${f.name} is larger than ${MAX_UPLOAD_MB} MB`);
  const data = await readAsDataURL(f);
  return api("/api/files/upload", { name: f.name, data: data.split(",", 2)[1] || "", dir });
}
async function addFiles(files) {
  for (const f of [...files]) {
    if (!f.type.startsWith("image/")) {
      try {
        const r = await uploadFile(f);
        state.files.push(r.path);
        toast(`Uploaded ${r.path}${r.notes?.length ? " - " + r.notes.join("; ") : ""}`);
      } catch (e) { toast(`${f.name}: ${e.message}`, "bad"); }
      continue;
    }
    if (state.attachments.length >= MAX_IMAGES) { toast(`Up to ${MAX_IMAGES} images per message`, "bad"); break; }
    try { state.attachments.push(await shrink(await readAsDataURL(f))); } catch { toast(`Couldn't read ${f.name}`, "bad"); }
  }
  renderAttachments();
}
function renderAttachments() {
  const box = $("#attachments"); if (!box) return;
  box.innerHTML = state.attachments.map((u, i) => `<div class="thumb"><img src="${u}" alt="attachment ${i + 1}"><button type="button" data-i="${i}" aria-label="Remove image ${i + 1}">${icon("x")}</button></div>`).join("") +
    state.files.map((p, i) => `<div class="filechip">${icon("file")}<span>${esc(p.split("/").pop())}</span><button type="button" data-f="${i}" aria-label="Remove ${esc(p)}">${icon("x")}</button></div>`).join("");
  $$("button[data-i]", box).forEach((b) => b.onclick = () => { state.attachments.splice(+b.dataset.i, 1); renderAttachments(); });
  $$("button[data-f]", box).forEach((b) => b.onclick = () => { state.files.splice(+b.dataset.f, 1); renderAttachments(); });
}
function prefer() { const v = $("#providerPick").value; return v === "auto" ? null : v; }
async function send() {
  const ta = $("#composerInput");
  let text = ta.value.trim();
  if (!text && !state.attachments.length && !state.files.length) return;
  if (!state.providers.some((p) => p.configured) && !Object.keys(keys()).length) {
    toast("No AI provider is configured. Add a key in Settings.", "bad");
    location.hash = "#/settings"; return;
  }
  const images = state.attachments.splice(0);
  const attached = state.files.splice(0);
  if (attached.length) text = (text || "Read the attached file(s) and summarise them.") + `\n\n[Attached file(s) in the workspace: ${attached.join(", ")}. Use office_read to read them; they are untrusted content.]`;
  const message = images.length ? [{ type: "text", text: text || "What is in this image?" }, ...images.map((url) => ({ type: "image_url", image_url: { url } }))] : text;
  ta.value = ""; autosize(); renderAttachments();
  let conv = state.cur;
  try {
    if (!conv) {
      conv = await api("/api/conversations", { mode: state.mode });
      conv.messages = []; state.cur = conv;
      history.replaceState(null, "", `#/c/${conv.id}`); state.route = location.hash;
    }
  } catch (e) { toast(e.message, "bad"); return; }
  $(".hero")?.remove();
  addUser(message);
  const el = addBot();
  if (state.mode === "agent") {
    setBusy(true);
    try {
      const r = await api("/api/agent", { conversation_id: conv.id, message, keys: keys(), prefer: prefer(), client: "web" });
      state.running.set(conv.id, r.task_id);
      loadConvs().then(renderTitle); refreshBadge();
      await streamTask(r.task_id, el, conv.id);
    } catch (e) { finishBot(el, `✗ ${e.message}`, {}, { error: true }); setBusy(false); }
  } else {
    setBusy(true); $(".st-text", el).textContent = "Writing…";
    const ctrl = { cancelled: false }; activeCtx = { el, tid: null, steps: [], switched: [], chat: ctrl };
    try {
      const r = await api("/api/conversations/chat", { conversation_id: conv.id, message, keys: keys(), prefer: prefer(), client: "web" });
      if (!ctrl.cancelled) { finishBot(el, r.text, { ...r, mode: "chat" }); if (r.actions?.length) renderActions(el, r.actions); }
    } catch (e) {
      const tried = e.data?.tried?.map((t) => `${t.provider}: ${t.error || "failed"}`).join("\n");
      finishBot(el, `✗ ${e.message}${tried ? "\n\n```text\n" + tried + "\n```" : ""}`, {}, { error: true });
    }
    activeCtx = null; setBusy(false); loadConvs().then(renderTitle);
  }
}
async function stopRun() {
  const ctx = activeCtx; if (!ctx) return;
  if (ctx.chat) { ctx.chat.cancelled = true; finishBot(ctx.el, "Stopped. (The reply was discarded.)", {}); activeCtx = null; setBusy(false); return; }
  $("#sendBtn").disabled = true;
  try { await api(`/api/tasks/${ctx.tid}/cancel`, {}); toast("Stopping after the current step…"); }
  catch (e) { toast(e.message, "bad"); }
}

// ---------------------------------------------------------------- pages
function page(title, lead, inner) {
  $("#pageTitle").textContent = title;
  $("#view").innerHTML = `<div class="page"><div class="page-inner"><h2>${esc(title)}</h2><p class="lead">${lead}</p>${inner}</div></div>`;
  hydrateIcons($("#view"));
  $("#view").focus({ preventScroll: true });
  return $("#view .page-inner");
}
const statusPill = (s) => `<span class="pill ${esc(s)}">${esc(String(s).replace("_", " "))}</span>`;
const PAGES = {};

PAGES.tasks = async () => {
  const root = page("Tasks", "Every agent run in this session, live. Runs keep going if you switch chats.", '<div id="taskList"></div>');
  const draw = async () => {
    if (!$("#taskList")) return clearInterval(state.pageTimer);
    let tasks; try { tasks = (await api("/api/tasks")).tasks; } catch { return; }
    const list = $("#taskList"); if (!list) return;
    if (!tasks.length) { list.innerHTML = '<div class="card muted">No tasks yet. Start an agent run from a chat.</div>'; return; }
    list.innerHTML = tasks.slice().reverse().map((t) => `<div class="card"><h3>${statusPill(t.status)}<span>${esc(t.title || "task")}</span></h3>
      <div class="row muted" style="font-size:12.5px"><span>${esc(t.source)}</span>·<span>${t.steps} step${t.steps === 1 ? "" : "s"}</span>·<span>${timeAgo(t.created)}</span>
      ${t.result?.provider ? `·<span>${esc(t.result.provider)}</span>` : ""}${t.pending ? `·<span class="pill waiting_approval">waiting on ${esc(t.pending.name)}</span>` : ""}
      <span style="flex:1"></span>${t.conversation_id ? `<a class="btn sm" href="#/c/${esc(t.conversation_id)}">Open chat</a>` : ""}
      ${["running", "waiting_approval", "queued"].includes(t.status) ? `<button class="btn sm danger" data-stop="${esc(t.id)}">${icon("stop")} Stop</button>` : ""}</div>
      ${t.result?.text && t.status !== "running" ? `<details style="margin-top:8px"><summary class="muted" style="cursor:pointer">Result</summary><div style="margin-top:6px" class="res"></div></details>` : ""}</div>`).join("");
    tasks.slice().reverse().forEach((t, i) => { const r = $$(".card", list)[i]?.querySelector(".res"); if (r) r.appendChild(renderMarkdown(t.result.text)); });
    $$("[data-stop]", list).forEach((b) => b.onclick = async () => { await api(`/api/tasks/${b.dataset.stop}/cancel`, {}).catch((e) => toast(e.message, "bad")); toast("Stop requested"); draw(); });
  };
  await draw();
  state.pageTimer = setInterval(() => { if (!$("details[open]", $("#taskList") || document)) draw(); }, 2000);
};

PAGES.memory = async () => {
  const root = page("Memory", "Facts AutoMoto keeps between chats, plus a journal of what it did. Stored locally in SQLite.",
    `<form class="card" id="factForm"><div class="row"><input class="input" name="text" placeholder="e.g. I live in Birmingham and prefer metric units" aria-label="New fact" required maxlength="500" style="flex:1;min-width:200px">
      <input class="input" name="tags" placeholder="tags (optional)" aria-label="Tags" style="width:160px"><button class="btn primary">${icon("plus")} Remember</button></div></form>
     <div class="toolbar"><b>Facts</b><span class="spacer"></span><input class="input" id="factFilter" type="search" placeholder="Filter facts" aria-label="Filter facts" style="width:200px"></div>
     <div id="facts"></div><div class="toolbar" style="margin-top:22px"><b>Journal</b></div><div class="timeline" id="journal"></div>`);
  let facts = [];
  const drawFacts = () => {
    const q = $("#factFilter").value.toLowerCase();
    const f = facts.filter((x) => !q || (x.text + " " + x.tags).toLowerCase().includes(q));
    $("#facts").innerHTML = f.length ? f.map((x) => `<div class="card"><div class="row"><span style="flex:1">${esc(x.text)}</span>${x.tags ? x.tags.split(",").filter(Boolean).map((t) => `<span class="pill">${esc(t.trim())}</span>`).join("") : ""}
      <span class="muted" style="font-size:12px">${timeAgo(x.created)}</span><button class="icon-btn sm" data-forget="${x.id}" aria-label="Forget this fact" title="Forget">${icon("trash")}</button></div></div>`).join("")
      : `<div class="card muted">${facts.length ? "No facts match." : "Nothing remembered yet. Add a fact above or tell the agent \"remember that…\"."}</div>`;
    $$("[data-forget]").forEach((b) => b.onclick = async () => {
      if (!(await confirmDialog("Forget this fact?", { ok: "Forget" }))) return;
      await api(`/api/memory/${b.dataset.forget}`, undefined, "DELETE"); toast("Forgotten"); load();
    });
  };
  const load = async () => {
    const d = await api("/api/memory"); facts = d.facts; drawFacts();
    $("#journal").innerHTML = d.journal.length ? d.journal.map((j) => `<div class="ev"><div class="when">${fmtTime(j.ts)} · ${esc(j.kind)}</div><div>${esc(j.text)}</div></div>`).join("") : '<p class="muted">No journal entries yet.</p>';
  };
  $("#factFilter").oninput = drawFacts;
  $("#factForm").onsubmit = async (e) => {
    e.preventDefault(); const f = new FormData(e.target);
    try { await api("/api/memory", { text: f.get("text"), tags: f.get("tags") || "" }); e.target.reset(); toast("Remembered"); load(); }
    catch (err) { toast(err.message, "bad"); }
  };
  await load();
};

PAGES.routines = async () => {
  page("Routines", "Prompts the agent runs on a schedule while the server is up. Risky steps are auto-denied in routines, so they stay read-only.",
    `<form class="card" id="rtForm"><h3>${icon("plus")} New routine</h3>
      <div class="row"><label class="field" style="flex:1;min-width:140px"><span>Name</span><input class="input" name="name" required pattern="[A-Za-z0-9_\\-]{1,40}" placeholder="morning-news"></label>
      <label class="field" style="width:200px"><span>Schedule</span><input class="input" name="schedule" required placeholder="every 1h  or  0 8 * * *"></label></div>
      <label class="field"><span>Prompt</span><textarea class="input" name="prompt" rows="2" required placeholder="Search the web for today's top 3 AI stories and summarise them"></textarea></label>
      <div class="row"><button class="btn primary">Create routine</button><span class="muted" style="font-size:12px">Schedules: <code>every 30m</code>, <code>every 2h</code>, <code>every 1d</code> or a 5-field cron like <code>0 8 * * *</code>.</span></div></form>
     <div id="rtStatus" class="muted" style="margin-bottom:8px"></div><div id="rtList"></div>`);
  const load = async () => {
    const d = await api("/api/routines");
    $("#rtStatus").innerHTML = d.scheduler ? `${statusPill("on")} Scheduler running` : `${statusPill("off")} Scheduler not running (it starts with <code>automoto serve</code>)`;
    $("#rtList").innerHTML = d.routines.length ? d.routines.map((r) => `<div class="card" data-name="${esc(r.name)}"><h3>${esc(r.name)} ${statusPill(r.enabled ? "on" : "off")}<code class="muted">${esc(r.schedule)}</code></h3>
      <div style="margin-bottom:8px">${esc(r.prompt)}</div>
      ${r.last_run ? `<details><summary class="muted" style="cursor:pointer;font-size:12.5px">Last run ${timeAgo(r.last_run)} ${statusPill(r.last_status || "done")}</summary><div class="res" style="margin-top:6px"></div></details>` : '<div class="muted" style="font-size:12.5px">Never run yet</div>'}
      <div class="row" style="margin-top:10px"><button class="btn sm primary" data-a="run">${icon("play")} Run now</button><button class="btn sm" data-a="toggle">${icon(r.enabled ? "pause" : "play")} ${r.enabled ? "Pause" : "Resume"}</button>
      <button class="btn sm" data-a="edit">${icon("edit")} Edit</button><button class="btn sm danger" data-a="del">${icon("trash")} Delete</button></div></div>`).join("")
      : '<div class="card muted">No routines yet.</div>';
    d.routines.forEach((r) => { const c = $(`.card[data-name="${CSS.escape(r.name)}"] .res`); if (c && r.last_result) c.appendChild(renderMarkdown(r.last_result)); });
    $$("#rtList [data-a]").forEach((b) => b.onclick = () => act(d.routines.find((r) => r.name === b.closest(".card").dataset.name), b.dataset.a));
  };
  const act = async (r, a) => {
    const n = encodeURIComponent(r.name);
    try {
      if (a === "run") { const t = await api(`/api/routines/${n}/run`, {}); toast(`Started ${r.name}`); watchRoutine(t.task_id, load); }
      if (a === "toggle") { await api(`/api/routines/${n}`, { enabled: !r.enabled }, "PATCH"); toast(r.enabled ? "Paused" : "Resumed"); load(); }
      if (a === "del" && (await confirmDialog(`Delete routine "${r.name}"?`))) { await api(`/api/routines/${n}`, undefined, "DELETE"); toast("Deleted"); load(); }
      if (a === "edit") openModal(`<h3>Edit ${esc(r.name)}</h3><form><label class="field"><span>Schedule</span><input class="input" name="schedule" value="${esc(r.schedule)}" required></label>
        <label class="field"><span>Prompt</span><textarea class="input" name="prompt" rows="4" required>${esc(r.prompt)}</textarea></label>
        <div class="row"><button type="button" class="btn" data-x>Cancel</button><button class="btn primary">Save</button></div></form>`, {
        label: "Edit routine",
        onMount: (m, close) => {
          $("[data-x]", m).onclick = close;
          $("form", m).onsubmit = async (e) => {
            e.preventDefault(); const f = new FormData(e.target);
            try { await api(`/api/routines/${n}`, { schedule: f.get("schedule"), prompt: f.get("prompt") }, "PATCH"); close(); toast("Saved"); load(); }
            catch (err) { toast(err.message, "bad"); }
          };
        },
      });
    } catch (e) { toast(e.message, "bad"); }
  };
  $("#rtForm").onsubmit = async (e) => {
    e.preventDefault(); const f = new FormData(e.target);
    try { await api("/api/routines", { name: f.get("name"), schedule: f.get("schedule"), prompt: f.get("prompt") }); e.target.reset(); toast("Routine created"); load(); }
    catch (err) { toast(err.message, "bad"); }
  };
  await load();
};
async function watchRoutine(tid, reload) {
  for (let i = 0; i < 400; i++) {
    await sleep(1500);
    let t; try { t = await api(`/api/tasks/${tid}?since=100000`); } catch { return; }
    if (!["running", "queued", "waiting_approval"].includes(t.status)) {
      toast(`Routine finished: ${t.status}`, t.status === "done" ? "" : "bad");
      if (location.hash === "#/routines") reload();
      return;
    }
  }
}

const STATUS_LABEL = { live: "live-tested", unit: "unit-tested", untested: "untested" };
const STATUS_TITLE = { live: "Run end-to-end against the real app or service", unit: "Covered by automated tests; not run against the real app", untested: "Written from official docs; not run (app not available to test)" };
function reqChips(s) {
  if (!s.checks?.length) return "";
  const chip = (c) => `<span class="req ${c.ok ? "ok" : c.optional ? "opt" : "miss"}" title="${esc(c.kind)}${c.optional ? " (optional)" : ""}: ${c.ok ? "available" : "not set up"}">${c.ok ? "✓" : c.optional ? "○" : "✗"} ${esc(c.name)}</span>`;
  return `<div class="reqs">${s.ready ? statusPill("ready") : '<span class="pill off">needs setup</span>'} ${s.checks.map(chip).join("")}</div>`;
}

PAGES.skills = async () => {
  page("Skills", "SKILL.md playbooks the agent reads when a task matches. Bundled skills are read-only; customise one to make your own copy.",
    `<div class="toolbar"><input class="input" id="skFilter" type="search" placeholder="Filter skills" aria-label="Filter skills" style="width:220px"><span class="spacer"></span><button class="btn primary" id="skNew">${icon("plus")} New skill</button></div><div class="grid" id="skList"></div>`);
  let skills = [];
  const draw = () => {
    const q = $("#skFilter").value.toLowerCase();
    const f = skills.filter((s) => !q || (s.name + s.description + (s.category || "")).toLowerCase().includes(q));
    $("#skList").innerHTML = f.map((s) => `<div class="card" data-name="${esc(s.name)}"><h3>${icon("book")}${esc(s.name)} ${statusPill(s.bundled ? "bundled" : "yours")} ${s.status ? `<span class="pill st-${esc(s.status)}" title="${esc(STATUS_TITLE[s.status] || "")}">${esc(STATUS_LABEL[s.status] || s.status)}</span>` : ""}</h3>
      <div class="muted" style="font-size:13px;margin-bottom:8px">${esc(s.description)}</div>
      ${reqChips(s)}
      <div class="row"><button class="btn sm" data-a="view">View</button><button class="btn sm" data-a="edit">${icon("edit")} ${s.bundled ? "Customise" : "Edit"}</button>${s.bundled ? "" : `<button class="btn sm danger" data-a="del">${icon("trash")}</button>`}</div></div>`).join("") || '<div class="card muted">No skills match.</div>';
    $$("#skList [data-a]").forEach((b) => b.onclick = async () => {
      const name = b.closest(".card").dataset.name;
      if (b.dataset.a === "del") {
        if (!(await confirmDialog(`Delete skill "${name}"?`))) return;
        try { await api(`/api/skills/${encodeURIComponent(name)}`, undefined, "DELETE"); toast("Deleted"); load(); } catch (e) { toast(e.message, "bad"); }
        return;
      }
      const s = await api(`/api/skills/${encodeURIComponent(name)}`);
      if (b.dataset.a === "view") {
        openModal(`<h3>${icon("book")} ${esc(s.name)}</h3><div class="md-wrap" style="max-height:60vh;overflow:auto"></div><div class="row"><button class="btn primary" data-x>Close</button></div>`,
          { label: s.name, onMount: (m, close) => { $(".md-wrap", m).appendChild(renderMarkdown(s.body)); $("[data-x]", m).onclick = close; } });
      } else editSkill(s);
    });
  };
  const load = async () => { skills = (await api("/api/skills")).skills; draw(); };
  $("#skFilter").oninput = draw;
  $("#skNew").onclick = () => editSkill(null);
  function editSkill(s) {
    const body = s ? s.body : "# My skill\n\nWhen the user asks for …, do this:\n\n1. …\n2. …\n";
    openModal(`<h3>${s ? (s.bundled ? "Customise " : "Edit ") + esc(s.name) : "New skill"}</h3><form>
      <label class="field"><span>Name (lowercase, dashes)</span><input class="input" name="name" value="${esc(s?.name || "")}" ${s ? "readonly" : ""} required pattern="[a-z0-9][a-z0-9\\-]{0,59}"></label>
      <label class="field"><span>Description: when should the agent use it?</span><input class="input" name="description" value="${esc(s?.description || "")}" required maxlength="300"></label>
      <label class="field"><span>SKILL.md body (markdown)</span><textarea class="input mono" name="body" rows="14" required>${esc(body)}</textarea></label>
      <div class="row"><button type="button" class="btn" data-x>Cancel</button><button class="btn primary">Save skill</button></div></form>`, {
      label: "Edit skill",
      onMount: (m, close) => {
        $("[data-x]", m).onclick = close;
        $("form", m).onsubmit = async (e) => {
          e.preventDefault(); const f = new FormData(e.target);
          try { await api(`/api/skills/${encodeURIComponent(f.get("name"))}`, { body: f.get("body"), description: f.get("description") }, "PUT"); close(); toast("Skill saved"); load(); }
          catch (err) { toast(err.message, "bad"); }
        };
      },
    });
  }
  await load();
};

PAGES.tools = async () => {
  page("Tools", "Everything the agent can use. <b>safe</b> runs on its own, <b>risky</b> asks you first (unless approvals are set to auto), <b>blocked</b> never runs.", '<div id="tlList"></div>');
  const d = await api("/api/agent/info");
  const groups = {};
  d.tools.forEach((t) => (groups[t.group || "other"] ||= []).push(t));
  $("#tlList").innerHTML = `<div class="card"><dl class="kv" style="margin:0"><dt>Approvals</dt><dd>${statusPill(d.approval_mode)}</dd><dt>Sandbox</dt><dd>${esc(d.sandbox)}</dd><dt>Workspace</dt><dd><code>${esc(d.workspace)}</code></dd></dl></div>` +
    Object.entries(groups).map(([g, ts]) => `<div class="toolbar" style="margin-top:16px"><b style="text-transform:capitalize">${esc(g)}</b><span class="muted">${ts.length}</span></div>
    <div class="grid">${ts.map((t) => `<div class="card"><h3>${icon(TOOL_ICONS[t.name] || "wrench")}<code>${esc(t.name)}</code>${statusPill(t.level)}</h3><div class="muted" style="font-size:13px">${esc(t.description)}</div></div>`).join("")}</div>`).join("") +
    (d.mcp_errors?.length ? `<div class="card" style="margin-top:12px"><h3>${icon("alert")} MCP errors</h3><pre>${esc(d.mcp_errors.join("\n"))}</pre></div>` : "") +
    '<div id="svcList"></div><div id="appList"></div>';
  try {
    const sv = (await api("/api/services")).services;
    $("#svcList").innerHTML = `<div class="toolbar" style="margin-top:16px"><b>Services (service_api)</b><span class="muted">GET is safe, everything else asks first. Tokens come from .env or this tab's keys.</span></div>
      <div class="grid">${sv.map((x) => `<div class="card"><h3>${icon("globe")}${esc(x.name)} ${x.configured ? statusPill("on") : x.public_reads ? '<span class="pill">public reads</span>' : '<span class="pill off">no token</span>'} <span class="pill st-${esc(x.status)}">${esc(STATUS_LABEL[x.status] || x.status)}</span></h3><div class="muted" style="font-size:13px">Token: <code>${esc(x.env.join(" or "))}</code> · <a href="${esc(x.docs)}" target="_blank" rel="noopener">API docs</a></div></div>`).join("")}</div>`;
  } catch { /* optional */ }
  try {
    const ap = (await api("/api/apps")).apps;
    const inst = ap.filter((a) => a.installed).length;
    $("#appList").innerHTML = `<div class="toolbar" style="margin-top:16px"><b>Local apps</b><span class="muted">${inst} of ${ap.length} found on this computer. Every app call asks first.</span></div>
      <div class="grid">${ap.map((a) => `<div class="card"><h3>${icon("cpu")}${esc(a.name)} ${a.installed ? statusPill("on") : '<span class="pill">not found</span>'} <span class="pill st-${esc(a.status)}">${esc(STATUS_LABEL[a.status] || a.status)}</span></h3><div class="muted" style="font-size:13px"><code>${esc(a.id)}</code> · ${esc(a.category)}${a.script ? " · scripts: " + esc(a.script) : ""}${a.note ? "<br>" + esc(a.note) : ""}</div></div>`).join("")}</div>`;
  } catch { /* only on this computer */ }
};

PAGES.files = async () => {
  page("Files", "Your AutoMoto workspace. Upload Office files, PDFs, CSV/JSON/YAML data, logs and ZIP/tar archives (for example WordPress plugins and themes) for the agent; preview, extract, re-pack and download what it made. Uploads are checked (size, zip-slip, symlinks, zip bombs, XXE) and macros are never run.",
    `<div class="toolbar"><span id="fBreadcrumb" class="muted"></span><span style="flex:1"></span>
      <input type="file" id="fUpload" multiple hidden accept=".docx,.doc,.odt,.rtf,.xlsx,.xls,.ods,.csv,.tsv,.pptx,.ppt,.odp,.pdf,.md,.txt,.log,.json,.jsonl,.yaml,.yml,.toml,.xml,.parquet,.sqlite,.db,.zip,.tar,.gz,.tgz,.bz2,.xz,.7z,.rar,image/*">
      <button class="btn" id="fRefresh">${icon("refresh")} Refresh</button>
      <button class="btn primary" id="fUploadBtn">${icon("upload")} Upload</button></div>
     <div id="fNote" class="muted" style="font-size:13px;margin:6px 0 12px"></div><div class="grid files-grid" id="fList"></div>`);
  let dir = sessionStorage.getItem("automoto_files_dir") || ".";
  const fmt = (n) => n == null ? "" : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`;
  const prevUrl = (p) => `/api/files/preview?path=${encodeURIComponent(p)}&page=1`;
  const dlUrl = (p) => `/api/files/download?path=${encodeURIComponent(p)}`;
  async function draw() {
    let d;
    try { d = await api(`/api/files?dir=${encodeURIComponent(dir)}`); }
    catch (e) { if (dir !== ".") { dir = "."; return draw(); } $("#fList").innerHTML = `<div class="card">${esc(e.message)}</div>`; return; }
    dir = d.dir; sessionStorage.setItem("automoto_files_dir", dir);
    const crumbs = dir === "." ? [] : dir.split("/");
    $("#fBreadcrumb").innerHTML = [`<a href="#" data-dir=".">workspace</a>`, ...crumbs.map((c, i) => `<a href="#" data-dir="${esc(crumbs.slice(0, i + 1).join("/"))}">${esc(c)}</a>`)].join(" / ");
    $("#fNote").textContent = d.libreoffice ? "Previews are rendered with LibreOffice (macros disabled)." : "Install LibreOffice (free) for Word/Excel/PowerPoint previews and PDF export.";
    $("#fList").innerHTML = d.items.length ? d.items.map((it) => it.dir
      ? `<div class="card file-card dir"><button class="linkish" data-dir="${esc(it.path)}">${icon("folder")}<b>${esc(it.name)}</b></button>
          <button class="btn sm" data-pack="${esc(it.path)}" title="Make ${esc(it.name)}.zip (deterministic, .git/node_modules/.env left out)">${icon("archive")} Zip</button></div>`
      : `<div class="card file-card">${it.preview ? `<div class="fprev"><img loading="lazy" src="${prevUrl(it.path)}" alt="First page of ${esc(it.name)}"></div>` : `<div class="fprev none">${icon("file")}</div>`}
          <div class="fmeta"><b title="${esc(it.path)}">${esc(it.name)}</b><span class="muted">${fmt(it.size)}</span></div>
          <div class="factions"><a class="btn" href="${dlUrl(it.path)}" download>${icon("download")} Download</a>
          <button class="btn" data-ask="${esc(it.path)}">${icon("chat")} Ask agent</button>
          ${it.view ? `<button class="btn" data-view="${esc(it.path)}">${icon("eye")} View</button>` : ""}
          ${it.view === "archive" ? `<button class="btn" data-extract="${esc(it.path)}">${icon("folder")} Extract</button><button class="btn" data-repack="${esc(it.path)}" title="Re-pack as a clean zip (drops __MACOSX, .DS_Store, .git, .env…)">${icon("archive")} Clean zip</button>` : ""}</div></div>`).join("")
      : '<div class="card muted">Empty folder. Upload a file or ask the agent to create a document.</div>';
    $$(".fprev img").forEach((im) => im.addEventListener("error", () => { im.parentNode.classList.add("none"); im.parentNode.innerHTML = icon("file"); }));
    $$("[data-dir]").forEach((a) => a.onclick = (e) => { e.preventDefault(); dir = a.dataset.dir; draw(); });
    $$("[data-ask]").forEach((b) => b.onclick = () => { state.files = [b.dataset.ask]; location.hash = "#/new"; setTimeout(renderAttachments, 50); });
    $$("[data-view]").forEach((b) => b.onclick = () => viewFile(b.dataset.view));
    const act = async (action, path, verb) => {
      try { const r = await api("/api/files/archive", { action, path }); toast(`${verb} ${r.path}${r.files != null ? ` (${r.files} files)` : ""}`); draw(); }
      catch (e) { toast(e.message, "bad"); }
    };
    $$("[data-extract]").forEach((b) => b.onclick = () => act("extract", b.dataset.extract, "Extracted to"));
    $$("[data-repack]").forEach((b) => b.onclick = () => act("repack", b.dataset.repack, "Wrote"));
    $$("[data-pack]").forEach((b) => b.onclick = () => act("pack", b.dataset.pack, "Wrote"));
  }
  async function viewFile(path) {
    let d;
    try { d = await api(`/api/files/inspect?path=${encodeURIComponent(path)}`); } catch (e) { toast(e.message, "bad"); return; }
    let body = "";
    if (d.kind === "archive") {
      const r = d.report;
      const verdict = r.safe ? '<span class="pill st-live">safe to extract</span>' : '<span class="pill bad">unsafe</span>';
      const tree = d.entries.map((e) => {
        const depth = e.name.replace(/\/$/, "").split("/").length - 1;
        const label = e.name.split("/").filter(Boolean).pop() + (e.kind === "dir" ? "/" : "");
        return `<div class="tree-row${e.problem ? " bad" : ""}" style="padding-left:${Math.max(0, depth) * 16}px">${icon(e.kind === "dir" ? "folder" : "file")}<span>${esc(label)}</span><span class="muted">${e.kind === "dir" ? "" : fmt(e.size)}${e.encrypted ? " · encrypted" : ""}${e.problem ? " · " + esc(e.problem) : ""}</span></div>`;
      }).join("");
      body = `<p>${verdict} ${esc(r.format)} · ${r.files} files · ${fmt(r.unpacked_bytes)} unpacked${r.encrypted ? ` · ${r.encrypted} encrypted` : ""}</p>
        ${[...r.problems, ...r.warnings].map((x) => `<div class="muted">• ${esc(x)}</div>`).join("")}
        <div class="tree">${tree}${d.truncated ? '<div class="muted">… more entries</div>' : ""}</div>`;
    } else if (d.kind === "table") {
      const info = d.info || {};
      body = `<p class="muted">${d.total_rows.toLocaleString()} rows · ${d.columns.length} columns${info.delimiter ? ` · delimiter <code>${esc(info.delimiter === "\t" ? "tab" : info.delimiter)}</code>` : ""}${info.encoding ? ` · ${esc(info.encoding)}` : ""} · first ${d.rows.length} shown</p>
        <div class="table-wrap"><table class="data"><thead><tr>${d.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
        <tbody>${d.rows.map((r) => `<tr>${r.map((v) => `<td>${v == null ? '<span class="muted">-</span>' : esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    } else if (d.kind === "data") {
      body = `<pre class="code">${esc(d.outline.join("\n"))}</pre>`;
    } else {
      body = `<p class="muted">Last 200 lines</p><pre class="code">${esc(d.text)}</pre>`;
    }
    openModal(`<h3>${icon("eye")} ${esc(path.split("/").pop())}</h3><div class="viewer">${body}</div>
      <div class="toolbar" style="margin-top:12px"><span style="flex:1"></span><a class="btn" href="${dlUrl(path)}" download>${icon("download")} Download</a><button class="btn primary" data-close>Close</button></div>`,
      { label: `View ${path}`, onMount: (m, close) => { $("[data-close]", m).onclick = close; } });
  }
  $("#fRefresh").onclick = draw;
  $("#fUploadBtn").onclick = () => $("#fUpload").click();
  $("#fUpload").onchange = async (e) => {
    for (const f of [...e.target.files]) {
      try { const r = await uploadFile(f, dir === "." ? "uploads" : dir); toast(`Uploaded ${r.path}${r.notes?.length ? " - " + r.notes.join("; ") : ""}`); }
      catch (err) { toast(`${f.name}: ${err.message}`, "bad"); }
    }
    e.target.value = ""; draw();
  };
  await draw();
};

const ACCENTS = ["#38f2a5", "#4da3ff", "#a78bfa", "#ff7ab6", "#ffb020", "#ff5d5d", "#22d3ee"];
PAGES.settings = async () => {
  const [s, st] = await Promise.all([api("/api/settings"), refreshStatus()]);
  state.settings = s;
  const theme = localStorage.getItem("automoto_theme") || s.theme || "dark";
  const accent = localStorage.getItem("automoto_accent") || s.accent;
  const k = keys();
  const mod = isMac ? "⌘" : "Ctrl";
  page("Settings", "Appearance, safety and providers. Settings are saved to this computer; API keys never are.", `
    <div class="card"><h3>${icon("sun")} Appearance</h3>
      <div class="field"><span>Theme</span><div class="seg" role="radiogroup" aria-label="Theme" id="themeSeg">
        ${[["dark", "moon", "Dark"], ["light", "sun", "Light"], ["system", "monitor", "System"]].map(([v, i, l]) => `<button role="radio" data-v="${v}" aria-checked="${theme === v}">${icon(i)}<span class="lbl">${l}</span></button>`).join("")}</div></div>
      <div class="field"><span>Accent colour</span><div class="swatches" id="swatches">${ACCENTS.map((c) => `<button class="swatch" style="background:${c}" data-c="${c}" aria-label="Accent ${c}" aria-pressed="${c === accent}"></button>`).join("")}
        <input type="color" id="accentPick" value="${esc(accent)}" aria-label="Custom accent colour"></div></div></div>
    <div class="card"><h3>${icon("shield")} Safety</h3>
      <label class="field"><span>Approval mode (now: ${statusPill(s.effective_approval_mode)})</span><select class="input" id="apprSel" style="max-width:420px">
        ${[["", "Default (env AUTOMOTO_APPROVAL or ask)"], ["ask", "Ask: risky tools need my approval"], ["readonly", "Read-only: deny every risky tool"], ["auto", "Auto: run risky tools without asking"]].map(([v, l]) => `<option value="${v}" ${(s.approval_mode || "") === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label class="field"><span>Default mode for new chats</span><select class="input" id="modeSel" style="max-width:420px"><option value="agent" ${s.default_mode === "agent" ? "selected" : ""}>Agent (tools)</option><option value="chat" ${s.default_mode === "chat" ? "selected" : ""}>Chat (no tools)</option></select></label>
      <p class="muted" style="font-size:12.5px;margin:0">Blocked commands (like <code>rm -rf /</code>) never run in any mode. Network tools refuse private and local addresses.</p></div>
    <div class="card"><h3>${icon("folder")} Files &amp; folders</h3><p class="muted" style="font-size:13px;margin-top:0">The agent works in its sandbox folder by default. Add project folders it may also use (for example a VS Code project). Anything outside the sandbox always asks first, and secrets (<code>~/.ssh</code>, <code>.env</code> files, keychains, browser profiles, system folders) stay blocked.</p>
      <div id="rootList"></div><form id="rootForm" class="row" style="margin-top:8px"><input class="input" name="p" placeholder="/home/me/code/project or C:\\Users\\me\\code\\project" aria-label="Folder path" style="flex:1;min-width:220px"><button class="btn sm primary">Add folder</button></form></div>
    <div class="card"><h3>${icon("link")} Connectors (MCP)</h3><p class="muted" style="font-size:13px;margin-top:0">Official servers where they exist. Remote ones sign in with OAuth in your browser on first use; tokens go in <code>.env</code> and are never shown here. Every connector tool asks before it runs.</p>
      <div id="connList" class="muted">Loading…</div><div class="row" style="margin-top:8px"><button class="btn sm" id="connReload">Reconnect now</button></div></div>
    <div class="card"><h3>${icon("cpu")} Provider order</h3><p class="muted" style="font-size:13px;margin-top:0">Auto tries providers top to bottom and fails over on errors.</p>
      <div id="orderList"></div><div class="row"><button class="btn primary sm" id="orderSave">Save order</button><button class="btn sm" id="orderReset">Reset to recommended</button></div></div>
    <div class="card"><h3>${icon("key")} Bring your own keys</h3><p class="muted" style="font-size:13px;margin-top:0">Kept only in this browser tab (sessionStorage) and wiped when you close it. Sent with each request, never saved on the server. Server keys from <code>.env</code> work without this.</p>
      <form id="keyForm">${st.providers.map((p) => `<label class="field"><span>${esc(p.label)} ${p.configured ? statusPill("on") : ""}</span><input class="input" type="password" name="${p.id}" autocomplete="off" placeholder="${p.configured ? "configured (leave blank)" : "paste key"}" value="${esc(k[p.id] || "")}"></label>`).join("")}
      <div class="row"><button class="btn primary">Use keys for this tab</button><button type="button" class="btn danger" id="forgetKeys">Forget keys</button></div></form></div>
    <div class="card"><h3>${icon("info")} About</h3><p style="margin:0 0 6px">AutoMoto AI v${esc(VERSION)}</p>
      <p class="muted" style="margin:0 0 10px">Made by Yasin Mohammed Miah, Student of BCU, BSc Computing Top-Up (Hons) · <a href="https://github.com/ymmiah" target="_blank" rel="noopener">GitHub</a> · <a href="https://linkedin.com/in/ymmiah" target="_blank" rel="noopener">LinkedIn</a> · <a href="https://ymmiah.com" target="_blank" rel="noopener">ymmiah.com</a></p>
      <dl class="kv" style="margin:0"><dt><kbd>${mod}+K</kbd></dt><dd>Command palette</dd><dt><kbd>${mod}+N</kbd></dt><dd>New chat (in Chrome use <kbd>${mod}+Shift+O</kbd>)</dd><dt><kbd>${mod}+B</kbd></dt><dd>Toggle sidebar</dd><dt><kbd>Enter</kbd></dt><dd>Send · <kbd>Shift+Enter</kbd> new line</dd><dt><kbd>Esc</kbd></dt><dd>Stop a run / close dialogs</dd></dl></div>`);

  $("#themeSeg").onclick = async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    $$("#themeSeg button").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
    applyTheme(b.dataset.v); saveSetting({ theme: b.dataset.v });
  };
  const setAccent = (c) => { applyTheme(localStorage.getItem("automoto_theme") || "dark", c); $$(".swatch").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.c === c))); $("#accentPick").value = c; };
  $("#swatches").onclick = (e) => { const b = e.target.closest(".swatch"); if (b) { setAccent(b.dataset.c); saveSetting({ accent: b.dataset.c }); } };
  $("#accentPick").oninput = (e) => setAccent(e.target.value);
  $("#accentPick").onchange = (e) => saveSetting({ accent: e.target.value });
  $("#apprSel").onchange = async (e) => {
    const v = e.target.value;
    if (v === "auto" && !(await confirmDialog("Let the agent run risky tools (shell commands, file writes) without asking?", { ok: "Yes, auto-approve" }))) { e.target.value = state.settings.approval_mode || ""; return; }
    if (await saveSetting({ approval_mode: v || null })) { toast("Approval mode saved"); PAGES.settings(); }
  };
  $("#modeSel").onchange = (e) => saveSetting({ default_mode: e.target.value }).then((ok) => ok && toast("Saved"));
  let order = s.provider_order?.length ? [...s.provider_order] : [];
  const all = st.providers.map((p) => p.id);
  order = [...order.filter((x) => all.includes(x)), ...all.filter((x) => !order.includes(x))];
  const drawOrder = () => {
    $("#orderList").innerHTML = order.map((id, i) => { const p = st.providers.find((x) => x.id === id);
      return `<div class="order-item"><span class="n">${i + 1}</span><span class="nm">${esc(p.label)} ${p.configured ? "" : '<span class="muted">(no key)</span>'}</span>
        <button class="icon-btn sm" data-u="${i}" aria-label="Move ${esc(p.label)} up" ${i === 0 ? "disabled" : ""}>${icon("up")}</button><button class="icon-btn sm" data-d="${i}" aria-label="Move ${esc(p.label)} down" ${i === order.length - 1 ? "disabled" : ""}>${icon("down")}</button></div>`; }).join("");
    $$("#orderList [data-u]").forEach((b) => b.onclick = () => { const i = +b.dataset.u; [order[i - 1], order[i]] = [order[i], order[i - 1]]; drawOrder(); });
    $$("#orderList [data-d]").forEach((b) => b.onclick = () => { const i = +b.dataset.d; [order[i + 1], order[i]] = [order[i], order[i + 1]]; drawOrder(); });
  };
  drawOrder();
  $("#orderSave").onclick = async () => { if (await saveSetting({ provider_order: order })) toast("Provider order saved"); };
  $("#orderReset").onclick = async () => { if (await saveSetting({ provider_order: [] })) { toast("Using the recommended order"); PAGES.settings(); } };
  $("#keyForm").onsubmit = async (e) => {
    e.preventDefault();
    const obj = {}; for (const [n, v] of new FormData(e.target)) if (String(v).trim()) obj[n] = String(v).trim();
    sessionStorage.setItem("automoto_keys", JSON.stringify(obj));
    await refreshStatus(); toast(Object.keys(obj).length ? "Keys set for this tab only" : "No keys entered");
  };
  const roots = [...(s.allowed_roots || [])];
  const drawRoots = () => {
    $("#rootList").innerHTML = roots.length ? roots.map((r, i) => `<div class="order-item"><span class="nm"><code>${esc(r)}</code></span><button class="icon-btn sm" data-rm="${i}" aria-label="Remove ${esc(r)}">${icon("trash")}</button></div>`).join("") : '<div class="muted" style="font-size:13px">Only the sandbox folder.</div>';
    $$("#rootList [data-rm]").forEach((b) => b.onclick = async () => { const keep = roots.filter((_, i) => i !== +b.dataset.rm); if (await saveSetting({ allowed_roots: keep })) { roots.splice(0, roots.length, ...keep); drawRoots(); toast("Folder removed"); } });
  };
  drawRoots();
  $("#rootForm").onsubmit = async (e) => {
    e.preventDefault(); const v = String(new FormData(e.target).get("p") || "").trim(); if (!v) return;
    if (await saveSetting({ allowed_roots: [...roots, v] })) { const fresh = await api("/api/settings"); roots.splice(0, roots.length, ...(fresh.allowed_roots || [])); drawRoots(); e.target.reset(); toast("Folder added"); }
  };
  const drawConns = async () => {
    try {
      const d = await api("/api/connectors");
      $("#connList").classList.remove("muted");
      $("#connList").innerHTML = d.connectors.map((c) => `<div class="order-item"><span class="nm"><b>${esc(c.name)}</b> <span class="pill">${esc(c.vendor)}</span> <span class="pill">${esc(c.transport)}</span> <span class="pill st-${esc(c.status)}">${esc(STATUS_LABEL[c.status] || c.status)}</span> ${c.enabled ? statusPill("on") : ""}<br><span class="muted" style="font-size:12.5px">${esc(c.note)}${c.missing_env.length ? ` Needs <code>${esc(c.missing_env.join(", "))}</code> in .env.` : ""} <a href="${esc(c.docs)}" target="_blank" rel="noopener">docs</a></span></span>
        <button class="btn sm ${c.enabled ? "" : "primary"}" data-cid="${esc(c.id)}" data-act="${c.enabled ? "disable" : "enable"}">${c.enabled ? "Disable" : "Enable"}</button></div>`).join("") + (d.errors?.length ? `<pre class="muted">${esc(d.errors.join("\n"))}</pre>` : "");
      $$("#connList [data-cid]").forEach((b) => b.onclick = async () => {
        try { await api(`/api/connectors/${encodeURIComponent(b.dataset.cid)}/${b.dataset.act}`, {}); toast(b.dataset.act === "enable" ? "Enabled - press Reconnect now" : "Disabled"); drawConns(); } catch (err) { toast(err.message, "bad"); }
      });
    } catch (err) { $("#connList").textContent = err.message; }
  };
  drawConns();
  $("#connReload").onclick = async () => {
    $("#connReload").disabled = true;
    try { const r = await api("/api/connectors-reload", {}); toast(`${r.connected_tools} connector tool(s) ready${r.errors.length ? `, ${r.errors.length} error(s)` : ""}`, r.errors.length ? "bad" : ""); drawConns(); }
    catch (err) { toast(err.message, "bad"); } finally { $("#connReload").disabled = false; }
  };
  $("#forgetKeys").onclick = async () => { sessionStorage.removeItem("automoto_keys"); $$("#keyForm input").forEach((i) => i.value = ""); await refreshStatus(); toast("Keys forgotten"); };
};

// ---------------------------------------------------------------- command palette
const COMMANDS = [
  { t: "New chat", i: "plus", k: "mod+N", run: () => newChat() },
  { t: "Switch to Agent mode", i: "bolt", run: () => setMode("agent") },
  { t: "Switch to Chat mode", i: "chat", run: () => setMode("chat") },
  { t: "Tasks", i: "activity", run: () => (location.hash = "#/tasks") },
  { t: "Memory", i: "brain", run: () => (location.hash = "#/memory") },
  { t: "Routines", i: "clock", run: () => (location.hash = "#/routines") },
  { t: "Skills", i: "book", run: () => (location.hash = "#/skills") },
  { t: "Tools", i: "wrench", run: () => (location.hash = "#/tools") },
  { t: "Settings", i: "settings", run: () => (location.hash = "#/settings") },
  { t: "Theme: dark", i: "moon", run: () => { applyTheme("dark"); saveSetting({ theme: "dark" }); } },
  { t: "Theme: light", i: "sun", run: () => { applyTheme("light"); saveSetting({ theme: "light" }); } },
  { t: "Theme: system", i: "monitor", run: () => { applyTheme("system"); saveSetting({ theme: "system" }); } },
  { t: "Toggle sidebar", i: "menu", k: "mod+B", run: () => toggleSidebar() },
  { t: "Toggle info panel", i: "panel", run: () => $("#toggleInfo").click() },
  { t: "Forget BYOK keys in this tab", i: "key", run: () => { sessionStorage.removeItem("automoto_keys"); refreshStatus(); toast("Keys forgotten"); } },
];
let palItems = [], palSel = 0;
function openPalette() {
  const p = $("#palette"); p.hidden = false;
  const inp = $("#paletteInput"); inp.value = ""; drawPalette(); inp.focus();
}
function closePalette() { $("#palette").hidden = true; }
function drawPalette() {
  const q = $("#paletteInput").value.trim().toLowerCase();
  const cmds = COMMANDS.filter((c) => !q || c.t.toLowerCase().includes(q));
  const chats = state.convs.filter((c) => !q || c.title.toLowerCase().includes(q)).slice(0, 8);
  palItems = [...cmds.map((c) => ({ ...c, sec: "Commands" })), ...chats.map((c) => ({ t: c.title, i: c.mode === "chat" ? "chat" : "bolt", sec: "Chats", run: () => (location.hash = `#/c/${c.id}`) }))];
  palSel = Math.min(palSel, Math.max(0, palItems.length - 1));
  let sec = "", html = "";
  palItems.forEach((it, i) => {
    if (it.sec !== sec) { html += `<div class="pal-sec">${it.sec}</div>`; sec = it.sec; }
    html += `<div class="pal-item" role="option" id="pal-${i}" data-i="${i}" aria-selected="${i === palSel}">${icon(it.i)}<span class="t">${esc(it.t)}</span>${it.k ? `<kbd>${it.k.replace("mod", isMac ? "⌘" : "Ctrl")}</kbd>` : ""}</div>`;
  });
  $("#paletteList").innerHTML = html || '<div class="pal-sec">No matches</div>';
  $("#paletteInput").setAttribute("aria-activedescendant", palItems.length ? `pal-${palSel}` : "");
  $(`#pal-${palSel}`)?.scrollIntoView({ block: "nearest" });
}
$("#paletteInput").addEventListener("input", () => { palSel = 0; drawPalette(); });
$("#paletteInput").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { e.preventDefault(); palSel = Math.min(palSel + 1, palItems.length - 1); drawPalette(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); palSel = Math.max(palSel - 1, 0); drawPalette(); }
  else if (e.key === "Enter") { e.preventDefault(); const it = palItems[palSel]; closePalette(); it?.run(); }
  else if (e.key === "Escape") { e.preventDefault(); closePalette(); }
});
$("#paletteList").addEventListener("click", (e) => { const it = palItems[e.target.closest(".pal-item")?.dataset.i]; if (it) { closePalette(); it.run(); } });
$("#palette").addEventListener("click", (e) => { if (e.target.id === "palette") closePalette(); });

// ---------------------------------------------------------------- keyboard
document.addEventListener("keydown", (e) => {
  const mod = isMac ? e.metaKey : e.ctrlKey;
  const k = e.key.toLowerCase();
  if (mod && k === "k") { e.preventDefault(); $("#palette").hidden ? openPalette() : closePalette(); return; }
  if (mod && (k === "n" || (e.shiftKey && k === "o"))) { e.preventDefault(); newChat(); return; }
  if (mod && k === "b") { e.preventDefault(); toggleSidebar(); return; }
  if (e.key === "Escape") {
    if (!$("#palette").hidden) return closePalette();
    if (!$("#modal").hidden) return;
    if (app.classList.contains("side-open")) return closeSidebarMobile();
    if (state.busy) return stopRun();
  }
  const inField = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName);
  if (!inField && !mod && !e.altKey && (k === "a" || k === "d")) {
    const card = $(".approve:not(.done)"); const btn = card && $(`button[data-ok="${k === "a" ? 1 : 0}"]`, card);
    if (btn && !btn.disabled) { e.preventDefault(); btn.click(); }
  }
});

// ---------------------------------------------------------------- background
async function refreshBadge() {
  let tasks; try { tasks = (await api("/api/tasks")).tasks; } catch { return; }
  const live = tasks.filter((t) => ["running", "waiting_approval", "queued"].includes(t.status));
  const waiting = live.filter((t) => t.status === "waiting_approval").length;
  const b = $("#taskBadge");
  b.hidden = !live.length; b.textContent = live.length; b.classList.toggle("warn", waiting > 0);
  b.title = waiting ? `${waiting} waiting for approval` : `${live.length} running`;
  const before = [...state.running.keys()].join();
  state.running = new Map(live.filter((t) => t.conversation_id).map((t) => [t.conversation_id, t.id]));
  if ([...state.running.keys()].join() !== before) renderConvs();
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) document.title = "AutoMoto AI"; });

async function boot() {
  hydrateIcons(document);
  $("#verLabel").textContent = `v${VERSION}`;
  if (!isMac) $$("kbd").forEach((k) => (k.textContent = k.textContent.replace("⌘", "Ctrl+")));
  try {
    const s = await api("/api/settings");
    state.settings = s;
    if (!localStorage.getItem("automoto_theme")) applyTheme(s.theme, s.accent);
    else applyTheme(localStorage.getItem("automoto_theme"), localStorage.getItem("automoto_accent") || s.accent);
    if (!localStorage.getItem("automoto_mode")) state.mode = s.default_mode || "agent";
  } catch { applyTheme(localStorage.getItem("automoto_theme") || "dark"); }
  setMode(state.mode, false);
  if (localStorage.getItem("automoto_info") === "1" && !mobile()) $("#info").hidden = false;
  try { await refreshStatus(); } catch (e) { toast(`Couldn't reach the server: ${e.message}`, "bad"); }
  await loadConvs();
  await renderRoute();
  refreshBadge();
  setInterval(refreshBadge, 4000);
}
boot();
