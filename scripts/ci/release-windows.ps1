# On a version tag: attach the Windows installers and a signed updater manifest (latest.json) to the release.
# The release is created as a draft if it doesn't exist yet; a maintainer publishes it.
param([string]$Dir = "out", [string]$Tag, [string]$Repo)
$ErrorActionPreference = "Stop"
$ver = $Tag.TrimStart("v")
$nsis = Get-ChildItem "$Dir/*-setup.exe" | Select-Object -First 1
$msi = Get-ChildItem "$Dir/*.msi" | Select-Object -First 1
$base = "https://github.com/$Repo/releases/download/$Tag"
$plat = @{}
foreach ($pair in @(@("nsis", $nsis), @("msi", $msi))) {
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
gh release view $Tag --repo $Repo *> $null
if ($LASTEXITCODE) {
  gh release create $Tag --repo $Repo --draft --verify-tag --title "AutoMoto AI $ver" --notes "Windows app and engine $ver. Notes: CHANGELOG.md"
  if ($LASTEXITCODE) { throw "could not create the release" }
}
gh release upload $Tag --repo $Repo --clobber (Get-ChildItem $Dir -File | ForEach-Object FullName)
if ($LASTEXITCODE) { throw "upload failed" }
"attached: $((Get-ChildItem $Dir -File).Name -join ', ')"
