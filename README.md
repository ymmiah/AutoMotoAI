<div align="center">

# 🤖 AutoMoto AI

**Open-Source AI Desktop Automation · Document Intelligence · Design Studio**

*Transform natural language into desktop actions, document exports, and professional AI-generated artwork — all from a single browser tab.*

[![Version](https://img.shields.io/badge/version-3.1.0-blue.svg)](https://github.com/ymmiah/automotoai)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Security](https://img.shields.io/badge/security-hardened-green.svg)](SECURITY.md)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/ymmiah/automotoai/pulls)

[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-412991.svg)](https://platform.openai.com)
[![Google](https://img.shields.io/badge/Google-Gemini_1.5-4285F4.svg)](https://ai.google.dev)
[![Anthropic](https://img.shields.io/badge/Anthropic-Claude_Opus_4.8-191919.svg)](https://anthropic.com)
[![BLACKBOX](https://img.shields.io/badge/BLACKBOX-AI-000000.svg)](https://blackbox.ai)

</div>

---

## What is AutoMoto AI?

AutoMoto AI is a **free, open-source** AI assistant that runs entirely in your browser and connects to your desktop. It combines four major AI providers into one unified interface, giving you:

- 🎨 **AI Design Studio** — generate professional images, inpaint regions with a brush, export to Photoshop/Illustrator/print formats
- 📄 **Document Intelligence** — read, summarise, combine, and export PDF · DOCX · PPTX · XLSX · CSV · Markdown
- ⚡ **Desktop Automation** — open apps, type text, press hotkeys, manage files, take screenshots
- 📊 **System Monitor** — real-time CPU / RAM / disk / network metrics and process manager
- 🛡️ **Production Security** — encrypted secrets, 2FA, tamper-evident audit log, sandboxed execution
- 🤖 **Multi-AI Chat** — streaming responses with tool-calling from GPT-4o, Gemini, Claude, or BLACKBOX AI

---

## ✨ Unique Implemented Features

### 🎨 AI Design Studio *(v3.0)*

A full-screen design environment powered by DALL-E 3 and DALL-E 2.

| Capability | Detail |
|---|---|
| **Text-to-image generation** | DALL-E 3 HD quality — 10 style presets injected into prompts automatically |
| **Style presets** | Photo · Logo · Poster · Social · Print · Icon · Product · Character · Background · Infographic |
| **Canvas sizes** | Square 1:1 · Landscape 16:9 · Portrait 9:16 |
| **Canvas inpainting** | Paint a mask with a brush directly on the generated image, then re-prompt only that area (DALL-E 2 edit) |
| **Accurate brush coordinates** | Pointer events with `scaleX/scaleY` correction — works even when the canvas is CSS-scaled |
| **Brush / eraser / clear** | Full mask editing workflow before sending the inpaint request |
| **SVG vector export** | vtracer raster→vector conversion; falls back to embedded-PNG SVG if vtracer not installed |
| **TIFF / Photoshop export** | TIFF at 300 DPI with LZW compression — drag straight into Photoshop |
| **AI / Illustrator export** | PDF/X-compatible file with embedded image — opens in Adobe Illustrator |
| **PNG print export** | PNG at 300 DPI — won't break when zoomed or printed large-format |
| **WebP export** | 90-quality WebP for optimised web delivery |
| **Lanczos upscaling** | 1× / 2× / 4× upscale applied before any export format |
| **Image gallery** | Browse and reload all generated images; click to re-open in the editor |
| **AI tool integration** | The chatbot can call `generate_image` directly when asked |

### 📄 Document Intelligence *(v3.0)*

Read, analyse, and export every common office format.

| Capability | Detail |
|---|---|
| **Multi-format reading** | PDF (pdfplumber) · DOCX · PPTX (slide text) · XLSX / XLS · CSV · Markdown · plain text · all code files |
| **Metadata extraction** | Page count · word count · row/column count · author · creation date |
| **Concurrent reading** | Up to 20 files read in parallel threads |
| **AI context injection** | Attach files in chat — full text is injected as context blocks |
| **Document creation** | Generate TXT · MD · HTML · DOCX · PDF · XLSX · CSV from AI output |
| **Format conversion** | Convert any supported format to any output format |
| **Multi-file combine** | Merge multiple documents into one output file |
| **DOCX styling** | Heading detection, bold/italic Markdown conversion in generated DOCX |
| **PDF creation** | fpdf2 with Markdown-to-text conversion, no system dependencies |
| **Download endpoint** | Secure path-sandboxed download — output restricted to `~/Documents/AutoMotoAI_Documents/` |

### 🛡️ Production Security *(new in v3.1)*

Five hardened security layers — all implemented, not just planned.

| Feature | Implementation |
|---|---|
| **Encrypted Config Storage** | Fernet AES-128-CBC + HMAC-SHA256; keys derived via PBKDF2-HMAC-SHA256 (200k iterations) from machine fingerprint; stored in `~/.automotoai/secrets.enc` (`0o600`) |
| **Two-Factor Authentication** | TOTP RFC 6238 via pyotp; protects process-kill, file-delete, app-launch; 30-minute sensitive tokens; opt-in, non-breaking |
| **Tamper-Evident Audit Log** | HMAC-SHA256 integrity chain in `logs/audit.jsonl`; every HTTP request logged; session tokens hashed (never raw); offline verification: `python -m src.core.audit --verify` |
| **Sandboxed Execution** | All 18 AI tools run in `ThreadPoolExecutor` with 60s timeout; per-session `ResourceGuard` (200 file limit, 500 MB limit); path allowlist; subprocess env stripping |
| **Auto Security Updates** | Background daemon queries PyPI JSON API on startup + every 24h; critical packages flagged at WARNING level; results at `GET /api/security/status` |

**Quick security setup:**
```bash
pip install cryptography pyotp
# Encrypt your API keys
python -c "
from dotenv import load_dotenv; load_dotenv()
from src.core.secret_store import secret_store
secret_store.migrate_from_env(['OPENAI_API_KEY','GEMINI_API_KEY','ANTHROPIC_API_KEY','BLACKBOX_API_KEY'])
"
```

See [SECURITY.md](SECURITY.md) for the complete security reference.

### 🤖 Multi-AI Chat with Tool Calling

| Capability | Detail |
|---|---|
| **4 providers** | OpenAI GPT-4o · Google Gemini 1.5 Flash · Anthropic Claude Opus 4.8 · BLACKBOX AI |
| **Current model defaults** | All defaults updated to latest 2025/2026 models |
| **Streaming SSE** | Tokens streamed token-by-token via Server-Sent Events |
| **Tool calling loop** | AI can invoke 18 tools: open apps, manage files, generate images, read documents, and more |
| **Gemini multi-turn** | Proper `role`/`parts` content format with `system_instruction` (not a flat concatenated prompt) |
| **Session management** | Server-issued session tokens — conversations persist across page refreshes |
| **Conversation history** | Multiple named conversations in the sidebar; switch between them |
| **Provider switcher** | Change AI provider mid-conversation from the topbar |

### ⚡ Desktop Automation (18 AI Tools)

| Tool | What it does |
|---|---|
| `open_application` | Launch any allowlisted app by name |
| `take_screenshot` | Capture the screen to PNG |
| `list_directory` | Browse files and folders |
| `create_file` / `create_directory` | File-system operations (with confirmation) |
| `get_system_info` | CPU · RAM · disk · network snapshot |
| `list_processes` | Top processes by CPU |
| `type_text` / `press_key` / `run_hotkey` | Keyboard simulation |
| `open_in_file_manager` | Open path in system file manager |
| `read_file` / `read_multiple_files` | Read any office/code format |
| `summarize_files` | Metadata + preview for each file |
| `combine_files` / `create_document` / `convert_document` | Document write operations |
| `generate_image` | DALL-E 3 image generation directly from chat |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- At least one AI provider API key

### Installation

```bash
git clone https://github.com/ymmiah/automotoai.git
cd automotoai

# Create virtual environment
python -m venv venv
source venv/bin/activate     # Linux / macOS
# venv\Scripts\activate      # Windows

# Install dependencies (includes security packages)
pip install -r requirements.txt

# Configure API keys
cp .env.example .env
# Edit .env and add your keys

# Launch
python main.py
```

Then open **http://127.0.0.1:5000** in your browser.

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

# Security (optional — defaults shown)
SANDBOX_TOOL_TIMEOUT=60
SECURITY_CHECK_INTERVAL_HOURS=24
```

---

## 🤖 AI Providers

| Provider | Default Model | Strengths |
|---|---|---|
| **OpenAI** | `gpt-4o` | Best overall reasoning, image generation (DALL-E) |
| **Google Gemini** | `gemini-1.5-flash` | Fast, cost-effective, long context |
| **Anthropic Claude** | `claude-opus-4-8` | Nuanced reasoning, coding, analysis |
| **BLACKBOX AI** | `blackboxai` | Developer-focused, competitive pricing |

Override any model via environment variable: `OPENAI_MODEL`, `GEMINI_MODEL`, `CLAUDE_MODEL`, `BLACKBOX_MODEL`.

---

## 🏗️ Project Structure

```
AutoMotoAI/
├── main.py                          # Entry point
├── requirements.txt                 # Dependencies
├── SECURITY.md                      # Security policy + feature docs
├── .env.example                     # Environment template
│
├── src/
│   ├── ai/
│   │   ├── base.py                  # AIProvider ABC + Message dataclass
│   │   ├── registry.py              # Multi-provider router + tool-call loop
│   │   ├── openai_provider.py       # GPT-4o chat + streaming
│   │   ├── gemini_provider.py       # Gemini multi-turn (role/parts format)
│   │   ├── claude_provider.py       # Claude streaming
│   │   ├── blackbox_provider.py     # BLACKBOX HTTP API
│   │   ├── image_generator.py       # DALL-E 3 generation + DALL-E 2 inpaint
│   │   └── tools.py                 # 18 tool definitions + sandboxed registry
│   │
│   ├── automation/
│   │   ├── desktop.py               # App launch, screenshot, file manager
│   │   ├── files.py                 # File-system CRUD
│   │   ├── input_sim.py             # Keyboard / mouse simulation
│   │   ├── monitor.py               # CPU / RAM / disk / process monitor
│   │   ├── document_reader.py       # Multi-format document reading
│   │   ├── document_writer.py       # Multi-format document writing
│   │   └── image_exporter.py        # PNG/WebP/SVG/PDF/TIFF/AI export engine
│   │
│   ├── core/
│   │   ├── config.py                # Env-var + encrypted-store configuration
│   │   ├── exceptions.py            # Custom exception hierarchy
│   │   ├── logging_config.py        # Rotating log handler setup
│   │   ├── secret_store.py          # Fernet encrypted API key storage  🔒
│   │   ├── audit.py                 # HMAC-chain audit logging            🔒
│   │   ├── totp.py                  # RFC 6238 two-factor authentication  🔒
│   │   ├── sandbox.py               # Tool execution sandbox + timeouts   🔒
│   │   └── updater.py               # Background security update checker  🔒
│   │
│   └── ui/web/
│       ├── server.py                # Flask REST API + SSE streaming
│       └── static/
│           ├── index.html           # SPA shell + Design Studio panel
│           ├── app.js               # Frontend logic (~1 400 lines)
│           └── style.css            # Catppuccin Mocha/Latte theme
```

---

## 🎨 Design Studio Walkthrough

1. Click **🎨 Design Studio** in the sidebar
2. Enter a prompt — e.g. *"Sleek electric car logo, blue lightning bolt, dark background"*
3. Choose a **Style** (Logo), **Canvas Size** (Square), and **Quality** (HD)
4. Click **✨ Generate Image** — DALL-E 3 creates your image in HD
5. **Paint a mask** with the brush over any area you want to change
6. Enter an inpaint prompt — e.g. *"Add gold trim around the lightning bolt"*
7. Click **🔧 Fix Selected Area** — DALL-E 2 regenerates only that region
8. Export to any format:
   - **PNG Print** (300 DPI) — for offset printing or large-format
   - **SVG Vector** — infinitely scalable, never pixelates
   - **TIFF/PS** (300 DPI) — drag into Photoshop
   - **AI/PDF** — drag into Adobe Illustrator
   - Use **4× Upscale** for maximum print resolution

---

## 📋 System Requirements

| Component | Minimum |
|---|---|
| OS | Windows 10/11, macOS 12+, Ubuntu 20.04+ |
| Python | 3.10 or higher |
| RAM | 4 GB (8 GB recommended) |
| Disk | 1 GB free |
| Network | Required for AI API calls |

---

## 🐛 Troubleshooting

**No AI providers available**
Add at least one `*_API_KEY` to your `.env` file.

**Image generation fails**
Requires `OPENAI_API_KEY` — DALL-E is an OpenAI product.

**SVG export has no vector conversion**
Install vtracer: `pip install vtracer`. Without it, export wraps the PNG inside an SVG envelope.

**TIFF / Pillow errors**
Install Pillow: `pip install Pillow`.

**Document format not supported**
Install optional packages: `pip install pdfplumber python-docx python-pptx openpyxl pandas fpdf2`.

**Encrypted store not working**
Install the cryptography package: `pip install cryptography`. Without it the app falls back to plain `.env`.

**2FA / TOTP errors**
Install pyotp: `pip install pyotp`. 2FA is opt-in — the app works without it.

**Sensitive operation blocked (403)**
2FA is configured and active. Call `POST /api/auth/2fa/verify` with your authenticator code to receive a `sensitive_token`, then include it in the request.

**Audit log integrity failure**
The audit log has been modified or corrupted. Check `logs/audit.jsonl` and run `python -m src.core.audit --verify` for details.

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

See [SECURITY.md](SECURITY.md) for the security model and responsible disclosure process.

---

## 📄 License

MIT — see [LICENSE](LICENSE) for details.

---

## 📞 Support

- 🐛 [Issues](https://github.com/ymmiah/automotoai/issues)
- 💬 [Discussions](https://github.com/ymmiah/automotoai/discussions)
- 🔒 Security issues: ymmiah96@gmail.com (private)
- 📧 General: ymmiah96@gmail.com

---

## 📊 Version History

### v3.1.0 — Current
- 🔒 **Encrypted Configuration Storage** — Fernet AES-128-CBC + PBKDF2-HMAC-SHA256 key derivation; API keys never plain-text on disk
- 🔒 **Two-Factor Authentication** — TOTP RFC 6238 via pyotp; protects destructive operations (kill, delete, launch)
- 🔒 **Tamper-Evident Audit Logging** — HMAC-SHA256 integrity chain; every HTTP request recorded in `logs/audit.jsonl`
- 🔒 **Sandboxed Execution** — all 18 AI tools time-boxed + resource-guarded + path-restricted in `ThreadPoolExecutor`
- 🔒 **Automatic Security Updates** — background PyPI checker with critical-package warnings at startup

### v3.0.0
- 🆕 AI Design Studio (DALL-E 3 generation + DALL-E 2 inpainting + 7 export formats)
- 🆕 Document Intelligence layer (read/write/convert 10+ formats)
- 🆕 18 AI tools including `generate_image`
- 🆕 Gemini multi-turn content format with system instruction
- 🆕 Updated all provider model defaults to latest 2025/2026 versions
- 🆕 Security hardening: CSRF, path sandboxing, upload limits, app allowlist
- 🆕 Catppuccin Mocha/Latte dual theme

### v2.1.0
- Added BLACKBOX AI as 4th provider
- HTML documentation website

### v2.0.0
- Multi-provider architecture (OpenAI · Gemini · Claude)
- Automatic provider fallback

### v1.0.0
- Initial release — OpenAI GPT-4 + core desktop automation

---

<div align="center">

**Built with ❤️ by Yasin Mohammed Miah**

[Back to Top](#-automoto-ai) · [Security](SECURITY.md) · [Issues](https://github.com/ymmiah/automotoai/issues) · [Discussions](https://github.com/ymmiah/automotoai/discussions)

</div>
