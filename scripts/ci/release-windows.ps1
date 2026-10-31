# On a version tag: attach the Windows installers and a signed updater manifest (latest.json) to the release,
# then rewrite the release notes ("Which file do I need?" table, changes, checksums: scripts/ci/release_notes.py).
# The release is created as a draft if it doesn't exist yet (a pre-release for -beta.N tags); a maintainer
# publishes it. For betas, latest.json is also what packaging/updater/beta.json must be updated to.
# latest.json points at the exact names in $Dir, so renamed files and the updater always agree.
param([string]$Dir = "out", [string]$Tag, [string]$Repo)
$ErrorActionPreference = "Stop"
$ver = $Tag.TrimStart("v")
$nsis = @(Get-ChildItem "$Dir/*.exe")
$msi = @(Get-ChildItem "$Dir/*.msi")
if ($nsis.Count -ne 1 -or $msi.Count -ne 1) { throw "expected one .exe and one .msi in $Dir" }
$base = "https://github.com/$Repo/releases/download/$Tag"
$plat = @{}
foreach ($pair in @(@("nsis", $nsis[0]), @("msi", $msi[0]))) {
  $sig = "$($pair[1].FullName).sig"
  if (-not (Test-Path $sig)) { throw "missing updater signature $sig (is TAURI_SIGNING_PRIVATE_KEY set?)" }
  $plat["windows-x86_64-$($pair[0])"] = @{ signature = (Get-Content $sig -Raw).Trim(); url = "$base/$($pair[1].Name)" }
}
$plat["windows-x86_64"] = $plat["windows-x86_64-nsis"]
$manifest = [ordered]@{
  version = $ver
  notes = "AutoMoto AI $ver - see https://github.com/$Repo/blob/main/CHANGELOG.md"
  pub_date = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
  platforms = $plat
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8NoBOM "$Dir/latest.json"
./scripts/ci/collect-windows.ps1 -Out $Dir -HashOnly | Out-Null   # SHA256SUMS.txt covers latest.json too
python scripts/ci/release_notes.py ensure --repo $Repo --tag $Tag
if ($LASTEXITCODE) { throw "could not create the release" }
gh release upload $Tag --repo $Repo --clobber (Get-ChildItem $Dir -File | ForEach-Object FullName)
if ($LASTEXITCODE) { throw "upload failed" }
"attached: $((Get-ChildItem $Dir -File).Name -join ', ')"
python scripts/ci/release_notes.py notes --repo $Repo --tag $Tag --out release-notes.md
if ($LASTEXITCODE) { throw "could not write the release notes" }
gh release edit $Tag --repo $Repo --notes-file release-notes.md
if ($LASTEXITCODE) { throw "could not update the release notes" }
