/* iPhone apps: plain steps, a draft page, and a button that is the only way to send it. */
export function mountDeveloperIos({api, host, getProject}) {
  const root = host.querySelector("#dsIosRoot");
  const brand = document.querySelector('meta[name="automoto-brand-short"]')?.content || "This app";
  const token = document.querySelector('meta[name="automoto-token"]')?.content || "";
  const csrf = document.querySelector('meta[name="automoto-csrf"]')?.content || "";
  root.innerHTML =
    '<section class="ios-panel">' +
      '<h3>iPhone app</h3>' +
      '<p class="ios-status" id="iosIntro"></p>' +
      '<ol id="iosSteps"></ol>' +
      '<div id="iosDraft" class="ios-draft" hidden></div>' +
      '<label><input id="iosSendOk" type="checkbox"> I have read this page, including the screenshot list. Send this app and this text to Apple.</label>' +
      '<button class="btn primary" type="button" id="iosSend" disabled>Send to Apple</button>' +
      '<p class="ios-status" id="iosStatus" role="status"></p>' +
    '</section>';
  const byId = (id) => root.querySelector("#" + id);
  let sha = "";

  function say(message, bad) {
    const node = byId("iosStatus");
    node.textContent = message || "";
    node.classList.toggle("bad", !!bad);
  }

  byId("iosSendOk").addEventListener("change", () => {
    byId("iosSend").disabled = !byId("iosSendOk").checked || !sha;
  });

  byId("iosSend").addEventListener("click", async () => {
    const project = getProject()?.project;
    if (!project || !sha || !byId("iosSendOk").checked) {
      say("Read the page and tick the box first.", true);
      return;
    }
    byId("iosSend").disabled = true;
    try {
      const headers = {
        "Content-Type": "application/json",
        "X-Automoto-Ios-Approval": "1",
        ...(token ? {"X-AutoMoto-Token": token} : {}),
        ...(csrf ? {"X-CSRF-Token": csrf} : {}),
      };
      const approved = await fetch("/api/developer/studio/ios/approve", {
        method: "POST", credentials: "same-origin", headers,
        body: JSON.stringify({
          project, confirmed: true, screenshots_acknowledged: true, listing_sha256: sha,
        }),
      });
      const approval = await approved.json().catch(() => ({}));
      if (!approved.ok) throw new Error(typeof approval.detail === "string" ? approval.detail : "Apple was not contacted.");
      const sent = await api("/api/developer/studio/ios/submit", {project, listing_sha256: sha});
      say(sent.message || (brand + " sent the approved page."));
      sha = "";
      byId("iosSendOk").checked = false;
    } catch (error) {
      say(error.message || "Apple was not contacted.", true);
      byId("iosSend").disabled = !byId("iosSendOk").checked;
    }
  });

  async function load() {
    try {
      const data = await api("/api/developer/studio/ios/wizard");
      byId("iosIntro").textContent = data.deployment?.message || "";
      const list = byId("iosSteps");
      list.replaceChildren();
      for (const step of data.steps || []) {
        const item = document.createElement("li");
        item.textContent = step.title + ". " + step.text;
        list.appendChild(item);
      }
    } catch (error) {
      say(error.message || "The iPhone steps could not be loaded.", true);
    }
  }

  async function projectChanged() {
    sha = "";
    byId("iosSendOk").checked = false;
    byId("iosSend").disabled = true;
    const project = getProject()?.project;
    const draft = byId("iosDraft");
    if (!project) {
      draft.hidden = true;
      return;
    }
    try {
      const params = new URLSearchParams({project});
      const data = await api("/api/developer/studio/ios/listing?" + params);
      sha = data.listing_sha256 || "";
      const page = data.listing || {};
      const shots = (page.screenshots || []).map((item) => item.label).join("\n");
      draft.hidden = false;
      draft.textContent = [
        page.name || "",
        page.description || "",
        "Privacy: " + (page.privacy || ""),
        shots,
      ].filter(Boolean).join("\n\n");
    } catch {
      draft.hidden = true;
      draft.textContent = "";
    }
  }

  load();
  return {projectChanged};
}
