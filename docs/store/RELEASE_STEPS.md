# Release 5.6.0 — what to do in Partner Center

These steps run on your PC, in your Microsoft account. The CI workflow builds the package.
It does not submit it, create a git tag, or publish a GitHub release.

Store listing: <https://apps.microsoft.com/detail/9n9j7flssfg8>
Product identity name: `ymmiah.AutoMotoAI`
Store ID: `9N9J7FLSSFG8`
App version: `5.6.0`
MSIX package version: `5.6.99.0` (stable slot, higher than `5.6.0-beta.N` which maps to `5.6.N.0`)

## 1. Confirm the pull request is green

Open the pull request into `main`. Wait until **Windows app** has finished.
Download the artifact named **`automoto-ai-msstore`**.

Inside it you should find:

- `AutoMoto-AI-5.6.0-Windows-x64.msixupload` — this is the file Partner Center accepts
- `AutoMoto-AI-5.6.0-Windows-x64.msix` — the unpacked package, for your own check
- `SHA256SUMS.txt`

Check the hash in PowerShell before you upload:

```powershell
Get-FileHash .\AutoMoto-AI-5.6.0-Windows-x64.msixupload -Algorithm SHA256
```

Compare it with the line for that file in `SHA256SUMS.txt`.

The workflow also uploads **`automoto-ai-windows`** (the `.exe` and `.msi` installers). Those
are for GitHub, not for Partner Center.

If the package was built without the repository variables, its identity is a placeholder and
Partner Center will reject it. The workflow needs these repository variables, copied from
Partner Center → your app → Product identity:

- `MSSTORE_IDENTITY_NAME` = `ymmiah.AutoMotoAI`
- `MSSTORE_PUBLISHER` = the `CN=...` string on that page
- `MSSTORE_PUBLISHER_DISPLAY_NAME` = `Yasin Mohammed Miah`
- `MSSTORE_DISPLAY_NAME` = `AutoMoto AI`

Re-run the Windows app workflow after those variables are set if the artifact still shows the
placeholder publisher.

## 2. Partner Center

1. Sign in at <https://partner.microsoft.com/dashboard/apps-and-games/overview>.
2. Open **AutoMoto AI**. The URL contains the Store ID `9N9J7FLSSFG8`.
3. If a submission is already in progress, finish or delete that draft first. Partner Center
   allows one open submission.
4. Click **Update** (or **Start submission** if this is the first package for this identity).
5. Open **Packages**.
6. Remove any older package that uses the same version `5.6.99.0` if one is already there.
   A new upload must be strictly higher than the newest package already published. `5.6.99.0`
   is higher than every `5.6.0-beta.N` package (`5.6.1.0` through `5.6.98.0`).
7. Upload **`AutoMoto-AI-5.6.0-Windows-x64.msixupload`**. Do not upload the loose `.msix`.
8. Set the availability to the markets you want. Leave device family as Desktop.
9. Open **Properties**. Category: Productivity. This app is a desktop app. Privacy policy URL:
   `https://github.com/ymmiah/AutoMotoAI/blob/main/docs/PRIVACY.md`.
10. Open **Age ratings**. Answer the questionnaire again if Microsoft asks. The app does not
    collect account data of its own when used in local mode.
11. Open **Pricing and availability**. Keep the price **Free**.
12. Open **Store listings** for en-GB (and any other language you list). Copy the description
    from `packaging/msstore/listing.md`. Add the screenshots from this release (chat, Settings
    → Offline AI, Help). The 1:1 and 9:16 images Microsoft asks for are described in
    `docs/WINDOWS-DISTRIBUTION.md`.
13. Read the submission notes. Leave **Submit to the Store** unpressed until you have checked
    the package version on the Packages page is `5.6.99.0` and the publisher is
    `ymmiah.AutoMotoAI`.
14. Press **Submit to the Store** only when you want certification to start. Certification is
    Microsoft's review, not something this repository can do.

There is an optional manual workflow button, **store_upload**, which sends the same
`.msixupload` as a **draft** if the Azure AD secrets are already in the repository. It does
not press Submit. Prefer the upload above if those secrets are not set.

## 3. Git tag and GitHub release, after you approve

Do this yourself, from `main`, after the pull request is merged:

```powershell
git checkout main
git pull
git tag v5.6.0
git push origin v5.6.0
```

Pushing the tag runs the Windows workflow again and attaches installers to the GitHub release
for that tag. The draft text to paste into the release body is
[GITHUB_RELEASE_DRAFT.md](GITHUB_RELEASE_DRAFT.md).

After the release assets exist, put their SHA-256 into `scripts/install.ps1` and
`scripts/install.sh` for version `5.6.0`, and point `packaging/updater/beta.json` (or a new
stable updater file) at the new installer. Do not invent those hashes before the files exist.

The wheel the installers bundle is built in CI from this source. It is not published to PyPI
by the tag alone.

## 4. What this repository will not do

- It will not press Submit in Partner Center.
- It will not create the tag `v5.6.0` or a GitHub release.
- It will not put store passwords, Azure secrets, or signing keys in the source.
