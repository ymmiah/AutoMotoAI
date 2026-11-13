# AutoMoto AI docs

AutoMoto AI is a free AI agent that runs on your own computer: it researches the web, works on Word, Excel,
PowerPoint, PDF, CSV and ZIP files in a sandbox, remembers what matters and asks before every risky step.
Every command on this site has a **copy button** in the top-right corner of its box.

> **Current stable: 5.6.0.** On Windows, [Get it from Microsoft](https://apps.microsoft.com/detail/9N9J7FLSSFG8)
> (recommended). The [GitHub release](https://github.com/ymmiah/AutoMotoAI/releases/tag/v5.6.0) also has
> advanced direct `.exe` / `.msi` installers, which may show a SmartScreen warning until they are signed.

**👉 [Start here: pick your device](START.md)** has easy steps for a Windows PC, an Android phone or iPhone, a Mac,
Linux or VS Code.

| Start here | |
|---|---|
| **[Pick your device](START.md)** | The easiest path for your device (Windows app, phone, Mac/Linux, VS Code), one account everywhere, help. |
| **[GUI guide](GUI-GUIDE.md)** | Step by step with screenshots: install, add a free key, open the app, every page, VS Code, hosted mode and the admin panel. |
| **[Install](INSTALL.md)** | Every OS in detail: Windows, macOS, Linux, Docker, Raspberry Pi, ChromeOS, phones. |
| **[iPhone apps](IOS.md)** | Describe an app, build it, put it on a real iPhone, and send it to Apple only when you press the button. |
| **[Windows app distribution](WINDOWS-DISTRIBUTION.md)** | SmartScreen, Azure Artifact Signing, Microsoft Store and winget (for maintainers). |
| **[Privacy policy](PRIVACY.md)** | No telemetry. Everything the app connects to, and when. |
| **[Hosting](HOSTING.md)** | Let other people use it with a daily limit; honest free-hosting comparison. |
| **[Publishing](PUBLISHING.md)** | How releases reach GitHub, the VS Code Marketplace, Open VSX and PyPI. |

Quick start (Windows PowerShell):

```powershell
git clone https://github.com/ymmiah/AutoMotoAI
```

```powershell
cd AutoMotoAI
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

Quick start (macOS / Linux):

```bash
git clone https://github.com/ymmiah/AutoMotoAI
```

```bash
cd AutoMotoAI
```

```bash
./scripts/install.sh
```

Then add a free key ([GUI guide, step 2](GUI-GUIDE.md#2-add-a-free-ai-key)) and start it:

```bash
automoto serve
```

![The AutoMoto home screen](gui-guide/02-home.png)

Source code, releases and issues: [github.com/ymmiah/AutoMotoAI](https://github.com/ymmiah/AutoMotoAI).
