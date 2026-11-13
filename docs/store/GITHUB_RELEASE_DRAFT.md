# GitHub release draft — v5.6.0

Paste this into the GitHub release **after** you tag `v5.6.0`. Do not publish it from CI.

**Title:** AutoMoto AI 5.6.0

**Body:**

AutoMoto AI 5.6.0 is the stable release after 5.6.0-beta.6.

### Install

- **Windows (recommended):** [Get it from Microsoft](https://apps.microsoft.com/detail/9N9J7FLSSFG8)
  (Store ID `9N9J7FLSSFG8`, identity `ymmiah.AutoMotoAI`). The Store package version is `5.6.99.0`.
  Microsoft signs this copy, so Windows does not show an unknown-publisher warning.
  Upload of that package is a separate Partner Center step: `docs/store/RELEASE_STEPS.md`.
- **Advanced:** direct installer (may show a SmartScreen warning until signed):
  `AutoMoto-AI-Setup-5.6.0-Windows-x64.exe` (per-user, no admin) or
  `AutoMoto-AI-5.6.0-Windows-x64.msi` (IT / all users).
- Store upload package (not a normal installer): `AutoMoto-AI-5.6.0-Windows-x64.msixupload`
- Python wheel: `automoto_ai-5.6.0-py3-none-any.whl`
- VS Code extension: `AutoMoto-AI-5.6.0-VSCode.vsix`

Check `SHA256SUMS.txt` before you run a direct installer.

### What changed

- Settings → Offline AI downloads a GGUF model and the llama.cpp engine inside the app.
  No Ollama install and no Python install. After the download, chat works offline.
  The catalog includes smaller Kimi, Qwen, Llama, Mistral, Gemma, DeepSeek and Phi models.
  Full Kimi K2 is listed as about 624 GB and is not offered as a download. You can import
  your own `.gguf` file. A model that does not fit this computer explains why.
- Help is in the app (F1): every setting, studio and tool in plain language.
- The layout is chat-first. Studios and chats sit in the sidebar. Settings is its own panel.
  The Windows caption buttons stay AutoMoto's own.
- The interface is usable with touch. Android and iOS project builds are described in
  `docs/mobile/STORE_ACCOUNTS.md`.

Licence: AGPL-3.0-only, with a commercial licence available. Copyright Yasin Mohammed Miah.
Versions up to and including 5.6.0-beta.3 stay MIT for those copies.
