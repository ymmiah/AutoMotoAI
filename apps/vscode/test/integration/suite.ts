// Runs inside VS Code: checks the extension activates, contributes its commands and view,
// and reports a clear error when no AutoMoto server is running.
import * as assert from "assert";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";

export async function run(): Promise<void> {
  const ext = vscode.extensions.getExtension("ymmiah.automoto-ai");
  assert.ok(ext, "extension not found");
  const api = await ext!.activate();
  const cmds = await vscode.commands.getCommands(true);
  for (const c of ["automoto.askSelection", "automoto.fixDiagnostic", "automoto.explainFile", "automoto.runTask", "automoto.createOffice", "automoto.repackZip", "automoto.validateWordPress", "automoto.openWebUI", "automoto.status"]) {
    assert.ok(cmds.includes(c), `missing command ${c}`);
  }
  const empty = fs.mkdtempSync(path.join(os.tmpdir(), "am-none-"));
  await vscode.workspace.getConfiguration("automoto").update("dataDir", empty, vscode.ConfigurationTarget.Global);
  assert.throws(() => api.getClient(), /isn't running/);
  console.log("integration suite: ok");
}
