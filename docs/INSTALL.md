# Install, run and deploy AutoMoto AI — every OS

This guide is for everyone, including first-timers. Copy the commands for **your** computer, top to bottom.
Everything here is free. Latest **stable** release: **v5.5.0** ([downloads](https://github.com/ymmiah/AutoMotoAI/releases/latest)).

> **Beta: 5.6.0 Beta 3** ([pre-release](https://github.com/ymmiah/AutoMotoAI/releases/tag/v5.6.0-beta.3)) adds the
> **Windows app** and **one account on every device**. New here? The simplest steps per device (Windows PC, phone,
> Mac/Linux, VS Code) are in **[Start here: pick your device](START.md)**. To install the beta engine with the
> scripts below, add `-Version 5.6.0b3` (Windows) or `--version 5.6.0b3` (macOS/Linux). Without it you get 5.5.0.

**Contents:** [Pick a way](#1-pick-a-way) · [Get a free AI key](#2-get-a-free-ai-key) · [Windows](#3-windows-1011) ·
[macOS](#4-macos-intel-and-apple-silicon) · [Linux](#5-linux-ubuntu--debian-fedora-arch-and-others) ·
[Docker](#6-docker-and-docker-compose-any-os) · [Host it for others](#7-host-it-for-other-people) ·
[VS Code, ChromeOS, Raspberry Pi, phones, BSD](#8-other-platforms) · [Update](#9-updating) ·
[Uninstall](#10-uninstalling) · [Troubleshooting](#11-troubleshooting) · [What was tested](#12-what-was-tested-where)

---

## 1. Pick a way

| You want… | Use | Time |
|---|---|---|
| The **Windows app (Beta)**: sign in to an AutoMoto account, or Local mode | The beta installer from Releases ([section 3](#windows-app)) | ~2 min |
| AutoMoto for **yourself** on Windows / macOS / Linux | The **installer script** for your OS (sections 3–5) | ~5 min |
| An isolated setup, or the same steps on every OS | **Docker Compose** (section 6) | ~10 min |
| Friends / classmates use it, with a **1-hour daily limit** | **Hosted mode** (section 7) | ~20 min |
| AutoMoto inside **VS Code** | Any of the above + the extension (section 8) | +2 min |

Good to know before you start:

* AutoMoto is a Python app (Python **3.10 or newer**). The command is **`automoto`** (or `python -m automoto`).
* It runs a small web app on **http://127.0.0.1:8765** — only your own computer can reach it unless you choose hosted mode.
* Your data (chats, memory, skills, files the agent makes) lives in **`~/.automoto`** —
  `C:\Users\<you>\.automoto` on Windows. The agent's sandbox is `~/.automoto/workspace`.
* Your keys go in **`~/.automoto/.env`** (the installers create it, readable only by you) or in environment variables.
  The agent can never read that folder.

## 2. Get a free AI key

You need **at least one** key. All of these have a free tier that doesn't need a card (limits change — check the links):

| Provider | Get a key | Put it in `.env` as | Notes |
|---|---|---|---|
| **NVIDIA NIM** (recommended) | <https://build.nvidia.com> → sign in → *Get API Key* | `NVIDIA_API_KEY=nvapi-…` | Free developer access for prototyping, rate-limited (around 40 requests/min); big models can be slow — set `AI_TIMEOUT=120` |
| **Google Gemini** | <https://aistudio.google.com/apikey> | `GEMINI_API_KEY=…` | Free tier in [supported countries](https://ai.google.dev/gemini-api/docs/available-regions); small per-day limits ([rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)) |
| **Groq** | <https://console.groq.com/keys> | `GROQ_API_KEY=gsk_…` | Free tier, very fast, per-minute and per-day limits ([limits](https://console.groq.com/docs/rate-limits)) |
| **OpenRouter** | <https://openrouter.ai/keys> | `OPENROUTER_API_KEY=sk-or-…` | `:free` models: about 20/min and 50/day without credit ([limits](https://openrouter.ai/docs/api_reference/limits)) |
| OpenAI / Anthropic | platform.openai.com / console.anthropic.com | `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Paid |

With several keys, AutoMoto picks the best AI per step and **fails over** automatically when one is busy.
Never share a key or paste it into a chat, an issue or a Git commit.

---

## 3. Windows 10/11

### Windows app

**Beta** (5.6.0 Beta 3). The easiest way on Windows 10/11 (64-bit). **No Python needed** to sign in to an AutoMoto account.

1. Download from the [5.6.0 Beta 3 pre-release](https://github.com/ymmiah/AutoMotoAI/releases/tag/v5.6.0-beta.3):
   * `AutoMoto-AI_5.6.0-beta.3_x64-setup.exe` — installs for you only, no admin (recommended), or
   * `AutoMoto-AI_5.6.0-beta.3_x64_en-US.msi` — installs for all users (admin; good for school/work PCs and silent installs).
2. Optional — check it against `SHA256SUMS.txt` from the same release:

   ```powershell
   (Get-FileHash "$HOME\Downloads\AutoMoto-AI_5.6.0-beta.3_x64-setup.exe").Hash
   ```

3. Run it. The app isn't code-signed yet, so SmartScreen says *"Windows protected your PC"* → **More info → Run anyway**
   ([why](WINDOWS-DISTRIBUTION.md)). WebView2 is installed automatically if the PC doesn't have it (Windows 11 does).
4. **Sign in** with the server address, username and password from your admin — or click **Start local mode**.

Silent installs (IT, scripts):

```powershell
.\AutoMoto-AI_5.6.0-beta.3_x64-setup.exe /S                                       # per-user, no admin
msiexec /i AutoMoto-AI_5.6.0-beta.3_x64_en-US.msi /qn /norestart                  # all users, admin PowerShell
```

**Local mode** runs AutoMoto on this PC without an account. It needs the engine from step 2 below; the app's
**Install the local engine** button runs the same official installer for you (it ships inside the app) and installs
the matching beta engine (`-Version 5.6.0b3`). The app
starts the engine when you pick Local mode and stops it when you close the window.

**Updates:** the beta app checks the beta channel on start and asks before updating; updates are signature-checked.
**Uninstall:** *Settings → Apps → AutoMoto AI → Uninstall* (your account and its chats stay on the server; Local mode
data stays in `%USERPROFILE%\.automoto`).

Step-by-step with screenshots: [GUI guide § 0](GUI-GUIDE.md#0-the-windows-app).
The rest of this section installs the **engine** (the command line, the web GUI and Local mode).

### Engine (command line and web GUI)

All commands are for **PowerShell** (Start menu → type *PowerShell*).

**Step 1 — Python and Git**

```powershell
winget install -e --id Python.Python.3.12
winget install -e --id Git.Git
```

Close PowerShell and open a **new** window, then check: `py --version` → `Python 3.12.x`.
(No winget? Get Python from <https://www.python.org/downloads/> and tick **"Add python.exe to PATH"**.)

**Step 2 — AutoMoto**

```powershell
cd $HOME
git clone https://github.com/ymmiah/AutoMotoAI
cd AutoMotoAI
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

The installer: finds Python, downloads the **v5.5.0 wheel** from GitHub Releases and refuses it unless its SHA-256
matches the checksum pinned in the script, installs it into a private virtualenv in
`%LOCALAPPDATA%\automoto-ai`, adds the `automoto` command to your user PATH and creates
`%USERPROFILE%\.automoto\.env`. No admin rights. Options:

| Option | Does |
|---|---|
| `-FromSource` | install this checkout (newest code on `main`) instead of the release |
| `-Full` | also Parquet, `.7z` without 7-Zip, TOML writing (`[office,data]` extras) |
| `-SystemDeps` | also LibreOffice, 7-Zip, Poppler and PHP via winget (asks first) |
| `-AutoStart` | start AutoMoto at log-on, without a window (Task Scheduler) |
| `-Uninstall` (`-Purge`) | remove it (and your data) |

No Git? Download **Source code (zip)** from the [release page](https://github.com/ymmiah/AutoMotoAI/releases/latest),
extract it, *right-click → Properties → Unblock* on `scripts\install.ps1` (or `Unblock-File scripts\install.ps1`),
and run the same `powershell -ExecutionPolicy Bypass -File scripts\install.ps1` in that folder.
`-ExecutionPolicy Bypass` only applies to this one run; it doesn't change your system policy.

**Step 3 — your key** (pick one)

```powershell
notepad "$env:USERPROFILE\.automoto\.env"        # paste: NVIDIA_API_KEY=nvapi-...   then save
# or, as a user environment variable (open a NEW window afterwards):
setx NVIDIA_API_KEY "nvapi-..."
```

**Step 4 — start it** (new PowerShell window)

```powershell
automoto status      # ✅ next to the AI you added
automoto serve       # opens the app in your browser
```

`serve` prints a one-time sign-in link and opens it. Closed the tab? Run `automoto open` in another window.
Stop the server with **Ctrl+C**.

**Optional tools** (for PDF export, `.7z`/`.rar`, PDF text, WordPress `php -l` checks) — or use `-SystemDeps`:

```powershell
winget install -e --id TheDocumentFoundation.LibreOffice
winget install -e --id 7zip.7zip
winget install -e --id oschwartz10612.Poppler
winget install -e --id PHP.PHP.8.4
```

Open a new window and run `automoto apps` to see what AutoMoto found. (AutoMoto also finds LibreOffice and 7-Zip in
`C:\Program Files` when they aren't on PATH.)

**Windows notes**

* **Firewall:** the normal app listens on `127.0.0.1` only, so Windows shouldn't ask. If it does ask about Python, you
  can click *Cancel* — only hosted mode on your Wi-Fi needs it, and then allow **Private networks** only.
* **SmartScreen / "running scripts is disabled":** the script isn't code-signed; that's why the command uses
  `-ExecutionPolicy Bypass`. Read the script first if you like — it's plain text.
* **"Python was not found; run without arguments to install from the Microsoft Store":** that's Windows' store alias.
  Install Python as in step 1, or turn off *Settings → Apps → Advanced app settings → App execution aliases → python.exe*.
* **WSL:** you can instead follow the [Linux steps](#5-linux-ubuntu--debian-fedora-arch-and-others) inside WSL (Ubuntu).
  WSL 2 normally forwards `localhost`, so the Windows browser can open `http://127.0.0.1:8765` (not tested here).
* **Manual install with pipx** (if you prefer):
  ```powershell
  py -m pip install --user pipx; py -m pipx ensurepath          # then open a new window
  # download automoto_ai-5.5.0-py3-none-any.whl from the release page, then check it:
  (Get-FileHash .\automoto_ai-5.5.0-py3-none-any.whl).Hash      # must be 755BC31B8F8B6F1ED5330C5356B05E9509F94F0EAFC3B6E9AA7EAB443F223107
  pipx install ".\automoto_ai-5.5.0-py3-none-any.whl[office]"
  ```
  With pipx and v5.5.0, set keys with `setx` (the installer's `automoto` command and newer versions also read `~/.automoto/.env`).

---

## 4. macOS (Intel and Apple Silicon)

Same steps on Intel and Apple Silicon (M1–M4). Use the **Terminal** app.

**Step 1 — Homebrew, Python, Git.** Install Homebrew with the official instructions at <https://brew.sh>
(or the `.pkg` installer from its GitHub releases), then:

```bash
brew install python@3.12 git
```

(If macOS asks to install the *command line developer tools*, click Install.)

**Step 2 — AutoMoto**

```bash
cd ~
git clone https://github.com/ymmiah/AutoMotoAI
cd AutoMotoAI
./scripts/install.sh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
```

`install.sh` checks the v5.5.0 wheel's SHA-256, installs into `~/.local/share/automoto-ai/venv`, puts the
`automoto` command in `~/.local/bin` and creates `~/.automoto/.env` (mode 600). Options: `--from-source`,
`--full`, `--system-deps`, `--service`, `--uninstall [--purge]`, `--help`.

**Step 3 — your key** (pick one)

```bash
open -e ~/.automoto/.env                                       # paste NVIDIA_API_KEY=nvapi-...  and save
# or for every terminal:
echo 'export NVIDIA_API_KEY="nvapi-..."' >> ~/.zshrc && source ~/.zshrc
```

**Step 4 — start it**

```bash
automoto status
automoto serve          # opens Safari/Chrome with a one-time sign-in link; Ctrl+C stops it
```

**Optional tools** — or `./scripts/install.sh --system-deps`:

```bash
brew install poppler sevenzip php
brew install --cask libreoffice
```

**macOS notes**

* **Gatekeeper:** AutoMoto itself is a Python package, so there's nothing to approve. If macOS blocks LibreOffice the
  first time, open it once from *Applications* (right-click → Open), then AutoMoto can use it headless.
* **Desktop control** (optional `--extras office,desktop`): macOS will ask you to allow Terminal/Python under
  *System Settings → Privacy & Security → Accessibility* and *Screen Recording*. Not needed for anything else.
* **Start at login:** `./scripts/install.sh --service` adds a launchd agent (`~/Library/LaunchAgents/com.ymmiah.automoto.plist`,
  log in `~/.automoto/automoto.log`). Then just run `automoto open`. Remove it with `./scripts/install.sh --uninstall`.

---

## 5. Linux (Ubuntu / Debian, Fedora, Arch and others)

**Step 1 — Python 3.10+ and Git**

```bash
# Ubuntu 22.04+ / Debian 12+ / Linux Mint / Pop!_OS / Raspberry Pi OS (64-bit)
sudo apt update && sudo apt install -y python3 python3-venv git
# Fedora
sudo dnf install -y python3 git
# Arch / Manjaro / EndeavourOS
sudo pacman -S --needed python git
# openSUSE Tumbleweed (Leap: python311 instead of python3)
sudo zypper install -y python3 git
```

Older systems (Ubuntu 20.04, Debian 11) ship Python 3.8/3.9 — too old; use [Docker](#6-docker-and-docker-compose-any-os).

**Step 2 — AutoMoto**

```bash
cd ~
git clone https://github.com/ymmiah/AutoMotoAI
cd AutoMotoAI
./scripts/install.sh            # add --system-deps for LibreOffice/poppler/7-Zip/PHP, --service to start at login
```

If it says `~/.local/bin` isn't on your PATH: `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc`.

**Step 3 — key:** `nano ~/.automoto/.env` → `NVIDIA_API_KEY=nvapi-…` (or `export NVIDIA_API_KEY=…` in `~/.bashrc`).

**Step 4 — start:** `automoto status` then `automoto serve`.

**Optional tools** (`--system-deps` runs the right line for you, after asking):

```bash
sudo apt install -y libreoffice-writer libreoffice-calc libreoffice-impress poppler-utils 7zip php-cli   # Ubuntu/Debian (older: p7zip-full)
sudo dnf install -y libreoffice-writer libreoffice-calc libreoffice-impress poppler-utils 7zip php-cli   # Fedora 41+
sudo pacman -S --needed libreoffice-fresh poppler 7zip php                                                # Arch
```

**Run it as a service** (starts when you log in, restarts if it crashes):

```bash
./scripts/install.sh --service            # writes ~/.config/systemd/user/automoto.service and enables it
automoto open                              # sign-in link for the running service
journalctl --user -u automoto -f           # logs
sudo loginctl enable-linger "$USER"        # optional: keep it running after logout / start at boot
```

Or by hand: create `~/.config/systemd/user/automoto.service` with

```ini
[Unit]
Description=AutoMoto AI (local web app on http://127.0.0.1:8765)
After=network-online.target

[Service]
ExecStart=%h/.local/bin/automoto serve --no-browser
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

then `systemctl --user daemon-reload && systemctl --user enable --now automoto`.

**From source for developers:** `python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[office,dev]"`
(`./setup.sh` + `./run.sh` do the same with `requirements.txt` and a `.env` in the repo folder).

---

## 6. Docker and Docker Compose (any OS)

Install **Docker Desktop** (Windows/macOS: `winget install -e --id Docker.DockerDesktop` or <https://docs.docker.com/desktop/>)
or **Docker Engine** on Linux (<https://docs.docker.com/engine/install/>). Then:

```bash
git clone https://github.com/ymmiah/AutoMotoAI
cd AutoMotoAI
```

Create a file called **`.env`** in that folder (it's git-ignored):

```ini
NVIDIA_API_KEY=nvapi-...
AUTOMOTO_ADMIN_USER=yourname
AUTOMOTO_ADMIN_PASSWORD=a-long-password-here
```

### Option A — hosted mode for yourself (Windows, macOS, Linux)

```bash
docker compose up -d --build
```

Open <http://127.0.0.1:8765> and sign in as `yourname`. Admins have no usage limit. In Docker you get the
**hosted tool set** (web research, Office, archives, data files — no shell or desktop control), which is the safe
choice for a container. Manage it with `docker compose exec automoto python -m automoto admin list`.

### Option B — full single-user mode (Linux only)

```bash
docker compose --profile local up -d --build automoto-local
docker compose exec automoto-local python -m automoto open --print     # one-time sign-in link, open it in your browser
```

This uses the host network so your browser counts as "this computer". Docker Desktop on Windows/macOS doesn't
give containers your `localhost` the same way — use option A there, or the normal install.

### Data, upgrades, extras

* Everything is stored in the named volume **`automoto-data`** (mounted at `/data`). It survives `docker compose down`,
  restarts and rebuilds. Only `docker compose down -v` deletes it.
* Backup: `docker compose exec -T automoto tar czf - -C /data . > automoto-backup.tgz`
* Update: `git pull && docker compose up -d --build`
* LibreOffice in the image (PDF export, ~600 MB more): `docker compose build --build-arg WITH_OFFICE=1 && docker compose up -d`
* Different port: `AUTOMOTO_PORT=8766` in `.env`.

---

## 7. Host it for other people

Hosted mode gives every person an account, their own sandbox and a usage limit (**60 minutes a day** by default).
You are the admin. Full reference: **[HOSTING.md](HOSTING.md)** (settings, honest free-host comparison, limits).

### Admin basics (any setup)

```bash
automoto admin create yourname                 # first user = admin (prompts for a password)
automoto admin invite --uses 10 --days 7       # invite code / link for friends (sign-up is invite-only by default)
automoto admin list                            # everyone and their usage today
automoto admin bonus ben 30                    # 30 extra minutes for ben today
automoto admin quota ben --minutes 120         # ben's own daily limit (or --unlimited / --default)
automoto admin settings --default-minutes 60   # default for everyone
automoto admin suspend ben                     # or: unsuspend / delete ben --yes / reset ben
```

(In Docker: put `docker compose exec automoto python -m automoto` in front instead of `automoto`.)
Everything is also on the **Admin** page in the web app.

### A. Your own PC + Cloudflare Tunnel (free, keeps data, HTTPS)

```bash
# after the normal install (sections 3-5):
automoto admin create yourname                 # you become the admin (prompts for a password)
cloudflared tunnel --url http://127.0.0.1:8765 # prints https://random-words.trycloudflare.com
```

In another terminal (PowerShell: `$env:NAME="value"` instead of `NAME=value`):

```bash
AUTOMOTO_MODE=multiuser AUTOMOTO_ALLOWED_HOSTS=random-words.trycloudflare.com AUTOMOTO_COOKIE_SECURE=1 automoto serve --hosted
```

Install `cloudflared`: `winget install -e --id Cloudflare.cloudflared` · `brew install cloudflared` · Linux:
<https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/>. Quick tunnels get a new
random URL each time; for a fixed address use a named tunnel with your own domain on Cloudflare.
Your PC must stay on while people use it.

### B. Oracle Cloud Always Free VM + Caddy (free, always on, HTTPS)

1. Sign up at <https://www.oracle.com/cloud/free/> (a card is used to verify you; stay on *Always Free* shapes).
2. Create an instance: **Ampere A1** (Arm), Ubuntu 24.04, up to 2 OCPU / 12 GB. Download the SSH key.
3. In the VCN's security list, allow TCP **80** and **443** from the internet. Point a domain (or a free
   DuckDNS-style name) at the VM's public IP.
4. On the VM:
   ```bash
   sudo apt update && sudo apt install -y docker.io docker-compose-v2 git caddy
   sudo iptables -I INPUT 6 -p tcp -m multiport --dports 80,443 -j ACCEPT && sudo netfilter-persistent save   # Oracle's Ubuntu images block these by default
   git clone https://github.com/ymmiah/AutoMotoAI && cd AutoMotoAI
   cat > .env <<'ENV'
   NVIDIA_API_KEY=nvapi-...
   AUTOMOTO_ADMIN_USER=yourname
   AUTOMOTO_ADMIN_PASSWORD=a-long-password-here
   AUTOMOTO_ALLOWED_HOSTS=automoto.example.com
   AUTOMOTO_COOKIE_SECURE=1
   AUTOMOTO_FORWARDED_ALLOW_IPS=*
   ENV
   chmod 600 .env
   sudo docker compose up -d --build
   echo 'automoto.example.com {
       reverse_proxy 127.0.0.1:8765
   }' | sudo tee /etc/caddy/Caddyfile && sudo systemctl reload caddy
   ```
   Caddy gets the HTTPS certificate automatically. `AUTOMOTO_FORWARDED_ALLOW_IPS=*` is right here because the
   container port is published on `127.0.0.1` only, so the only way in is through Caddy (it lets per-IP sign-in
   limits see real visitors).
5. Open `https://automoto.example.com`, sign in, make invites on the Admin page.

### C. Render free (demo only — data is wiped)

Fork the repo → <https://render.com> → *New → Blueprint* → your fork (uses `render.yaml`) → set `NVIDIA_API_KEY`,
`AUTOMOTO_ADMIN_USER`, `AUTOMOTO_ADMIN_PASSWORD`. Free services sleep after 15 minutes and have **no disk**:
every sleep/redeploy deletes all accounts except the admin from env, and all files. Good for a demo, not for users.

### D. Phones and tablets on your home Wi-Fi

```bash
AUTOMOTO_MODE=multiuser AUTOMOTO_ALLOWED_HOSTS=192.168.1.20 AUTOMOTO_COOKIE_SECURE=0 automoto serve --hosted --host 0.0.0.0
```

(use your PC's LAN address — `ipconfig` / `ip addr`). Phones open `http://192.168.1.20:8765` and sign in. Plain
HTTP is only OK on a network you trust; for anything else use option A or B.

---

## 8. Other platforms

| Platform | How | Status |
|---|---|---|
| **VS Code extension** (any OS) | Download `automoto-ai-5.5.0.vsix` from the release → `code --install-extension automoto-ai-5.5.0.vsix` (or *Extensions → … → Install from VSIX*). Start `automoto serve` first; the extension finds it by itself. | ✅ tested in CI (real VS Code on Linux) |
| **VS Code Remote-SSH / WSL / Dev Containers / Codespaces** | The extension runs on the **remote** side, so install and start AutoMoto **there** (Linux steps). VS Code's port forwarding keeps `localhost:8765` working for the web app over SSH. | 🟡 should work, not tested |
| **Cursor / VSCodium** | Same `.vsix` (Open VSX listing coming once published). | 🟡 not tested |
| **ChromeOS** | *Settings → About ChromeOS → Developers → Linux development environment → Turn on*, then the Debian steps in section 5 inside the Linux terminal. If Chrome can't open `127.0.0.1:8765`, enable it under *Linux → Port forwarding*, or install a browser inside Linux (`sudo apt install chromium`). | 🟡 not tested |
| **Raspberry Pi / Arm boards** | 64-bit Raspberry Pi OS (Bookworm, Python 3.11) → Linux steps. 4 GB RAM or more if you add LibreOffice. The Docker image is multi-arch (`python:3.12-slim`) and builds on arm64. | 🟡 not tested on Pi hardware |
| **Android / iPhone / iPad** | Use the **web app in the phone's browser** from a hosted server (section 7, A/B/D). It has a phone layout. | ✅ phone layout tested in a headless browser |
| **Flutter mobile app** (`apps/mobile`) | Scaffold only: plain chat to your PC with `AUTOMOTO_API_TOKEN`, build it yourself with Flutter. Not in the app stores. | 🧱 not store-ready |
| **Desktop app** (`apps/desktop`, Tauri) | Scaffold; build it yourself with Rust ≥ 1.90. | 🧱 not released |
| **FreeBSD / OpenBSD** | `pkg install python311 git rust` then a venv + `pip install automoto_ai-5.5.0-py3-none-any.whl` may work — some dependencies (pydantic-core, uvloop) have no BSD wheels and build from source. Or use a Linux VM. | 🔴 untested |
| **Android (Termux)** | Not supported (pandas/pydantic-core builds); use the web app from a hosted server instead. | 🔴 |

---

## 9. Updating

| Installed with | Update |
|---|---|
| Installer script | `cd AutoMotoAI && git pull` then run the installer again (`./scripts/install.sh` / `install.ps1`). New releases add their checksum to the script; `--from-source` / `-FromSource` installs the newest `main`. |
| pipx | download the new wheel, check its SHA-256, `pipx install --force "<wheel>[office]"` |
| Docker Compose | `git pull && docker compose up -d --build` |
| VS Code extension | install the new `.vsix` (or update from the Marketplace once published) |

Your data in `~/.automoto` (or the Docker volume) is kept across updates.

## 10. Uninstalling

```bash
./scripts/install.sh --uninstall            # macOS / Linux  (add --purge to delete ~/.automoto too)
```
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Uninstall      # Windows (-Purge deletes your data)
[Environment]::SetEnvironmentVariable("NVIDIA_API_KEY", $null, "User")       # if you used setx
```
```bash
pipx uninstall automoto-ai                  # pipx installs
docker compose down                         # Docker (add -v to delete the data volume)
code --uninstall-extension ymmiah.automoto-ai
```

---

## 11. Troubleshooting

| Problem | Fix |
|---|---|
| `automoto: command not found` / not recognised | Open a **new** terminal. macOS/Linux: add `~/.local/bin` to PATH (see the installer's message). Windows: the installer adds `%LOCALAPPDATA%\automoto-ai\bin` to your user PATH. `python -m automoto …` always works inside the venv. |
| `Port 8765 … is already in use` | AutoMoto is probably already running: `automoto open`. Or another app uses the port: `automoto serve --port 8766` (or `AUTOMOTO_PORT=8766`). |
| "No keys yet" / the key isn't found | `automoto status` shows **"Settings read from: …"** — check your key is in that file (spelled exactly `NVIDIA_API_KEY=…`, no spaces around `=`). After `setx`/editing `~/.zshrc`, open a new terminal. Placeholder values like `your_key` are ignored. |
| Answers time out / NIM is slow | Add `AI_TIMEOUT=120` to `~/.automoto/.env` (the installers already do). Add a second provider key so AutoMoto can fail over. |
| `403` / *"the key was rejected"* from a provider | The key is wrong, expired or has no access: make a new one (NVIDIA: <https://build.nvidia.com>) and replace it in `~/.automoto/.env`. AutoMoto stops trying that provider's other models after a 403. |
| `404` / `NotFoundError` / *"model not available to this key"* | The model isn't enabled for your key (NIM free keys differ). AutoMoto tries the provider's other models automatically and skips a 404 model for 1 hour. `automoto doctor` (or **Settings → Test keys**) sends a 1-token request to each model and prints the `NIM_MODEL=` / `NIM_AGENT_MODEL=` / `NIM_VISION_MODEL=` lines that work. |
| `503` / `502` / `500` / `429` / timeouts | The provider is busy. AutoMoto retries the same model twice with backoff (honouring `Retry-After`), then tries other models, then other providers. Tune with `AUTOMOTO_RETRIES` (0–5, default 2) and `AUTOMOTO_RETRY_BUDGET_S` (default 20). A 429 moves straight to the next provider after the retries. |
| `403 missing session token` | The one-time link was already used or is over 1 hour old. Run `automoto open` (or `automoto open --print` over SSH / Docker / services). |
| `401 please sign in` (hosted) | Sign in again (sessions last 7 days). On plain `http://` (LAN, local Docker) set `AUTOMOTO_COOKIE_SECURE=0`, otherwise the browser drops the cookie. |
| `421` / "host not allowed" | You opened it by a name AutoMoto doesn't know — add it: `AUTOMOTO_ALLOWED_HOSTS=your.domain` (comma-separated). |
| "too many failed sign-ins" | 5 wrong passwords lock an account for 15 minutes. An admin can unlock it by setting a new password: `automoto admin passwd <name>`. |
| PDF export / `.doc` / previews say LibreOffice is missing | Install it (section 3/4/5), open a new terminal, check `automoto apps`. Everything else works without it. |
| `.7z` / `.rar` not supported | Install 7-Zip (and `unar` for rar), or `--full` for the pure-Python 7z reader. |
| `ensurepip is not available` (Ubuntu/Debian) | `sudo apt install python3-venv`, run the installer again. |
| Windows: "Python was not found…Microsoft Store" | Install Python (section 3) or turn off the *App execution alias* for python.exe. |
| Behind a company proxy | Set `HTTPS_PROXY=http://proxy:port` (pip and the AI providers use it). The agent's own web tools (`web_search`, `fetch_url`) connect directly and **don't** use a proxy. If your DNS returns fake IPs (Clash/Surge `198.18.x.x`), set `AUTOMOTO_NET_ALLOW_CIDRS=198.18.0.0/15`. |
| Checksum mismatch in the installer | Don't continue: download again or use `--from-source`. If it persists, open an issue. |
| Hosted users see "limit reached" | That's the quota: give time with `automoto admin bonus <name> 30` or the Admin page. |

Still stuck? Run `automoto status` and open an issue at <https://github.com/ymmiah/AutoMotoAI/issues> (never paste keys).

---

## 12. What was tested where

| What | Where |
|---|---|
| `scripts/install.sh` (release wheel with checksum, `--from-source`, server start, one-time sign-in, port-in-use message, uninstall, `.env` mode 600) | CI on **ubuntu-latest** and **macos-latest**; by hand on Debian 13 (x86-64) |
| `scripts/install.ps1` (release wheel under Windows PowerShell 5.1, `-FromSource` under PowerShell 7, PATH, server + sign-in, uninstall) | CI on **windows-latest**; PSScriptAnalyzer clean |
| Start at login (`--service` / `-AutoStart`) | CI on all three: the systemd user service (ubuntu), launchd agent (macOS) and Task Scheduler task (Windows) each started the server, which answered on port 8765; then removed by `--uninstall`. Unit file also checked with `systemd-analyze verify` |
| Docker image, hosted mode, single-user host-network mode, Compose up/down/up with the data volume | CI (ubuntu) and by hand on Debian 13 |
| Hosted mode on a LAN address (phone scenario) | By hand on Debian 13: sign-in by IP works, other host names get 421 |
| Windows app (`.exe` NSIS + `.msi`): build, Rust unit tests, silent install (`/S`, `msiexec /qn`), launch on the sign-in screen, Local mode starts the engine and it answers `/api/health`, closing the window stops it, silent uninstall | CI on **windows-latest** (`.github/workflows/desktop.yml`, screenshots saved as an artifact) |
| App sign-in, opening the account, two devices on one account seeing the same chat, My devices, admin sign-out, Local mode | By hand: the same app built on Debian 13 (Linux WebKitGTK), against a hosted server on the same machine |
| Python test suite | CI on Windows, macOS, Linux × Python 3.10 and 3.13 |
| ChromeOS, Raspberry Pi, WSL, Codespaces, BSD, Oracle Cloud, Cloudflare Tunnel, Render | **Not tested** — instructions follow each platform's documentation |
