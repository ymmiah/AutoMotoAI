// Launches a real VS Code (downloaded by @vscode/test-electron) with this extension and runs suite.ts.
import * as path from "path";
import { runTests } from "@vscode/test-electron";

async function main(): Promise<void> {
  const root = path.resolve(__dirname, "../../..");
  await runTests({
    extensionDevelopmentPath: root,
    extensionTestsPath: path.resolve(__dirname, "suite"),
    launchArgs: ["--disable-extensions", "--disable-gpu", "--no-sandbox", root],
  });
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
