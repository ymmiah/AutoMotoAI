# AutoMoto AI - Version History & Changelog

## Version 5.5.0 "Agent" - 28/10/2026
**Let other people use AutoMoto: an opt-in hosted multi-user mode with a 1-hour daily limit you control, plus a release you can download.**

### New
- **Hosted multi-user mode** (`AUTOMOTO_MODE=multiuser`, `serve --hosted`). Single-user local mode stays the
  default and is unchanged.
  - **Accounts:** sign up / sign in with scrypt-hashed passwords. Sign-up is invite-only by default; the admin
    can switch to open or closed. Invite links (`/?invite=am-…`) with a use count and expiry.
  - **Sessions:** HttpOnly, SameSite=Strict (Secure on HTTPS) cookies stored as hashes, per-session CSRF
    token plus Origin check, rate limits on sign-in/sign-up, 15-minute lockout after 5 wrong passwords.
  - **Usage quota:** 60 minutes of active usage per day by default (`AUTOMOTO_DEFAULT_QUOTA_MINUTES`). Active
    usage = model-call time + tool time (approval waits excluded). Daily reset at a configurable UTC hour, or
    weekly. Optional request and estimated-token caps. Checked on the server before every model call; a run
    that hits the limit stops with a friendly "limit reached, resets at …" card, and the sidebar shows a meter.
  - **Admin (owner) control:** `automoto admin create` or `AUTOMOTO_ADMIN_USER`/`_PASSWORD`. Admin page and CLI
    to list users and usage, set a personal limit or unlimited, give bonus minutes (expire at the next reset),
    reset usage, suspend/unsuspend, delete (with their files), change defaults, toggle sign-up, create
    invites, read the usage and audit logs. Role checks on the server, self-protection, audit log.
  - **Hosted safety:** per-user workspace, memory, skills, conversations and tasks; tools limited to web,
    memory, skills, Office, archive, WordPress and data; no shell, apps, desktop, folders, MCP or connector
    secrets; approvals forced to ask; 20 MB uploads, 200 MB storage and 2 concurrent runs per user; a route
    allow-list closes every endpoint not reviewed for hosted use.
  - **Account page:** remaining time, limits and password change.
- **Docker image** (`Dockerfile`, non-root, `/data` volume, poppler/PHP/7-Zip, optional LibreOffice) and a
  Render blueprint. **docs/HOSTING.md** compares free hosts honestly (which keep data, which aren't free).
  Public host names from Render / Koyeb / Hugging Face are allowed automatically.
- **Publishing:** GitHub Release with the `.vsix`, wheel and sdist. A `Publish` workflow on version tags pushes
  to the VS Code Marketplace / Open VSX when `VSCE_PAT` / `OVSX_PAT` exist (skips otherwise) and to PyPI by
  trusted publishing when `PYPI_PUBLISH=true`. **docs/PUBLISHING.md** has the exact steps.
- **Packaging:** SPDX license, project URLs and classifiers in `pyproject.toml`; the extension has gallery
  banner, pricing and issue links for the stores.
- `POST /api/files/delete` (both modes).

### Tests
- `tests/test_multiuser.py` (23 tests): hashing, sign-up modes and invites, cookie flags, lockout and rate
  limits, CSRF/Origin, the route allow-list across every route, master tokens disabled, local mode has no
  accounts API, admin role checks and actions, quota maths (bonus expiry, reset hour, weekly, caps), agent and
  chat stopping on quota, per-user task limit, isolation of files/chats/memory/tasks, hosted tool set,
  upload/storage limits, env bootstrap, CLI admin, platform host names.
- CI: new `docker` job builds the image and smoke-tests hosted mode.

### Live-tested
- Multi-user server on the box with an admin and two users: one user ran NIM agent tasks until her
  1-minute limit stopped her (limit card and meter); the admin gave the other user 30 bonus minutes from the
  Admin page; the user saw the new allowance.

## Version 5.4.0 "Agent" - 28/10/2026
**ZIP and other archives, WordPress plugins and themes, and CSV and other data files: extract, work on them and repack.**

### New
- **Archive tools** (group `archive`): `archive_list`, `archive_inspect`, `archive_read`, `archive_extract`,
  `archive_create`, `archive_repack` and `download_file`.
  - zip, tar, tar.gz/tgz, tar.bz2, tar.xz and single-file .gz can be listed, extracted and created.
  - 7z and rar are extract-only, through py7zr, unar or the 7z CLI when installed (status shown in
    `archive_inspect`).
  - Repacks are deterministic. You choose the top-level folder, and `.git`, `node_modules`, `.DS_Store`,
    `__MACOSX` and `.env` are excluded by default.
  - `download_file` fetches through the SSRF guard (100 MB cap), and downloaded archives are checked on arrival.
- **WordPress tools** (group `wordpress`): `wp_validate`, `wp_security_review`, `wp_bump_version`,
  `wp_add_guard` and `wp_package`.
  - **Plugin checks:** slug folder, `Plugin Name` header, `readme.txt` headers and Stable tag, no dev files.
  - **Theme checks:** `style.css` header, `index.php` or block templates, `theme.json`, screenshot, Text Domain.
  - **Lint and review:** `php -l` on every PHP file, a heuristic security checklist, and phpcs/WPCS when
    installed.
  - **Version bump:** updates the header, `@version` tags, VERSION constants, the Stable tag and the changelog.
  - **Guard and package:** inserts an ABSPATH guard (CRLF kept) and builds an installable zip with the slug as
    its top-level folder.
- **Data tools** (group `data`): `data_inspect`, `data_query`, `data_convert`, `data_read`, `sqlite_query`,
  `text_search`, `text_tail`, `pdf_text` and `image_info`.
  - **CSV/TSV:** encoding sniffing (including a cp1252 heuristic), plus delimiter, header and decimal-comma
    detection.
  - **Querying:** dd/mm and ISO dates, and filter/sort/group/aggregate with pandas.
  - **Derived columns:** a safe expression language, e.g. `[Units] * [Price]` and `yearmonth(Date)`.
  - **Other formats:** Excel, JSON/JSONL, YAML, TOML, XML, Parquet and read-only SQLite.
  - **Text and media:** Markdown outline, log tail/grep/summary, image metadata and PDF text.
  - **Outputs:** CSV, TSV, xlsx, JSON, JSONL, Parquet and Markdown.
- **Three skills:** `zip-archives`, `wordpress-plugins-themes` and `data-files`, for 42 skills in total.
- **Web app:**
  - **Uploads:** the Files page and 📎 accept zip/tar/7z/csv/tsv/json/yaml/xml/parquet/sqlite/log/md files up to
    50 MB. Archives are inspected on upload and unsafe ones are refused.
  - **Viewers:** an archive tree, a CSV/Excel table preview with row counts, a JSON/YAML outline and a text view.
  - **Actions:** Extract, "Clean zip" (deterministic repack) and Zip-folder buttons.
  - **API:** `GET /api/files/inspect` and `POST /api/files/archive`.
- **VS Code:** **AutoMoto: Repack folder as ZIP** and **AutoMoto: Validate WordPress plugin/theme** (command
  palette and Explorer context menu).
- **Dependencies:** PyYAML and tomli (Python < 3.11) are required. The optional `data` extra adds pyarrow, py7zr and
  tomli-w.

### Security
- **Archive safety:**
  - Zip-slip, absolute, drive-letter, `..` and NUL names are refused.
  - Symlink, hardlink and device members are skipped.
  - Bomb limits (bytes, files, ratio, nesting) are counted while streaming.
  - Extraction goes into a temp folder and is moved into place only on success.
  - Zip passwords are used only when you give one and are masked in events.
- `download_file` taints the run, so later risky calls ask again. Archive and data tool output is fenced as
  untrusted.
- **Data safety:**
  - YAML uses `safe_load` and XML uses defusedxml (no DTDs).
  - SQLite is read-only and immutable, with an authorizer and a time limit.
  - Pillow's pixel limit applies.
  - xlsx output writes `=`/`+`/`-`/`@` cells as text (no formula injection).
- **New:** every HTTP request now has a total deadline. A live run found a download that stalled for minutes, so `download_file`
  now also retries a throttled connection (under 32 KB/s after 15 s) up to 3 times.

### Tests
- New tests:
  - 31 archive tests (malicious zips and tars: traversal, absolute, symlink, hardlink, bombs, a lying gzip size,
    nested bombs, encrypted, cp437 names, 7z, the files API, a download deadline and a retry for throttled downloads)
  - 13 WordPress tests (including CRLF files)
  - 13 data tests (including Parquet, decimal commas and derived columns)
- **Total:** 296 tests.
- **CI:** the `office` job also installs PHP and 7-Zip, adds pyarrow and py7zr, and runs these suites with no
  skips.
- **Live (NVIDIA NIM, Nemotron 3.5 Super VL):** the agent ran three tasks, with samples in
  `automoto-archive-samples/`.
  - **Download:** it downloaded the real hello-dolly 1.7.2 zip and inspected it.
  - **Edit and repack:** it bumped hello-dolly to 1.8.0, added the ABSPATH guard, escaped the lyric output and
    repacked it as an installable zip.
  - **CSV analysis:** it analysed a cp1252, `;`-delimited, decimal-comma CSV (revenue by region and month, top
    products, missing units) into xlsx/csv/json. The figures matched an independent pandas check.
- **Live validation:** the real Twenty Twenty-Four 1.6 theme passed validation.
- **Bugs found and fixed in those runs:** `@version` docblock tags were not bumped, aggregate sums showed float
  noise, and a stalled download could hang the agent.

### Limitations
- rar is not tested and cannot be created. Creating 7z is not supported. AES-encrypted zips need py7zr or 7z.
- phpcs/WPCS and the official Plugin Check are optional and were not installed here (the result reports this).
  The security checklist is heuristic.
- A zip password is visible to the model in its own tool call (it is masked in the event log).
- Uploads are capped at 50 MB. Large data files are capped by size and rows (configurable).

## Version 5.3.0 "Agent" - 28/10/2026
**A free Office suite: Word, Excel, PowerPoint and PDF, up to publication standard.**

### New
- **Office tools** (group `office`): `office_create_docx`, `office_create_xlsx`, `office_create_pptx`,
  `office_read`, `office_edit`, `office_convert`, `office_recalc`, `office_render`, `office_check` and
  `office_review`. They are built on python-docx, openpyxl, python-pptx and pypdf, with LibreOffice headless
  for PDF export, legacy `.doc/.xls/.ppt/.rtf` and OpenDocument, and formula recalculation, and poppler for
  page renders. No Microsoft Office is needed.
- **Word:** A4/Letter, title page, a contents page with real page numbers (two passes through LibreOffice,
  headings matched as whole lines), Heading 1-3, lists, tables with numbered captions and repeating header rows,
  images with alt text and "Figure n" captions, header, "Page X of Y" footer, comments, and Harvard references
  (Cite Them Right style, sorted, hanging indent). Also a Markdown → docx/pdf fallback when pandoc is missing.
- **Excel:** formulas, number formats, conditional formatting, validation lists, charts with explicit colours
  (so LibreOffice draws them filled), frozen header, autofilter, named ranges and landscape fit-to-width printing.
  `office_recalc` recalculates every formula and lists values and errors.
- **PowerPoint:** 16:9 with the template's placeholders widened correctly, one theme, ten layouts (title,
  section, bullets, two-content, comparison, image, table, chart, statement, quote), slide numbers, footer and
  speaker notes. Empty placeholders are removed.
- **Lint (`office_check`):** heading hierarchy and duplicates, alt text, TOC placeholders, broken
  cross-references, document title, formula errors and missing sheets, approximate slide text overflow, small
  fonts, off-slide shapes, missing notes, and PDF fonts embedded / tagged / title / bookmarks.
- **Vision review (`office_review`):** renders up to 6 pages into one contact sheet (works with one-image
  models) and asks a vision model for a layout critique. On NIM it uses Nemotron VL first ("careful" mode),
  with Llama 3.2 Vision as the fallback. The review is advisory.
- **Six skills:** `word-documents`, `excel-spreadsheets`, `powerpoint-decks`, `publication-ready-pdf`,
  `google-docs-sheets-slides` and `microsoft-365-office` (39 skills in total).
- **Cloud office services:** `google-docs`, `google-sheets`, `google-slides` and `msgraph` in `service_api`
  (BYOK OAuth tokens). Graph is limited to files.
- **Web app:** a Files page (upload, page thumbnails, download, "Ask agent"), and the 📎 button now attaches
  Office/PDF files (they are uploaded to `uploads/` and passed to the agent as paths).
  API: `GET /api/files`, `POST /api/files/upload`, `GET /api/files/download`, `GET /api/files/preview`.
- **VS Code:** "AutoMoto: Create document/spreadsheet/deck from prompt…".

### Agent improvements
- When a model announces a step ("Now I'll build the document…") without calling a tool, it is asked once to
  make the call instead of ending the task. This is capped at two nudges per run.
- Agent steps get a bigger output budget (`AI_AGENT_MAX_TOKENS`, default max(AI_MAX_TOKENS, 8000)), so a whole
  document spec fits in one tool call. Empty replies from reasoning models are retried once on the same model.

### Security
- Office files are untrusted input. The guards are size, part-count, total and ratio limits (zip bombs), unsafe
  part names, DTD/ENTITY refusal (XXE), and macro and external-link detection.
- LibreOffice runs with a throwaway profile, macro security set to very high, macro execution disabled, VBA not
  loaded or executable, links never updated, a timeout, no shell and a secret-free environment.
- Office/PDF text is fenced as untrusted. The files API is limited to the workspace, with hidden/secret names
  refused, nosniff attachment downloads and raster-only previews.
- Microsoft Graph mail, chats, calendars, contacts and directory calls are blocked, as are sharing, invite and
  grant endpoints on every service.

### Tests
- 34 office tests (builders, readers, zip bomb/XXE/traversal/macros/links, LibreOffice conversion, TOC page
  numbers, recalc, renders, lint, policy, tools, services, files API) and 2 loop tests.
- A new CI `office` job installs LibreOffice and poppler on Ubuntu and runs the office tests with no skips.
- Live (NVIDIA NIM, Nemotron 3.5 Super VL): an agent built a report (title page, contents, table, figure,
  Harvard references) → PDF, a 12-month budget model (78 formulas, recalculated with 0 errors, chart) → PDF, and
  a 6-slide pitch deck with notes → PDF. Each was checked, vision-reviewed and rendered to PNG. Layout bugs found
  in those runs were fixed: duplicated "Figure 1:"/"Source:" labels, wrong TOC page when a heading word appeared
  in body text, a duplicated References heading, unfilled Excel chart bars, zero-height slide placeholders, and
  an invalid multi-image request to one-image vision models.

### Limitations
- Footnotes, tracked changes, equations, SmartArt and PDF/A validation are not supported.
- Google and Microsoft 365 APIs are untested live (they need your OAuth token).
- Overflow detection is approximate.
- LibreOffice/poppler were exercised on Linux only. Windows/macOS run the same code, but CI there skips those tests.

## Version 5.2.0 "Agent" - 28/10/2026
**Skills, local apps, services, a VS Code extension, and a security pass.**

### New
- **Skills library:** 29 new bundled skills (33 in total). They cover web design, HTML/CSS, graphic design, video
  and audio editing, bug fixing, the Linux terminal, Python, JavaScript, LaTeX, Go, algorithms and cross-platform
  apps (Tauri, Electron, Flutter, PyInstaller, Go), plus VS Code, Photoshop, Illustrator, Premiere Pro, AutoCAD,
  Canva, Google Drive, OneDrive, GitHub, GitLab, Notion, Figma, Vercel, Zotero, online shopping research
  (Amazon/eBay/Etsy) and travel research (Booking.com). New front matter declares `tools`, `apps`,
  `optional_apps`, `env`, `connectors`, `category` and `status`. `automoto skills`, `GET /api/skills` and the Skills
  page show requirement checks and ✅/🟡/🔴 test status.
- **Local apps** (`apps.py`): a registry of 30 apps with per-OS detection. New tools are `list_apps`, `run_app`
  (no shell, per-app flag deny-lists, path checks), `open_in_app` and `run_app_script`. `run_app_script` drives
  Photoshop/Illustrator via ExtendScript over COM or AppleScript, AutoCAD via `accoreconsole`, Blender via
  `--python` and GIMP via Script-Fu. CLI: `automoto apps`.
- **Services** (`services.py`): a `service_api` tool for GitHub, GitLab, Vercel, Figma, Notion and Zotero REST
  APIs, using BYOK or `.env` tokens. GET is safe and writes are risky. Secret/admin endpoints and whole-repo
  deletes are blocked, and tokens are redacted.
- **Connector catalogue** (`mcp_catalog.py`): official MCP servers for GitHub (Docker), and GitLab, Notion, Figma,
  Canva, Vercel and Google Drive (remote, via `mcp-remote` OAuth). Also OneDrive and Zotero (community) and the
  reference filesystem server. Manage them in Settings → Connectors or with `automoto mcp`. `${VAR}` placeholders
  are expanded at start.
- **VS Code extension** (`apps/vscode`): a chat view, Ask about selection, Fix this error (with a quick fix),
  Explain file, Run agent task on workspace, Allow folder, Open web UI and Status. Approvals appear as modal
  dialogs. It is tested with mocha and @vscode/test-electron, and CI builds the `.vsix`.
- **Allowed folders:** `allowed_roots` setting / `AUTOMOTO_ALLOWED_ROOTS` / Settings → Files. Tasks can work in an
  allowed folder (`workspace` on `POST /api/agent`, `--workspace` on the CLI). Access outside the sandbox always asks.
- **Tools:** `edit_file` (exact snippet replace) and `search_files` (regex search that skips secrets).
- **CLI:** `automoto open` (fresh one-time sign-in link), `apps`, `mcp`, `--workspace`. `skills` now shows
  readiness.
- **API:** `/api/apps`, `/api/services`, `/api/connectors` (+ enable/disable/reload), `/api/session/launch`.
  `/api/agent/info` adds `extra_roots`.

### Security
- Launch-link sign-in: a one-time link sets an HttpOnly, SameSite=Strict cookie, and the page no longer
  contains the token. Without it you get a locked page.
- Host check (DNS rebinding, 421) and Origin check (CSRF, 403). Cookie writes need a same-origin `Origin`.
- Rate limiting (429), security headers, no `Server` header, and Swagger off by default.
- `session.json` (0600) for local clients, removed on exit.
- Secret-path blocklist: SSH/cloud/kube credentials, keychains, browser profiles, shell start-up files, system
  folders, AutoMoto's data folder, and `.env`/key files everywhere. Shell commands and app arguments that
  mention them are blocked.
- Prompt-injection defences: untrusted output is fenced in `<untrusted>`, auto-approval is suspended after a run
  reads web or third-party content, and the system prompt has rules against secrets and purchases.
- netguard strips credential headers on cross-host redirects. MCP servers get a cleaned environment.
- The v4 `run_command` no longer uses `shell=True` and goes through the same blocklist.
- CI `security` job: pip-audit, bandit, npm audit. See the threat model in SECURITY.md.
- The desktop shell makes a random launch token for its own window. Its loading page is now committed (it was
  hidden by the `dist/` ignore rule).

### Fixed
- `edit_file` with `count=0` replaced only one occurrence.
- git's `-C` was refused by a case-insensitive `-c` rule.
- CLI output no longer crashes on non-UTF-8 Windows consoles.

### Tested
- 203 pytest tests (91 new).
- Live on Linux: ffmpeg/ffprobe (generate, trim, scale, loudnorm), ImageMagick (SVG→PNG, resize, text),
  Tectonic (PDF with maths), LibreOffice (txt→PDF), git, Node, npm, Python, Go, GitHub and GitLab public API reads,
  and the MCP filesystem server.
- Two NVIDIA NIM agent runs went through the VS Code extension's client: the video-editing skill end to end, and a
  bug fix in an allowed folder that ignored an injected instruction.
- The VS Code extension passes lint, unit tests and an integration test in a real VS Code, and packages to a `.vsix`.
- Not testable here: Adobe apps, AutoCAD, OAuth connectors, Docker, Tauri build (needs Rust ≥ 1.90).

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
