// First-admin / password-reset page. The setup code is never on this page; it is in the server log.
const $ = (s) => document.querySelector(s);
let mode = "create";

function showError(message) {
  const err = $("#authErr");
  err.textContent = message;
  err.hidden = !message;
}

async function load() {
  let info = { available: false, reason: "Could not reach the server." };
  try {
    info = await (await fetch("/api/setup/info", { credentials: "same-origin" })).json();
  } catch { /* keep the fallback */ }
  if (!info.available) {
    $("#setupForm").hidden = true;
    $("#authClosed").hidden = false;
    $("#authClosed").textContent = info.reason || "Setup is not available.";
    $("#authTitle").textContent = "Setup is closed";
    $("#authLead").textContent = "If you already created an admin, sign in. If the code expired, restart the server and copy the new code from the logs.";
    return;
  }
  mode = info.mode === "reset" ? "reset" : "create";
  const min = info.min_password || 12;
  $("#pwHint").textContent = mode === "reset"
    ? `At least ${min} characters. This password is temporary: after you sign in, choose a different one.`
    : `At least ${min} characters, not a common password, and not containing your username.`;
  if (mode === "reset") {
    $("#authTitle").textContent = "Reset the admin password";
    $("#authLead").textContent = "Copy the reset code from the server logs (AUTOMOTO_ADMIN_RESET=1). It works once.";
    $("#authBtn").textContent = "Reset password";
    if (info.username) {
      const user = $('[name="username"]');
      user.value = info.username;
      user.readOnly = true;
    }
  }
}

$("#setupForm").onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const password = f.get("password") || "";
  if (password !== (f.get("again") || "")) {
    showError("The two passwords don't match.");
    return;
  }
  const btn = $("#authBtn");
  btn.disabled = true;
  try {
    const r = await fetch("/api/setup", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code: (f.get("code") || "").trim(),
        username: (f.get("username") || "").trim(),
        password,
      }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : (d.detail?.[0]?.msg || r.statusText));
    location.replace("/");
  } catch (err) {
    showError(err.message);
  } finally {
    btn.disabled = false;
  }
};

load();
