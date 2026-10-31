# Build the Microsoft Store package from the Tauri build: stage the app exe + resources + Assets, generate
# AppxManifest.xml (packaging/msstore/msix.py), make resources.pri, run makeappx (which validates the manifest
# against the Windows schemas), check the package unpacks, and wrap it as .msixupload for Partner Center.
# The package is NOT signed: the Microsoft Store signs it. -TestInstall signs a throw-away copy with a
# self-signed certificate, installs it, launches it, checks it runs and removes it again (CI only).
param([string]$Out = "msstore", [switch]$TestInstall)
$ErrorActionPreference = "Stop"
$ver = (Get-Content apps/desktop/src-tauri/tauri.conf.json -Raw | ConvertFrom-Json).version
$mver = python packaging/msstore/msix.py version $ver
if ($LASTEXITCODE) { throw "version mapping failed" }
$kit = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\makeappx.exe" | Sort-Object FullName | Select-Object -Last 1
if (-not $kit) { throw "makeappx.exe not found (Windows SDK)" }
$bin = $kit.DirectoryName
"Windows SDK tools: $bin"
$stage = Join-Path $env:RUNNER_TEMP "msix-stage"
Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $stage, "$stage\Assets", "$stage\resources", $Out | Out-Null
$release = "apps/desktop/src-tauri/target/release"
Copy-Item "$release/AutoMoto AI.exe" $stage
Copy-Item scripts/install.ps1 "$stage\resources\install.ps1"   # same place Tauri's bundle puts it
Copy-Item packaging/branding/out/msix/*.png "$stage\Assets"
Copy-Item LICENSE, NOTICE $stage
python packaging/msstore/msix.py manifest --version $ver --out "$stage\AppxManifest.xml"
if ($LASTEXITCODE) { throw "manifest generation failed" }
# resources.pri lets Windows pick the right image size (scale-100...400, targetsize-16...256)
Push-Location $stage
& "$bin\makepri.exe" createconfig /cf priconfig.xml /dq en-US /pv 10.0.0 /o | Out-Null
& "$bin\makepri.exe" new /pr . /cf priconfig.xml /mn AppxManifest.xml /of resources.pri /o
$priCode = $LASTEXITCODE
Remove-Item priconfig.xml -ErrorAction SilentlyContinue
Pop-Location
if ($priCode) { "::warning::makepri failed ($priCode) - packaging without resources.pri (the 100% images are used)"; Remove-Item "$stage\resources.pri" -ErrorAction SilentlyContinue }
$name = "AutoMoto-AI-$ver-Windows-x64"
$msix = Join-Path $Out "$name.msix"
& "$bin\makeappx.exe" pack /d $stage /p $msix /o
if ($LASTEXITCODE) { throw "makeappx pack failed (see the errors above: manifest schema or missing files)" }
$unpacked = Join-Path $env:RUNNER_TEMP "msix-unpacked"
& "$bin\makeappx.exe" unpack /p $msix /d $unpacked /o | Out-Null
if ($LASTEXITCODE) { throw "makeappx unpack failed" }
foreach ($f in @("AutoMoto AI.exe", "AppxManifest.xml", "resources\install.ps1", "Assets\StoreLogo.png", "Assets\Square44x44Logo.png")) {
  if (-not (Test-Path (Join-Path $unpacked $f))) { throw "package is missing $f" }
}
# .msixupload = a zip with the .msix inside: what Partner Center asks for
$upload = Join-Path $Out "$name.msixupload"
Compress-Archive -Path $msix -DestinationPath "$upload.zip" -Force
Move-Item "$upload.zip" $upload -Force
[xml]$m = Get-Content "$stage\AppxManifest.xml"
"package: $msix ($((Get-Item $msix).Length) bytes), version $mver (app $ver), identity $($m.Package.Identity.Name) / $($m.Package.Identity.Publisher)"
Get-ChildItem $Out | ForEach-Object { "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name } | Set-Content -Encoding ascii (Join-Path $Out "SHA256SUMS.txt")

if ($TestInstall) {
  # sign a COPY with a throw-away self-signed certificate whose subject matches the manifest Publisher
  $test = Join-Path $env:RUNNER_TEMP "msix-test.msix"
  Copy-Item $msix $test -Force
  $pub = $m.Package.Identity.Publisher
  $cert = New-SelfSignedCertificate -Type Custom -Subject $pub -KeyUsage DigitalSignature -FriendlyName "AutoMoto MSIX CI test" `
    -CertStoreLocation "Cert:\CurrentUser\My" -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}")
  $pfx = Join-Path $env:RUNNER_TEMP "msix-test.pfx"
  $pw = ConvertTo-SecureString -String ([Guid]::NewGuid().ToString()) -Force -AsPlainText
  Export-PfxCertificate -Cert $cert -FilePath $pfx -Password $pw | Out-Null
  & "$bin\signtool.exe" sign /fd SHA256 /f $pfx /p ([System.Net.NetworkCredential]::new("", $pw).Password) $test
  if ($LASTEXITCODE) { throw "test signing failed" }
  $cer = Join-Path $env:RUNNER_TEMP "msix-test.cer"
  Export-Certificate -Cert $cert -FilePath $cer | Out-Null
  Import-Certificate -FilePath $cer -CertStoreLocation "Cert:\LocalMachine\TrustedPeople" | Out-Null
  try {
    Add-AppxPackage -Path $test
    $pkg = Get-AppxPackage -Name $m.Package.Identity.Name
    if (-not $pkg) { throw "package didn't install" }
    "installed: $($pkg.PackageFullName) at $($pkg.InstallLocation)"
    Start-Process "shell:AppsFolder\$($pkg.PackageFamilyName)!AutoMotoAI"
    $proc = $null
    for ($i = 0; $i -lt 30 -and -not $proc; $i++) { Start-Sleep 1; $proc = Get-Process -Name "AutoMoto AI" -ErrorAction SilentlyContinue }
    if (-not $proc) { throw "the packaged app didn't start" }
    Start-Sleep 6
    $proc = Get-Process -Name "AutoMoto AI" -ErrorAction SilentlyContinue
    if (-not $proc) { throw "the packaged app exited right after starting" }
    "packaged app running: pid $($proc[0].Id), window '$($proc[0].MainWindowTitle)'"
    $proc | Stop-Process -Force
  } finally {
    Get-AppxPackage -Name $m.Package.Identity.Name | Remove-AppxPackage -ErrorAction SilentlyContinue
    Get-ChildItem Cert:\LocalMachine\TrustedPeople | Where-Object Subject -eq $pub | Remove-Item -ErrorAction SilentlyContinue
    Remove-Item $cert.PSPath, $pfx, $cer, $test -ErrorAction SilentlyContinue
  }
}
