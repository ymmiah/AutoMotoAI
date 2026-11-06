// The app's own sign-in screen. It talks only to the app (Tauri commands), never to the network:
// the Rust side does the HTTPS calls, keeps the device key in the OS credential store and opens the
// AutoMoto page in this window.
const invoke = (cmd, args) => window.__TAURI__.core.invoke(cmd, args);
const $ = (s) => document.querySelector(s);
const params = new URLSearchParams(location.search);

function busy(text) {
  $("#busy").hidden = !text;
  $("#busyText").textContent = text || "";
  document.querySelectorAll("button:not([data-chrome])").forEach((b) => { b.disabled = !!text; });
}
function note(text, ok = false) {
  const n = $("#note");
  n.hidden = !text;
  n.textContent = text || "";
  n.className = "note" + (ok ? " ok" : "");
}
function errText(e) { return typeof e === "string" ? e : (e && e.message) || String(e); }

let info = null;
let refreshing = false;
let installing = false;

// Recheck after the external installer finishes without overwriting a sign-in draft.
async function refreshInfo() {
  if (refreshing || !$("#busy").hidden) return;
  refreshing = true;
  $("#refreshBtn").disabled = true;
  try { info = await invoke("app_info"); draw(false); }
  catch (e) { note(errText(e)); }
  finally { refreshing = false; $("#refreshBtn").disabled = false; }
}

function draw(fillForm = true) {
  const platform = info.windows ? "Windows" : info.mac ? "macOS" : "Linux";
  $("#ver").textContent = `${platform} app ${info.version} ${info.channel || ""}`.trim();
  $("#chan").hidden = !info.channel;
  if (fillForm) {
    $("#server").value = info.server || "";
    $("#username").value = info.username || "";
    $("#device").value = info.device_name || "";
  }
  const signed = info.signed_in && info.server;
  $("#signedIn").hidden = !signed;
  $("#signForm").hidden = !!signed;
  if (signed) { $("#siUser").textContent = info.username || "you"; $("#siServer").textContent = info.server; }
  const e = info.engine;
  $("#engineState").className = "small " + (e || info.engine_running ? "ok-dot" : "no-dot");
  const old = !!(e && e.outdated);
  $("#engineState").textContent = old
    ? `Engine ${e.version} found, but this app uses ${e.wanted}. Update it to get Offline AI and the latest fixes.`
    : info.engine_running ? "An AutoMoto engine is already running on this PC."
    : e ? `Engine found (${e.how}${e.version ? ", " + e.version : ""}).` : "The local engine is not installed yet.";
  const missing = !e && !info.engine_running;
  $("#installBtn").hidden = !(missing || old) || !info.windows;
  $("#installBtn").textContent = old ? "Update the local engine" : "Install the local engine";
  $("#installHelp").hidden = !(missing || old);
  if (!info.windows) {
    $("#cmd").textContent = "bash scripts/install.sh";
    $("#cmdHint").textContent = "Run the installer in a terminal (from the AutoMotoAI folder):";
    $("#store").textContent = info.mac ? "the macOS Keychain" : "your login keyring";
  }
}

async function openAccount() {
  busy("Opening your AutoMoto account…");
  try {
    const r = await invoke("open_account");
    if (r && r.signed_out) { busy(""); info.signed_in = false; draw(); note(r.message || "This device was signed out - sign in again."); $("#password").focus(); }
  } catch (e) { busy(""); note(errText(e)); }
}

async function startLocal() {
  busy("Starting AutoMoto on this PC… (the first start can take a minute)");
  try {
    const r = await invoke("start_local");
    if (r && r.missing) { busy(""); info.engine = null; info.engine_running = false; draw(false); note("Install the local engine first (see Work on this computer)."); }
  } catch (e) { busy(""); note(errText(e)); }
}

async function signIn(ev) {
  ev.preventDefault();
  note("");
  busy("Signing in…");
  try {
    await invoke("sign_in", { server: $("#server").value, username: $("#username").value, password: $("#password").value, deviceName: $("#device").value });
    $("#password").value = "";
    $("#password").type = "password";
    $("#showPassword").textContent = "Show";
    $("#showPassword").setAttribute("aria-pressed", "false");
    $("#showPassword").setAttribute("aria-label", "Show password");
    // Keep the launcher consistent if opening the account fails after a successful login.
    info = await invoke("app_info"); draw();
    await openAccount();
  } catch (e) { busy(""); note(errText(e)); $("#password").select(); }
}

async function main() {
  try { info = await invoke("app_info"); } catch (e) { note(errText(e)); return; }
  draw();
  $("#signIn").addEventListener("submit", signIn);
  $("#openBtn").addEventListener("click", openAccount);
  $("#outBtn").addEventListener("click", async () => {
    busy("Signing out…");
    try {
      const result = await invoke("sign_out");
      busy(""); info.signed_in = false; draw();
      note(result.revoked
        ? "Signed out. The device token was cancelled on the server."
        : "Signed out locally, but the server could not confirm revocation. Open Account → My devices once connected to revoke this device.", result.revoked);
    } catch (e) { busy(""); note(errText(e)); }
  });
  $("#localBtn").addEventListener("click", startLocal);
  $("#refreshBtn").addEventListener("click", refreshInfo);
  window.addEventListener("focus", () => { if (installing) refreshInfo(); });
  $("#showPassword").addEventListener("click", () => {
    const show = $("#password").type === "password";
    $("#password").type = show ? "text" : "password";
    $("#showPassword").textContent = show ? "Hide" : "Show";
    $("#showPassword").setAttribute("aria-label", show ? "Hide password" : "Show password");
    $("#showPassword").setAttribute("aria-pressed", String(show));
  });
  $("#installBtn").addEventListener("click", async () => {
    busy("Opening the engine installer…");
    try { await invoke("install_engine"); installing = true; note(info.engine && info.engine.outdated
      ? "PowerShell opened to update the engine. When it says it is done, click Start local mode."
      : "PowerShell opened with the installer. Answer its questions; when it says it is done, click Start local mode.", true); }
    catch (e) { note(errText(e)); }
    finally { busy(""); }
  });
  document.querySelectorAll("[data-link]").forEach((a) => a.addEventListener("click", (ev) => { ev.preventDefault(); invoke("open_link", { which: a.dataset.link }).catch((e) => note(errText(e))); }));
  if (params.get("note") === "signed-out") note("Signed out of this device.", true);
  if (params.get("note") === "revocation-unconfirmed") note("Signed out locally. Server revocation could not be confirmed; revoke this device in Account → My devices when connected.");
  // open what was used last time, unless the user came back here on purpose
  if (params.get("auto") === "local") return startLocal();
  if (params.get("home") === "1") return;
  if (info.mode === "account" && info.signed_in) return openAccount();
  // an outdated engine stays on this screen once, so the Update button is seen
  if (info.mode === "local" && (info.engine || info.engine_running) && !(info.engine && info.engine.outdated)) return startLocal();
  (info.server ? $("#username") : $("#server")).focus();
}

main();
