# Copy the Tauri installers to one folder with clear, URL-friendly release names and write SHA256SUMS.txt:
#   AutoMoto-AI-Setup-5.6.0-beta.4-Windows-x64.exe (+ .sig)   the NSIS installer, for most people
#   AutoMoto-AI-5.6.0-beta.4-Windows-x64.msi (+ .sig)         the MSI, for IT / all users
# The names use the app version, so a beta is called a beta even where Windows needs a plain number (the MSI
# product version is 5.6.0 for 5.6.0-beta.4). Releases up to 5.6.0-beta.3 used AutoMoto-AI_<ver>_x64-setup.exe
# and AutoMoto-AI_<ver>_x64_en-US.msi; those stay as they are. The names come from scripts/ci/release_notes.py.
#   -HashOnly   only rewrite SHA256SUMS.txt (after the files were replaced by Authenticode-signed ones)
param([string]$Out = "out", [switch]$HashOnly)
$ErrorActionPreference = "Stop"
function Write-Sums {
  $lines = Get-ChildItem $Out -File | Where-Object Name -ne "SHA256SUMS.txt" | Sort-Object Name | ForEach-Object {
    "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name
  }
  $lines | Set-Content -Encoding ascii (Join-Path $Out "SHA256SUMS.txt")
  Get-ChildItem $Out -File | ForEach-Object { "{0,-50} {1,12:N0} bytes" -f $_.Name, $_.Length }
  $lines
}
if ($HashOnly) { Write-Sums; exit 0 }
$bundle = "apps/desktop/src-tauri/target/release/bundle"
New-Item -ItemType Directory -Force $Out | Out-Null
$ver = (Get-Content apps/desktop/src-tauri/tauri.conf.json -Raw | ConvertFrom-Json).version
$names = python scripts/ci/release_notes.py names $ver | ConvertFrom-Json
if ($LASTEXITCODE -or -not $names.setup) { throw "could not get the release file names" }
$exe = @(Get-ChildItem "$bundle/nsis/*-setup.exe")
$msi = @(Get-ChildItem "$bundle/msi/*.msi")
if ($exe.Count -ne 1 -or $msi.Count -ne 1) { throw "expected one NSIS installer and one MSI, got $($exe.Count) and $($msi.Count)" }
foreach ($pair in @(@($exe[0], $names.setup), @($msi[0], $names.msi))) {
  Copy-Item $pair[0].FullName (Join-Path $Out $pair[1])
  if (Test-Path "$($pair[0].FullName).sig") { Copy-Item "$($pair[0].FullName).sig" (Join-Path $Out "$($pair[1]).sig") }
}
Write-Sums
