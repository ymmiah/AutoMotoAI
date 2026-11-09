// Build-time Monaco entry point. All runtime imports are bundled and served locally.
// Monaco 0.57+ uses new package exports; import the documented main entry.
import * as monaco from "monaco-editor";

const root = "/static/vendor/monaco/";
self.MonacoEnvironment = {
  getWorker(_workerId, label) {
    let entry = "editor.worker.js";
    if (label === "typescript" || label === "javascript") entry = "ts.worker.js";
    else if (label === "json") entry = "json.worker.js";
    else if (["css", "scss", "less"].includes(label)) entry = "css.worker.js";
    else if (["html", "handlebars", "razor"].includes(label)) entry = "html.worker.js";
    return new Worker(root + entry, { type: "module", name: "automoto-" + label });
  }
};
export { monaco };
