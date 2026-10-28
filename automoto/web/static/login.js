// Hosted-mode sign-in / sign-up page (no inline scripts: the CSP forbids them).
const $ = (s) => document.querySelector(s);
let mode = "in", info = { signup: "invite", min_password: 10 };

function setMode(m) {
  mode = m;
  $("#tabIn").setAttribute("aria-selected", m === "in");
  $("#tabUp").setAttribute("aria-selected", m === "up");
  $("#authTitle").textContent = m === "in" ? "Sign in" : "Create account";
  $("#authBtn").textContent = m === "in" ? "Sign in" : "Create account";
  $("#inviteRow").hidden = !(m === "up" && info.signup === "invite");
  $("#pwHint").hidden = m !== "up";
  $("#pwHint").textContent = `At least ${info.min_password} characters, not containing your username.`;
  $('[name="password"]').autocomplete = m === "in" ? "current-password" : "new-password";
  $("#authErr").hidden = true;
}

async function load() {
  try { info = await (await fetch("/api/auth/info", { credentials: "same-origin" })).json(); } catch { /* defaults */ }
  if (info.signup === "closed") { $("#tabUp").hidden = true; $("#authLead").textContent += " New accounts are created by the admin."; }
  const inv = new URLSearchParams(location.search).get("invite");
  if (inv && info.signup !== "closed") { setMode("up"); $('[name="invite"]').value = inv; } else setMode("in");
}

$("#tabIn").onclick = () => setMode("in");
$("#tabUp").onclick = () => setMode("up");
$("#authForm").onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = { username: (f.get("username") || "").trim(), password: f.get("password") || "" };
  if (mode === "up") body.invite = (f.get("invite") || "").trim();
  const btn = $("#authBtn"); btn.disabled = true;
  try {
    const r = await fetch(mode === "in" ? "/api/auth/login" : "/api/auth/signup", {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : (d.detail?.[0]?.msg || r.statusText));
    location.replace("/");
  } catch (err) {
    $("#authErr").textContent = err.message; $("#authErr").hidden = false;
  } finally { btn.disabled = false; }
};
load();
