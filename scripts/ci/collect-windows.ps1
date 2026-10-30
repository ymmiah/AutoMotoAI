# Copy the Tauri installers to one folder with URL-friendly names (GitHub turns spaces into dots) and
# print their sizes and SHA-256 hashes.
param([string]$Out = "out")
$ErrorActionPreference = "Stop"
$bundle = "apps/desktop/src-tauri/target/release/bundle"
New-Item -ItemType Directory -Force $Out | Out-Null
$files = @(Get-ChildItem "$bundle/nsis/*-setup.exe*") + @(Get-ChildItem "$bundle/msi/*.msi*")
if (-not ($files | Where-Object Name -like "*.exe") -or -not ($files | Where-Object Name -like "*.msi")) { throw "installers missing" }
foreach ($f in $files) {
  $name = $f.Name -replace ' ', '-'
  Copy-Item $f.FullName (Join-Path $Out $name)
}
Get-ChildItem $Out | ForEach-Object {
  $h = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
  "{0,-45} {1,10:N0} bytes  sha256 {2}" -f $_.Name, $_.Length, $h
} | Tee-Object -FilePath (Join-Path $Out "SHA256SUMS.txt")
