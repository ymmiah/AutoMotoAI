# AutoMoto AI — Windows app (Tauri 2) — Beta

> **Beta** (5.6.0-beta.2). The window title, sign-in screen, About and installer names say so.

The **AutoMoto AI app** is a small native window (Tauri 2, the system WebView2 on Windows) that opens on a
**sign-in screen** with two choices:

* **Your AutoMoto account** — sign in to an AutoMoto server (hosted mode, see `docs/HOSTING.md`). Chats, files,
  memory, usage time and bonus time live on the server, so the same account shows the same things in the app, in a
  browser and on a phone.
* **Local mode** — no account: the app starts the AutoMoto engine installed on this PC on `127.0.0.1:8765`, opens
  it, and stops it when the window closes.

Users: download the installer from [Releases](https://github.com/ymmiah/AutoMotoAI/releases/latest) — see
[docs/INSTALL.md → Windows app](../../docs/INSTALL.md#windows-app) and
[the GUI guide § 0](../../docs/GUI-GUIDE.md#0-the-windows-app). The Windows build is what CI ships and tests; the
same code builds on macOS and Linux (`npm run build`) but those builds aren't released or tested in CI.

## How it works

| Part | File |
|---|---|
| Sign-in / mode screen (static HTML/JS, no remote code) | `dist/index.html`, `dist/app.js`, `dist/app.css` |
| Commands the page can call (7, all checked against the caller's URL) | `src-tauri/src/main.rs`, `build.rs`, `capabilities/default.json` |
| Account sign-in, device token, launch codes (HTTP in Rust, never in the page) | `src-tauri/src/account.rs` |
| Local engine: find, start, wait for `/api/health`, stop (whole process tree) | `src-tauri/src/local.rs` |
| Settings (server address, username, device name, last mode — no secrets) | `src-tauri/src/settings.rs` → `%APPDATA%\com.ymmiah.automoto\settings.json` |

**Account sign-in:** the password goes once to `POST /api/auth/device/login` and the server returns a revocable
device token. The token is kept in **Windows Credential Manager** (macOS Keychain; on Linux the kernel keyring, which forgets it at logout) — never in a
file and never given to the web page. To open the window the app exchanges the token for a one-time 60-second launch
code and loads `<server>/?device_launch=<code>`, which becomes a normal browser session tied to that device. The user
sees and revokes devices in **Account → My devices**; admins in **Admin → Signed-in apps**. Server addresses must be
`https://` (plain `http://` only for `localhost`/`127.0.0.1`).

**Why Local mode doesn't bundle Python:** a frozen Python (PyInstaller) sidecar would add ~150–250 MB per install,
is a frequent antivirus/SmartScreen false-positive, and would need its own update path. Instead the installer ships
the official `scripts/install.ps1`; **Install the local engine** runs it in a visible PowerShell window (the same
checksum-pinned install as the docs), and the app then finds `%LOCALAPPDATA%\automoto-ai\venv\Scripts\python.exe`
(or `AUTOMOTO_PYTHON`). If an engine is already running on 8765, the app asks it for a one-time link (like the VS
Code extension) instead of starting a second one.

## Security

* **Capabilities:** only this app's 7 commands, only for the bundled local page (`"local": true`); no `core:default`,
  no shell, fs or http plugins exposed to JavaScript. Remote pages (the account server, the local engine) get **no**
  IPC access.
* **CSP** on the bundled page: `default-src 'self'; script-src 'self'; connect-src ipc: http://ipc.localhost; …`;
  `freezePrototype` on.
* **Navigation:** the window may show only the app page, the signed-in server's origin and the local engine; every
  other link (and `target=_blank`) opens in the default browser.
* **Network:** rustls, no redirects followed, credentials never put in URLs.
* **Updates** come from the **beta channel** (`packaging/updater/beta.json`, the signed `latest.json` of the newest
  beta release) and are checked against the public key in `tauri.conf.json`; an update without a valid signature is refused. The private key exists only as the repo
  secrets `TAURI_SIGNING_PRIVATE_KEY` / `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` (and Yasin's offline backup).
* The installers contain no keys or secrets. The default server address can be baked in at build time with the repo
  variable `AUTOMOTO_DEFAULT_SERVER`.

## Build from source

Prerequisites: Rust **1.90+**, Node 20+, and the [Tauri prerequisites](https://v2.tauri.app/start/prerequisites/)
(Windows: Visual Studio C++ Build Tools + WebView2; Linux: `libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev`).

```powershell
cd apps\desktop
npm ci
npm run build:win          # -> src-tauri\target\release\bundle\nsis\*.exe and bundle\msi\*.msi
```

Without the updater key, build with `npx tauri build --config '{"bundle":{"createUpdaterArtifacts":false}}'`.
Development: `npm run dev`. Rust checks: `cd src-tauri && cargo test && cargo clippy -- -D warnings`.

## CI and releases

`.github/workflows/desktop.yml` (windows-latest) checks that all version numbers agree, runs the Rust tests and
clippy, builds the `.exe` and `.msi`, then smoke-tests **each** installer on the runner: silent install (`/S`,
`msiexec /qn`), launch on the sign-in screen (screenshot), `--local` starts the engine and `/api/health` answers,
closing the window stops the engine, silent uninstall. Installers and screenshots are uploaded as artifacts. On a
`v*` tag it also writes the signed `latest.json` and attaches everything to that tag's GitHub Release (created as a
draft if it doesn't exist yet).

Signing, the Microsoft Store and winget: [docs/WINDOWS-DISTRIBUTION.md](../../docs/WINDOWS-DISTRIBUTION.md).

## Limits (honest list)

* Not Authenticode-signed yet: SmartScreen warns on first run (*More info → Run anyway*).
* Local mode needs the engine installed separately (one click, but it downloads Python packages).
* The app shows the server's own web GUI; there is no offline copy of account chats.
* macOS and Linux builds compile but are not released or tested in CI.
