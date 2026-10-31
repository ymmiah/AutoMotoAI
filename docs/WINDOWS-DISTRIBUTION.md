# Shipping the Windows app: SmartScreen, signing, winget and the Microsoft Store

Status for **5.6.0 Beta 3** (checked 31 October 2026): the app is a **beta**, published **free as a GitHub
pre-release** (`v5.6.0-beta.3`; 5.5.0 stays the latest stable release), as an NSIS
`.exe` and an `.msi`, **not code-signed**. Updates are signed with the Tauri updater key, so the app only installs
updates that came from this repository's release workflow. A winget manifest is ready in `packaging/winget/` but
**has not been submitted**. A Microsoft Store (MSIX) edition is prepared (below); nothing has been signed up for.

## What users see today (SmartScreen)

Windows SmartScreen checks downloaded programs. An **unsigned** program, or a new one without download reputation,
shows **"Windows protected your PC"**. Users click **More info → Run anyway**. That's expected for the 5.6.0 beta.

* Reputation is built per signing certificate (or per file for unsigned files), over time and downloads.
  **EV certificates no longer skip this**: Microsoft says paying for EV just to avoid the warning "is no longer justified".
  — [Microsoft Learn: SmartScreen reputation for Windows app developers](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)
* Microsoft's own signing service (**Azure Artifact Signing**, formerly Trusted Signing, about US$9.99/month) is
  open to organisations in the USA, Canada, the EU and the UK, but to **individual developers only in the USA and
  Canada** — so not to an individual in the UK, who would need an OV certificate from a certificate authority.
  — same page, and [Code signing options for Windows app developers](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options)

## Chosen route: the Microsoft Store (MSIX)

Checked 31 October 2026. The plan is a **Microsoft Store edition** packaged as **MSIX**: Microsoft signs MSIX packages
when they pass certification, so it needs **no certificate** and Store installs don't show the SmartScreen warning.
The GitHub `.exe`/`.msi` stay as they are (unsigned) for people who don't use the Store.

* **Free individual developer account** (no fee, also in the UK): start at <https://storedeveloper.microsoft.com>,
  choose *Individual developer*, verify with a government ID and a selfie on your phone. That page is the only entry
  to the free flow. — [Open a developer account](https://learn.microsoft.com/en-us/windows/apps/publish/partner-center/open-a-developer-account),
  [What's new for individual developers](https://learn.microsoft.com/en-us/windows/apps/publish/whats-new-individual-developer)
  (Individual accounts are meant for people publishing "not in relation to their business, trade, or profession".
  The Store app itself is free; if selling commercial licences turns into a business, a Company account may be the
  right type later.)
* **MSIX vs EXE/MSI:** "For Store submissions, MSIX/AppX packages don't need a CA-trusted signature — Microsoft
  re-signs the package". An EXE/MSI listing (policy 10.2.9) needs every file signed with a Trusted-Root CA
  certificate, a versioned HTTPS download URL and a silent install. — [Publish your first Windows app](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/publish-first-app),
  [Store policies 7.20](https://learn.microsoft.com/en-us/windows/apps/publish/store-policies)
* **How it's built:** the *Windows app* workflow packs the Tauri app into
  `AutoMoto-AI-<version>-Windows-x64.msixupload` (artifact `automoto-ai-msstore`) with
  [`scripts/ci/pack-msix.ps1`](https://github.com/ymmiah/AutoMotoAI/blob/main/scripts/ci/pack-msix.ps1): the manifest
  comes from [`packaging/msstore/msix.py`](https://github.com/ymmiah/AutoMotoAI/blob/main/packaging/msstore/msix.py)
  (brand.py), the tiles from `packaging/branding/generate.py`; `makeappx` validates it, and CI test-installs a
  self-signed copy and launches it. The uploaded package itself is unsigned (the Store signs it).
* **Identity:** Partner Center gives the package *Name*, *Publisher* (`CN=…`) and *Publisher display name* after you
  reserve the app name. Put them in the repository **variables** `MSSTORE_IDENTITY_NAME`, `MSSTORE_PUBLISHER`,
  `MSSTORE_PUBLISHER_DISPLAY_NAME` and the reserved name in `MSSTORE_DISPLAY_NAME`. Until then a placeholder
  identity is used (it builds, but Partner Center rejects it).
* **Version numbers:** MSIX needs four numbers and the **last must be 0** for the Store ("reserved for Store use").
  The beta keeps its version (`5.6.0-beta.3`); the package version is `X.Y.(Z×100+N).0`, and a stable release
  uses `N = 99` so it is always higher than its betas: `5.6.0-beta.3 → 5.6.3.0`, `5.6.0 → 5.6.99.0`,
  `5.6.1-beta.1 → 5.6.101.0`. — [App package requirements](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/app-package-requirements)
* **Updates:** the Store updates Store installs. The app detects that it runs from an MSIX package and switches its
  own updater off (no automatic check; *Check for updates* says the Store handles it). Policy 10.2.5 (update only
  through the Store) is written for games, but a second updater would install a separate non-Store copy anyway.
* **Beta testing:** a **private audience** (only people whose Microsoft accounts you list can see and install it;
  can be changed to public later, but not back) and, after the first publish, **package flights** for known-user
  groups. — [Visibility options](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/visibility-options),
  [Package flights](https://learn.microsoft.com/en-us/windows/apps/publish/package-flights)
* **Optional automation:** a manual *Windows app* run with **store_upload** ticked uploads the package to Partner
  Center as a **draft** (`msstore publish --noCommit`). It needs the secrets `AZURE_AD_TENANT_ID`,
  `AZURE_AD_APPLICATION_CLIENT_ID`, `AZURE_AD_APPLICATION_SECRET`, `SELLER_ID` and the variable `MSSTORE_PRODUCT_ID`,
  and works only after the first submission was published by hand. — [GitHub Actions for the Store](https://learn.microsoft.com/en-us/windows/apps/publish/msstore-dev-cli/github-actions)
* **Listing kit** (descriptions, keywords, age-rating answers, screenshots, certification notes):
  [`packaging/msstore/`](https://github.com/ymmiah/AutoMotoAI/tree/main/packaging/msstore). Privacy policy URL:
  <https://ymmiah.github.io/AutoMotoAI/PRIVACY.html>.

### Store policies that matter for AutoMoto

* **10.1** the listing must describe what the app really does, including limits; **10.1.3** at most seven search terms.
* **10.2.2** no downloading code that changes the described function: the optional *local engine* install (Python +
  the AutoMoto engine from PyPI/GitHub, only after the user agrees) and the approval-gated terminal tool are
  described in the listing and the certification notes.
* **10.2.4** dependencies on other software must be stated **at the start of the description**: an AI provider key
  or local AI model, and an AutoMoto account server or the local engine.
* **10.5.1** a privacy policy URL is required (desktop/Win32 apps always need one).
* **11.11** IARC age rating questionnaire; **11.16 live generative AI**: say so in the listing and in Partner
  Center, and offer a way to report bad output (the app's *Report a problem* link and the *Report content* issue form).
* **runFullTrust** is a restricted capability; explain in the submission notes that it's a desktop (Win32) app.

### Not applicable: SignPath Foundation

SignPath Foundation's free certificates require "an OSI-approved Open Source license **without commercial
dual-licensing**". AutoMoto AI is AGPL-3.0 **plus** a paid commercial licence, so it doesn't qualify; the SignPath
steps were removed from the workflow. — [SignPath terms](https://signpath.org/terms.html)

## winget (Windows Package Manager)

Manifests for the beta are in [`packaging/winget/manifests/y/ymmiah/AutoMotoAI/Beta/5.6.0-beta.3/`](https://github.com/ymmiah/AutoMotoAI/tree/main/packaging/winget/manifests/y/ymmiah/AutoMotoAI/Beta/5.6.0-beta.3)
as the package **`ymmiah.AutoMotoAI.Beta`** (winget-pkgs keeps pre-releases under their own identifier, so the stable
`ymmiah.AutoMotoAI` can come later) (schema 1.12, NSIS per-user installer, URL and SHA-256 of the release file). A submission is a pull request to
`microsoft/winget-pkgs`; an automated process validates the manifest, checks the package against the winget
policies and checks it isn't known to be malicious (false positives can be sent to Microsoft Defender).
— [Submit packages to Windows Package Manager](https://learn.microsoft.com/en-us/windows/package-manager/package/repository)

To submit (Yasin, when ready — this has **not** been done):

```powershell
winget install wingetcreate
winget validate --manifest packaging\winget\manifests\y\ymmiah\AutoMotoAI\Beta\5.6.0-beta.3
winget install --manifest packaging\winget\manifests\y\ymmiah\AutoMotoAI\Beta\5.6.0-beta.3   # test install locally
wingetcreate submit packaging\winget\manifests\y\ymmiah\AutoMotoAI\Beta\5.6.0-beta.3           # opens a PR on microsoft/winget-pkgs
```

For later versions: `wingetcreate update ymmiah.AutoMotoAI.Beta --version <new> --urls <setup.exe URL> --submit`.
Unsigned installers can be flagged by the SmartScreen part of the validation.

## Update channel

The beta app checks `https://raw.githubusercontent.com/ymmiah/AutoMotoAI/main/packaging/updater/beta.json` (the
signed `latest.json` of the newest beta, committed after each beta release). It does **not** use
`releases/latest`, so a beta never becomes "latest" and stable users aren't offered betas. For a stable app
release, point `plugins.updater.endpoints` in `tauri.conf.json` back to
`https://github.com/ymmiah/AutoMotoAI/releases/latest/download/latest.json`.

## The updater key (keep it safe)

* The **public** key is in `apps/desktop/src-tauri/tauri.conf.json` (`plugins.updater.pubkey`).
* The **private** key and its password are repository secrets `TAURI_SIGNING_PRIVATE_KEY` and
  `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`. They are not in the repository.
* If the private key is lost, installed apps can't verify new updates: users would have to install the next
  version by hand. Keep an offline backup (password manager) of the key and its password.
