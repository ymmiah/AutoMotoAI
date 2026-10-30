# AutoMoto AI for VS Code

Chat with your local **AutoMoto AI** agent from VS Code: ask about selected code, fix errors from the
Problems list, explain files, and run agent tasks on your project. The agent itself runs in AutoMoto
(`python -m automoto serve`) with its sandbox, approvals and secret-file blocklist. This extension is
a thin, token-protected client for it.

## Setup
1. Install AutoMoto AI (see the [main README](https://github.com/ymmiah/AutoMotoAI#quick-start)) and add at least one AI key to `.env`.
2. Start it: `python -m automoto serve --no-browser`.
3. Install the extension: search **AutoMoto AI** in the Extensions view (VS Code Marketplace, or Open VSX in
   VSCodium / Cursor), or download `automoto-ai-5.5.0.vsix` (or the `automoto-ai-5.6.0-beta.1.vsix` pre-release) from
   [GitHub Releases](https://github.com/ymmiah/AutoMotoAI/releases) and use **Extensions → … → Install from VSIX…**
   (or `code --install-extension automoto-ai-5.5.0.vsix`).
4. Open the **AutoMoto AI** view in the activity bar.

The extension finds the server through AutoMoto's private session file (`~/.automoto/session.json`,
readable only by you), so there's nothing to configure. It only talks to `127.0.0.1` / `localhost`.

## Requirements
- VS Code 1.85+ and Python 3.10+ with AutoMoto AI 5.5 running locally. The extension uses the single-user
  local server; it doesn't sign in to hosted multi-user servers (use their web page instead).

## Commands
| Command | What it does |
|---|---|
| **AutoMoto: Ask about selection** (`Ctrl+Alt+A` / `Cmd+Alt+A`) | Sends the selected code and your question. |
| **AutoMoto: Fix this error** | Also a 💡 quick fix on any diagnostic. The agent reads the file, makes the smallest fix with `edit_file`, and runs tests. Every edit asks first. |
| **AutoMoto: Explain this file** | Editor and Explorer context menus. |
| **AutoMoto: Run agent task on workspace…** | Any goal ("add a test for the parser"). The agent works in the open folder. |
| **AutoMoto: Let the agent work in this folder** | Adds the folder to AutoMoto's allowed folders. |
| **AutoMoto: Open the AutoMoto web UI** | Opens the full GUI with a one-time sign-in link. |

## Safety
- Each risky step (write, edit, shell command, app run) appears as a modal **Allow / Deny** dialog, showing the reason and arguments.
- Your project folder is used only after you agree, and only in a trusted workspace.
- `.env` files, keys, `~/.ssh` and similar files are blocked by AutoMoto, whatever the agent is told.
- Code you send is marked as data, so instructions hidden in a file are not followed.
- `automoto.serverUrl` and `automoto.dataDir` are machine-level settings, so a cloned repo's `.vscode/settings.json` can't redirect your token.

Made by Yasin Mohammed Miah, Student of BCU, BSc Computing Top-Up (Hons) ·
[GitHub](https://github.com/ymmiah) · [LinkedIn](https://linkedin.com/in/ymmiah) · [ymmiah.com](https://ymmiah.com)
