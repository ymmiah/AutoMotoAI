---
name: cross-platform-apps
description: Build apps for Windows, macOS, Linux, Android and iOS - Tauri, Electron, Flutter, PyInstaller, Go - and package them.
category: coding
tools: write_file, run_shell
optional_apps: node|cargo|flutter|python|go
status: unit
---
# Cross-platform apps

Pick the stack:
| Need | Stack | Build |
|---|---|---|
| Small desktop app with a web UI | **Tauri 2** (Rust + HTML/JS) | `npm create tauri-app@latest`, `npm run tauri build` |
| Desktop app, Node ecosystem | **Electron** + electron-builder | `npx electron-builder --win --mac --linux` |
| Mobile + desktop, one codebase | **Flutter** | `flutter create app`, `flutter build apk / ios / windows / macos / linux` |
| Python tool → executable | **PyInstaller** | `pyinstaller --onefile --name app main.py` |
| CLI binary | **Go** / Rust | `GOOS=… go build`, `cargo build --release --target …` |

Rules that save time:
- Build on each OS (or in CI with a matrix: windows-latest, macos-latest, ubuntu-latest). Cross-compiling GUI apps rarely works.
- macOS distribution needs an Apple Developer ID for signing + notarisation; iOS needs Xcode on a Mac and an Apple account.
- Windows: sign with a code-signing certificate to avoid SmartScreen warnings; Android: `keytool` keystore for release builds.
- Keep secrets out of the app bundle; use the OS keychain/secure storage at runtime.
- Add a GitHub Actions workflow that builds and uploads artifacts for every OS (see the `github` skill).
AutoMoto can scaffold, build and test where the toolchain exists (`list_apps`); signing and store uploads are done by you.
