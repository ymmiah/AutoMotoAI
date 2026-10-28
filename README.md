<div align="center">

# 🤖 AutoMoto AI v4 — “Cousin”

**One assistant, every free AI. If one AI is down, the next one answers.**

*Multi-provider AI router with auto-failover, smart vision routing, a local web UI and
confirmed desktop actions — plus desktop (Tauri) and mobile (Flutter) app scaffolds.*

[![Version](https://img.shields.io/badge/version-4.0.0-38f2a5?style=for-the-badge)](CHANGELOG.md)
[![CI](https://img.shields.io/github/actions/workflow/status/ymmiah/AutoMotoAI/ci.yml?branch=main&style=for-the-badge&label=tests)](https://github.com/ymmiah/AutoMotoAI/actions)
[![License](https://img.shields.io/badge/license-MIT-blue?style=for-the-badge)](LICENSE)

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Rich](https://img.shields.io/badge/Rich_CLI-000000?style=for-the-badge&logo=gnometerminal&logoColor=white)
![Tauri](https://img.shields.io/badge/Tauri_2-24C8D8?style=for-the-badge&logo=tauri&logoColor=white)
![Flutter](https://img.shields.io/badge/Flutter-02569B?style=for-the-badge&logo=flutter&logoColor=white)

![NVIDIA NIM](https://img.shields.io/badge/NVIDIA_NIM-76B900?style=for-the-badge&logo=nvidia&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini-8E75B2?style=for-the-badge&logo=googlegemini&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-F55036?style=for-the-badge&logoColor=white)
![OpenRouter](https://img.shields.io/badge/OpenRouter-6566F1?style=for-the-badge&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=for-the-badge&logo=openai&logoColor=white)
![Claude](https://img.shields.io/badge/Claude-D97757?style=for-the-badge&logo=anthropic&logoColor=white)

</div>

---

## What it is

AutoMoto AI is a practical “cousin” assistant for **any project** — coding, debugging,
writing, planning, reading screenshots and photos, and (on your own computer) doing simple
desktop jobs after you confirm them.

You bring one or more API keys (four providers have free tiers). AutoMoto:

1. **Picks the best AI for the task** — vision for images/screens, strongest model for code
   and long reasoning, fastest model for quick chat.
2. **Auto-switches** to the next available AI on rate limits, 5xx errors, bad keys, timeouts
   or a model your key can't use — and tells you which AI answered and what it skipped.
3. **Never sends an image to an AI that can't see.**

### What ships in v4 (and what doesn't)

| Part | Status |
|---|---|
| Python AI router (`automoto/router.py`, `providers.py`) | ✅ Working, tested (mocked) + live-tested on NVIDIA NIM |
| CLI (`python -m automoto`) — chat, ask, status, recommend | ✅ Working |
| Local web UI (`python -m automoto serve`) — chat, provider chips, auto mode, image paste/drop, screen explain, BYOK | ✅ Working |
| Desktop tools (open app/URL, files/folders, screenshot, type, hotkey, optional shell) with confirmation | ✅ Working on Windows/macOS/Linux (GUI tools need a desktop session) |
| Desktop app — Tauri 2 shell for Windows / macOS / Linux (`apps/desktop`) | 🧱 Scaffold — build locally with Rust + Tauri CLI |
| Mobile app — Flutter for Android / iOS (`apps/mobile`) | 🧱 Scaffold — needs Flutter SDK; iOS needs Xcode; not store-ready |
| Voice I/O, image generation “Design Studio”, document export, 2FA | ❌ Not in v4 (they were listed in old v3.x docs but never existed in code) |

---

## 👁 Provider & vision matrix

Defaults chosen in Oct 2026 from each provider's model catalogue. Every model can be overridden in `.env`.

| Provider | Key | Free tier | Vision | Default text model | Vision model | Strong model (code/reasoning) | Auto priority |
|---|---|---|---|---|---|---|---|
| **NVIDIA NIM** | `NVIDIA_API_KEY` | ✅ | ✅ (1 image/request) | `meta/llama-3.2-11b-vision-instruct` | same | opt-in via `NIM_STRONG_MODEL` | 1 |
| **Google Gemini** | `GEMINI_API_KEY` | ✅ | ✅ | `gemini-flash-latest` | `gemini-flash-latest` | `gemini-pro-latest` | 2 |
| **Groq** | `GROQ_API_KEY` | ✅ | ✅ (preview model) | `openai/gpt-oss-20b` | `qwen/qwen3.8-27b` | `openai/gpt-oss-120b` | 3 |
| **OpenRouter** | `OPENROUTER_API_KEY` | ✅ `:free` | ✅ | `openrouter/free` | `google/gemma-4-31b-it:free` | `nvidia/nemotron-3-ultra-550b-a55b:free` | 4 |
| **OpenAI** | `OPENAI_API_KEY` | paid | ✅ | `gpt-5.4-mini` | `gpt-5.4-mini` | `gpt-5.5` | 5 |
| **Anthropic Claude** | `ANTHROPIC_API_KEY` | paid | ✅ | `claude-haiku-4-5` | `claude-haiku-4-5` | `claude-sonnet-4-6` | 6 |

Notes
- When a request has an image, AutoMoto switches that provider to its **vision** model (e.g. Groq's
  text model `gpt-oss-20b` is text-only, so Groq uses `qwen3.8-27b` for images). A provider with
  `supports_vision=False` is skipped entirely for image requests.
- If a strong model fails (e.g. your free key can't access it), the same provider's default
  model is tried before moving to the next provider.
- **BLACKBOX** (v2/v3) was removed: there is no documented public chat API to integrate honestly.

### How “auto” picks (task heuristic)

`recommend_provider(task_hint)` / `classify_task()` in `automoto/router.py`:

| Task | Detected by | Ranking |
|---|---|---|
| **vision** | an attached image, or words like *screenshot, on my screen, photo, OCR, receipt, design, UI, diagram* | vision-capable only, strongest first |
| **code / deep** | *code, bug, traceback, refactor, SQL, architecture, plan, analyse…* or a long prompt (>600 chars) | strongest first (Claude/OpenAI → Gemini → NIM/Groq/OpenRouter), uses strong model |
| **chat** | everything else | fastest first (Groq → Gemini/OpenAI → NIM/Claude → OpenRouter) |

Order of attempts: your `prefer` / `AI_PROVIDER` (if it has a key) → the recommended provider → every other configured provider by priority.

---

## 🚀 Quick start

```bash
git clone https://github.com/ymmiah/AutoMotoAI.git
cd AutoMotoAI
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # Windows: copy .env.example .env
# add at least one key, e.g. NVIDIA_API_KEY=nvapi-...  (free: https://build.nvidia.com)
```

Or just run `./setup.sh` (macOS/Linux) / `setup.bat` (Windows).

```bash
python -m automoto serve      # web UI → http://127.0.0.1:8765  (or ./run.sh / run.bat)
python -m automoto            # terminal chat (/image <path> to attach, /status, /exit)
python -m automoto status     # which AIs are ready + vision matrix
python -m automoto ask "Explain this error" --image screenshot.png
python -m automoto recommend "what's on my screen?"
```

No keys? You get a clear message telling you which env vars to set. One key → chat works.
Two or more → if the first fails, the next answers automatically (the UI shows
`switched: groq → nim`).

### Use it from Python

```python
from automoto.router import ask, recommend_provider

ans = ask("Write a SQL query for monthly signups", prefer="auto")
print(ans.text, ans.provider, ans.model, ans.tried)

ans = ask([{"role": "user", "content": [
    {"type": "text", "text": "Read this receipt"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
]}])                                  # routed to a vision-capable AI only
print(recommend_provider("refactor my python class"))
```

### HTTP API (shared brain for web, desktop and mobile)

| Endpoint | What |
|---|---|
| `GET /api/health` | version + OS |
| `GET/POST /api/status` | providers, keys present (never the keys), vision flags, models |
| `POST /api/chat` | `{messages, prefer, need_vision, keys?, client}` → `{text, provider, model, task, tried, actions}` |
| `POST /api/recommend` | `{task}` → which AI would handle it |
| `POST /api/actions/execute` | run one proposed action (`confirmed: true` required, this computer only) |
| `POST /api/screen/explain` | screenshot → vision AI (confirmed, this computer only) |

Interactive docs at `/api/docs` while the server runs.

---

## 🖥 Desktop actions (Windows · macOS · Linux)

Ask things like *“open notepad”*, *“create a folder called invoices”*, *“open ymmiah.com”*.
The AI proposes actions; you click **Run** (web) or type **y** (CLI). Nothing that changes your
machine runs without that.

| Tool | Risk | Notes |
|---|---|---|
| `system_info`, `list_dir` | safe | read-only |
| `open_url`, `open_app`, `create_folder`, `create_file` | confirm | `open_app` uses `start` / `open -a` / PATH + `gtk-launch`; files never overwrite |
| `screenshot`, `type_text`, `hotkey` | confirm | need `pyautogui` + a desktop session |
| `run_command` | danger | off unless `AUTOMOTO_ALLOW_SHELL=1` |

Phones never get desktop tools — the mobile app is chat + camera/photos only.

---

## 📱 Apps

### Desktop (Windows · macOS · Linux) — `apps/desktop` (Tauri 2)
A ~10 MB native window around the same web UI. It starts `python -m automoto serve` for you
and stops it when you close the window. See [apps/desktop/README.md](apps/desktop/README.md).

```bash
cd apps/desktop && npm install && npm run dev        # needs Rust + the Tauri prerequisites
npm run build                                        # .msi/.exe on Windows, .dmg/.app on macOS
```

### Mobile (Android · iOS) — `apps/mobile` (Flutter)
Chat, provider status, BYOK keys in Keychain/Keystore, camera/photo attach for vision. Talks to
your AutoMoto server over your LAN/VPN. See [apps/mobile/README.md](apps/mobile/README.md).

```bash
# on your PC
AUTOMOTO_API_TOKEN=$(python -c "import secrets;print(secrets.token_urlsafe(24))") \
  python -m automoto serve --host 0.0.0.0 --no-browser
# in apps/mobile
./tool/bootstrap.sh && flutter run
```

These are honest scaffolds: they compile from source with the usual SDKs, but signing, store
listings and production builds need your own Xcode / Android Studio setup.

---

## 🔒 Security

- **BYOK** — no keys in the repo; `.env` is git-ignored; web UI keys live in `sessionStorage` (gone on tab close); mobile keys in Keychain/Keystore.
- Keys are never logged or returned by the API.
- Local server binds `127.0.0.1`, uses a per-launch session token, and refuses network binding without `AUTOMOTO_API_TOKEN`.
- Desktop actions: fixed tool list, explicit confirmation, local-only, no delete tool, shell off by default.

Details in [SECURITY.md](SECURITY.md).

---

## 🧪 Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

All AI calls are mocked — no keys needed. Covers registry vision flags, failover when the first
provider raises, vision requests skipping non-vision providers, strong→default model fallback,
BYOK keys, key masking, action confirmation and the web API token. CI runs on Windows, macOS and Linux.

## 🗂 Layout

```
automoto/
  providers.py   provider registry (vision flags, models, priority) + transports
  router.py      ask(), auto-failover, classify_task(), recommend_provider()
  agent.py       Cousin system prompt + action parsing
  desktop.py     OS-aware desktop tools with risk levels
  server.py      FastAPI API + web UI
  cli.py         Rich CLI
  web/index.html browser UI
apps/desktop     Tauri 2 shell (Windows/macOS/Linux)
apps/mobile      Flutter app (Android/iOS)
tests/           pytest (mocked)
```

---

## 👤 Developer

**Yasin Mohammed Miah** — Student of BCU, BSc Computing Top-Up (Hons) · [@ymmiah](https://github.com/ymmiah) · [ymmiah.com](https://ymmiah.com)

Other projects: [GhostWires](https://github.com/ymmiah/GhostWires) (OSINT recon, [live](https://ghostwires.onrender.com)) ·
[AegisSec](https://github.com/ymmiah/AegisSec) (security problem registry) · [OpenSecGate](https://github.com/ymmiah/OpenSecGate)

MIT licensed — see [LICENSE](LICENSE). Contributions welcome: [CONTRIBUTING.md](CONTRIBUTING.md).
