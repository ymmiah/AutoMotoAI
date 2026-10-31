# Notes for certification (Partner Center → Submission options)

Paste this and fill in the test key or account (Partner Center keeps these notes private to Microsoft's testers).

```
AutoMoto AI (Beta) is a desktop (Win32) app built with Tauri (Rust + Microsoft Edge WebView2), packaged as MSIX.

Restricted capability runFullTrust: it's a classic desktop app. Full trust is needed to run its own local engine (a Python program in the user's profile, started and stopped by the app on 127.0.0.1:8765), to read and write the documents the user asks it to create, and to store the user's sign-in token in Windows Credential Manager.

How to test:
1. Start the app. The first screen offers "Sign in to your account" or "Start local mode".
2. Easiest: Sign in with this test account on our test server: <SERVER URL> / user <USER> / password <PASSWORD>.
   Or: Start local mode. The app asks before installing the free local engine (Python from winget/python.org and the AutoMoto engine from GitHub/PyPI) into the user profile. Then open Settings → AI keys and paste this test key: <TEST KEY>.
3. Type: "Make a Word report about the benefits of exercise". The app shows its steps, asks for approval before writing the file (click Approve), then offers the .docx in Files.

Dynamic content / downloads: the only code the app downloads is the optional local engine above, after the user agrees; it's the same open-source project (https://github.com/ymmiah/AutoMotoAI). The terminal and file tools only run after the user approves each action, inside a sandbox folder.

Updates: the Store edition never updates itself; its built-in updater is switched off when it runs from the MSIX package.

Generative AI: replies are produced by the AI provider/model the user chooses. Users can report content with "Report a problem" (links to https://github.com/ymmiah/AutoMotoAI/issues/new?template=report-content.yml).

Privacy policy: https://ymmiah.github.io/AutoMotoAI/PRIVACY.html. No telemetry.
```

**Important:** without a working key or account the testers can't see the app do anything (policy 10.1.2,
"fully functional"). Create a throw-away test account on your server, or a free provider key with a low limit, and
revoke it after certification. Never commit it to the repository.
