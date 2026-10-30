<#
.SYNOPSIS
  AutoMoto AI installer for Windows 10/11 (PowerShell 5.1 or 7+).

.DESCRIPTION
  Installs AutoMoto AI into its own virtualenv under %LOCALAPPDATA%\automoto-ai, adds an `automoto`
  command to your user PATH and creates %USERPROFILE%\.automoto\.env for your keys.
  Safe by design: the release wheel is checked against a pinned SHA-256, nothing is piped into a shell,
  no admin rights are needed, and optional tools are installed with winget only after you agree.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -FromSource -Full
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -SystemDeps
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -AutoStart
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Uninstall
#>
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '', Justification = 'interactive installer: coloured console output')]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSReviewUnusedParameter', 'Yes', Justification = 'used inside Confirm-Step')]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSUseShouldProcessForStateChangingFunctions', '', Justification = 'only edits the user PATH during -Uninstall')]
[CmdletBinding()]
param(
    [string]$Version = "5.5.0",
    [string]$Sha256 = "",
    [string]$Wheel = "",
    [switch]$FromSource,
    [string]$SourceDir = "",
    [string]$FromGit = "",
    [string]$Extras = "office",
    [switch]$Full,
    [switch]$SystemDeps,
    [switch]$AutoStart,
    [switch]$Yes,
    [switch]$Uninstall,
    [switch]$Purge
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # much faster Invoke-WebRequest on Windows PowerShell 5.1

$Repo = "ymmiah/AutoMotoAI"
$Pinned = @{
    "5.5.0"   = "755bc31b8f8b6f1ed5330c5356b05e9509f94f0eafc3b6e9aa7eab443f223107"
    "5.6.0b1" = "0c9529605b3d18e9739f408da745074a48dd77408fdc4526e241938955a13b22"   # beta (tag v5.6.0-beta.1)
}
$AppDir = Join-Path $env:LOCALAPPDATA "automoto-ai"
$Venv = Join-Path $AppDir "venv"
$BinDir = Join-Path $AppDir "bin"
$DataDir = if ($env:AUTOMOTO_DATA_DIR) { $env:AUTOMOTO_DATA_DIR } else { Join-Path $env:USERPROFILE ".automoto" }
if ($Full) { $Extras = "office,data" }
if (-not $SourceDir) { $SourceDir = Split-Path -Parent $PSScriptRoot }

function Say([string]$m) { Write-Host "==> $m" -ForegroundColor Green }
function Warn([string]$m) { Write-Host "!!  $m" -ForegroundColor Yellow }
function Confirm-Step([string]$q) {
    if ($Yes) { return $true }
    $a = Read-Host "$q [y/N]"
    return ($a -match '^(y|yes)$')
}

function Remove-FromUserPath([string]$dir) {
    $p = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($p) {
        $parts = $p.Split(";") | Where-Object { $_ -and ($_.TrimEnd("\") -ne $dir.TrimEnd("\")) }
        [Environment]::SetEnvironmentVariable("Path", ($parts -join ";"), "User")
    }
}

$TaskName = "AutoMoto AI"
if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Say "Removed the '$TaskName' log-on task"
    }
    Say "Removing $AppDir"
    if (Test-Path $AppDir) { Remove-Item -Recurse -Force $AppDir }
    Remove-FromUserPath $BinDir
    if ($Purge) {
        if (Confirm-Step "Also delete $DataDir (chats, memory, workspace files, keys)?") {
            if (Test-Path $DataDir) { Remove-Item -Recurse -Force $DataDir }
            Say "Deleted $DataDir"
        }
    } else {
        Say "Kept your data in $DataDir (delete it yourself, or run with -Uninstall -Purge)"
    }
    return
}

# ---- 1. Python 3.10+ ---------------------------------------------------------------------------------
function Find-Python {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in "3.13", "3.12", "3.11", "3.10") { $candidates += , @("py", "-$v") }
    }
    $candidates += , @("python")
    $candidates += , @("python3")
    foreach ($c in $candidates) {
        $exe = $c[0]; $pre = @($c | Select-Object -Skip 1)
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        try {
            # the Microsoft Store "python" alias opens the Store instead of running - this check skips it
            $out = & $exe @pre -c "import sys; print(sys.executable if sys.version_info >= (3, 10) else '')" 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) { return ($out | Select-Object -Last 1).Trim() }
        } catch { continue }
    }
    return $null
}
$Py = Find-Python
if (-not $Py) {
    Warn "Python 3.10 or newer is needed. Install it, open a NEW PowerShell window, and run this again:"
    Write-Host "  winget install -e --id Python.Python.3.12"
    Write-Host "  (or https://www.python.org/downloads/ - tick 'Add python.exe to PATH')"
    exit 1
}
Say "Using $(& $Py -V) at $Py"

# ---- 2. optional tools via winget -------------------------------------------------------------------
if ($SystemDeps) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Warn "winget not found (install 'App Installer' from the Microsoft Store). Skipping optional tools."
    } else {
        $ids = "TheDocumentFoundation.LibreOffice", "7zip.7zip", "oschwartz10612.Poppler", "PHP.PHP.8.4"
        Write-Host ("  winget install -e --id " + ($ids -join ", "))
        if (Confirm-Step "Install these optional Office/PDF/archive/PHP tools with winget?") {
            foreach ($id in $ids) {
                winget install -e --id $id --accept-package-agreements --accept-source-agreements
                if ($LASTEXITCODE -ne 0) { Warn "winget couldn't install $id (maybe already installed) - continuing" }
            }
        } else { Warn "Skipped optional tools." }
    }
}

# ---- 3. virtualenv -------------------------------------------------------------------------------------
$VPy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VPy)) {
    Say "Creating a private virtualenv in $Venv"
    New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
    & $Py -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "Couldn't create the virtualenv" }
}
& $VPy -m pip install --quiet --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }

# ---- 4. get and install AutoMoto ---------------------------------------------------------------------
$ExtraSpec = if ($Extras) { "[$Extras]" } else { "" }
if ($FromSource) {
    if (-not (Test-Path (Join-Path $SourceDir "pyproject.toml"))) { throw "$SourceDir is not an AutoMoto source folder" }
    Say "Installing from source: $SourceDir"
    & $VPy -m pip install --quiet --upgrade "$SourceDir$ExtraSpec"
} elseif ($FromGit) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git is needed for -FromGit (winget install -e --id Git.Git)" }
    Say "Installing from https://github.com/$Repo @ $FromGit"
    & $VPy -m pip install --quiet --upgrade "automoto-ai$ExtraSpec @ git+https://github.com/$Repo.git@$FromGit"
} else {
    if (-not $Sha256) { $Sha256 = $Pinned[$Version] }
    if (-not $Sha256) { throw "No pinned checksum for $Version - pass -Sha256 <hash from the release page> or use -FromSource" }
    $Name = "automoto_ai-$Version-py3-none-any.whl"
    $Tmp = Join-Path ([IO.Path]::GetTempPath()) ("automoto-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $Tmp | Out-Null
    $File = Join-Path $Tmp $Name
    try {
        if ($Wheel) { Copy-Item $Wheel $File }
        else {
            # beta wheels (5.6.0b1) live under the tag v5.6.0-beta.1
            $Tag = if ($Version -match '^(\d+\.\d+\.\d+)b(\d+)$') { "v$($Matches[1])-beta.$($Matches[2])" } else { "v$Version" }
            $Url = "https://github.com/$Repo/releases/download/$Tag/$Name"
            Say "Downloading $Url"
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $Url -OutFile $File -UseBasicParsing
        }
        $Got = (Get-FileHash -Algorithm SHA256 -Path $File).Hash.ToLowerInvariant()
        if ($Got -ne $Sha256.ToLowerInvariant()) { throw "Checksum mismatch for $Name (got $Got, expected $Sha256) - not installing" }
        Say "SHA-256 verified: $Got"
        & $VPy -m pip install --quiet --upgrade "$File$ExtraSpec"
    } finally {
        Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
    }
}
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# ---- 5. the `automoto` command (reads %USERPROFILE%\.automoto\.env) ----------------------------------
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$Code = "import os, sys; sys.path[:] = [p for p in sys.path if p not in ('', '.')]; from dotenv import load_dotenv; d = os.environ.get('AUTOMOTO_DATA_DIR') or os.path.join(os.path.expanduser('~'), '.automoto'); load_dotenv(os.path.join(os.path.expanduser(d), '.env'), override=False); sys.argv[0] = 'automoto'; from automoto.cli import main; sys.exit(main())"
$Cmd = "@echo off`r`nrem AutoMoto AI launcher made by scripts\install.ps1 - loads keys from %USERPROFILE%\.automoto\.env`r`n`"$VPy`" -c `"$Code`" %*`r`n"
[IO.File]::WriteAllText((Join-Path $BinDir "automoto.cmd"), $Cmd, [Text.Encoding]::ASCII)
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $UserPath) { $UserPath = "" }
if (-not ($UserPath.Split(";") -contains $BinDir)) {
    [Environment]::SetEnvironmentVariable("Path", ($BinDir + ";" + $UserPath).TrimEnd(";"), "User")
    Say "Added $BinDir to your user PATH (open a new terminal to use 'automoto')"
}
$env:Path = "$BinDir;$env:Path"

# ---- 6. settings file for keys ---------------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$EnvFile = Join-Path $DataDir ".env"
if (-not (Test-Path $EnvFile)) {
    $Template = @(
        "# AutoMoto AI settings. Add at least ONE key (free: NVIDIA NIM at https://build.nvidia.com,",
        "# Gemini at https://aistudio.google.com/apikey, Groq at https://console.groq.com/keys,",
        "# OpenRouter at https://openrouter.ai/keys). Environment variables override this file.",
        "NVIDIA_API_KEY=", "GEMINI_API_KEY=", "GROQ_API_KEY=", "OPENROUTER_API_KEY=",
        "# Slow answers / timeouts? Raise this (seconds):", "AI_TIMEOUT=120")
    [IO.File]::WriteAllLines($EnvFile, $Template)
    Say "Created $EnvFile - put your key(s) there (notepad `"$EnvFile`")"
} else {
    Say "Kept your existing $EnvFile"
}

# ---- 7. check ------------------------------------------------------------------------------------------------
& (Join-Path $BinDir "automoto.cmd") --version
if ($LASTEXITCODE -ne 0) { throw "automoto --version failed" }
# ---- 8. optional: start at log-on (no window, no admin rights) -------------------------------------------
if ($AutoStart) {
    $PyW = Join-Path $Venv "Scripts\pythonw.exe"
    # pythonw has no console: send output to %USERPROFILE%\.automoto\automoto.log
    $CodeW = "import os, sys; d = os.environ.get('AUTOMOTO_DATA_DIR') or os.path.join(os.path.expanduser('~'), '.automoto'); os.makedirs(d, exist_ok=True); sys.stdout = sys.stderr = open(os.path.join(d, 'automoto.log'), 'a', buffering=1, encoding='utf-8'); " + $Code
    $Action = New-ScheduledTaskAction -Execute $PyW -Argument ("-c `"$CodeW`" serve --no-browser")
    $Trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
        -Description "AutoMoto AI local web app (http://127.0.0.1:8765)" -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Say "AutoMoto now starts when you log on (Task Scheduler: '$TaskName'). Open it with: automoto open"
}

Write-Host ""
Write-Host "Done. Next (in a NEW PowerShell window):"
Write-Host "  1. notepad `"$EnvFile`"     # paste a key, e.g. NVIDIA_API_KEY=nvapi-..."
Write-Host "  2. automoto status           # shows which AIs are ready"
Write-Host "  3. automoto serve            # opens the web app (http://127.0.0.1:8765)"
Write-Host "Guide: https://github.com/$Repo/blob/main/docs/INSTALL.md"
