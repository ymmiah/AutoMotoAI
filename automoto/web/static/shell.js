// Desktop shell: title bar menus, icon rail, projects, unread dots, the
// resizable preview panel and composer extras. app.js passes its helpers in
// through initShell(); nothing here talks to providers directly.
import { icon, hydrateIcons } from "./icons.js";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(key, fallback) { try { const v = JSON.parse(localStorage.getItem(key)); return v ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ } },
};
const IMAGE_EXT = /\.(png|jpe?g|gif|webp|bmp)$/i;
const OFFICE_EXT = /\.(pdf|docx?|xlsx?|pptx?|odt|ods|odp|rtf)$/i;
const TEXT_EXT = /\.(md|markdown|txt|log|json|jsonl|ya?ml|toml|xml|csv|tsv|ini|cfg|py|js|mjs|cjs|ts|tsx|jsx|css|html?|sh|ps1|bat|rs|go|java|kt|kts|c|h|cpp|hpp|cs|rb|php|swift|sql|tex|bib|typ|qmd|r|lua|pl|ex|exs|scm|dart|vue|svelte)$/i;
const MAX_PREVIEW = 15 * 1024 * 1024;
const MAX_TEXT = 2 * 1024 * 1024;
const fmtSize = (b) => b == null ? "" : b < 1024 ? `${b} B` : b < 1048576 ? `${Math.round(b / 1024)} KB` : `${(b / 1048576).toFixed(1)} MB`;
const baseName = (p) => String(p || "").split(/[/\\]/).pop() || String(p || "");

let ctx = null;
let lastField = null; // text field that had focus before a menu opened (for Edit actions)

// ---------------------------------------------------------------- dropdowns
let openDD = null; // { trigger, panel, onClose }
function closeDD(focusTrigger = false) {
  if (!openDD) return;
  const { trigger, panel, onClose } = openDD;
  openDD = null;
  panel.hidden = true;
  trigger?.setAttribute("aria-expanded", "false");
  onClose?.();
  if (focusTrigger) trigger?.focus();
}
function ddItems(panel) { return $$("[role='menuitem'], [role='menuitemradio']", panel).filter((el) => !el.disabled && el.getClientRects().length); }
function showDD(trigger, panel, { focusFirst = true, onClose, place } = {}) {
  if (openDD && openDD.panel === panel) { closeDD(true); return; }
  closeDD();
  hydrateIcons(panel);
  panel.hidden = false;
  place?.(panel, trigger);
  trigger?.setAttribute("aria-expanded", "true");
  openDD = { trigger, panel, onClose };
  if (focusFirst) ddItems(panel)[0]?.focus();
}
function wireDDKeys(panel) {
  panel.addEventListener("keydown", (e) => {
    const list = ddItems(panel);
    if (!list.length) return;
    const i = list.indexOf(document.activeElement);
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
      e.preventDefault();
      const n = e.key === "Home" ? 0 : e.key === "End" ? list.length - 1 : (i + (e.key === "ArrowDown" ? 1 : -1) + list.length) % list.length;
      list[n].focus();
    } else if (e.key === "Escape") {
      e.preventDefault(); e.stopPropagation(); closeDD(true);
    } else if (e.key === "Tab") {
      closeDD();
    }
  });
}
document.addEventListener("mousedown", (e) => {
  if (!openDD) return;
  if (openDD.panel.contains(e.target) || openDD.trigger?.contains(e.target)) return;
  closeDD();
}, true);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && openDD) { e.preventDefault(); e.stopPropagation(); closeDD(true); }
}, true);
document.addEventListener("focusin", (e) => {
  const t = e.target;
  if (t && (t.matches?.("input, textarea, [contenteditable='true']")) && !t.closest(".am-dd")) lastField = t;
});

// ---------------------------------------------------------------- actions
const isNative = () => !!(window.__TAURI_INTERNALS__ && typeof window.__TAURI_INTERNALS__.invoke === "function");
function native(action) {
  try { return Promise.resolve(window.__TAURI_INTERNALS__.invoke("chrome_action", { action })).catch(() => null); }
  catch { return Promise.resolve(null); }
}
// Zoom the workspace only. The 40px caption keeps its size so the native
// caption hit-test (chrome.rs) still lines up with the buttons.
function setZoom(z) {
  if (z === 1) document.documentElement.style.removeProperty("--zoom");
  else document.documentElement.style.setProperty("--zoom", String(z));
}
function zoom(step) {
  let z = step === 0 ? 1 : Math.round((store.get("automoto.zoom", 1) + step) * 10) / 10;
  z = Math.min(1.6, Math.max(0.7, z));
  store.set("automoto.zoom", z);
  setZoom(z);
  ctx.toast(`Zoom ${Math.round(z * 100)}%`);
}
function editCommand(cmd) {
  const field = lastField && lastField.isConnected ? lastField : null;
  field?.focus();
  if (cmd === "paste") {
    if (!navigator.clipboard?.readText) { ctx.toast("Press Ctrl+V to paste here.", "warn"); return; }
    navigator.clipboard.readText().then((text) => {
      if (!field || !text) return;
      if ("selectionStart" in field && typeof field.value === "string") {
        const s = field.selectionStart ?? field.value.length, en = field.selectionEnd ?? s;
        field.setRangeText(text, s, en, "end");
        field.dispatchEvent(new Event("input", { bubbles: true }));
      } else document.execCommand("insertText", false, text);
    }).catch(() => ctx.toast("Press Ctrl+V to paste here.", "warn"));
    return;
  }
  const map = { undo: "undo", redo: "redo", cut: "cut", copy: "copy", "select-all": "selectAll" };
  try { document.execCommand(map[cmd]); } catch { /* not supported here */ }
}
function openFilePicker() {
  const ta = $("#fileInput");
  if (ta) { ta.click(); return; }
  const input = document.createElement("input");
  input.type = "file"; input.multiple = true; input.hidden = true;
  document.body.appendChild(input);
  input.onchange = async () => {
    for (const f of [...input.files]) {
      try { const r = await ctx.uploadFile(f, "uploads"); ctx.toast(`Uploaded ${r.path}`); openPreview(r.path, { name: f.name, bytes: f.size }); }
      catch (err) { ctx.toast(`${f.name}: ${err.message}`, "bad"); }
    }
    input.remove();
  };
  input.click();
}
function showShortcuts() {
  const rows = [["New chat", "Ctrl+N"], ["Quick commands", "Ctrl+K"], ["Search chats", "Ctrl+Shift+F"], ["Toggle sidebar", "Ctrl+B"],
    ["Toggle preview panel", "Ctrl+."], ["Open file", "Ctrl+O"], ["Settings", "Ctrl+,"], ["Zoom in / out / reset", "Ctrl+= / Ctrl+- / Ctrl+0"],
    ["Back / forward", "Alt+Left / Alt+Right"], ["Approve / deny a step", "A / D"], ["Guide", "F1"]];
  ctx.openModal(`<h3>Keyboard shortcuts</h3><dl class="kv" style="grid-template-columns:1fr auto">${rows.map(([a, k]) => `<dt>${esc(a)}</dt><dd><kbd>${esc(k)}</kbd></dd>`).join("")}</dl><div class="row"><button class="btn primary" data-close>Done</button></div>`,
    { label: "Keyboard shortcuts", onMount: (m, close) => { $("[data-close]", m).onclick = close; } });
}
function showAbout() {
  const ver = ($("#verLabel")?.textContent || "").trim();
  ctx.openModal(`<h3>${esc(ctx.BRAND)}</h3><p class="muted">${esc(ver)}</p><p>Your personal workspace for documents, research, spreadsheets, visuals and code. Risky steps always ask you first.</p><p class="muted small">AGPL-3.0-only or commercial licence.</p><div class="row"><button class="btn primary" data-close>Close</button></div>`,
    { label: `About ${ctx.BRAND}`, onMount: (m, close) => { $("[data-close]", m).onclick = close; } });
}
export function runAction(name) {
  switch (name) {
    case "new-chat": return ctx.newChat();
    case "new-project": return newProject();
    case "open-file": return openFilePicker();
    case "files": location.hash = "#/files"; return;
    case "settings": location.hash = "#/settings"; return;
    case "quit": if (isNative()) native("quit"); else ctx.toast("Close this browser tab to quit.", "warn"); return;
    case "undo": case "redo": case "cut": case "copy": case "paste": case "select-all": return editCommand(name);
    case "find": {
      if (document.querySelector("#app").classList.contains("side-collapsed")) ctx.toggleSidebar();
      if (matchMedia("(max-width: 760px)").matches && !$("#app").classList.contains("side-open")) ctx.toggleSidebar();
      const s = $("#convSearch"); s?.focus(); s?.select(); return;
    }
    case "palette": return ctx.openPalette();
    case "toggle-sidebar": return ctx.toggleSidebar();
    case "toggle-panel": return togglePanel();
    case "toggle-rail": { const off = !$("#app").classList.contains("rail-off"); $("#app").classList.toggle("rail-off", off); store.set("automoto.rail.off", off); return; }
    case "zoom-in": return zoom(0.1);
    case "zoom-out": return zoom(-0.1);
    case "zoom-reset": return zoom(0);
    case "theme": return $("#quickTheme")?.click();
    case "reload": return location.reload();
    case "guide": location.hash = "#/help"; return;
    case "shortcuts": return showShortcuts();
    case "updates": if (isNative()) native("updates"); else ctx.toast("Updates arrive through the Microsoft Store or your server.", ""); return;
    case "report": window.open($("#reportLink")?.href, "_blank", "noopener"); return;
    case "source": window.open($("#sourceLink")?.href, "_blank", "noopener"); return;
    case "about": return showAbout();
    default: return undefined;
  }
}

// ---------------------------------------------------------------- menubar
function wireMenubar() {
  const bar = $("#amMenubar");
  if (!bar) return;
  const buttons = $$(".am-mb-btn", bar);
  const panelOf = (b) => $(`[data-menu-panel="${b.dataset.menu}"]`, bar);
  buttons.forEach((b, i) => {
    const panel = panelOf(b);
    wireDDKeys(panel);
    b.addEventListener("click", () => showDD(b, panel));
    b.addEventListener("mouseenter", () => { if (openDD && buttons.includes(openDD.trigger) && openDD.trigger !== b) showDD(b, panel, { focusFirst: false }); });
    b.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") { e.preventDefault(); if (!openDD || openDD.panel !== panel) showDD(b, panel); else ddItems(panel)[0]?.focus(); }
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); buttons[(i + (e.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length].focus(); }
    });
    panel.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      const next = buttons[(i + (e.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length];
      showDD(next, panelOf(next));
    });
  });
}
// Any element with data-do inside a dropdown or the rail runs the matching action.
document.addEventListener("click", (e) => {
  const item = e.target.closest("[data-do]");
  if (!item || !ctx) return;
  e.preventDefault();
  closeDD();
  runAction(item.dataset.do);
});

// ---------------------------------------------------------------- rail
const STUDIOS = ["documents", "research", "spreadsheets", "visual", "developer"];
function syncRail() {
  const pg = (location.hash || "#/new").split("/")[1] || "new";
  $$(".rail [data-rail]").forEach((el) => {
    const r = el.dataset.rail;
    const on = r === "new" ? false : r === "chat" ? (pg === "new" || pg === "c") : r === "studios" ? STUDIOS.includes(pg) : r === pg;
    el.classList.toggle("active", on);
  });
}
function wireRail() {
  const rail = $("#rail");
  if (!rail) return;
  $$("[data-rail-menu]", rail).forEach((b) => {
    const panel = $(`[data-rail-panel="${b.dataset.railMenu}"]`, rail);
    wireDDKeys(panel);
    b.addEventListener("click", () => showDD(b, panel, {
      place: (p, t) => { p.style.top = Math.max(8, Math.min(t.offsetTop, rail.clientHeight - p.offsetHeight - 8)) + "px"; },
    }));
    panel.addEventListener("click", (e) => { if (e.target.closest("a")) closeDD(); });
  });
  $("[data-rail='new']", rail)?.addEventListener("click", (e) => { e.preventDefault(); ctx.newChat(); });
  $("#railAvatar")?.addEventListener("click", () => { location.hash = ctx.HOSTED ? "#/account" : "#/settings"; });
  if (store.get("automoto.rail.off", false)) $("#app").classList.add("rail-off");
  window.addEventListener("hashchange", syncRail);
  syncRail();
}
export function setAvatar(name) {
  const el = $("#railAvatarText");
  if (!el) return;
  const letter = String(name || "").trim().charAt(0).toUpperCase();
  el.innerHTML = letter ? esc(letter) : icon("user");
  if (name) $("#railAvatar").title = name;
}

// ---------------------------------------------------------------- projects (folders on this device)
const PKEY = "automoto.projects.v1";
const projects = () => store.get(PKEY, []);
const saveProjects = (list) => store.set(PKEY, list);
export function projectOf(convId) { return projects().find((p) => p.chats.some((c) => c.id === convId)) || null; }
export async function newProject(withConv) {
  const name = await ctx.promptDialog("New project", "", { ok: "Create" });
  if (!name) return null;
  const list = projects();
  const p = { id: "p" + Date.now().toString(36), name, open: true, chats: [] };
  list.push(p); saveProjects(list);
  if (withConv) moveToProject(withConv, p.id); else ctx.renderConvs();
  ctx.toast(`Project “${name}” created`);
  return p;
}
export function moveToProject(conv, projectId) {
  const list = projects();
  for (const p of list) p.chats = p.chats.filter((c) => c.id !== conv.id);
  const target = list.find((p) => p.id === projectId);
  if (target) { target.chats.unshift({ id: conv.id, title: conv.title }); target.open = true; }
  saveProjects(list);
  ctx.renderConvs();
}
export function pickProject(conv) {
  const list = projects();
  const cur = projectOf(conv.id);
  ctx.openModal(`<h3>Move “${esc(conv.title)}” to a project</h3>
    <div class="pal-list" style="display:flex;flex-direction:column;gap:4px;margin:6px 0 4px">
    ${list.map((p) => `<button type="button" class="btn ghost" data-p="${esc(p.id)}" style="justify-content:flex-start">${icon("folder")} ${esc(p.name)}${cur?.id === p.id ? " ✓" : ""}</button>`).join("") || '<p class="muted">No projects yet.</p>'}
    </div><div class="row">${cur ? '<button type="button" class="btn" data-p="">Remove from project</button>' : ""}<button type="button" class="btn" data-new>${icon("folder_plus")} New project</button><button type="button" class="btn primary" data-close>Done</button></div>`,
  { label: "Move to project", onMount: (m, close) => {
    $$("[data-p]", m).forEach((b) => b.onclick = () => { moveToProject(conv, b.dataset.p); close(); });
    $("[data-new]", m).onclick = () => { close(); setTimeout(() => newProject(conv), 0); };
    $("[data-close]", m).onclick = close;
  } });
}
export function renderProjects(convRow) {
  const box = $("#projectList");
  if (!box) return;
  const list = projects();
  const known = new Map((ctx.state.convs || []).map((c) => [c.id, c]));
  let changed = false;
  for (const p of list) for (const c of p.chats) { const k = known.get(c.id); if (k && k.title !== c.title) { c.title = k.title; changed = true; } }
  if (changed) saveProjects(list);
  box.innerHTML = list.map((p) => `<div class="project" role="listitem" data-project="${esc(p.id)}">
      <div class="project-row" tabindex="0" role="button" aria-expanded="${p.open ? "true" : "false"}" data-ptoggle>${icon("folder")}<span class="t">${esc(p.name)}</span><span class="n">${p.chats.length || ""}</span>
        <span class="p-acts"><button type="button" class="icon-btn sm" data-prename aria-label="Rename project">${icon("edit")}</button><button type="button" class="icon-btn sm" data-pdelete aria-label="Delete project">${icon("trash")}</button></span></div>
      ${p.open ? `<div class="project-chats">${p.chats.map((c) => convRow(known.get(c.id) || { id: c.id, title: c.title, mode: "agent", updated: 0 })).join("") || '<div class="empty-list">Use “Move to project” on a chat.</div>'}</div>` : ""}
    </div>`).join("");
  $$(".project", box).forEach((el) => {
    const id = el.dataset.project;
    const toggle = () => { const l = projects(); const p = l.find((x) => x.id === id); if (p) { p.open = !p.open; saveProjects(l); renderProjects(convRow); } };
    $("[data-ptoggle]", el).addEventListener("click", (e) => { if (!e.target.closest("button")) toggle(); });
    $("[data-ptoggle]", el).addEventListener("keydown", (e) => { if ((e.key === "Enter" || e.key === " ") && e.target === e.currentTarget) { e.preventDefault(); toggle(); } });
    $("[data-prename]", el).onclick = async () => {
      const l = projects(); const p = l.find((x) => x.id === id); if (!p) return;
      const name = await ctx.promptDialog("Rename project", p.name); if (!name) return;
      p.name = name; saveProjects(l); renderProjects(convRow);
    };
    $("[data-pdelete]", el).onclick = async () => {
      const l = projects(); const p = l.find((x) => x.id === id); if (!p) return;
      if (!(await ctx.confirmDialog(`Delete the project “${p.name}”? Its chats stay in Recents.`))) return;
      saveProjects(l.filter((x) => x.id !== id)); ctx.renderConvs();
    };
  });
}
export const projectChatIds = () => new Set(projects().flatMap((p) => p.chats.map((c) => c.id)));
export function forgetConv(id) {
  const list = projects(); let hit = false;
  for (const p of list) { const n = p.chats.length; p.chats = p.chats.filter((c) => c.id !== id); hit ||= n !== p.chats.length; }
  if (hit) saveProjects(list);
}

// ---------------------------------------------------------------- unread dots
const SKEY = "automoto.seen.v1";
let seen = store.get(SKEY, null);
export function noteConvs(convs) {
  if (!seen) { seen = {}; for (const c of convs) seen[c.id] = c.updated; store.set(SKEY, seen); }
  const cur = ctx.state.cur?.id;
  let dirty = false;
  for (const c of convs) {
    if (!(c.id in seen) || c.id === cur) { if (seen[c.id] !== c.updated) { seen[c.id] = c.updated; dirty = true; } }
  }
  if (dirty) store.set(SKEY, seen);
}
export const isUnread = (c) => !!(seen && c.id in seen && c.updated > seen[c.id] + 0.5 && ctx.state.cur?.id !== c.id && !ctx.state.running.has(c.id));
export function markSeen(conv) {
  if (!conv) return;
  seen = seen || {};
  seen[conv.id] = Math.max(conv.updated || 0, Date.now() / 1000);
  store.set(SKEY, seen);
}

// ---------------------------------------------------------------- conversation menu
function wireConvMenu() {
  const btn = $("#convMore"), panel = $("#convMenu");
  if (!btn || !panel) return;
  wireDDKeys(panel);
  btn.addEventListener("click", () => {
    const c = ctx.state.cur;
    panel.innerHTML = (c ? `<button type="button" role="menuitem" data-c="rename">${icon("edit")}Rename</button>
      <button type="button" role="menuitem" data-c="project">${icon("folder")}Move to project…</button>
      <button type="button" role="menuitem" data-c="copy">${icon("copy")}Copy conversation</button>
      <div role="separator"></div>` : "") +
      `<button type="button" role="menuitem" data-do="toggle-panel">${icon("panel")}Toggle preview panel <span class="k">Ctrl+.</span></button>
      <button type="button" role="menuitem" data-do="new-chat">${icon("plus")}New chat <span class="k">Ctrl+N</span></button>` +
      (c ? `<div role="separator"></div><button type="button" role="menuitem" data-c="delete" style="color:var(--bad)">${icon("trash")}Delete chat</button>` : "");
    showDD(btn, panel);
  });
  panel.addEventListener("click", (e) => {
    const b = e.target.closest("[data-c]"); const c = ctx.state.cur;
    if (!b || !c) return;
    closeDD();
    if (b.dataset.c === "rename") ctx.renameConv(c.id);
    if (b.dataset.c === "project") pickProject(c);
    if (b.dataset.c === "delete") ctx.deleteConv(c.id);
    if (b.dataset.c === "copy") {
      const text = $$("#thread .msg").map((m) => (m.classList.contains("user") ? "You: " : `${ctx.BRAND_SHORT}: `) + ($(".bubble, .answer", m)?.innerText || "").trim()).join("\n\n");
      ctx.copyText(text); ctx.toast("Conversation copied");
    }
  });
}

// ---------------------------------------------------------------- preview panel
const pv = { tabs: [], active: "run", recent: store.get("automoto.preview.recent", []) };
const info = () => $("#info");
function setPanel(open) {
  const el = info(); if (!el) return;
  el.hidden = !open;
  localStorage.setItem("automoto_info", open ? "1" : "0");
  $("#toggleInfo")?.setAttribute("aria-pressed", String(open));
}
export function togglePanel(force) { setPanel(typeof force === "boolean" ? force : info().hidden); }
export const panelOpen = () => !info().hidden;
function remember(path, meta) {
  pv.recent = [{ path, name: meta.name || baseName(path), bytes: meta.bytes ?? null }, ...pv.recent.filter((r) => r.path !== path)].slice(0, 12);
  store.set("automoto.preview.recent", pv.recent);
}
export function noteFiles(files) {
  for (const f of files || []) if (f?.path) remember(f.path, { name: f.name, bytes: f.bytes });
}
function drawTabs() {
  const list = $("#pvTabList"); if (!list) return;
  list.innerHTML = pv.tabs.map((t) => `<span role="tab" tabindex="0" class="pv-tab${pv.active === t.id ? " active" : ""}" data-pv-tab="${esc(t.id)}" aria-selected="${pv.active === t.id}" title="${esc(t.path)}">${icon(IMAGE_EXT.test(t.path) ? "image" : TEXT_EXT.test(t.path) ? "code" : "file")}<span class="pv-tab-t">${esc(t.name)}</span><span class="pv-x" role="button" tabindex="-1" aria-label="Close tab ${esc(t.name)}" data-pv-x="${esc(t.id)}">${icon("x")}</span></span>`).join("");
  $("#pvTabRun")?.classList.toggle("active", pv.active === "run");
  $("#pvTabRun")?.setAttribute("aria-selected", String(pv.active === "run"));
  $$(".pv-pane", info()).forEach((p) => { p.hidden = (p.dataset.pane === "run") !== (pv.active === "run"); });
  $(".pv-tab.active", list)?.scrollIntoView({ block: "nearest", inline: "nearest" });
}
function activate(id) {
  pv.active = id;
  drawTabs();
  if (id !== "run") renderFile(pv.tabs.find((t) => t.id === id));
}
function closeTab(id) {
  const i = pv.tabs.findIndex((t) => t.id === id);
  if (i < 0) return;
  pv.tabs.splice(i, 1);
  if (pv.active === id) activate(pv.tabs[Math.min(i, pv.tabs.length - 1)]?.id || "run"); else drawTabs();
}
export function openPreview(path, meta = {}) {
  if (!path) return;
  let tab = pv.tabs.find((t) => t.path === path);
  if (!tab) { tab = { id: "t" + Math.random().toString(36).slice(2, 9), path, name: meta.name || baseName(path), bytes: meta.bytes ?? null, source: false }; pv.tabs.push(tab); }
  else if (meta.bytes != null) tab.bytes = meta.bytes;
  remember(path, tab);
  setPanel(true);
  activate(tab.id);
}
function emptyState(tab, title, why) {
  return `<div class="pv-empty"><div class="pv-empty-ico">${icon("file")}</div><h3>${esc(title)}</h3><p>${esc(why)}</p>
    <div class="row"><a class="btn sm" href="/api/files/download?path=${encodeURIComponent(tab.path)}" download>${icon("download")} Download</a><button type="button" class="btn sm" data-pv-files>${icon("folder")} Show in Files</button></div></div>`;
}
let renderSeq = 0;
async function renderFile(tab) {
  if (!tab) return;
  const seq = ++renderSeq;
  const body = $("#pvBody");
  $("#pvName").textContent = tab.name; $("#pvName").title = tab.path;
  $("#pvSize").textContent = fmtSize(tab.bytes);
  const srcBtn = $("#pvSource");
  const textual = TEXT_EXT.test(tab.path);
  srcBtn.disabled = !/\.(md|markdown|html?|csv|tsv|json)$/i.test(tab.path);
  srcBtn.setAttribute("aria-pressed", String(!!tab.source));
  body.innerHTML = `<div class="pv-loading">Opening ${esc(tab.name)}…</div>`;
  const fail = (title, why) => { if (seq === renderSeq) { body.innerHTML = emptyState(tab, title, why); wireEmpty(tab); } };
  if (tab.bytes != null && tab.bytes > MAX_PREVIEW) return fail("Could not open file", `This file is too large to preview here (${fmtSize(tab.bytes)}). Download it or open it with another app.`);
  if (IMAGE_EXT.test(tab.path) || (OFFICE_EXT.test(tab.path) && !tab.source)) {
    const img = new Image();
    img.className = "pv-img"; img.alt = `Preview of ${tab.name}`;
    img.onload = () => { if (seq === renderSeq) { body.innerHTML = ""; body.appendChild(img); } };
    img.onerror = () => fail("Could not open file", OFFICE_EXT.test(tab.path) ? "A preview of this document is not available on this computer. Previews of Office files need LibreOffice." : "This picture could not be shown.");
    img.src = `/api/files/preview?path=${encodeURIComponent(tab.path)}&page=1`;
    return;
  }
  if (textual && (tab.bytes == null || tab.bytes <= MAX_TEXT)) {
    try {
      const r = await fetch(`/api/files/download?path=${encodeURIComponent(tab.path)}`, { credentials: "same-origin", headers: ctx.authHeaders() });
      if (!r.ok) throw new Error(r.status === 404 ? "The file is no longer in the workspace." : `The server said ${r.status}.`);
      const size = Number(r.headers.get("content-length") || 0);
      if (size > MAX_TEXT) return fail("Could not open file", `This file is too large to preview here (${fmtSize(size)}).`);
      const text = await r.text();
      if (seq !== renderSeq) return;
      if (tab.bytes == null) { tab.bytes = text.length; $("#pvSize").textContent = fmtSize(tab.bytes); }
      if (/\.(md|markdown)$/i.test(tab.path) && !tab.source) { body.innerHTML = ""; body.appendChild(ctx.renderMarkdown(text)); return; }
      if (/\.(csv|tsv)$/i.test(tab.path) && !tab.source) { body.innerHTML = csvTable(text, /\.tsv$/i.test(tab.path) ? "\t" : ","); return; }
      if (/\.json$/i.test(tab.path) && !tab.source) { let pretty = text; try { pretty = JSON.stringify(JSON.parse(text), null, 2); } catch { /* keep raw */ } body.innerHTML = `<pre class="pv-src">${esc(pretty)}</pre>`; return; }
      body.innerHTML = `<pre class="pv-src">${esc(text)}</pre>`;
      return;
    } catch (e) { return fail("Could not open file", e.message); }
  }
  return renderInspect(tab, seq);
}
function csvTable(text, sep) {
  const rows = [];
  let row = [], cell = "", quoted = false;
  for (let i = 0; i < text.length && rows.length < 501; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (ch === '"') quoted = false; else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === sep) { row.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") { if (ch === "\r" && text[i + 1] === "\n") i++; row.push(cell); rows.push(row); row = []; cell = ""; }
    else cell += ch;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  const [head = [], ...body] = rows.filter((r) => r.length > 1 || r[0]);
  return `<p class="muted small">${body.length}${body.length >= 500 ? "+" : ""} rows · ${head.length} columns</p><div class="table-wrap"><table class="data"><thead><tr>${head.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${body.slice(0, 500).map((r) => `<tr>${r.map((v) => `<td>${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
async function renderInspect(tab, seq) {
  const body = $("#pvBody");
  let d;
  try { d = await ctx.api(`/api/files/inspect?path=${encodeURIComponent(tab.path)}`); }
  catch (e) { return seq === renderSeq && (body.innerHTML = emptyState(tab, "Could not open file", e.status === 415 || /preview|type/i.test(e.message) ? "There is no preview for this kind of file. You can still download it or open it with another app." : e.message), wireEmpty(tab)); }
  if (seq !== renderSeq) return;
  if (d.kind === "table") {
    body.innerHTML = `<p class="muted small">${Number(d.total_rows || 0).toLocaleString()} rows · ${d.columns.length} columns · first ${d.rows.length} shown</p>
      <div class="table-wrap"><table class="data"><thead><tr>${d.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${d.rows.map((r) => `<tr>${r.map((v) => `<td>${v == null ? "" : esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  } else if (d.kind === "archive") {
    body.innerHTML = `<p class="muted small">${esc(d.report?.format || "archive")} · ${d.report?.files ?? d.entries.length} files</p><div class="tree">${d.entries.map((e) => `<div class="tree-row">${icon(e.kind === "dir" ? "folder" : "file")}<span>${esc(e.name)}</span></div>`).join("")}</div>`;
  } else if (d.kind === "data") {
    body.innerHTML = `<pre class="pv-src">${esc((d.outline || []).join("\n"))}</pre>`;
  } else {
    body.innerHTML = `<pre class="pv-src">${esc(d.text || "")}</pre>`;
  }
}
function wireEmpty(tab) {
  $("[data-pv-files]", $("#pvBody"))?.addEventListener("click", () => ctx.openWorkspaceFile(tab.path));
}
function openWithMenu(tab) {
  const p = tab.path;
  const items = [
    `<a role="menuitem" href="/api/files/download?path=${encodeURIComponent(p)}" download>${icon("download")}Download a copy</a>`,
    `<button type="button" role="menuitem" data-ow="files">${icon("folder")}Files</button>`,
  ];
  if (/\.(docx|pdf|pptx|xlsx|md|txt)$/i.test(p) || /\.document\.json$/i.test(p)) items.push(`<button type="button" role="menuitem" data-ow="documents">${icon("file")}Documents studio</button>`);
  if (IMAGE_EXT.test(p)) items.push(`<button type="button" role="menuitem" data-ow="visual">${icon("image")}Visual studio (layers)</button>`);
  items.push(`<button type="button" role="menuitem" data-ow="ask">${icon("chat")}Ask the assistant about it</button>`, `<div role="separator"></div>`, `<button type="button" role="menuitem" data-ow="copy">${icon("copy")}Copy path</button>`);
  return items.join("");
}
function wirePanel() {
  const el = info(); if (!el) return;
  const w = store.get("automoto.panel.w", null);
  if (w) document.documentElement.style.setProperty("--info-w", w + "px");
  $("#toggleInfo").setAttribute("aria-pressed", String(!el.hidden));
  $("#pvTabRun").addEventListener("click", () => activate("run"));
  $("#pvTabList").addEventListener("click", (e) => {
    const x = e.target.closest("[data-pv-x]");
    if (x) { e.stopPropagation(); closeTab(x.dataset.pvX); return; }
    const t = e.target.closest("[data-pv-tab]"); if (t) activate(t.dataset.pvTab);
  });
  $("#pvTabList").addEventListener("keydown", (e) => {
    const t = e.target.closest("[data-pv-tab]"); if (!t) return;
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(t.dataset.pvTab); }
    if (e.key === "Delete") { e.preventDefault(); closeTab(t.dataset.pvTab); }
  });
  $("#pvSource").addEventListener("click", () => {
    const tab = pv.tabs.find((t) => t.id === pv.active); if (!tab) return;
    tab.source = !tab.source; renderFile(tab);
  });
  const owBtn = $("#pvOpenWith"), owMenu = $("#pvOpenMenu");
  wireDDKeys(owMenu);
  owBtn.addEventListener("click", () => {
    const tab = pv.tabs.find((t) => t.id === pv.active); if (!tab) return;
    owMenu.innerHTML = openWithMenu(tab); showDD(owBtn, owMenu);
  });
  owMenu.addEventListener("click", (e) => {
    const tab = pv.tabs.find((t) => t.id === pv.active); if (!tab) return;
    if (e.target.closest("a")) { closeDD(); return; }
    const b = e.target.closest("[data-ow]"); if (!b) return;
    closeDD();
    const p = tab.path;
    if (b.dataset.ow === "files") ctx.openWorkspaceFile(p);
    if (b.dataset.ow === "documents") { sessionStorage.setItem("automoto_document_open_path", p); location.hash = "#/documents"; }
    if (b.dataset.ow === "visual") { sessionStorage.setItem("automoto_visual_open_image", p); location.hash = "#/visual"; }
    if (b.dataset.ow === "ask") ctx.askAbout(p);
    if (b.dataset.ow === "copy") { ctx.copyText(p); ctx.toast("Path copied"); }
  });
  // "+" tab: recent files, then a small workspace browser.
  const addBtn = $("#pvAdd"), addMenu = $("#pvAddMenu");
  wireDDKeys(addMenu);
  const drawAdd = async (dir) => {
    let html = "";
    if (dir == null) {
      html += `<div class="dd-label">Recent files</div>` + (pv.recent.length ? pv.recent.map((r) => `<button type="button" role="menuitem" data-pv-open="${esc(r.path)}" data-bytes="${r.bytes ?? ""}">${icon(IMAGE_EXT.test(r.path) ? "image" : "file")}<span>${esc(r.name)}<span class="dd-sub">${esc(r.path)}</span></span></button>`).join("") : `<div class="muted small" style="padding:4px 10px 8px">Files the assistant makes appear here.</div>`);
      html += `<div role="separator"></div><button type="button" role="menuitem" data-pv-dir=".">${icon("folder")}Browse workspace…</button><button type="button" role="menuitem" data-do="open-file">${icon("upload")}Open a file from this computer…</button>`;
      addMenu.innerHTML = html; hydrateIcons(addMenu); return;
    }
    addMenu.innerHTML = `<div class="pv-loading">Loading…</div>`;
    try {
      const d = await ctx.api(`/api/files?dir=${encodeURIComponent(dir)}`);
      const up = d.dir === "." ? "" : `<button type="button" role="menuitem" data-pv-dir="${esc(d.dir.split("/").slice(0, -1).join("/") || ".")}">${icon("back")}Up</button>`;
      addMenu.innerHTML = `<div class="dd-label">${esc(d.dir === "." ? "workspace" : d.dir)}</div>${up}` + (d.items.map((it) => it.dir
        ? `<button type="button" role="menuitem" data-pv-dir="${esc(it.path)}">${icon("folder")}${esc(it.name)}</button>`
        : `<button type="button" role="menuitem" data-pv-open="${esc(it.path)}" data-bytes="${it.size ?? ""}">${icon("file")}${esc(it.name)}<span class="k">${esc(fmtSize(it.size))}</span></button>`).join("") || '<div class="muted small" style="padding:4px 10px">Empty folder</div>');
    } catch (e) { addMenu.innerHTML = `<div class="muted small" style="padding:6px 10px">${esc(e.message)}</div>`; }
    ddItems(addMenu)[0]?.focus();
  };
  addBtn.addEventListener("click", () => { drawAdd(null); showDD(addBtn, addMenu); });
  addMenu.addEventListener("click", (e) => {
    const d = e.target.closest("[data-pv-dir]");
    if (d) { e.stopPropagation(); drawAdd(d.dataset.pvDir); return; }
    const o = e.target.closest("[data-pv-open]");
    if (o) { closeDD(); openPreview(o.dataset.pvOpen, { bytes: o.dataset.bytes ? Number(o.dataset.bytes) : null }); }
  });
  // Drag the left edge to resize; arrow keys work too.
  const handle = $("#pvResize");
  const apply = (px) => {
    const max = Math.max(320, Math.min(980, window.innerWidth - 420));
    const v = Math.round(Math.min(max, Math.max(300, px)));
    document.documentElement.style.setProperty("--info-w", v + "px");
    return v;
  };
  handle.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    handle.setPointerCapture(e.pointerId); handle.classList.add("drag");
    const right = el.getBoundingClientRect().right;
    const move = (ev) => apply(right - ev.clientX);
    const up = (ev) => { handle.classList.remove("drag"); handle.removeEventListener("pointermove", move); handle.removeEventListener("pointerup", up); store.set("automoto.panel.w", apply(right - ev.clientX)); };
    handle.addEventListener("pointermove", move); handle.addEventListener("pointerup", up);
  });
  handle.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    store.set("automoto.panel.w", apply(el.getBoundingClientRect().width + (e.key === "ArrowLeft" ? 24 : -24)));
  });
  drawTabs();
}

// ---------------------------------------------------------------- composer extras
const APPROVALS = [["ask", "Ask before risky steps", "Stops and asks before anything that changes files or runs commands."],
  ["readonly", "Read-only", "Looks at files but never changes them."], ["auto", "Auto-approve", "Risky steps run without asking. Passwords and system folders stay blocked."]];
let approvalNow = null;
function chipLabel() {
  const mode = ctx.state.mode === "chat" ? "Chat" : "Assistant";
  const a = APPROVALS.find((x) => x[0] === approvalNow);
  return ctx.state.mode === "chat" ? "Chat only" : `${mode} · ${a ? a[1].replace(" before risky steps", " first") : "Ask first"}`;
}
export function syncComposerChips() {
  const chip = $("#approvalChip");
  if (chip) {
    $(".cmp-label", chip).textContent = chipLabel();
    chip.classList.toggle("auto", approvalNow === "auto" && ctx.state.mode !== "chat");
  }
  const src = $("#providerPick"), dst = $("#modelPick");
  if (src && dst) {
    dst.innerHTML = src.innerHTML.replace("Auto · best available", "Auto");
    dst.value = src.value; dst.title = src.title;
  }
}
async function loadApproval() {
  try {
    const s = ctx.state.settings || await ctx.api("/api/settings");
    approvalNow = s?.approval_mode || s?.effective_approval_mode || "ask";
  } catch { approvalNow = approvalNow || "ask"; }
  syncComposerChips();
}
export function wireComposerExtras() {
  const chip = $("#approvalChip"), menu = $("#approvalMenu");
  if (chip && menu) {
    wireDDKeys(menu);
    chip.addEventListener("click", () => {
      const m = ctx.state.mode;
      menu.innerHTML = `<div class="dd-label">How it works</div>
        <button type="button" role="menuitemradio" class="dd-rich" data-cmp-mode="agent" aria-checked="${m !== "chat"}">${icon("bolt")}<span>Assistant<span class="dd-sub">Does the steps and makes the files.</span></span></button>
        <button type="button" role="menuitemradio" class="dd-rich" data-cmp-mode="chat" aria-checked="${m === "chat"}">${icon("chat")}<span>Chat<span class="dd-sub">An answer only, no files or tools.</span></span></button>
        <div role="separator"></div><div class="dd-label">Approvals</div>` +
        APPROVALS.map(([v, l, d]) => `<button type="button" role="menuitemradio" class="dd-rich" data-appr="${v}" aria-checked="${approvalNow === v}">${icon(v === "auto" ? "alert" : v === "readonly" ? "eye" : "shield")}<span>${esc(l)}<span class="dd-sub">${esc(d)}</span></span></button>`).join("");
      showDD(chip, menu);
    });
    menu.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-cmp-mode], [data-appr]"); if (!b) return;
      closeDD(true);
      if (b.dataset.cmpMode) { ctx.setMode(b.dataset.cmpMode); syncComposerChips(); return; }
      const v = b.dataset.appr;
      if (await ctx.saveSetting({ approval_mode: v })) { approvalNow = v; syncComposerChips(); ctx.toast(`Approvals: ${APPROVALS.find((x) => x[0] === v)[1]}`); }
    });
  }
  const model = $("#modelPick");
  if (model) model.addEventListener("change", () => {
    const src = $("#providerPick"); src.value = model.value; src.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const mic = $("#micBtn");
  if (mic) mic.addEventListener("click", () => dictate(mic));
  if (approvalNow == null) loadApproval(); else syncComposerChips();
}
let recog = null;
function dictate(btn) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { ctx.toast("Voice typing is not available here. On Windows, press Win+H to dictate.", "warn"); return; }
  if (recog) { recog.stop(); return; }
  const ta = $("#composerInput");
  const start = ta.value;
  recog = new SR();
  recog.interimResults = true; recog.continuous = false; recog.lang = navigator.language || "en-GB";
  btn.classList.add("listening"); btn.setAttribute("aria-pressed", "true");
  recog.onresult = (e) => {
    const said = [...e.results].map((r) => r[0].transcript).join("");
    ta.value = (start ? start.replace(/\s*$/, " ") : "") + said;
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  };
  recog.onerror = (e) => { if (e.error !== "aborted") ctx.toast(`Voice typing stopped: ${e.error}`, "warn"); };
  recog.onend = () => { recog = null; btn.classList.remove("listening"); btn.setAttribute("aria-pressed", "false"); ta.focus(); };
  recog.start();
}

// ---------------------------------------------------------------- message actions
export function speak(text, btn) {
  if (!window.speechSynthesis) { ctx.toast("Read aloud is not available here.", "warn"); return; }
  if (speechSynthesis.speaking) { speechSynthesis.cancel(); $$(".msg-actions [aria-pressed='true']").forEach((b) => b.setAttribute("aria-pressed", "false")); if (btn?.dataset.speaking) { delete btn.dataset.speaking; return; } }
  const u = new SpeechSynthesisUtterance(String(text || "").replace(/[#*_`>|]/g, " ").slice(0, 8000));
  btn?.setAttribute("aria-pressed", "true"); if (btn) btn.dataset.speaking = "1";
  u.onend = u.onerror = () => { btn?.setAttribute("aria-pressed", "false"); if (btn) delete btn.dataset.speaking; };
  speechSynthesis.speak(u);
}
export function moreMenu(btn, items) {
  let panel = btn.parentElement.querySelector(".am-dd");
  if (!panel) { panel = document.createElement("div"); panel.className = "am-dd"; panel.setAttribute("role", "menu"); panel.hidden = true; btn.parentElement.appendChild(panel); wireDDKeys(panel); }
  panel.innerHTML = items.map((it, i) => `<button type="button" role="menuitem" data-i="${i}">${icon(it.icon)}${esc(it.label)}</button>`).join("");
  panel.onclick = (e) => { const b = e.target.closest("[data-i]"); if (!b) return; closeDD(true); items[Number(b.dataset.i)].run(); };
  showDD(btn, panel);
}

// ---------------------------------------------------------------- keyboard
function wireKeys() {
  document.addEventListener("keydown", (e) => {
    if (!$("#palette")?.hidden || !$("#modal")?.hidden) return;
    const mod = e.ctrlKey || e.metaKey;
    const k = e.key;
    if (mod && !e.shiftKey && k === ".") { e.preventDefault(); togglePanel(); return; }
    if (mod && (k === "=" || k === "+")) { e.preventDefault(); zoom(0.1); return; }
    if (mod && k === "-") { e.preventDefault(); zoom(-0.1); return; }
    if (mod && k === "0") { e.preventDefault(); zoom(0); return; }
    if (mod && k === ",") { e.preventDefault(); location.hash = "#/settings"; return; }
    if (mod && !e.shiftKey && k.toLowerCase() === "o") { e.preventDefault(); openFilePicker(); return; }
    if (mod && e.shiftKey && k.toLowerCase() === "f") { e.preventDefault(); runAction("find"); return; }
    if (e.altKey && !mod && k === "ArrowLeft") { e.preventDefault(); history.back(); return; }
    if (e.altKey && !mod && k === "ArrowRight") { e.preventDefault(); history.forward(); }
  });
}

// macOS shows Command / Option shortcuts; the key handler already accepts Cmd as Ctrl.
function macLabels(root) {
  if (!root) return;
  const mac = (t) => t.replace(/Ctrl\+/g, "\u2318").replace(/Alt\+/g, "\u2325").replace(/Shift\+/g, "\u21e7");
  $$(".k", root).forEach((el) => { el.textContent = mac(el.textContent); });
  $$("[title]", root).forEach((el) => { el.title = mac(el.title); });
  const quit = $('[data-do="quit"]', root);
  if (quit && quit.firstChild) quit.firstChild.textContent = "Quit ";
}

// ---------------------------------------------------------------- init
export function initShell(context) {
  ctx = context;
  const letter = (ctx.BRAND_SHORT || ctx.BRAND || "").trim().charAt(0).toUpperCase();
  $$(".am-chrome-app .am-mark, .rail-mark, .side-head .logo").forEach((el) => { el.textContent = letter; });
  const z = store.get("automoto.zoom", 1);
  if (z && z !== 1) setZoom(z);
  wireMenubar(); wireRail(); wireConvMenu(); wirePanel(); wireKeys();
  if (document.documentElement.dataset.os === "mac") macLabels($("#amChrome"));
  const brandBtn = $("#brandPick"), brandMenu = $("#brandMenu");
  if (brandBtn && brandMenu) {
    wireDDKeys(brandMenu);
    brandBtn.addEventListener("click", () => {
      $("#brandSwitch").hidden = !!$("#switchLocation")?.hidden;
      showDD(brandBtn, brandMenu);
    });
    brandMenu.addEventListener("click", (e) => { if (e.target.closest("a")) closeDD(); });
  }
  $("#sideNew")?.addEventListener("click", () => ctx.newChat());
  $("#sideSearch")?.addEventListener("click", () => runAction("find"));
  $("#navBack")?.addEventListener("click", () => history.back());
  $("#navForward")?.addEventListener("click", () => history.forward());
  $("#chromeSide")?.addEventListener("click", () => ctx.toggleSidebar());
  setAvatar("");
  hydrateIcons(document);
}
