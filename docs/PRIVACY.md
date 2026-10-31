# Privacy policy

*AutoMoto AI (all editions: Windows app, Microsoft Store app, web interface, VS Code extension, Python engine).
Last updated: 31 October 2026.*

**In short:** AutoMoto AI has **no telemetry, no analytics and no advertising**. The project (Yasin Mohammed Miah)
does **not** receive your chats, files or keys. The app only sends data to services **you** choose: the AI provider
you add a key for, the web pages a task opens, the connectors you set up, and the account server you sign in to.

This program will not transfer any information to other networked systems unless specifically requested by the
user or the person installing or operating it.

## What the app handles

| Information | Where it's kept | Who receives it |
|---|---|---|
| Your messages, the files you attach or let a task use, and the results | on your computer (`~/.automoto`), or on the account server you sign in to | the AI provider you chose, when you send a message or run a task |
| AI provider keys and connector tokens you type in | on your computer (a local settings file; the Windows app keeps its sign-in token in the Windows Credential Manager) or in the browser tab | only the service the key belongs to |
| Account name and password (only if you use an AutoMoto account server) | on that server; passwords are stored as salted scrypt hashes | the server operator (your admin, teacher or yourself) |
| Memory, routines and settings | on your computer or your account server | nobody else |

The app doesn't ask for your location, contacts, health or payment information.

## What it connects to, and when

| Connection | When | What is sent |
|---|---|---|
| The AI providers **you** add a key for (NVIDIA NIM, Google Gemini, Groq, OpenRouter, OpenAI, Anthropic) | when you chat or run a task | your messages and the files or tool results the task uses. **Their** privacy policies apply. |
| A local AI (Ollama, llama.cpp, LM Studio…) on your computer or home network | when you pick it | the same, but it never leaves your network |
| Web search (DuckDuckGo) and the web pages, feeds and developer sites (GitHub, Stack Exchange, Hacker News, Bluesky) a task opens | only when you ask for research or give a link | the search words or the page address |
| Connectors you set up (GitHub, Notion, Google Drive…) | only when you connect them and a task uses them | the request for that service, with the token you gave |
| Your AutoMoto account server | while signed in | your chats and files, to the server address **you** entered |
| Update check (Windows app from GitHub only): `raw.githubusercontent.com`, `github.com` | a few seconds after start, and when you click *Check for updates* | a normal web request (IP address, app version). `AUTOMOTO_NO_UPDATE_CHECK=1` turns it off. **The Microsoft Store edition doesn't do this**: the Store updates it. |
| Microsoft WebView2 download (installer from GitHub only) | during installation, only if WebView2 is missing | Microsoft's own installer |
| Python, Python packages (python.org, PyPI, winget) | only when you click *Install the local engine* and agree | the package downloads |

**Offline mode** (Settings) switches all web and connector traffic off. Data in transit to providers and servers uses
HTTPS where the service supports it (local AIs on your own network may use plain HTTP).

## AI-generated content

Replies, documents and other output are made by the **AI model you choose** and can be wrong, incomplete or
inappropriate. Check important results. Actions that change files, run commands or contact other services ask for
your approval first. To report inappropriate or harmful output, open an issue at
<https://github.com/ymmiah/AutoMotoAI/issues> (choose *Report content*) or use the contact below.

## Your choices

* Use a **local AI** to keep everything on your own computer or network.
* Delete chats, memory and files in the app, or delete the `~/.automoto` folder (on Windows,
  `%USERPROFILE%\.automoto`). Uninstalling the app removes the app; your data folder stays until you delete it.
* Remove a key or connector in **Settings**; revoke it at the provider too if you like.
* On an account server, ask its operator to delete your account (admins can do it in the admin panel).

## Account servers run by others

If you sign in to a server that someone else runs, that person is responsible for the data on it. The project
doesn't run a public server and doesn't receive that data.

## Children

AutoMoto AI isn't directed at children under 13 and doesn't knowingly collect their information.

## Microsoft Store

If you install the app from the Microsoft Store, Microsoft handles the download, installation, updates and any
reviews or crash reports under the [Microsoft Privacy Statement](https://privacy.microsoft.com/privacystatement).
The project only sees the totals Microsoft shows developers in Partner Center (for example, install counts).

## Changes and contact

Changes to this policy are listed in the [repository history](https://github.com/ymmiah/AutoMotoAI/commits/main/docs/PRIVACY.md).
Questions: [GitHub issues](https://github.com/ymmiah/AutoMotoAI/issues), [github.com/ymmiah](https://github.com/ymmiah)
or [ymmiah.com](https://ymmiah.com).

Source code: [github.com/ymmiah/AutoMotoAI](https://github.com/ymmiah/AutoMotoAI) ·
Licence: [AGPL-3.0-only](https://github.com/ymmiah/AutoMotoAI/blob/main/LICENSE), or a
[commercial licence](https://github.com/ymmiah/AutoMotoAI/blob/main/COMMERCIAL-LICENSE.md).
