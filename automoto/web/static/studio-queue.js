/* Studio task queue. Lives for the whole page, so switching studios does not cancel work. */
const STUDIOS = ["documents", "research", "spreadsheets", "visual", "developer"];
const runners = new Map();
const aborts = new Map();
let client = null;
let pumping = false;

function $(sel, root = document) { return root.querySelector(sel); }

async function reload() {
  const data = await client.api("/api/studio-queue");
  draw(data.jobs || []);
  return data.jobs || [];
}

function draw(jobs) {
  const box = $("#studioQueue");
  if (!box) return;
  const live = jobs.filter((job) => job.status !== "done" && job.status !== "cancelled");
  const recent = jobs.filter((job) => job.status === "done" || job.status === "cancelled").slice(-3);
  const rows = [...live, ...recent];
  box.hidden = rows.length === 0;
  if (!rows.length) { box.innerHTML = ""; return; }
  box.innerHTML = `<div class="sq-head"><b>Studio tasks</b><span class="muted small">A new task waits, then starts on its own. Switching studios does not stop the one that is running.</span></div>` +
    rows.map((job) => `<div class="sq-row" data-sq="${client.esc(job.id)}" data-status="${client.esc(job.status)}">
      <span class="pill ${job.status === "running" ? "running" : job.status === "done" ? "done" : job.status === "cancelled" ? "off" : ""}">${client.esc(job.status)}</span>
      <span class="grow"><b>${client.esc(job.title)}</b><span class="muted small"> ${client.esc(job.studio)} · ${client.esc(job.progress || "")}</span></span>
      ${job.status === "queued" ? `<button type="button" class="icon-btn sm" data-sq-up="${client.esc(job.id)}" aria-label="Move earlier">↑</button><button type="button" class="icon-btn sm" data-sq-down="${client.esc(job.id)}" aria-label="Move later">↓</button>` : ""}
      ${job.status === "queued" || job.status === "running" ? `<button type="button" class="btn sm" data-sq-cancel="${client.esc(job.id)}">Cancel</button>` : ""}
    </div>`).join("");
}

async function pump() {
  if (pumping) return;
  pumping = true;
  try {
    for (;;) {
      const jobs = await reload();
      const running = jobs.find((job) => job.status === "running" && runners.has(job.id) && !aborts.has(job.id));
      if (!running) break;
      await runJob(running.id);
    }
  } finally {
    pumping = false;
  }
}

async function runJob(id) {
  const run = runners.get(id);
  if (!run || aborts.has(id)) return;
  const ctrl = new AbortController();
  aborts.set(id, ctrl);
  try {
    await run({
      id,
      signal: ctrl.signal,
      update: async (text) => {
        try { await client.api("/api/studio-queue/progress", { id, progress: text }); } catch { /* the panel still shows the last line */ }
        const jobs = await reload().catch(() => []);
        return jobs;
      },
    });
    if (ctrl.signal.aborted) return;
    await client.api("/api/studio-queue/finish", { id, ok: true, progress: "Done" });
    client.toast("Studio task finished");
  } catch (err) {
    if (!ctrl.signal.aborted) {
      try { await client.api("/api/studio-queue/finish", { id, ok: false, progress: err.message || "Stopped" }); } catch { /* already finished */ }
      client.toast(err.message || "Studio task stopped", "bad");
    }
  } finally {
    aborts.delete(id);
    runners.delete(id);
  }
}

export function bindStudioQueue(opts) {
  client = opts;
  const box = $("#studioQueue");
  if (!box || box.dataset.bound) return;
  box.dataset.bound = "1";
  box.addEventListener("click", async (event) => {
    const up = event.target.closest("[data-sq-up]");
    const down = event.target.closest("[data-sq-down]");
    const cancel = event.target.closest("[data-sq-cancel]");
    try {
      if (up) await client.api("/api/studio-queue/reorder", { id: up.dataset.sqUp, direction: "up" });
      else if (down) await client.api("/api/studio-queue/reorder", { id: down.dataset.sqDown, direction: "down" });
      else if (cancel) {
        const id = cancel.dataset.sqCancel;
        aborts.get(id)?.abort();
        await client.api("/api/studio-queue/cancel", { id });
        runners.delete(id);
      } else return;
      await reload();
      void pump();
    } catch (err) { client.toast(err.message, "bad"); }
  });
  reload().catch(() => {});
}

export async function enqueueStudioTask({ studio, title, run }) {
  if (!client) throw new Error("Studio queue is not ready.");
  if (!STUDIOS.includes(studio)) throw new Error("Unknown studio.");
  const job = await client.api("/api/studio-queue", { studio, title });
  if (typeof run === "function") runners.set(job.id, run);
  // Paint before starting work. A pump that is already inside the running task
  // would otherwise hide this row until that task finished.
  await reload();
  void pump();
  return job;
}

export function attachStudioDrop(host) {
  if (!host || host.querySelector(".studio-drop")) return;
  const zone = document.createElement("div");
  zone.className = "studio-drop";
  zone.innerHTML = "<strong>Drop files here</strong><span>They stay on this computer. You can keep using this studio while a task runs.</span>";
  const lead = host.querySelector(".lead");
  (lead || host).insertAdjacentElement("afterend", zone);
  const take = (files) => {
    const input = host.querySelector("input[type=file]");
    if (!input || typeof DataTransfer === "undefined") return;
    const bag = new DataTransfer();
    for (const file of files) bag.items.add(file);
    input.files = bag.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  };
  zone.addEventListener("dragover", (event) => { event.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    zone.classList.remove("over");
    if (event.dataTransfer?.files?.length) take([...event.dataTransfer.files]);
  });
}

if (typeof window !== "undefined") {
  window.automotoQueue = { enqueue: enqueueStudioTask };
}
