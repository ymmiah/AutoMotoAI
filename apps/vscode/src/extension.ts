// AutoMoto AI for VS Code: a thin client for the local `python -m automoto serve` agent.
// The agent runs in AutoMoto (with its sandbox, approvals and secret-path blocklist);
// this extension sends prompts, shows tool steps, and asks you about every risky step.
import * as path from "path";
import * as vscode from "vscode";
import { AgentEvent, ApiError, AutoMotoClient, summariseArgs } from "./client";
import { ChatViewProvider } from "./chatView";
import { askSelectionPrompt, explainFilePrompt, fixDiagnosticPrompt } from "./prompts";
import { readSession, SessionError } from "./session";

let output: vscode.OutputChannel;
let chat: ChatViewProvider;
let running: { cancelled: boolean } | undefined;

function cfg() {
  const c = vscode.workspace.getConfiguration("automoto");
  return {
    serverUrl: c.get<string>("serverUrl", ""),
    dataDir: c.get<string>("dataDir", ""),
    provider: c.get<string>("provider", "auto"),
    maxSteps: c.get<number>("maxSteps", 12),
  };
}

export function getClient(): AutoMotoClient {
  const c = cfg();
  return new AutoMotoClient(readSession({ dataDir: c.dataDir, serverUrl: c.serverUrl }));
}

function folderFor(uri?: vscode.Uri): vscode.WorkspaceFolder | undefined {
  if (uri) return vscode.workspace.getWorkspaceFolder(uri);
  return vscode.workspace.workspaceFolders?.[0];
}

function relPath(uri: vscode.Uri): string {
  const f = folderFor(uri);
  return f ? path.relative(f.uri.fsPath, uri.fsPath).split(path.sep).join("/") : path.basename(uri.fsPath);
}

/** Make sure the agent may use ``folder`` (added to AutoMoto's allowed roots after you agree). */
async function ensureAllowed(client: AutoMotoClient, folder: string): Promise<boolean> {
  if (!vscode.workspace.isTrusted) {
    vscode.window.showWarningMessage("AutoMoto: trust this workspace first (agent tasks can run commands in it).");
    return false;
  }
  const info = await client.info();
  const roots: string[] = info.extra_roots || [];
  const norm = (p: string) => path.resolve(p).toLowerCase();
  if (roots.some((r) => norm(folder) === norm(r) || norm(folder).startsWith(norm(r) + path.sep))) return true;
  const pick = await vscode.window.showWarningMessage(
    `Let AutoMoto work in "${folder}"?`,
    { modal: true, detail: "The folder is added to AutoMoto's allowed folders (Settings → Files). Every write, edit and command there still asks you first, and secrets like .env files and keys stay blocked." },
    "Allow this folder",
  );
  if (pick !== "Allow this folder") return false;
  await client.addAllowedRoot(folder);
  return true;
}

async function approve(ev: AgentEvent): Promise<boolean> {
  const detail = `${ev.reason || "risky step"}\n\n${ev.name}(${summariseArgs(ev.args, 600)})`;
  const pick = await vscode.window.showWarningMessage(`AutoMoto wants to: ${ev.label || ev.name}`, { modal: true, detail }, "Allow", "Deny");
  return pick === "Allow";
}

function describe(ev: AgentEvent): string | undefined {
  switch (ev.type) {
    case "plan":
      return ev.summary ? `✦ ${ev.summary}` : undefined;
    case "tool_call":
      return `▸ ${ev.label || ev.name} ${summariseArgs(ev.args)}`;
    case "approval":
      return ev.approved ? "  ✓ allowed" : "  ✗ denied";
    case "tool_result":
      return `  ${ev.ok ? "✓" : "✗"} ${String(ev.output ?? ev.error ?? "").split("\n")[0].slice(0, 160)}`;
    case "error":
      return `  ! ${ev.error}`;
    default:
      return undefined;
  }
}

export async function runPrompt(prompt: string, opts: { workspaceUri?: vscode.Uri; title?: string } = {}): Promise<void> {
  if (running) {
    vscode.window.showInformationMessage("AutoMoto is already working on something - stop it first.");
    return;
  }
  let client: AutoMotoClient;
  try {
    client = getClient();
    await client.health();
  } catch (e) {
    return showError(e);
  }
  let workspace: string | undefined;
  if (opts.workspaceUri) {
    const f = folderFor(opts.workspaceUri);
    if (!f) return showError(new Error("open a folder first"));
    try {
      if (!(await ensureAllowed(client, f.uri.fsPath))) return;
    } catch (e) {
      return showError(e);
    }
    workspace = f.uri.fsPath;
  }
  chat.reveal();
  chat.post({ type: "user", text: opts.title || prompt.slice(0, 600) });
  chat.post({ type: "busy", value: true });
  output.appendLine(`\n── ${new Date().toLocaleTimeString()} ${opts.title || prompt.split("\n")[0].slice(0, 80)}`);
  running = { cancelled: false };
  const c = cfg();
  try {
    const res = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Window, title: "AutoMoto is working…" },
      () => client.runAgent([{ role: "user", content: prompt }], {
        workspace, prefer: c.provider, maxSteps: c.maxSteps, signal: running, approve,
        onEvent: (ev) => {
          const line = describe(ev);
          if (line) {
            output.appendLine(line);
            chat.post({ type: "step", text: line });
          }
        },
      }),
    );
    const meta = [res.provider, res.model, res.steps ? `${res.steps} step(s)` : "", res.stopped].filter(Boolean).join(" · ");
    chat.post({ type: res.status === "error" ? "error" : "bot", text: res.text || "(no answer)", meta });
    output.appendLine(res.text || "(no answer)");
  } catch (e) {
    showError(e);
  } finally {
    running = undefined;
    chat.post({ type: "busy", value: false });
  }
}

function showError(e: unknown): void {
  const msg = e instanceof SessionError || e instanceof ApiError ? e.message : `AutoMoto: ${(e as Error)?.message || e}`;
  chat?.post({ type: "error", text: msg });
  vscode.window.showErrorMessage(msg, "How to start AutoMoto").then((p) => {
    if (p) vscode.env.openExternal(vscode.Uri.parse("https://github.com/ymmiah/AutoMotoAI#vs-code-extension"));
  });
}

class FixProvider implements vscode.CodeActionProvider {
  static readonly kinds = [vscode.CodeActionKind.QuickFix];
  provideCodeActions(doc: vscode.TextDocument, _r: vscode.Range, ctx: vscode.CodeActionContext): vscode.CodeAction[] {
    return ctx.diagnostics.slice(0, 3).map((d) => {
      const a = new vscode.CodeAction(`Fix with AutoMoto: ${d.message.split("\n")[0].slice(0, 60)}`, vscode.CodeActionKind.QuickFix);
      a.command = { command: "automoto.fixDiagnostic", title: "Fix with AutoMoto", arguments: [doc.uri, d] };
      a.diagnostics = [d];
      return a;
    });
  }
}

const SEVERITY = ["error", "warning", "info", "hint"];

export function activate(context: vscode.ExtensionContext): { getClient: typeof getClient } {
  output = vscode.window.createOutputChannel("AutoMoto AI");
  chat = new ChatViewProvider(context.extensionUri, async (text, useWs) => {
    await runPrompt(text, { workspaceUri: useWs ? vscode.workspace.workspaceFolders?.[0]?.uri : undefined, title: text });
  }, () => {
    if (running) running.cancelled = true;
  });
  const reg = (id: string, fn: (...a: any[]) => unknown) => context.subscriptions.push(vscode.commands.registerCommand(id, fn));
  context.subscriptions.push(output, vscode.window.registerWebviewViewProvider(ChatViewProvider.viewId, chat, { webviewOptions: { retainContextWhenHidden: true } }));
  context.subscriptions.push(vscode.languages.registerCodeActionsProvider({ scheme: "file" }, new FixProvider(), { providedCodeActionKinds: FixProvider.kinds }));

  reg("automoto.askSelection", async () => {
    const ed = vscode.window.activeTextEditor;
    if (!ed || ed.selection.isEmpty) return vscode.window.showInformationMessage("Select some code first.");
    const q = await vscode.window.showInputBox({ prompt: "Ask AutoMoto about the selection", value: "Explain this code and point out any bugs." });
    if (!q) return;
    const code = ed.document.getText(ed.selection);
    await runPrompt(askSelectionPrompt(q, relPath(ed.document.uri), ed.document.languageId, ed.selection.start.line + 1, code), { title: q });
  });

  reg("automoto.explainFile", async (uri?: vscode.Uri) => {
    const target = uri instanceof vscode.Uri ? uri : vscode.window.activeTextEditor?.document.uri;
    if (!target) return vscode.window.showInformationMessage("Open a file first.");
    const doc = await vscode.workspace.openTextDocument(target);
    await runPrompt(explainFilePrompt(relPath(target), doc.languageId, doc.getText()), { title: `Explain ${relPath(target)}` });
  });

  reg("automoto.fixDiagnostic", async (uri?: vscode.Uri, diag?: vscode.Diagnostic) => {
    let doc: vscode.TextDocument | undefined;
    if (uri instanceof vscode.Uri) doc = await vscode.workspace.openTextDocument(uri);
    else doc = vscode.window.activeTextEditor?.document;
    if (!doc) return vscode.window.showInformationMessage("Open a file with a problem first.");
    if (!diag) {
      const all = vscode.languages.getDiagnostics(doc.uri);
      const line = vscode.window.activeTextEditor?.selection.active.line;
      diag = all.find((d) => line !== undefined && d.range.start.line <= line && d.range.end.line >= line);
      if (!diag && all.length) {
        const pick = await vscode.window.showQuickPick(all.map((d) => ({ label: d.message.split("\n")[0], description: `line ${d.range.start.line + 1}`, d })), { placeHolder: "Which problem should AutoMoto fix?" });
        diag = pick?.d;
      }
      if (!diag) return vscode.window.showInformationMessage("No problems found in this file.");
    }
    const from = Math.max(0, diag.range.start.line - 20);
    const to = Math.min(doc.lineCount - 1, diag.range.end.line + 20);
    const context = doc.getText(new vscode.Range(from, 0, to, doc.lineAt(to).text.length));
    const folder = folderFor(doc.uri);
    const code = typeof diag.code === "object" ? String(diag.code.value) : diag.code !== undefined ? String(diag.code) : undefined;
    const prompt = fixDiagnosticPrompt(relPath(doc.uri), doc.languageId,
      { message: diag.message, severity: SEVERITY[diag.severity] || "problem", line: diag.range.start.line + 1, source: diag.source, code },
      context, from + 1, !!folder);
    await runPrompt(prompt, { workspaceUri: folder?.uri, title: `Fix: ${diag.message.split("\n")[0].slice(0, 100)}` });
  });

  reg("automoto.runTask", async () => {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) return vscode.window.showInformationMessage("Open a folder first.");
    const goal = await vscode.window.showInputBox({ prompt: `What should AutoMoto do in ${folder.name}?`, placeHolder: "e.g. add input validation to the signup form and a test for it" });
    if (!goal) return;
    await runPrompt(`${goal}\n\n(You are working in the user's VS Code project "${folder.name}". Use the vscode and bug-fixing skills.)`, { workspaceUri: folder.uri, title: goal });
  });

  reg("automoto.createOffice", async () => {
    type OfficeKind = vscode.QuickPickItem & { docKind: string; ext: string; skill: string; tool: string };
    const kinds: OfficeKind[] = [
      { label: "$(file-text) Word document (.docx)", docKind: "Word document", ext: "docx", skill: "word-documents", tool: "office_create_docx" },
      { label: "$(table) Excel spreadsheet (.xlsx)", docKind: "Excel spreadsheet", ext: "xlsx", skill: "excel-spreadsheets", tool: "office_create_xlsx" },
      { label: "$(preview) PowerPoint deck (.pptx)", docKind: "PowerPoint deck", ext: "pptx", skill: "powerpoint-decks", tool: "office_create_pptx" },
    ];
    const pick = await vscode.window.showQuickPick<OfficeKind>(kinds, { placeHolder: "What should AutoMoto create?" });
    if (!pick) return;
    const what = await vscode.window.showInputBox({
      prompt: `Describe the ${pick.docKind}`,
      placeHolder: pick.ext === "docx" ? "e.g. a 3-page report on renewable energy in the UK with a table and Harvard references"
        : pick.ext === "xlsx" ? "e.g. a 12-month budget with income, costs, profit formulas and a chart"
          : "e.g. a 6-slide pitch for a student app, with speaker notes",
    });
    if (!what) return;
    const folder = vscode.workspace.workspaceFolders?.[0];
    const where = folder ? `in the project folder "${folder.name}" (an office/ subfolder)` : "in scratch/";
    const prompt = `Create a ${pick.docKind}: ${what}\n\nLoad the ${pick.skill} skill first and follow it. Use ${pick.tool} to save it ${where}, ` +
      "then export a PDF with office_convert, run office_check and fix every error, and tell me the file paths.";
    await runPrompt(prompt, { workspaceUri: folder?.uri, title: `Create ${pick.docKind}: ${what}`.slice(0, 160) });
  });

  reg("automoto.repackZip", async (uri?: vscode.Uri) => {
    const target = uri ?? (await vscode.window.showOpenDialog({ canSelectFolders: true, canSelectFiles: false, openLabel: "Zip this folder" }))?.[0];
    if (!target) return;
    const folder = folderFor(target);
    if (!folder) return vscode.window.showInformationMessage("Pick a folder inside the open workspace.");
    const rel = relPath(target) || ".";
    const name = path.basename(target.fsPath);
    const prompt = `Repack the folder "${rel}" as a ZIP. Load the zip-archives skill. Use archive_create with sources=["${rel}"] ` +
      `and out="dist/${name}.zip" (deterministic, default excludes so .git, node_modules, .DS_Store, __MACOSX and .env are left out; ` +
      `keep "${name}" as the top-level folder). If the folder is a WordPress plugin or theme, use wp_package instead and then ` +
      "wp_validate the zip. Finish with archive_list on the result and tell me the path, file count, size and sha256.";
    await runPrompt(prompt, { workspaceUri: folder.uri, title: `Repack ${rel} as ZIP` });
  });

  reg("automoto.validateWordPress", async (uri?: vscode.Uri) => {
    const target = uri ?? (await vscode.window.showOpenDialog({ canSelectFolders: true, canSelectFiles: true, filters: { "WordPress zip": ["zip"] }, openLabel: "Validate" }))?.[0];
    if (!target) return;
    const folder = folderFor(target);
    if (!folder) return vscode.window.showInformationMessage("Pick a plugin/theme folder or zip inside the open workspace.");
    const rel = relPath(target) || ".";
    const prompt = `Validate the WordPress plugin or theme at "${rel}". Load the wordpress-plugins-themes skill and run wp_validate on it ` +
      "(structure, headers, readme.txt Stable tag, php -l, security checklist). Summarise errors, warnings and the security findings " +
      "with file:line, and suggest concrete fixes. Do not change any files unless I ask.";
    await runPrompt(prompt, { workspaceUri: folder.uri, title: `Validate WordPress package ${rel}` });
  });

  reg("automoto.allowWorkspace", async () => {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) return vscode.window.showInformationMessage("Open a folder first.");
    try {
      if (await ensureAllowed(getClient(), folder.uri.fsPath)) vscode.window.showInformationMessage(`AutoMoto can now work in ${folder.name} (with approvals).`);
    } catch (e) {
      showError(e);
    }
  });

  reg("automoto.openWebUI", async () => {
    try {
      vscode.env.openExternal(vscode.Uri.parse(await getClient().launchUrl()));
    } catch (e) {
      showError(e);
    }
  });

  reg("automoto.status", async () => {
    try {
      const c = getClient();
      const [h, info] = await Promise.all([c.health(), c.info()]);
      const msg = `AutoMoto ${h.version} at ${c.url} · approvals: ${info.approval_mode} · ${info.tools.filter((t: { hidden?: boolean }) => !t.hidden).length} tools · ${info.skills.length} skills`;
      output.appendLine(msg);
      vscode.window.showInformationMessage(msg);
    } catch (e) {
      showError(e);
    }
  });
  return { getClient };
}

export function deactivate(): void {
  if (running) running.cancelled = true;
}
