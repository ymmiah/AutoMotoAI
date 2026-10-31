# Updater channels for the Windows app

* `beta.json` — the **beta channel**. The beta app (`5.6.0-beta.N`) checks
  `https://raw.githubusercontent.com/ymmiah/AutoMotoAI/main/packaging/updater/beta.json`. After a beta release,
  copy that release's `latest.json` here and commit it. Every file it points to is signed with the updater key;
  the app refuses anything whose signature doesn't match the public key in `apps/desktop/src-tauri/tauri.conf.json`,
  so this file can't be used to push an unsigned build. From 5.6.0 Beta 4 the installers are called
  `AutoMoto-AI-Setup-<version>-Windows-x64.exe` / `AutoMoto-AI-<version>-Windows-x64.msi`; `latest.json` already
  uses the new names, so copying it is all that's needed.
* Stable app releases will use `https://github.com/ymmiah/AutoMotoAI/releases/latest/download/latest.json`.
