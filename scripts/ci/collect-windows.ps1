# Copy the Tauri installers to one folder with URL-friendly names (GitHub turns spaces into dots) and
# print their sizes and SHA-256 hashes.
param([string]$Out = "out")
$ErrorActionPreference = "Stop"
$bundle = "apps/desktop/src-tauri/target/release/bundle"
New-Item -ItemType Directory -Force $Out | Out-Null
$files = @(Get-ChildItem "$bundle/nsis/*-setup.exe*") + @(Get-ChildItem "$bundle/msi/*.msi*")
if (-not ($files | Where-Object Name -like "*.exe") -or -not ($files | Where-Object Name -like "*.msi")) { throw "installers missing" }
# name every file after the app version, so a beta is called a beta even where Windows needs a plain
# number (the MSI product version is 5.6.0 for 5.6.0-beta.1): AutoMoto-AI_5.6.0-beta.1_x64-setup.exe
$ver = (Get-Content apps/desktop/src-tauri/tauri.conf.json -Raw | ConvertFrom-Json).version
foreach ($f in $files) {
  $name = $f.Name -replace ' ', '-'
  $name = $name -replace '^AutoMoto-AI_[^_]+_', "AutoMoto-AI_${ver}_"
  Copy-Item $f.FullName (Join-Path $Out $name)
}
Get-ChildItem $Out | ForEach-Object {
  $h = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
  "{0,-45} {1,10:N0} bytes  sha256 {2}" -f $_.Name, $_.Length, $h
} | Tee-Object -FilePath (Join-Path $Out "SHA256SUMS.txt")
