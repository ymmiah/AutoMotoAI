/* One shared, accessible copy button for the whole app.

   - Every <pre> (code, commands, logs, diffs, outputs) gets an always-visible copy button in its
     top-right corner. It stays in place while the box scrolls.
   - Any element with data-copy (file paths, commands, URLs, values) gets a small copy button after it.
     data-copy="text" copies that text; an empty data-copy copies the element's own text.
   - Never on secrets: nothing inside [data-sensitive], [data-no-copy], form fields or editable areas,
     and the button hides itself when the text looks like a token or private key.
   - Keyboard and screen readers: a real <button> with a label; the result ("Copied" or how to copy by
     hand) is announced through one polite live region and shown next to the button. */
import { icon } from "./icons.js";

const SECRET_RE = new RegExp([
  "\\bgh[pousr]_[A-Za-z0-9]{20,}", "\\bgithub_pat_[A-Za-z0-9_]{20,}", "\\bgl(?:pat|oas|dt|rt|cbt|ptt|ft)-[A-Za-z0-9_-]{16,}",
  "\\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}", "\\b[rs]k_live_[A-Za-z0-9]{16,}", "\\bxox[abposr]-[A-Za-z0-9-]{10,}",
  "\\b(?:AKIA|ASIA)[0-9A-Z]{16}\\b", "\\bAIza[0-9A-Za-z_-]{30,}", "\\bhf_[A-Za-z0-9]{30,}", "\\bnpm_[A-Za-z0-9]{36}\\b",
  "-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----",
].join("|"));
const SKIP = "[data-sensitive],[data-no-copy],input,textarea,select,[contenteditable=''],[contenteditable='true'],div.code";
const FLASH_MS = 1500;

/** True when the text looks like it holds a secret (token, API key or private key). */
export function looksSecret(text) { return SECRET_RE.test(String(text || "")); }

/** Text to put on the clipboard: exact text, trailing newline dropped, "$ " prompts dropped when asked. */
export function copyableText(text, { prompt = false } = {}) {
  let t = String(text ?? "").replace(/\r\n?/g, "\n").replace(/\n+$/, "");
  if (prompt) t = t.split("\n").map((l) => l.replace(/^\s*(?:\$|>|PS [^>]*>)\s?/, "")).join("\n");
  return t;
}

let live = null;
/** Say something to screen readers without moving focus. */
export function announce(message) {
  if (!document.body) return;
  if (!live || !live.isConnected) {
    live = document.createElement("div");
    live.id = "copyLive"; live.className = "sr"; live.setAttribute("aria-live", "polite"); live.setAttribute("role", "status");
    document.body.append(live);
  }
  live.textContent = "";
  setTimeout(() => { live.textContent = message; }, 30);
}

/** Put text on the clipboard. Resolves true on success. */
export async function copyText(text) {
  const value = String(text ?? "");
  try { await navigator.clipboard.writeText(value); return true; } catch { /* fall back below */ }
  try {
    const ta = document.createElement("textarea");
    ta.value = value; ta.setAttribute("readonly", ""); ta.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0";
    const prev = document.activeElement;
    document.body.append(ta); ta.select();
    const ok = document.execCommand("copy");
    ta.remove(); prev?.focus?.({ preventScroll: true });
    return !!ok;
  } catch { return false; }
}

/** Show the "Copied" state on a button for a moment and announce the result. */
export function flash(btn, ok) {
  if (!btn) { announce(ok ? "Copied" : "Couldn't copy. Select the text and press Ctrl+C."); return; }
  clearTimeout(btn._copyTimer);
  // Icon buttons swap to a tick; buttons with words say "Copied" for a moment instead.
  const words = btn.textContent.trim();
  if (btn._copyIcon == null) btn._copyIcon = btn.innerHTML;
  if (words && !btn.classList.contains("copy-btn")) btn.textContent = ok ? "Copied" : "Couldn't copy";
  else btn.innerHTML = icon(ok ? "check" : "alert");
  btn.classList.toggle("copied", ok); btn.classList.toggle("copy-failed", !ok);
  btn.dataset.copyState = ok ? "copied" : "failed";
  announce(ok ? "Copied" : "Couldn't copy. Select the text and press Ctrl+C.");
  btn._copyTimer = setTimeout(() => {
    btn.innerHTML = btn._copyIcon; btn._copyIcon = null;
    btn.classList.remove("copied", "copy-failed"); delete btn.dataset.copyState;
  }, FLASH_MS);
}

/** A copy button. getText() is read at click time. */
export function copyButton({ getText, label = "code", cls = "", prompt = false } = {}) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = ("copy-btn " + cls).trim();
  btn.setAttribute("aria-label", "Copy " + label);
  btn.title = "Copy";
  btn.innerHTML = icon("copy");
  btn._copyReady = true;
  btn.addEventListener("click", async (e) => {
    e.preventDefault(); e.stopPropagation();
    const text = copyableText(getText?.() ?? "", { prompt });
    if (!text.trim() || looksSecret(text)) { flash(btn, false); return; }
    flash(btn, await copyText(text));
  });
  return btn;
}

function labelFor(pre) {
  if (pre.dataset.copyLabel) return pre.dataset.copyLabel;
  const aria = pre.getAttribute("aria-label");
  if (aria) return aria.length > 60 ? "text" : aria.charAt(0).toLowerCase() + aria.slice(1);
  if (/diff/i.test(pre.className)) return "changes";
  if (/log|output|result/i.test(pre.className)) return "output";
  return "code";
}
const preText = (pre) => {
  let t = "";
  for (const n of pre.childNodes) if (!(n.nodeType === 1 && n.classList.contains("copy-anchor"))) t += n.textContent;
  return t;
};
function eligible(node) { return node.isConnected && !node.closest(SKIP); }

/** Give one <pre> its copy button (idempotent; safe to call on every change). */
export function enhancePre(pre) {
  if (!eligible(pre)) return;
  let anchor = pre.firstChild;
  // Rebuild if the anchor is missing, moved, or was re-parsed from HTML (a re-parsed button has no handler).
  if (!(anchor && anchor.nodeType === 1 && anchor.classList.contains("copy-anchor") && anchor.firstChild?._copyReady)) {
    pre.querySelectorAll(":scope > .copy-anchor").forEach((a) => a.remove());
    anchor = document.createElement("span");
    anchor.className = "copy-anchor"; anchor.setAttribute("data-copy-ui", "");
    anchor.append(copyButton({ getText: () => preText(pre), label: labelFor(pre), prompt: "prompt" in pre.dataset }));
    pre.prepend(anchor);
    pre.classList.add("has-copy");
  }
  const text = preText(pre);
  const hide = !text.trim() || looksSecret(text);
  const btn = anchor.firstChild;
  if (btn && btn.hidden !== hide) btn.hidden = hide;
}

/** Give one [data-copy] element its copy button, placed right after it. */
export function enhanceValue(node) {
  if (!eligible(node)) return;
  const getText = () => node.dataset.copy || node.textContent;
  let btn = node.nextElementSibling;
  if (!(btn && btn.classList.contains("copy-inline") && btn._copyFor === node)) {
    btn = copyButton({ getText, label: node.dataset.copyLabel || "text", cls: "copy-inline", prompt: "prompt" in node.dataset });
    btn._copyFor = node; btn.setAttribute("data-copy-ui", "");
    node.after(btn);
  }
  const hide = !String(getText() || "").trim() || looksSecret(getText());
  if (btn.hidden !== hide) btn.hidden = hide;
}

/** Enhance everything under root once. */
export function enhanceCopyable(root = document.body) {
  if (!root || root.nodeType !== 1) return;
  if (root.matches?.("pre")) enhancePre(root);
  if (root.matches?.("[data-copy]")) enhanceValue(root);
  root.querySelectorAll("pre").forEach(enhancePre);
  root.querySelectorAll("[data-copy]").forEach(enhanceValue);
}

/** Watch the page so content added later (chat, logs, studio outputs) gets copy buttons too. */
export function installCopyButtons(root = document.body) {
  if (!root || root._copyObserver) return root?._copyObserver;
  enhanceCopyable(root);
  const pending = new Set();
  let queued = false;
  const flush = () => {
    queued = false;
    const items = [...pending]; pending.clear();
    for (const n of items) if (n.isConnected) enhanceCopyable(n);
  };
  const obs = new MutationObserver((records) => {
    for (const r of records) {
      const t = r.target.nodeType === 1 ? r.target : r.target.parentElement;
      if (!t || t.closest?.("[data-copy-ui]")) continue;
      const pre = t.closest?.("pre");
      if (pre) pending.add(pre);
      if (r.type === "attributes") { pending.add(t); continue; }
      for (const n of r.addedNodes) if (n.nodeType === 1 && !n.hasAttribute("data-copy-ui")) pending.add(n);
    }
    if (pending.size && !queued) { queued = true; requestAnimationFrame(flush); }
  });
  obs.observe(root, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["data-copy", "data-sensitive"] });
  root._copyObserver = obs;
  return obs;
}
