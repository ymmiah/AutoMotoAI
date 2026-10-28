# AutoMoto AI — Desktop app (Tauri 2)

Native window for **Windows, macOS and Linux** around the AutoMoto web UI (v5 agent mode included).
Status: **scaffold** — it builds from source; code-signing/notarisation are up to you.

How it works: on launch the Rust shell starts `python -m automoto serve --no-browser`
on `127.0.0.1:8765` (unless it's already running), shows a loading page, then loads the real UI.
Closing the window stops the server it started. No keys are stored in the app — they stay in
your `.env` or the UI's per-tab 🔑 Keys dialog. Desktop tools still need confirmation.

## Prerequisites
- Python setup from the repo root (`pip install -r requirements.txt`, `.env` with a key)
- Rust (stable) + Node 18+
- Tauri OS prerequisites: <https://v2.tauri.app/start/prerequisites/>
  - **Windows:** Visual Studio C++ Build Tools + WebView2 (preinstalled on Windows 11)
  - **macOS:** Xcode Command Line Tools
  - **Linux:** `libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev`

## Run / build
```bash
cd apps/desktop
npm install
# Tell the shell where the repo and your Python live (defaults: "." and python/python3)
export AUTOMOTO_HOME="$(cd ../.. && pwd)"
export AUTOMOTO_PYTHON="$AUTOMOTO_HOME/venv/bin/python"     # Windows: ..\..\venv\Scripts\python.exe
npm run dev          # development window
npm run build        # Windows: .msi + .exe (NSIS) · macOS: .app + .dmg · Linux: .deb/.AppImage
npm run build:mac    # universal (Intel + Apple Silicon) — run on a Mac
```

Electron alternative: not included (Tauri is ~10× lighter). Any Electron `BrowserWindow`
pointed at `http://127.0.0.1:8765` after spawning the same Python command works the same way.

## Not done yet (honest list)
- Python is not bundled; the app expects the repo + venv. (Next step: PyInstaller sidecar.)
- No auto-update, tray icon or code signing.
