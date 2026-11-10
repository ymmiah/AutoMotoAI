// Full-screen step shown until a temporary password is replaced.
const $ = (s) => document.querySelector(s);
const csrf = document.querySelector('meta[name="automoto-csrf"]')?.content || "";

function showError(message) {
  const err = $("#authErr");
  err.textContent = message;
  err.hidden = !message;
}

$("#pwForm").onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const neu = f.get("password") || "";
  if (neu !== (f.get("again") || "")) {
    showError("The two new passwords don't match.");
    return;
  }
  const btn = $("#authBtn");
  btn.disabled = true;
  try {
    const r = await fetch("/api/auth/password", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify({ current: f.get("current") || "", new: neu }),
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

$("#signOut").onclick = async () => {
  await fetch("/api/auth/logout", {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: "{}",
  }).catch(() => {});
  location.replace("/");
};
