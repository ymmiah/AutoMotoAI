# AutoMoto AI - Version History & Changelog

## Version 4.0.0 "Cousin" - 27/10/2026
**Rebuild: the code now matches the README.**

### Fixed (what was broken in 2.1 / "3.1")
- `openai.ChatCompletion` (removed in openai>=1.0) replaced with the current client.
- `gemini-pro` (retired) replaced; Gemini now uses Google's OpenAI-compatible endpoint.
- Failover only happened when a provider *wasn't configured*; real errors (429, 5xx, bad key,
  timeout) were returned to the user as text. Now every failure moves to the next AI.
- `VERSION` still said 2.1.0 while the README advertised 3.1.0.
- System prompt claimed "Windows assistant"; tools now work on Windows, macOS and Linux.
- `.gitignore` ignored `test_*.py`, so tests could never be committed.
- README/SECURITY described a browser UI, voice I/O, Design Studio, 33 tools, TOTP 2FA and
  encrypted vaults that did not exist in code. Those claims are removed.

### New
- `automoto/` package: provider registry with vision flags, priority, text/vision/strong models.
- Providers: NVIDIA NIM, Google Gemini, Groq, OpenRouter (free), OpenAI, Anthropic Claude.
- `ask()` with auto-failover, `need_vision` routing, per-request BYOK keys, `tried` trail.
- Task heuristic: `classify_task()` / `recommend_provider()` (vision / code / chat).
- FastAPI local web UI with provider chips, auto mode, image paste/drop, screen explain,
  BYOK dialog (sessionStorage), and Run/Skip cards for proposed desktop actions.
- Rich CLI: chat, `ask --image`, `status`, `recommend`, `serve`.
- Desktop tools with risk levels and mandatory confirmation; shell off by default.
- `apps/desktop` Tauri 2 shell (Windows/macOS/Linux) and `apps/mobile` Flutter app
  (Android/iOS) scaffolds.
- pytest suite (mocked HTTP) + CI on Windows/macOS/Linux.

### Removed
- BLACKBOX provider (no documented public chat API).
- Legacy docs that described non-existent features (INDEX, PROJECT_SUMMARY, DOCUMENTATION,
  ARCHITECTURE.txt, setup_guide.txt, AI_PROVIDERS_GUIDE, QUICKSTART) - replaced by README.

---

> Note: README "v3.0/v3.1" entries were documentation-only; no v3 code was ever released.

## Version 2.1.0 - 11/10/2025
**Major Update: BLACKBOX AI Integration & Complete HTML Documentation**

### 🆕 New Features
- ✅ Added BLACKBOX AI as 4th AI provider
- ✅ Complete HTML/CSS documentation website
- ✅ Multi-provider automatic fallback system
- ✅ Enhanced API error handling

### 🔧 Technical Changes
- Added `requests` library to requirements.txt
- Implemented `ask_ai_blackbox()` function in main.py
- Added BLACKBOX_API_KEY to config.py
- Added BLACKBOX_API_URL configuration
- Updated test_installation.py for BLACKBOX verification
- Enhanced .env.example with 4 providers

### 📚 Documentation
- Created comprehensive HTML documentation site
- Added index.html (home page)
- Added getting-started.html (setup guide)
- Added installation.html (installation instructions)
- Added ai-providers.html (AI providers guide)
- Added features.html (features documentation)
- Added styles.css (responsive design)
- Added docs/README.md (documentation guide)

### 🐛 Bug Fixes
- Fixed Python syntax errors in actions.py
- Improved error messages for API failures
- Enhanced fallback logic for provider switching

---

## Version 2.0.0 - 11/10/2025
**Major Update: Multi-AI Provider Support**

### 🆕 New Features
- ✅ Added Google Gemini API support
- ✅ Added Anthropic Claude API support
- ✅ Multi-provider configuration system
- ✅ Automatic provider fallback
- ✅ Provider selection via environment variables

### 🔧 Technical Changes
- Refactored main.py for multi-provider support
- Added `initialize_ai_providers()` function
- Implemented `ask_ai_openai()` function
- Implemented `ask_ai_gemini()` function
- Implemented `ask_ai_claude()` function
- Added provider-specific error handling
- Updated config.py with AI_MODELS dictionary
- Added AI_TEMPERATURE and AI_MAX_TOKENS settings

### 📚 Documentation
- Created AI_PROVIDERS_GUIDE.md
- Updated README.md with multi-provider info
- Added provider comparison tables
- Added API key setup instructions

---

## Version 1.0.0 - 11/10/2025
**Initial Release: OpenAI-Powered Windows Automation**

### 🎉 Core Features
- ✅ Voice input via speech recognition
- ✅ Text input via GUI dialogs
- ✅ OpenAI GPT-4 integration
- ✅ Desktop automation with PyAutoGUI
- ✅ Application control (open/close)
- ✅ Window management (minimize/maximize)
- ✅ File and folder creation
- ✅ Screenshot capture
- ✅ Text-to-speech feedback
- ✅ Safe execution with user confirmation

### 📁 Project Structure
- Created main.py, config.py, actions.py, interaction.py, prompts.py
- Created requirements.txt, .env.example, .gitignore
- Created setup.bat, run.bat, test_installation.py
- Created comprehensive documentation files

### 📦 Dependencies
- openai, python-dotenv, pyttsx3, speechrecognition, pyautogui, pywin32

---

## Version Summary

| Version | Date | Key Features | AI Providers |
|---------|------|--------------|--------------|
| **2.1.0** | 11/10/2025 | BLACKBOX AI + HTML Docs | 4 providers |
| **2.0.0** | 11/10/2025 | Multi-AI Support | 3 providers |
| **1.0.0** | 11/10/2025 | Initial Release | 1 provider |

---

## Future Roadmap

### v2.2.0 (Planned)
- Complete remaining HTML documentation pages
- Usage guide, API reference, troubleshooting, examples

### v3.0.0 (Planned)
- Web browser automation
- Task scheduling
- Email & calendar integration
- Advanced file operations

---

**Last Updated:** 11/10/2025
**Current Version:** 2.1.0
