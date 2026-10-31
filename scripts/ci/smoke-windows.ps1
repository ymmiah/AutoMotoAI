# Clean-machine smoke test of one installer: silent install -> launch -> (sign-in screen screenshot) ->
# Local mode starts the engine and it answers /api/health -> closing the window stops the engine ->
# silent uninstall removes the app.
param([ValidateSet("nsis", "msi")][string]$Kind, [string]$Dir = "out", [string]$Shots = "shots")
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $Shots | Out-Null
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

function Shot([string]$name) {
  try {
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
    $bmp.Save((Join-Path $Shots "$Kind-$name.png"), [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
  } catch { "::warning::screenshot failed: $_" }
}
function Healthy { try { Invoke-RestMethod http://127.0.0.1:8765/api/health -TimeoutSec 3 | Out-Null; $true } catch { $false } }
function Engine { Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "automoto" -and $_.CommandLine -match "8765" } }

if (Healthy) { throw "something already answers on 8765" }
# start from a first run: the app reopens the last mode, and a previous run used Local mode
Remove-Item -Recurse -Force "$env:APPDATA\com.ymmiah.automoto" -ErrorAction SilentlyContinue

# 1. install silently
if ($Kind -eq "nsis") {
  $setup = Get-ChildItem "$Dir/*.exe" | Select-Object -First 1
  $p = Start-Process $setup.FullName -ArgumentList "/S" -Wait -PassThru
  if ($p.ExitCode) { throw "NSIS installer exit code $($p.ExitCode)" }
  $exe = Join-Path $env:LOCALAPPDATA "AutoMoto AI\AutoMoto AI.exe"
} else {
  $msi = Get-ChildItem "$Dir/*.msi" | Select-Object -First 1
  $p = Start-Process msiexec.exe -ArgumentList "/i", "`"$($msi.FullName)`"", "/qn", "/norestart", "/l*v", "`"$Shots\msi-install.log`"" -Wait -PassThru
  if ($p.ExitCode) { throw "msiexec exit code $($p.ExitCode)" }
  $exe = Join-Path $env:ProgramFiles "AutoMoto AI\AutoMoto AI.exe"
}
if (-not (Test-Path $exe)) {
  "::warning::app not at $exe, searching"
  $found = Get-ChildItem -Recurse -Filter "AutoMoto AI.exe" $env:LOCALAPPDATA, $env:ProgramFiles -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $found) { throw "app not found after install" }
  $exe = $found.FullName
}
"installed: $exe ($((Get-Item $exe).Length) bytes)"
$res = Join-Path (Split-Path $exe) "resources\install.ps1"
if (-not (Test-Path $res)) { throw "bundled installer script missing: $res" }

# 2. launch on the sign-in screen
$app = Start-Process $exe -PassThru
Start-Sleep 8
if ($app.HasExited) { throw "the app exited at once (code $($app.ExitCode))" }
Shot "sign-in-screen"
if (Healthy) { throw "the engine started without being asked" }
$app.CloseMainWindow() | Out-Null
if (-not $app.WaitForExit(15000)) { Stop-Process -Id $app.Id -Force }

# 3. --local starts the installed engine, and the window opens it
$app = Start-Process $exe -ArgumentList "--local" -PassThru
$ok = $false
foreach ($i in 1..90) { if (Healthy) { $ok = $true; break }; Start-Sleep 1 }
if (-not $ok) {
  Get-ChildItem -Recurse "$env:LOCALAPPDATA\com.ymmiah.automoto" -Filter *.log -ErrorAction SilentlyContinue | ForEach-Object { Copy-Item $_.FullName $Shots; Get-Content $_.FullName -Tail 40 }
  throw "the local engine did not answer on 8765"
}
"local engine healthy: $(Invoke-RestMethod http://127.0.0.1:8765/api/health | ConvertTo-Json -Compress)"
$eng = @(Engine)
if (-not $eng) { throw "no engine process" }
if ($eng[0].ParentProcessId -ne $app.Id) { "::warning::engine parent $($eng[0].ParentProcessId) is not the app $($app.Id)" }
Start-Sleep 6
Shot "local-mode"

# 4. closing the window stops the engine it started
$app.CloseMainWindow() | Out-Null
if (-not $app.WaitForExit(20000)) { Stop-Process -Id $app.Id -Force; throw "the app did not close" }
$gone = $false
foreach ($i in 1..20) { if (-not (Healthy) -and -not (Engine)) { $gone = $true; break }; Start-Sleep 1 }
if (-not $gone) { Engine | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; throw "the engine kept running after the app closed" }
"engine stopped with the app"

# 5. uninstall silently
if ($Kind -eq "nsis") {
  $un = Join-Path (Split-Path $exe) "uninstall.exe"
  $p = Start-Process $un -ArgumentList "/S" -Wait -PassThru
  foreach ($i in 1..30) { if (-not (Test-Path $exe)) { break }; Start-Sleep 1 }
} else {
  $p = Start-Process msiexec.exe -ArgumentList "/x", "`"$($msi.FullName)`"", "/qn", "/norestart" -Wait -PassThru
  if ($p.ExitCode) { throw "msiexec /x exit code $($p.ExitCode)" }
}
if (Test-Path $exe) { throw "still installed after uninstall" }
"${Kind}: install, launch, local mode, close and uninstall all passed"
