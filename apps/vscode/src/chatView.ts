// Chat sidebar. The webview only renders text (textContent, no HTML from the model) and talks
// to the extension with postMessage; the extension holds the token and calls the API.
import * as crypto from "crypto";
import * as vscode from "vscode";

export type ChatHandler = (text: string, useWorkspace: boolean) => Promise<void>;

export class ChatViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewId = "automoto.chat";
  private view?: vscode.WebviewView;
  private pending: unknown[] = [];

  constructor(private readonly extensionUri: vscode.Uri, private readonly onSend: ChatHandler, private readonly onStop: () => void) {}

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = { enableScripts: true, localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, "media")] };
    view.webview.html = this.html(view.webview);
    view.webview.onDidReceiveMessage(async (m: any) => {
      if (m?.type === "send" && typeof m.text === "string" && m.text.trim()) {
        await this.onSend(m.text.slice(0, 20000), !!m.workspace);
      } else if (m?.type === "stop") {
        this.onStop();
      } else if (m?.type === "ready") {
        for (const p of this.pending.splice(0)) view.webview.postMessage(p);
      }
    });
  }

  post(message: unknown): void {
    if (this.view) this.view.webview.postMessage(message);
    else this.pending.push(message);
  }

  reveal(): void {
    if (this.view) this.view.show?.(true);
    else vscode.commands.executeCommand("automoto.chat.focus");
  }

  private html(webview: vscode.Webview): string {
    const nonce = crypto.randomBytes(16).toString("base64");
    const js = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "media", "chat.js"));
    const css = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "media", "chat.css"));
    const csp = [`default-src 'none'`, `style-src ${webview.cspSource}`, `script-src 'nonce-${nonce}'`, `img-src ${webview.cspSource}`].join("; ");
    return `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="${css}"></head>
<body><div id="log" role="log" aria-live="polite"></div>
<form id="f"><textarea id="t" rows="3" placeholder="Ask AutoMoto… (Enter to send, Shift+Enter for a new line)" aria-label="Message"></textarea>
<div class="bar"><label><input type="checkbox" id="ws"> work in this folder</label><span class="sp"></span>
<button type="button" id="stop" hidden>Stop</button><button id="send">Send</button></div></form>
<script nonce="${nonce}" src="${js}"></script></body></html>`;
  }
}
