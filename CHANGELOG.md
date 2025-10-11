# AutoMoto AI - Version History & Changelog

## Version 2.1.0 (Current) - 11/10/2025
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
