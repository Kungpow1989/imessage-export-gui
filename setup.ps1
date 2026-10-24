# iMessage Export GUI setup (for running from source)
# Most people should download the ready-made .exe from the Releases page instead:
#   https://github.com/Kungpow1989/imessage-export-gui/releases/latest
#
# Installs everything imessage_export_gui.py needs on Windows:
#   1. Python 3.10 or newer (via winget, if missing)
#   2. PySide6 and pymobiledevice3 (for backing up the iPhone)
#   3. Apple Devices app (for the iPhone USB driver, if neither it nor iTunes is installed)
#   4. imessage-exporter.exe (latest Windows build from GitHub, saved next to this script)
#   5. ImageMagick and ffmpeg (optional, for converting photos, audio and video)
#   6. A desktop shortcut
#
# Safe to run again later. It updates imessage-exporter, PySide6 and pymobiledevice3.

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$GuiScript = Join-Path $Here 'imessage_export_gui.py'
$ExporterExe = Join-Path $Here 'imessage-exporter.exe'

function Step($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function Ok($text)   { Write-Host "   OK: $text" -ForegroundColor Green }
function Warn($text) { Write-Host "   $text" -ForegroundColor Yellow }

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Have-Winget { return [bool](Get-Command winget -ErrorAction SilentlyContinue) }

function Winget-Install($id) {
    winget install -e --id $id --accept-package-agreements --accept-source-agreements --silent
    Refresh-Path
}

function Find-Python {
    # Prefer the py launcher; skip the Microsoft Store "python.exe" stub, which fails the check below
    $candidates = @()
    foreach ($cmd in 'py', 'python', 'python3') {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) { $candidates += $cmd }
    }
    $candidates += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | ForEach-Object { $_.FullName }

    foreach ($cmd in $candidates) {
        try {
            $out = & $cmd -c "import sys; print(sys.executable); print(1 if sys.version_info >= (3, 10) else 0)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $out.Count -ge 2 -and $out[1].Trim() -eq '1' -and (Test-Path $out[0].Trim())) {
                return $out[0].Trim()
            }
        } catch { }
    }
    return $null
}

Write-Host "iMessage Export GUI setup" -ForegroundColor White
Write-Host "Installing into: $Here"

if (-not (Test-Path $GuiScript)) {
    Warn "imessage_export_gui.py isn't in this folder. Put setup.bat, setup.ps1 and imessage_export_gui.py together, then run setup again."
    exit 1
}

# ---------- 1. Python ----------
Step "Python"
$Python = Find-Python
if (-not $Python) {
    if (-not (Have-Winget)) {
        Warn "Python 3.10+ isn't installed and winget isn't available."
        Warn "Install Python from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run setup again."
        exit 1
    }
    Write-Host "   Python 3.10+ not found. Installing Python 3.12..."
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements --silent
    Refresh-Path
    $Python = Find-Python
    if (-not $Python) {
        Warn "Python installed but this window can't see it yet. Close this window and run setup again."
        exit 1
    }
}
$PyVersion = & $Python -c "import platform; print(platform.python_version())"
Ok "Python $PyVersion at $Python"

# ---------- 2. Python packages ----------
Step "PySide6 and pymobiledevice3"
& $Python -m pip install --upgrade --quiet pip
& $Python -m pip install --upgrade --quiet PySide6 pymobiledevice3
if ($LASTEXITCODE -ne 0) { Warn "pip couldn't install the packages. See the errors above."; exit 1 }
$PySideVersion = & $Python -c "import PySide6; print(PySide6.__version__)"
Ok "PySide6 $PySideVersion"
$PmdVersion = & $Python -c "from importlib.metadata import version; print(version('pymobiledevice3'))"
Ok "pymobiledevice3 $PmdVersion"

# ---------- 3. iPhone USB driver ----------
Step "iPhone USB driver (Apple Mobile Device Service)"
$appleService = Get-Service -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like '*Apple Mobile Device*' } | Select-Object -First 1
if ($appleService) {
    if ($appleService.Status -ne 'Running') {
        Warn "Installed but not running. It usually starts by itself when the iPhone is plugged in."
    } else {
        Ok "Installed and running"
    }
} else {
    Write-Host "   Not found. It comes with the Apple Devices app (or iTunes), which is needed to talk to the iPhone over USB."
    $installed = $false
    if (Have-Winget) {
        $answer = Read-Host "   Install Apple Devices from the Microsoft Store now? [Y/n]"
        if ($answer -eq '' -or $answer -match '^[Yy]') {
            winget install --id 9NP83LWLPZ9K --source msstore --accept-package-agreements --accept-source-agreements
            $installed = ($LASTEXITCODE -eq 0)
        }
    }
    if ($installed) {
        Ok "Apple Devices installed. Open it once and plug in the iPhone so the driver finishes setting up."
    } else {
        Warn "Opening the Microsoft Store page for Apple Devices. Install it, then you're set."
        Start-Process 'ms-windows-store://pdp/?productid=9NP83LWLPZ9K'
    }
}

# ---------- 4. imessage-exporter ----------
Step "imessage-exporter"
try {
    $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/ReagentX/imessage-exporter/releases/latest' -Headers @{ 'User-Agent' = 'imessage-export-gui-setup' }
    $asset = $release.assets | Where-Object { $_.name -match 'windows.*\.exe$' } | Select-Object -First 1
    if (-not $asset) { throw "No Windows .exe in release $($release.tag_name)" }

    $current = $null
    if (Test-Path $ExporterExe) {
        try { $current = (& $ExporterExe -V 2>$null) -replace '[^\d\.]', '' } catch { }
    }
    if ($current -and $current -eq $release.tag_name) {
        Ok "Already up to date ($current)"
    } else {
        Write-Host "   Downloading $($asset.name) ($([math]::Round($asset.size / 1MB, 1)) MB) from release $($release.tag_name)..."
        $tmp = "$ExporterExe.download"
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $tmp -UseBasicParsing
        Move-Item -Force $tmp $ExporterExe
        Unblock-File $ExporterExe -ErrorAction SilentlyContinue
        $ver = & $ExporterExe -V
        Ok "$ver saved to $ExporterExe"
    }
} catch {
    Warn "Couldn't download imessage-exporter: $($_.Exception.Message)"
    Warn "Get imessage-exporter-x86_64-pc-windows-gnu.exe from https://github.com/ReagentX/imessage-exporter/releases"
    Warn "rename it to imessage-exporter.exe and put it in $Here"
}

# ---------- 5. ImageMagick and ffmpeg ----------
Step "ImageMagick and ffmpeg (optional, for converting HEIC photos, audio and video)"
$needMagick = -not (Get-Command magick -ErrorAction SilentlyContinue)
$needFfmpeg = -not (Get-Command ffmpeg -ErrorAction SilentlyContinue)
if (-not $needMagick) { Ok "ImageMagick already installed" }
if (-not $needFfmpeg) { Ok "ffmpeg already installed" }
if ($needMagick -or $needFfmpeg) {
    if (-not (Have-Winget)) {
        Warn "winget isn't available, so skipping. Attachments will still export, just not converted."
    } else {
        $answer = Read-Host "   Install the missing ones now? [Y/n]"
        if ($answer -eq '' -or $answer -match '^[Yy]') {
            if ($needMagick) { Winget-Install 'ImageMagick.ImageMagick' }
            if ($needFfmpeg) { Winget-Install 'Gyan.FFmpeg' }
            Ok "Installed. They'll be picked up the next time the app starts."
        } else {
            Warn "Skipped. You can run setup again any time to add them."
        }
    }
}

# ---------- 6. Desktop shortcut ----------
Step "Desktop shortcut"
$PythonW = Join-Path (Split-Path $Python) 'pythonw.exe'
if (-not (Test-Path $PythonW)) { $PythonW = $Python }
$Shortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'iMessage Export.lnk'
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($Shortcut)
$lnk.TargetPath = $PythonW
$lnk.Arguments = "`"$GuiScript`""
$lnk.WorkingDirectory = $Here
$lnk.IconLocation = "$env:SystemRoot\System32\imageres.dll,15"
$lnk.Description = 'Back up an iPhone and export its iMessages'
$lnk.Save()
Ok "Created $Shortcut"

# ---------- Done ----------
Write-Host ""
Write-Host "All set. Open 'iMessage Export' from your desktop." -ForegroundColor Green
Write-Host "Plug in the iPhone, unlock it, and use step 1 in the app to back it up."
