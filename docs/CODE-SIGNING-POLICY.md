# Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io/), certificate by
[SignPath Foundation](https://signpath.org/).

> **Status:** AutoMoto AI is applying to SignPath Foundation. Until the project is approved, Windows releases are
> **not** code-signed (SmartScreen shows *"Windows protected your PC"*: **More info → Run anyway**). Signed releases
> will be marked as such in their release notes.

## What is signed

* The Windows installers attached to the [GitHub Releases](https://github.com/ymmiah/AutoMotoAI/releases) of this
  repository: `AutoMoto-AI_<version>_x64-setup.exe` (NSIS) and `AutoMoto-AI_<version>_x64_en-US.msi` (MSI, including
  the `AutoMoto AI.exe` app inside it).
* Only files built by the [Windows app workflow](https://github.com/ymmiah/AutoMotoAI/blob/main/.github/workflows/desktop.yml)
  on GitHub-hosted runners from the source code in this repository. SignPath verifies the origin of every file
  before it is signed, and every release is approved by hand.
* Nothing from other projects is signed with this certificate. Third-party files that ship inside the installers
  keep their own publisher's signature (or none).

The app's updater also checks a separate **update signature** (`.sig`, minisign/Tauri updater key) over the final,
Authenticode-signed installer before it installs an update.

## Team roles

| Role | Members |
|---|---|
| Authors (committers) | [Yasin Mohammed Miah (@ymmiah)](https://github.com/ymmiah) |
| Reviewers | [Yasin Mohammed Miah (@ymmiah)](https://github.com/ymmiah) - every pull request from anyone else is reviewed before it is merged |
| Approvers | [Yasin Mohammed Miah (@ymmiah)](https://github.com/ymmiah) - approves each signing request in SignPath |

All team members use multi-factor authentication on GitHub and SignPath.

## Privacy policy

This program will not transfer any information to other networked systems unless specifically requested by the
user or the person installing or operating it. There is no telemetry, no analytics and no advertising.

What it connects to, and when:

| Connection | When | What is sent |
|---|---|---|
| The AI providers **you** add a key for (NVIDIA NIM, Google Gemini, Groq, OpenRouter, OpenAI, Anthropic) | when you chat or run a task | your messages and the files or tool results the task uses, to the provider you chose. Their privacy policies apply. |
| A local AI (Ollama, llama.cpp, LM Studio…) on your computer or home network | when you pick it | the same, but it never leaves your network |
| Web search (DuckDuckGo) and the web pages, feeds and developer sites (GitHub, Stack Exchange, Hacker News, Bluesky) a task opens | only when you ask for research or give a link | the search words or the page address |
| Connectors you set up (GitHub, Notion, Google Drive…) | only when you connect them and a task uses them | the request for that service, with the token you gave |
| Your AutoMoto account server (if you sign in) | while signed in | your chats and files, to the server **you** typed in |
| Update check: `raw.githubusercontent.com` and `github.com` (this repository's releases) | a few seconds after the Windows app starts, and when you click *Check for updates* | a normal web request (your IP address and app version in the user agent); nothing else. Set `AUTOMOTO_NO_UPDATE_CHECK=1` to turn the automatic check off. |
| Microsoft WebView2 download | during installation, only if WebView2 is missing | Microsoft's own installer |
| Python packages (PyPI, python.org, winget) | only when you click *Install the local engine* and agree | the package downloads |

Offline mode (Settings) switches all web and connector traffic off. Keys you type in the app stay on your computer
(or in the browser tab) and are never sent to the project.

Source: [github.com/ymmiah/AutoMotoAI](https://github.com/ymmiah/AutoMotoAI) · Licence: [AGPL-3.0-only](https://github.com/ymmiah/AutoMotoAI/blob/main/LICENSE) (OSI-approved; versions up to 5.6.0-beta.3 were MIT) ·
Report a problem: [GitHub issues](https://github.com/ymmiah/AutoMotoAI/issues). To report a signed file that breaks this
policy, write to support@signpath.io.
