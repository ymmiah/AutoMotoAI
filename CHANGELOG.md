# AutoMoto AI - Version History & Changelog

## Version 5.1.0 "Agent" - 28/10/2026
**A real app: AutoMoto's web UI is rebuilt as a full chat app.**

### New
- **App-style GUI** (`automoto/web/`): a sidebar with new chat, search and saved conversations (grouped by date,
  with rename and delete) and navigation to the pages. Next to it are the chat pane and an optional run-info pane
  showing status, provider, model, steps and failovers. The frontend is vanilla ES modules with no build step;
  marked, DOMPurify and highlight.js are vendored under `web/static/vendor/`, so nothing loads from a CDN.
- **Chat:** markdown with highlighted code and copy buttons, live tool-step cards (icons, arguments, results,
  timing), inline Approve / Deny cards (A / D keys), a Stop button, image paste, drag-drop and attach (shrunk in
  the browser, max 4), an Agent / Chat toggle, an Auto-first provider picker, and an answer footer with the
  provider, model, steps and failovers. Runs keep going in the background and pick up again when you reopen the
  chat.
- **Pages:**
  - Memory: add, filter and forget facts, and a journal timeline.
  - Routines: create, edit, pause or resume, run now, delete, and the last result.
  - Skills: list, view, create, edit and customise.
  - Tasks: live, with stop.
  - Tools: safety badges.
  - Settings: theme (dark, light or system), accent colour, approval mode, default mode, provider order, and
    BYOK keys kept in sessionStorage only.
- **Saved conversations** (`conversations.py`): SQLite in `AUTOMOTO_DATA_DIR`. Titles come from the first message.
  Agent runs started with `conversation_id` take their history from the database and save the answer with its
  provider, model and steps. Thinking events, oversized tool outputs and keys are never stored.
- **Settings** (`settings.py`, `GET/PUT /api/settings`): `approval_mode` overrides `AUTOMOTO_APPROVAL`, and
  `provider_order` reorders Auto failover. The API refuses anything that looks like a key, token, secret or
  password.
- **API:**
  - `/api/conversations` (list, search, create, read, rename, delete) and `/api/conversations/chat`
  - `PUT/DELETE /api/skills/{name}` (user skills only, from this computer only)
  - `PATCH /api/routines/{name}`
  - "Run now" for a routine records its last result
- **UX:**
  - Ctrl/⌘+K command palette, Ctrl/⌘+N or Ctrl/⌘+Shift+O for a new chat, Ctrl/⌘+B for the sidebar, Esc to stop
  - an empty state with suggestion chips, and toasts
  - a mobile layout (off-canvas sidebar below 760 px)
  - reduced-motion support, ARIA labels and live regions

### Security
- The index page sends a strict CSP (`script-src 'self'`, no inline scripts, `frame-ancestors 'none'`,
  `object-src 'none'`), plus `nosniff`, `no-referrer` and `no-store`. The session token moved into a meta tag.
- Model output is rendered through DOMPurify, and links open with `noopener noreferrer`.
- Everything from 5.0 is unchanged: the SSRF guard, sandbox, approvals and loopback-only desktop tools.

### Tests
- 12 new tests:
  - conversations: titles, search, history and meta slimming
  - the conversation chat and agent endpoints, checking that no BYOK key leaks into storage
  - settings validation, the approval-mode override and provider order
  - skill save and delete
  - routine PATCH and run-now recording
  - static assets and the CSP header
- 112 in total.

### Notes
- Live updates use polling (`/api/tasks/{id}?since=`), not SSE.
- The v4 screen-capture button is not in the new GUI. `/api/screen/explain` still works.
- Chrome reserves Ctrl+N for itself, so use Ctrl+Shift+O there.

## Version 5.0.0 "Agent" - 28/10/2026
**AutoMoto becomes an agent: it uses tools step by step until the job is done.**

### New
- **Agent loop** (`automoto/loop.py`): goal → AI → tool calls → approval policy → results → repeat,
  with a max-steps guard (`AUTOMOTO_MAX_STEPS`, default 12) and a summary when the limit is hit.
- **Tool calling on every provider** (`router.ask_turn`, `toolcalls.py`): native tool calls for
  OpenAI-compatible APIs (NIM, Gemini, Groq, OpenAI) and Claude (`tool_use`), plus a JSON-in-text
  protocol for models without them (OpenRouter free, or `AUTOMOTO_TOOL_MODE=text`). A rejected
  native call is retried in text mode. **Failover works mid-task**: one neutral history is
  re-rendered for whichever provider takes the next step. Providers with a rejected key are
  skipped for the rest of the run.
- **Tools**: `list_dir`, `read_file`, `write_file`, `run_shell`, `web_search` (DuckDuckGo HTML, no key),
  `fetch_url`, `remember`, `recall`, `forget`, `load_skill`, and desktop actions (`system_info`, `open_url`,
  `open_app`, `type_text`, `hotkey`).
- **Sandbox** (`sandbox.py`): a workspace jail at `~/.automoto/workspace` (symlink-safe). Shell commands run
  with the workspace as cwd, secret-free environment variables, a timeout and a process-tree kill. An optional
  Docker runner adds `--network none` and resource limits.
- **Approval policy** (`policy.py`): each call is safe, risky or blocked, with `AUTOMOTO_APPROVAL=ask|auto|readonly`,
  `AUTOMOTO_AUTO_APPROVE` and `AUTOMOTO_BLOCK_TOOLS`. Writes into `scratch/` are safe. Destructive or system
  shell commands are blocked.
- **SSRF guard** (`netguard.py`): blocks private and reserved ranges, including IPv4-mapped IPv6, NAT64, 6to4 and
  Teredo. Connections are pinned to the checked IP and redirects are re-checked. `AUTOMOTO_NET_ALLOW_CIDRS` is an
  opt-in for fake-IP DNS proxies; loopback and link-local can never be allow-listed.
- **Memory** (`memory.py`): SQLite facts plus a dated journal, injected compactly into the system prompt.
- **Skills** (`skills.py`): `SKILL.md` folders in `~/.automoto/skills`, with four bundled examples.
- **Routines** (`routines.py`): interval or 5-field cron schedules. They run while `serve` is up, are logged to
  `routines.log` and the journal, and risky tools are auto-denied.
- **Background tasks** (`tasks.py`): every web agent run is a thread with streamed events, Approve/Deny and cancel.
- **MCP client** (`mcp.py`): stdio servers from `~/.automoto/mcp.json`, exposed as `mcp__server__tool`.
- **Web UI**: Agent/Chat toggle, collapsible tool steps, approval cards, and a side panel with tasks, memory,
  routines, tools and skills. BYOK keys are still kept in sessionStorage only.
- **CLI**: agent chat by default (`--plain` for v4 chat), plus `do`, `routines`, `memory`, `skills` and `tools`.
- 74 new tests (100 total). CI also smoke-tests the new CLI commands.

### Changed
- NIM's first model for agent steps is `nvidia/nemotron-3.5-super-vl-120b-a12b` (`NIM_AGENT_MODEL`), and Groq's is
  `openai/gpt-oss-120b`. Plain chat keeps the v4 defaults.
- The desktop app scaffold version was bumped to 5.0.0. The mobile app still uses the plain-chat API.

### Known limits
- Native tool calling on Gemini, Groq, OpenAI and Claude is implemented and unit-tested but not yet live-tested.
- The Docker runner has not been tested on a machine with Docker.
- The local (non-Docker) sandbox is a cwd jail with command checks, not OS-level isolation.
- No Playwright browser tool yet.

---

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
