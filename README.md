<div align="center">

# 🤖 AutoMoto AI

**Open-Source AI Desktop Automation · Document Intelligence · Design Studio · Voice I/O**

*Transform natural language into desktop actions, document exports, professional AI-generated artwork, and spoken responses — all from a single browser tab.*

[![Version](https://img.shields.io/badge/version-3.1.0-blue.svg)](https://github.com/ymmiah/automotoai)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/ymmiah/automotoai/pulls)
[![Security](https://img.shields.io/badge/security-v3.1-success.svg)](SECURITY.md)

[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-412991.svg)](https://platform.openai.com)
[![Google](https://img.shields.io/badge/Google-Gemini_1.5-4285F4.svg)](https://ai.google.dev)
[![Anthropic](https://img.shields.io/badge/Anthropic-Claude_Opus_4.8-191919.svg)](https://anthropic.com)
[![BLACKBOX](https://img.shields.io/badge/BLACKBOX-AI-000000.svg)](https://blackbox.ai)

</div>

---

## What is AutoMoto AI?

AutoMoto AI is a **free, open-source** AI assistant that runs in your browser and connects to your real desktop — Windows, macOS, and Linux. It combines four AI providers in one unified interface:

- 🎨 **AI Design Studio** — generate professional images, inpaint regions with a brush, export to Photoshop / Illustrator / print formats
- 📄 **Document Intelligence** — read, summarise, combine, and export PDF · DOCX · PPTX · XLSX · CSV · Markdown
- 🎙️ **Voice I/O** — text-to-speech AI responses with auto-speak, real-time speech recognition, audio file transcription
- ⚡ **Desktop Automation** — open apps, type text, manage windows, take screenshots, show GUI dialogs — **real Linux support** via xdotool / wmctrl
- 🔒 **Production Security** — encrypted API key storage, TOTP 2FA, tamper-evident audit logs, sandboxed execution, automatic update checks
- 📊 **System Monitor** — real-time CPU / RAM / disk / network metrics and process manager
- 🤖 **Multi-AI Chat** — streaming responses with tool-calling across GPT-4o, Gemini, Claude, or BLACKBOX AI

---

## ✨ Unique Implemented Features

### 🎙️ Voice I/O *(new in v3.1)*

Real text-to-speech and speech-to-text — no cloud lock-in, works offline.

| Capability | Detail |
|---|---|
| **Text-to-speech** | pyttsx3 → espeak → flite → festival (automatic fallback chain) |
| **Speech-to-WAV file** | Server generates a WAV file served at `/api/voice/audio/<file>` |
| **Speech Recognition (browser)** | Web Speech API — real-time interim results shown while speaking, auto-sends on recognition end |
| **Microphone transcription (server)** | SpeechRecognition + PyAudio with dynamic energy calibration |
| **Audio file transcription** | OpenAI Whisper API → local whisper model → Google STT fallback |
| **Auto-speak toggle** | 🔇/🔊 button in topbar — AI replies read aloud automatically via browser TTS |
| **Voice settings** | Language (10 locales), speed (0.75× – 1.5×), auto-speak — all persisted in localStorage |
| **Multi-language** | en-US, en-GB, fr, de, es, it, pt-BR, ja, zh-CN, ar |
| **AI tool integration** | `speak` and `transcribe_audio` tools let the AI synthesize and transcribe directly |

**Linux setup:**
```bash
sudo apt install espeak          # TTS (offline, no internet needed)
sudo apt install flite           # lightweight TTS alternative
sudo apt install python3-pyaudio portaudio19-dev && pip install pyaudio  # microphone
```

---

### 🎨 AI Design Studio *(new in v3.0)*

A full-screen design environment powered by DALL-E 3 and DALL-E 2.

| Capability | Detail |
|---|---|
| **Text-to-image generation** | DALL-E 3 HD quality — 10 style presets injected into prompts automatically |
| **Style presets** | Photo · Logo · Poster · Social · Print · Icon · Product · Character · Background · Infographic |
| **Canvas sizes** | Square 1:1 · Landscape 16:9 · Portrait 9:16 |
| **Canvas inpainting** | Paint a mask with a brush directly on the generated image, re-prompt only that area (DALL-E 2 edit) |
| **Accurate brush coordinates** | Pointer events with `scaleX/scaleY` correction — works even when the canvas is CSS-scaled |
| **SVG vector export** | vtracer raster→vector conversion; falls back to embedded-PNG SVG if vtracer not installed |
| **TIFF / Photoshop export** | TIFF at 300 DPI with LZW compression — drag straight into Photoshop |
| **AI / Illustrator export** | PDF/X-compatible file with embedded image — opens in Adobe Illustrator |
| **PNG print export** | PNG at 300 DPI — won't break when zoomed or printed large-format |
| **WebP export** | 90-quality WebP for optimised web delivery |
| **Lanczos upscaling** | 1× / 2× / 4× upscale applied before any export format |
| **Image gallery** | Browse and reload all generated images; click to re-open in the editor |
| **AI tool integration** | The chatbot can call `generate_image` directly when asked |

---

### 📄 Document Intelligence *(new in v3.0)*

| Capability | Detail |
|---|---|
| **Multi-format reading** | PDF · DOCX · PPTX · XLSX / XLS · CSV · Markdown · plain text · all code files |
| **Metadata extraction** | Page count · word count · row/column count · author · creation date |
| **Concurrent reading** | Up to 20 files read in parallel threads |
| **AI context injection** | Attach files in chat — full text injected as context blocks |
| **Document creation** | Generate TXT · MD · HTML · DOCX · PDF · XLSX · CSV from AI output |
| **Format conversion** | Convert any supported input to any output format |
| **Multi-file combine** | Merge multiple documents into one output file |
| **Download endpoint** | Path-sandboxed download — output restricted to `~/Documents/AutoMotoAI_Documents/` |

---

### 🔒 Production Security *(new in v3.1)*

Five security modules fully implemented — not placeholders.

| Feature | Module | How it works |
|---|---|---|
| **Encrypted API key storage** | `src/core/secret_store.py` | Fernet (AES-128-CBC + HMAC-SHA256) with PBKDF2-HMAC-SHA256 (200 000 iter) key derived from machine fingerprint; stored at `~/.automotoai/secrets.enc` |
| **Two-factor authentication** | `src/core/totp.py` | TOTP RFC 6238 via pyotp; protects `/api/monitor/kill`, `/api/files/delete`, `/api/apps/launch`; 30-minute sensitive token TTL |
| **Tamper-evident audit log** | `src/core/audit.py` | HMAC-SHA256 chain at `logs/audit.jsonl` — every entry's MAC covers content + previous MAC; verifiable offline with `python -m src.core.audit --verify` |
| **Sandboxed tool execution** | `src/core/sandbox.py` | ThreadPoolExecutor with configurable timeout (60 s default); per-session `ResourceGuard` (200 file writes / 500 MB); path allowlist; subprocess env stripping |
| **Automatic update checks** | `src/core/updater.py` | Background daemon polls PyPI JSON API every 24 hours; critical packages flagged at WARNING; results at `GET /api/security/status` |

**Quick security setup:**
```bash
pip install cryptography pyotp qrcode[pil]

# Migrate existing .env keys to encrypted store
python -c "
from dotenv import load_dotenv; load_dotenv()
from src.core.secret_store import secret_store
secret_store.migrate_from_env(['OPENAI_API_KEY','GEMINI_API_KEY','ANTHROPIC_API_KEY','BLACKBOX_API_KEY'])
"

# Enable 2FA
curl -X POST http://127.0.0.1:5000/api/auth/2fa/setup \
  -H "X-Requested-With: XMLHttpRequest" -H "Content-Type: application/json" -d '{}'
```

See [SECURITY.md](SECURITY.md) for full documentation.

---

### ⚡ Desktop Automation — Real Linux Support *(upgraded in v3.1)*

Full cross-platform automation — **no mocking, no stubs**.

#### Window Management

| Platform | Backend |
|---|---|
| Windows | pygetwindow |
| Linux (X11) | wmctrl primary → xdotool fallback |
| Linux (Wayland) | ydotool |
| macOS | AppleScript via `osascript` |

```bash
# Linux one-time setup
sudo apt install wmctrl xdotool          # window management
sudo apt install ydotool                 # Wayland support
```

#### Screenshots — 6 backends tried in order

```
pyautogui → scrot → gnome-screenshot → maim → ImageMagick import → xwd+convert
```

```bash
sudo apt install scrot         # lightweight, fastest
sudo apt install maim          # modern scrot replacement
```

#### Keyboard & Mouse — 3-tier fallback

```
pyautogui  →  xdotool  →  ydotool (Wayland)
```

New actions: `scroll()`, `drag()`, `click()` all with xdotool fallback.

#### GUI Dialogs — Real native dialogs

| Backend | Trigger |
|---|---|
| tkinter | Built-in Python; used when `DISPLAY`/`WAYLAND_DISPLAY` is set |
| zenity | GNOME fallback (`sudo apt install zenity`) |
| kdialog | KDE fallback |
| Log fallback | Headless servers: action is logged instead of crashing |

```bash
sudo apt install zenity        # GNOME dialog fallback
```

#### Installed App Discovery

| Platform | Source |
|---|---|
| Linux | XDG `.desktop` files → dpkg → rpm → flatpak → snap |
| Windows | Registry (HKLM + HKCU Uninstall keys) |
| macOS | `/Applications` + Homebrew |

---

### 🤖 Multi-AI Chat with Tool Calling

33 AI tools the assistant can call autonomously:

| Category | Tools |
|---|---|
| **Desktop** | `open_application`, `take_screenshot`, `list_directory`, `create_file`, `create_directory`, `open_in_file_manager` |
| **Input** | `type_text`, `press_key`, `run_hotkey`, `mouse_click`, `mouse_scroll`, `mouse_drag` |
| **Windows** | `list_windows`, `focus_window`, `minimize_window`, `maximize_window`, `close_window` |
| **Dialogs** | `show_dialog`, `ask_yes_no`, `ask_input_dialog`, `open_file_dialog`, `save_file_dialog` |
| **Voice** | `speak`, `listen`, `transcribe_audio` |
| **Monitor** | `get_system_info`, `list_processes` |
| **Documents** | `read_file`, `read_multiple_files`, `summarize_files`, `combine_files`, `create_document`, `convert_document` |
| **Design** | `generate_image` |

| Provider | Default Model | Strengths |
|---|---|---|
| **OpenAI** | `gpt-4o` | Best reasoning, image generation (DALL-E) |
| **Google Gemini** | `gemini-1.5-flash` | Fast, cost-effective, long context |
| **Anthropic Claude** | `claude-opus-4-8` | Nuanced reasoning, coding, analysis |
| **BLACKBOX AI** | `blackboxai` | Developer-focused |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- At least one AI provider API key

### Installation

```bash
git clone https://github.com/ymmiah/automotoai.git
cd automotoai

python -m venv venv
source venv/bin/activate      # Linux / macOS
# venv\Scripts\activate       # Windows

pip install -r requirements.txt

cp .env.example .env
# Edit .env — add your API keys

python main.py
```

Open **http://127.0.0.1:5000** in your browser.

### Optional Linux dependencies

```bash
# Window management
sudo apt install wmctrl xdotool

# Screenshots
sudo apt install scrot maim

# TTS / voice
sudo apt install espeak
sudo apt install python3-pyaudio portaudio19-dev && pip install pyaudio

# GUI dialogs
sudo apt install python3-tk zenity

# Security extras
pip install cryptography pyotp qrcode[pil]
```

### .env configuration

```env
# AI providers — add the ones you have
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
BLACKBOX_API_KEY=...

# Defaults
DEFAULT_AI_PROVIDER=openai
OPENAI_MODEL=gpt-4o
GEMINI_MODEL=gemini-1.5-flash
CLAUDE_MODEL=claude-opus-4-8

# Security
SECURITY_CHECK_INTERVAL_HOURS=24
SANDBOX_TOOL_TIMEOUT=60
SANDBOX_MAX_FILES=200
SANDBOX_MAX_BYTES=524288000

# Server
WEB_HOST=127.0.0.1
WEB_PORT=5000
```

---

## 🏗️ Project Structure

```
AutoMotoAI/
├── main.py
├── requirements.txt
├── SECURITY.md                          # Full security documentation
│
├── src/
│   ├── ai/
│   │   ├── base.py                      # AIProvider ABC + Message dataclass
│   │   ├── registry.py                  # Multi-provider router + tool-call loop
│   │   ├── openai_provider.py           # GPT-4o chat + streaming
│   │   ├── gemini_provider.py           # Gemini multi-turn (role/parts format)
│   │   ├── claude_provider.py           # Claude streaming
│   │   ├── blackbox_provider.py         # BLACKBOX HTTP API
│   │   ├── image_generator.py           # DALL-E 3 generation + DALL-E 2 inpaint
│   │   └── tools.py                     # 33 tool definitions + registry
│   │
│   ├── automation/
│   │   ├── desktop.py                   # App launch · window mgmt · screenshots (cross-platform)
│   │   ├── files.py                     # File-system CRUD
│   │   ├── input_sim.py                 # Keyboard / mouse · xdotool / ydotool fallbacks
│   │   ├── monitor.py                   # CPU / RAM / disk / process monitor
│   │   ├── voice.py                     # 🆕 TTS (pyttsx3/espeak/flite) + STT (Whisper/Google)
│   │   ├── dialog.py                    # 🆕 GUI dialogs (tkinter / zenity / kdialog)
│   │   ├── document_reader.py           # Multi-format document reading
│   │   ├── document_writer.py           # Multi-format document writing
│   │   └── image_exporter.py            # PNG/WebP/SVG/PDF/TIFF/AI export engine
│   │
│   ├── core/
│   │   ├── config.py                    # Env config + encrypted secret store integration
│   │   ├── exceptions.py                # Custom exception hierarchy
│   │   ├── secret_store.py              # 🔒 Fernet encrypted API key storage
│   │   ├── audit.py                     # 🔒 HMAC-SHA256 tamper-evident audit log
│   │   ├── totp.py                      # 🔒 TOTP 2FA for sensitive operations
│   │   ├── sandbox.py                   # 🔒 Tool execution sandbox + resource limits
│   │   └── updater.py                   # 🔒 Background PyPI security update checker
│   │
│   └── ui/web/
│       ├── server.py                    # Flask REST API + SSE streaming (60+ endpoints)
│       └── static/
│           ├── index.html               # SPA shell + Design Studio + voice controls
│           ├── app.js                   # Frontend logic (~1 350 lines)
│           └── style.css                # Catppuccin Mocha/Latte theme
```

---

## 🎨 Design Studio Walkthrough

1. Click **🎨 Design Studio** in the sidebar
2. Enter a prompt — e.g. *"Sleek electric car logo, blue lightning bolt, dark background"*
3. Choose **Style** (Logo), **Canvas Size** (Square), **Quality** (HD)
4. Click **✨ Generate Image** — DALL-E 3 creates the image
5. **Paint a mask** over any area you want to change
6. Enter an inpaint prompt — *"Add gold trim around the lightning bolt"*
7. Click **🔧 Fix Selected Area** — DALL-E 2 regenerates only that region
8. Export:
   - **PNG Print** (300 DPI) — for offset printing / large-format
   - **SVG Vector** — infinitely scalable
   - **TIFF/PS** (300 DPI) — drag into Photoshop
   - **AI/PDF** — drag into Adobe Illustrator
   - **4× Upscale** for maximum resolution

---

## 🔒 Security API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/auth/2fa/setup` | POST | Generate TOTP secret + QR code URI |
| `/api/auth/2fa/verify` | POST | Verify TOTP code → get sensitive token |
| `/api/auth/2fa/status` | GET | Check if 2FA is enabled |
| `/api/security/status` | GET | Sandbox config + update report |
| `/api/security/audit/verify` | GET | Verify audit log integrity chain |
| `/api/security/secrets/migrate` | POST | Migrate `.env` keys to encrypted store |
| `/api/voice/status` | GET | TTS / STT backend availability |
| `/api/voice/speak` | POST | Synthesize text → WAV file |
| `/api/voice/transcribe` | POST | Transcribe uploaded audio file |
| `/api/window/list` | GET | List open windows |
| `/api/window/focus` | POST | Focus window by title |
| `/api/dialog/message` | POST | Show native GUI message dialog |
| `/api/desktop/status` | GET | Desktop automation capability map |

---

## 📋 System Requirements

| Component | Minimum |
|---|---|
| OS | Windows 10/11 · macOS 12+ · Ubuntu 20.04+ |
| Python | 3.10 or higher |
| RAM | 4 GB (8 GB recommended) |
| Disk | 1 GB free |
| Network | Required for AI API calls |
| Display | Optional — headless servers supported (voice + file ops work without display) |

---

## 🐛 Troubleshooting

**No AI providers available**
Add at least one `*_API_KEY` to your `.env` file.

**Image generation fails**
Requires `OPENAI_API_KEY` — DALL-E is an OpenAI product.

**Voice recognition not working (browser)**
Use Chrome or Edge — Web Speech API is not supported in Firefox.

**TTS has no audio (server)**
Install espeak: `sudo apt install espeak` — or `pip install pyttsx3`.

**Microphone not working**
Install PyAudio: `sudo apt install python3-pyaudio portaudio19-dev && pip install pyaudio`.

**Window management fails on Linux**
Install wmctrl or xdotool: `sudo apt install wmctrl xdotool`.

**Screenshots fail on Linux**
Install scrot: `sudo apt install scrot`. Make sure `DISPLAY` is set.

**GUI dialogs don't appear**
Install tkinter (`sudo apt install python3-tk`) or zenity (`sudo apt install zenity`). Set `DISPLAY=:0` if running remotely.

**No display / headless server**
Desktop automation, screenshots, and GUI dialogs need `DISPLAY` set. All other features (AI chat, documents, voice synthesis to file, security, monitoring) work headless.

**SVG export has no vector conversion**
Install vtracer: `pip install vtracer`. Without it, export wraps the PNG inside an SVG envelope.

**2FA setup fails**
Install `pip install pyotp qrcode[pil]`.

**Security / encryption errors**
Install `pip install cryptography`.

---

## 🤝 Contributing

Contributions are welcome — bug fixes, new AI providers, additional export formats, UI improvements.

```bash
git clone https://github.com/ymmiah/automotoai.git
cd automotoai
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```

---

## 📄 License

MIT — see [LICENSE](LICENSE) for details.

---

## 📞 Support

- 🐛 [Issues](https://github.com/ymmiah/automotoai/issues)
- 💬 [Discussions](https://github.com/ymmiah/automotoai/discussions)
- 🔒 [Security](SECURITY.md)
- 📧 ymmiah96@gmail.com

---

## 📊 Version History

### v3.1.0 — Current
- 🆕 **Voice I/O** — TTS (pyttsx3 / espeak / flite fallback chain) + STT (Whisper API / Google)
- 🆕 **Auto-speak** — 🔇/🔊 toggle reads every AI reply aloud via browser Speech Synthesis
- 🆕 **Speech Recognition** — real-time interim results, multi-language, auto-send on end
- 🆕 **GUI dialogs** — tkinter / zenity / kdialog with graceful headless fallback
- 🆕 **Linux window management** — wmctrl + xdotool: focus, minimize, maximize, close, move/resize
- 🆕 **Multi-backend screenshots** — pyautogui → scrot → gnome-screenshot → maim → ImageMagick
- 🆕 **Linux app discovery** — XDG .desktop files + dpkg/rpm/flatpak/snap
- 🆕 **xdotool / ydotool input fallback** — keyboard/mouse work without pyautogui when DISPLAY is set
- 🆕 **15 new AI tools** — voice, window, dialog, mouse click/scroll/drag
- 🆕 **Encrypted API key storage** — Fernet AES-128 + PBKDF2 (200k iterations)
- 🆕 **TOTP 2FA** — protects kill/delete/launch operations
- 🆕 **Tamper-evident audit log** — HMAC-SHA256 chain
- 🆕 **Sandboxed tool execution** — timeout + resource limits + path allowlist
- 🆕 **Automatic security update checks** — background PyPI daemon

### v3.0.0
- 🆕 AI Design Studio (DALL-E 3 generation + DALL-E 2 inpainting + 7 export formats)
- 🆕 Document Intelligence (read/write/convert 10+ formats)
- 🆕 18 AI tools including `generate_image`
- 🆕 Gemini multi-turn content format with system instruction
- 🆕 Updated all provider model defaults to latest 2025/2026 versions
- 🆕 Security hardening: CSRF, path sandboxing, upload limits, app allowlist

### v2.1.0
- Added BLACKBOX AI as 4th provider

### v2.0.0
- Multi-provider architecture (OpenAI · Gemini · Claude)

### v1.0.0
- Initial release — OpenAI GPT-4 + core desktop automation

---

<div align="center">

**Built with ❤️ by Yasin Mohammed Miah**

[Back to Top](#-automoto-ai) · [Issues](https://github.com/ymmiah/automotoai/issues) · [Security](SECURITY.md) · [Discussions](https://github.com/ymmiah/automotoai/discussions)

</div>