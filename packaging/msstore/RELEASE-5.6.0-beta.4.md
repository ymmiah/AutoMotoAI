# AutoMoto AI 5.6.0 Beta 4 — Microsoft Store update

**App version:** 5.6.0-beta.4  
**Store MSIX version:** 5.6.4.0  
**Architecture:** Windows x64  
**Store product:** [9N9J7FLSSFG8](https://apps.microsoft.com/detail/9n9j7flssfg8?hl=en-GB&gl=GB)

## What's new

- Improved chat auto-scrolling and accurate scrollbar behaviour: replies follow automatically when the user is at the bottom, without disrupting manual scrolling.
- Added a **Latest reply** shortcut.
- Improved access to Memory and exported files, including opening supported files directly from chat.
- Improved selection, downloading and testing of free on-device models, including Google Gemma 3 and Qwen.
- Added clearer switching between offline AI, cloud providers and the app's local/hosted sign-in screens.
- Added optional Z.ai GLM and Moonshot Kimi API providers (your own API keys are required).
- Fixed mobile chat state changes, confirmation dialog dismissal and lost chat drafts.
- Improved desktop sign-out messaging when remote device-token revocation cannot be confirmed.

## Submission details

- Upload the `AutoMoto-AI-5.6.0-beta.4-Windows-x64.msixupload` file from the **automoto-ai-msstore** GitHub Actions artifact.
- The Store package is unsigned before submission; Microsoft signs the package during its certification/distribution process.
- GitHub Actions builds a matching `automoto_ai-5.6.0b4-py3-none-any.whl` and includes it in the MSIX, with its SHA-256 digest. This avoids depending on an unreleased Beta 4 engine wheel.
- The optional local engine still requires Python 3.10+ and installation of Python dependencies; Ollama is a separate free inference runtime that must be installed and the model must be downloaded before fully offline use.
- Cloud-provider keys, quotas and charges are managed by the respective providers.
- Local chats/workspace files and hosted-account chats/files are separate unless explicitly synchronised by a supported account workflow.
- Do **not** submit until CI (including the Windows MSIX install smoke test) succeeds and Partner Center confirms the package name and publisher match the existing product.

**Partner Center description of changes (short):**
Improved chat scrolling and file access, smoother local/cloud switching, free Gemma local-model support, optional Z.ai and Kimi providers, and stability fixes.

## Required manual steps

1. Download and inspect the GitHub Actions `automoto-ai-msstore` artifact.
2. Open Microsoft Partner Center and create an update for the existing Store product.
3. Replace the previous MSIX package with the new `.msixupload`, review the metadata and run certification checks.
4. Submit for certification when tests and package identity checks pass.

The presence of a package artifact does **not** mean it has been uploaded to Partner Center or published by Microsoft.
