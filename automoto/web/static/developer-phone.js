/* Phone control: the person turns it on with a button the assistant cannot press. */
export function mountDeveloperPhone({api, host}) {
  const BASE = "/api/developer/studio/phone";
  const root = host.querySelector("#dsPhoneRoot");
  const token = document.querySelector('meta[name="automoto-token"]')?.content || "";
  const csrf = document.querySelector('meta[name="automoto-csrf"]')?.content || "";
  const headers = {...(token ? {"X-AutoMoto-Token": token} : {}), ...(csrf ? {"X-CSRF-Token": csrf} : {})};
  root.innerHTML =
    '<section class="phone-panel" aria-labelledby="phoneTitle">' +
      '<div class="phone-head"><h3 id="phoneTitle">Android phone control</h3>' +
        '<span class="phone-badge" id="phoneBadge">Off</span></div>' +
      '<p class="phone-note">The assistant reads the screen as text and can tap, type, scroll and open apps. ' +
        'Each action asks you first, and it never types into password boxes. Control turns itself off after 30 minutes.</p>' +
      '<ol class="phone-steps" id="phoneSteps"></ol>' +
      '<div class="phone-row"><label for="phoneDevice">Phone</label>' +
        '<select id="phoneDevice" class="input"></select>' +
        '<button class="btn" type="button" id="phoneRefresh">Refresh</button></div>' +
      '<label class="phone-check" id="phoneConsent"><input id="phoneOk" type="checkbox"> I understand the assistant can see this phone\'s screen, ' +
        'including messages and notifications, while control is on.</label>' +
      '<div class="phone-row"><button class="btn primary" type="button" id="phoneOn" disabled>Turn on phone control</button>' +
        '<button class="btn" type="button" id="phoneOff" hidden>Stop phone control</button>' +
        '<button class="btn" type="button" id="phoneShot" hidden>Show the screen</button></div>' +
      '<img class="phone-shot" id="phoneImg" alt="Current phone screen" hidden>' +
      '<p class="phone-status" id="phoneStatus" role="status" aria-live="polite"></p>' +
    '</section>';
  const byId = (id) => root.querySelector("#" + id);
  let devices = [], on = false, shotUrl = "";

  function say(message, bad) {
    byId("phoneStatus").textContent = message || "";
    byId("phoneStatus").classList.toggle("bad", !!bad);
  }

  function ready() {
    const device = devices.find((d) => d.serial === byId("phoneDevice").value);
    byId("phoneOn").disabled = on || !byId("phoneOk").checked || device?.state !== "device";
  }

  function draw(data) {
    devices = data.devices || [];
    on = !!data.control?.on;
    const steps = byId("phoneSteps");
    steps.replaceChildren(...(data.steps || []).map((text) => Object.assign(document.createElement("li"), {textContent: text})));
    steps.hidden = on;
    const select = byId("phoneDevice");
    select.replaceChildren(...devices.map((d) => {
      const label = (d.model || d.serial) + (d.state === "device" ? "" : d.state === "unauthorized" ? " (tap Allow on the phone)" : " (" + d.state + ")");
      return Object.assign(document.createElement("option"), {value: d.serial, textContent: label});
    }));
    if (!devices.length) select.appendChild(Object.assign(document.createElement("option"), {value: "", textContent: "No phone found"}));
    if (on) select.value = data.control.serial;
    select.disabled = on;
    byId("phoneBadge").textContent = on ? "On · " + data.control.minutes_left + " min left" : "Off";
    byId("phoneBadge").classList.toggle("live", on);
    byId("phoneConsent").hidden = on;
    byId("phoneOn").hidden = on;
    byId("phoneOff").hidden = !on;
    byId("phoneShot").hidden = !on;
    if (!on) hideShot();
    ready();
    if (!data.adb) say("adb is not installed. Install Android SDK Platform-Tools, then press Refresh.", true);
    else if (on) say("Phone control is on for " + (data.control.model || data.control.serial) + ". Ask the assistant in chat.");
    else say(devices.length ? "Pick the phone, tick the box and turn control on." : "Plug in the phone and press Refresh.");
  }

  function hideShot() {
    if (shotUrl) URL.revokeObjectURL(shotUrl);
    shotUrl = "";
    byId("phoneImg").hidden = true;
  }

  async function refresh() {
    try { draw(await api(BASE + "/status")); } catch (error) { say(error.message || "The phone status could not be loaded.", true); }
  }

  byId("phoneOk").addEventListener("change", ready);
  byId("phoneDevice").addEventListener("change", ready);
  byId("phoneRefresh").addEventListener("click", refresh);

  byId("phoneOn").addEventListener("click", async () => {
    if (!byId("phoneOk").checked) return say("Tick the box first.", true);
    byId("phoneOn").disabled = true;
    try {
      const response = await fetch(BASE + "/connect", {
        method: "POST", credentials: "same-origin",
        headers: {...headers, "Content-Type": "application/json", "X-Automoto-Phone-Approval": "1"},
        body: JSON.stringify({serial: byId("phoneDevice").value, confirmed: true, understood_screen_access: true}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Phone control stayed off.");
      byId("phoneOk").checked = false;
      await refresh();
    } catch (error) {
      say(error.message, true);
      ready();
    }
  });

  byId("phoneOff").addEventListener("click", async () => {
    try { await api(BASE + "/disconnect", {}); } catch (error) { say(error.message, true); }
    await refresh();
  });

  byId("phoneShot").addEventListener("click", async () => {
    try {
      const response = await fetch(BASE + "/screenshot", {credentials: "same-origin", headers});
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "No picture came back.");
      hideShot();
      shotUrl = URL.createObjectURL(await response.blob());
      byId("phoneImg").src = shotUrl;
      byId("phoneImg").hidden = false;
    } catch (error) {
      say(typeof error.message === "string" ? error.message : "No picture came back.", true);
      if (/off/i.test(error.message || "")) refresh();
    }
  });

  refresh();
  return {refresh};
}
