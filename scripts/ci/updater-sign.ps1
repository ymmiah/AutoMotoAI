# After Authenticode signing (or when it was skipped), write Tauri updater .sig files for the
# final .exe and .msi in $Dir, then rewrite SHA256SUMS.txt so checksums match those files.
# Skips with a notice when TAURI_SIGNING_PRIVATE_KEY is not set (PR / unsigned builds).
param([string]$Dir = "out")
$ErrorActionPreference = "Stop"
if (-not (Test-Path $Dir)) { throw "missing folder $Dir" }
if (-not $env:TAURI_SIGNING_PRIVATE_KEY) {
  Write-Host "::notice::No updater signing key - leaving installers without .sig files"
  ./scripts/ci/collect-windows.ps1 -Out $Dir -HashOnly
  exit 0
}
$files = @(Get-ChildItem $Dir -File | Where-Object { $_.Extension -in ".exe", ".msi" })
if ($files.Count -eq 0) { throw "no .exe or .msi in $Dir" }
Push-Location apps/desktop
try {
  foreach ($f in $files) {
    $signArgs = @("tauri", "signer", "sign", "--private-key", $env:TAURI_SIGNING_PRIVATE_KEY, $f.FullName)
    if ($env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD) { $signArgs += @("--password", $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD) }
    & npx --no-install @signArgs
    if ($LASTEXITCODE) { throw "tauri signer failed for $($f.Name)" }
  }
} finally {
  Pop-Location
}
./scripts/ci/collect-windows.ps1 -Out $Dir -HashOnly
