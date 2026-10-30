// The app's own sign-in screen. It talks only to the app (Tauri commands), never to the network:
// the Rust side does the HTTPS calls, keeps the device key in the OS credential store and opens the
// AutoMoto page in this window.
const invoke = (cmd, args) => window.__TAURI__.core.invoke(cmd, args);
const $ = (s) => document.querySelector(s);
const params = new URLSearchParams(location.search);

function busy(text) {
  $("#busy").hidden = !text;
  $("#busyText").textContent = text || "";
  document.querySelectorAll("button").forEach((b) => { b.disabled = !!text; });
}
function note(text, ok = false) {
  const n = $("#note");
  n.hidden = !text;
  n.textContent = text || "";
  n.className = "note" + (ok ? " ok" : "");
}
function errText(e) { return typeof e === "string" ? e : (e && e.message) || String(e); }

let info = null;

function draw() {
  $("#ver").textContent = `Windows app ${info.version} ${info.channel || ""}`.trim();
  $("#chan").hidden = !info.channel;
  $("#server").value = info.server || "";
  $("#username").value = info.username || "";
  $("#device").value = info.device_name || "";
  const signed = info.signed_in && info.server;
  $("#signedIn").hidden = !signed;
  $("#signForm").hidden = !!signed;
  if (signed) { $("#siUser").textContent = info.username || "you"; $("#siServer").textContent = info.server; }
  const e = info.engine;
  $("#engineState").className = "small " + (e || info.engine_running ? "ok-dot" : "no-dot");
  $("#engineState").textContent = info.engine_running ? "An AutoMoto engine is already running on this PC."
    : e ? `Engine found (${e.how}).` : "The local engine is not installed yet.";
  const missing = !e && !info.engine_running;
  $("#installBtn").hidden = !missing || !info.windows;
  $("#installHelp").hidden = !missing;
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
    if (r && r.missing) { busy(""); info.engine = null; draw(); note("Install the local engine first (see the Local mode box)."); }
  } catch (e) { busy(""); note(errText(e)); }
}

async function signIn(ev) {
  ev.preventDefault();
  note("");
  busy("Signing in…");
  try {
    await invoke("sign_in", { server: $("#server").value, username: $("#username").value, password: $("#password").value, deviceName: $("#device").value });
    $("#password").value = "";
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
    try { await invoke("sign_out"); } catch (e) { note(errText(e)); }
    busy(""); info.signed_in = false; draw(); note("Signed out. This device's key was cancelled on the server.", true);
  });
  $("#localBtn").addEventListener("click", startLocal);
  $("#installBtn").addEventListener("click", async () => {
    try { await invoke("install_engine"); note("PowerShell opened with the installer. Answer its questions; when it says it is done, click Start local mode.", true); }
    catch (e) { note(errText(e)); }
  });
  document.querySelectorAll("[data-link]").forEach((a) => a.addEventListener("click", (ev) => { ev.preventDefault(); invoke("open_link", { which: a.dataset.link }).catch((e) => note(errText(e))); }));
  if (params.get("note") === "signed-out") note("Signed out of this device.", true);
  // open what was used last time, unless the user came back here on purpose
  if (params.get("auto") === "local") return startLocal();
  if (params.get("home") === "1") return;
  if (info.mode === "account" && info.signed_in) return openAccount();
  if (info.mode === "local" && (info.engine || info.engine_running)) return startLocal();
  (info.server ? $("#username") : $("#server")).focus();
}

main();
