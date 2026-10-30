# Shipping the Windows app: SmartScreen, signing, winget and the Microsoft Store

Status for **5.6.0 Beta 2** (checked 30 October 2026): the app is a **beta**, published **free as a GitHub
pre-release** (`v5.6.0-beta.2`; 5.5.0 stays the latest stable release), as an NSIS
`.exe` and an `.msi`, **not code-signed**. Updates are signed with the Tauri updater key, so the app only installs
updates that came from this repository's release workflow. A winget manifest is ready in `packaging/winget/` but
**has not been submitted**. Nothing has been signed up for.

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

## Free code signing for open source: SignPath Foundation

[SignPath Foundation](https://signpath.org) signs releases of open-source projects for free, with a certificate
issued to SignPath Foundation. What its [terms](https://signpath.org/terms.html) ask for (summary — read the page):

* an **OSI-approved licence** for every component, no commercial dual-licensing (AutoMoto AI is MIT), and
  **no proprietary code** in what's signed;
* the project is **actively maintained**, **already released** in the form to be signed, and its functions are
  **described on the download page**; for programs they also want "a certain verifiable reputation";
* no malware or potentially unwanted programs, and **no hacking tools** (features that find or exploit security
  holes or get around security measures) — be ready to explain AutoMoto's approval-gated shell and desktop tools;
* everyone on the team uses **MFA** on SignPath and GitHub; roles (authors, reviewers, approvers) are declared, and
  **every release is approved by hand** before it's signed; SignPath checks the files were built by CI from this
  repository;
* a **"Code signing policy"** section on the project's home page and release pages;
* the certificate carries **SignPath Foundation's** name, so Windows shows them as the publisher.

To apply (Yasin, when ready): fill in the application on signpath.org, link this repository and the release
workflow, then add the SignPath GitHub Action between *Build the installers* and *Collect the installers* in
`.github/workflows/desktop.yml`. The updater signature must be made **after** Authenticode signing (re-run
`npx tauri signer sign` on the signed files), otherwise the update check fails.

## Microsoft Store

* **Individual developer accounts are now free** — no registration fee; you verify with an ID document and a
  selfie. Start at <https://storedeveloper.microsoft.com> — that is the only entry to the free flow; signing up via
  Partner Center or Visual Studio still shows the old US$19 flow.
  — [What's new for individual developers](https://learn.microsoft.com/en-us/windows/apps/publish/whats-new-individual-developer),
  [Windows Developer Blog, 10 Sept 2025](https://blogs.windows.com/windowsdeveloper/2025/09/10/),
  [Open a developer account](https://learn.microsoft.com/en-us/windows/apps/publish/partner-center/open-a-developer-account)
* **An MSI or EXE listed in the Store must be Authenticode-signed** with a certificate that chains to the Microsoft
  Trusted Root Program; self-signed isn't accepted. The Store links to your installer URL and checks it.
  — [App package requirements for MSI/EXE apps](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msi/app-package-requirements)
* An **MSIX** package is re-signed by Microsoft for free when you submit it, so no certificate is needed for the
  Store itself. Tauri doesn't build MSIX directly; it would need an extra packaging step (MSIX Packaging Tool or
  `makeappx`) and testing. Store-installed MSIX apps update through the Store, not the Tauri updater.
  — [Code signing options](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options),
  [Publish your first Windows app](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/overview)

So the realistic free paths are: **(a)** SignPath Foundation → signed `.exe`/`.msi` → Store listing of the MSI/EXE,
or **(b)** an MSIX build for the Store only. Both need Yasin to create the accounts himself.

## winget (Windows Package Manager)

Manifests for the beta are in [`packaging/winget/manifests/y/ymmiah/AutoMotoAI/Beta/5.6.0-beta.2/`](https://github.com/ymmiah/AutoMotoAI/tree/main/packaging/winget/manifests/y/ymmiah/AutoMotoAI/Beta/5.6.0-beta.2)
as the package **`ymmiah.AutoMotoAI.Beta`** (winget-pkgs keeps pre-releases under their own identifier, so the stable
`ymmiah.AutoMotoAI` can come later) (schema 1.12, NSIS per-user installer, URL and SHA-256 of the release file). A submission is a pull request to
`microsoft/winget-pkgs`; an automated process validates the manifest, checks the package against the winget
policies and checks it isn't known to be malicious (false positives can be sent to Microsoft Defender).
— [Submit packages to Windows Package Manager](https://learn.microsoft.com/en-us/windows/package-manager/package/repository)

To submit (Yasin, when ready — this has **not** been done):

```powershell
winget install wingetcreate
winget validate --manifest packaging\winget\manifests\y\ymmiah\AutoMotoAI\Beta\5.6.0-beta.2
winget install --manifest packaging\winget\manifests\y\ymmiah\AutoMotoAI\Beta\5.6.0-beta.2   # test install locally
wingetcreate submit packaging\winget\manifests\y\ymmiah\AutoMotoAI\Beta\5.6.0-beta.2           # opens a PR on microsoft/winget-pkgs
```

For later versions: `wingetcreate update ymmiah.AutoMotoAI.Beta --version <new> --urls <setup.exe URL> --submit`.
Unsigned installers can be flagged by the SmartScreen part of the validation; if that happens, sign first (above).

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
