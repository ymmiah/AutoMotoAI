# AutoMoto AI 5.6.0 Beta 5 — Microsoft Store update

App: **5.6.0-beta.5** · Engine: **5.6.0b5** · Store: **5.6.5.0** · Windows x64

Existing Store product: [9N9J7FLSSFG8](https://apps.microsoft.com/detail/9n9j7flssfg8).

## What's new

- Redesigned desktop launcher with clearer account/local choices, installation guidance, a password visibility control, and light/dark appearance following the system.
- Refreshed chat workspace with filterable starting ideas, AI configuration status, quick commands, and a theme shortcut.
- Unsent message drafts survive navigation between chats and Settings during the current session. Draft text stays in memory; closing/reloading the window clears it.
- Dialogs and the command palette keep keyboard focus inside and return focus on dismissal; background shortcuts cannot trigger actions through an overlay.
- Engine installation status refreshes when returning from the installer, with a manual refresh option that preserves an unfinished sign-in form.
- Store packages include the matching engine wheel with SHA-256 verification, so installing the engine does not depend on an unpublished GitHub release.
- Includes current main's visual PowerPoint generation, original-image preservation, and layout quality checks.
- Offline AI recommends a stronger model when the graphics card can hold it, keeps a longer context on strong PCs, and warns when it has to use a weaker downloaded model. Offline mode does not fall back to a cloud provider.
- The Windows window uses AutoMoto's caption bar (Menu, minimize, maximize, close) instead of the system title-bar buttons. Settings is grouped into Assistant, Offline AI, Appearance, Folders, Providers and More.

## Update file

The **Windows app** workflow produces the artifact **`automoto-ai-msstore`**. Upload **`AutoMoto-AI-5.6.0-beta.5-Windows-x64.msixupload`** to Partner Center (MSIX identity **5.6.5.0**). The same artifact also contains `AutoMoto-AI-5.6.0-beta.5-Windows-x64.msix` and `SHA256SUMS.txt`. The unsigned `.msixupload` is what Partner Center asks for; a separately signed throw-away copy is used for the CI install/launch smoke test. Do not submit a second package at 5.6.5.0 if that version is already published.

1. Wait for the PR's Windows build, Rust checks, browser regressions, and MSIX install/launch checks to pass.
2. Download `automoto-ai-msstore` from that successful run and verify `SHA256SUMS.txt`.
3. Confirm the package identity/publisher exactly matches the existing product's Partner Center identity. Missing repository identity variables produce a **test-only placeholder**, which must not be submitted. Set `MSSTORE_IDENTITY_NAME`, `MSSTORE_PUBLISHER`, `MSSTORE_PUBLISHER_DISPLAY_NAME`, and `MSSTORE_DISPLAY_NAME` to the existing product's values and rebuild if necessary.
4. Create an update for the existing product in Partner Center, upload the `.msixupload`, review metadata/screenshots, and submit for certification. Optional poster art (720×1080) and box art (1080×1080) derived from the existing icon are in `packaging/msstore/images/`. Replace them in Partner Center if you have final marketing art. Do not submit a package whose identity is still the test placeholder.

This change does not publish a GitHub release or submit the app to Microsoft. The older Beta 4 PR is not required for this update.

## Requirements and validation

- Windows 10 1809+ with WebView2. Local engine installation needs Python 3.10+ and internet access for Python dependencies. Python and Ollama are not bundled.
- Fully offline inference requires Ollama plus a downloaded model. Cloud inference uses the user's own provider configuration and may incur provider charges.
- Account data lives on the configured server; local data stays in the local workspace. Choosing a cloud model transmits the requested content to that provider.
- Browser regression tests cover idea filtering, draft recovery, dialog focus, themes, mobile overflow, and launcher engine refresh. UI screenshots are saved in the `automoto-ui-screenshots` CI artifact.

**Partner Center change text:**
A redesigned start screen and workspace, filterable task ideas, easier AI setup, draft recovery while navigating, better keyboard accessibility, and more reliable local-engine updates.
