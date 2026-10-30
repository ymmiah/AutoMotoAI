# AutoMoto AI docs

AutoMoto AI is a free AI agent that runs on your own computer: it researches the web, works on Word, Excel,
PowerPoint, PDF, CSV and ZIP files in a sandbox, remembers what matters and asks before every risky step.
Every command on this site has a **copy button** in the top-right corner of its box.

> **New: 5.6.0 Beta 2** with the **Windows app** and **one account on every device**
> ([download](https://github.com/ymmiah/AutoMotoAI/releases/tag/v5.6.0-beta.2)). It's a beta; 5.5.0 stays the stable version.

**👉 [Start here: pick your device](START.md)** has easy steps for a Windows PC, an Android phone or iPhone, a Mac,
Linux or VS Code.

| Start here | |
|---|---|
| **[Pick your device](START.md)** | The easiest path for your device (Windows app, phone, Mac/Linux, VS Code), one account everywhere, help. |
| **[GUI guide](GUI-GUIDE.md)** | Step by step with screenshots: install, add a free key, open the app, every page, VS Code, hosted mode and the admin panel. |
| **[Install](INSTALL.md)** | Every OS in detail: Windows, macOS, Linux, Docker, Raspberry Pi, ChromeOS, phones. |
| **[Windows app distribution](WINDOWS-DISTRIBUTION.md)** | SmartScreen, code signing, Microsoft Store and winget (for maintainers). |
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
