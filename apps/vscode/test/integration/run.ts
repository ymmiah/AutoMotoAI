// Launches a real VS Code (downloaded by @vscode/test-electron) with this extension and runs suite.ts.
import * as path from "path";
import { downloadAndUnzipVSCode, runTests } from "@vscode/test-electron";

// CI runners sometimes hit slow or flaky connections to the VS Code update CDN.
// Download once with a generous timeout and our own retries, then run against that build.
async function downloadWithRetry(attempts = 5): Promise<string> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      return await downloadAndUnzipVSCode({ timeout: 120_000 });
    } catch (err) {
      lastError = err;
      console.warn(`VS Code download attempt ${attempt}/${attempts} failed: ${String(err)}`);
      if (attempt < attempts) {
        await new Promise((resolve) => setTimeout(resolve, attempt * 10_000));
      }
    }
  }
  throw lastError;
}

async function main(): Promise<void> {
  const root = path.resolve(__dirname, "../../..");
  const vscodeExecutablePath = await downloadWithRetry();
  await runTests({
    vscodeExecutablePath,
    extensionDevelopmentPath: root,
    extensionTestsPath: path.resolve(__dirname, "suite"),
    launchArgs: ["--disable-extensions", "--disable-gpu", "--no-sandbox", root],
  });
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
