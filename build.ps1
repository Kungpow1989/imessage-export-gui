# Builds the Windows release: a folder with "iMessage Export.exe", the bundled
# imessage-exporter.exe and license files, zipped as iMessage-Export-Windows-x64.zip.
#
# Used by .github/workflows/release.yml, and can be run locally on Windows:
#   powershell -ExecutionPolicy Bypass -File build.ps1

$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Here

$AppName = 'iMessage Export'
$Dist = Join-Path $Here "dist\$AppName"
$ZipPath = Join-Path $Here 'dist\iMessage-Export-Windows-x64.zip'

Write-Host "== Installing build tools"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller==6.22.3
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Write-Host "== Building $AppName.exe"
# These modules come in with pymobiledevice3 but aren't used for backups. Leaving them out
# keeps the download much smaller.
$exclude = @('av', 'jedi', 'IPython', 'parso', 'matplotlib', 'tkinter',
             'PySide6.QtWebEngineCore', 'PySide6.QtQuick', 'PySide6.QtQml',
             'PySide6.Qt3DCore', 'PySide6.QtMultimedia')
$pyiArgs = @('--noconfirm', '--clean', '--windowed', '--name', $AppName,
             '--icon', 'assets\icon.ico', '--add-data', 'assets\icon.ico;assets',
             '--collect-all', 'pymobiledevice3')
foreach ($m in $exclude) { $pyiArgs += @('--exclude-module', $m) }
$pyiArgs += 'imessage_export_gui.py'
python -m PyInstaller @pyiArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "== Adding imessage-exporter"
$headers = @{ 'User-Agent' = 'imessage-export-gui-build' }
if ($env:GITHUB_TOKEN) { $headers['Authorization'] = "Bearer $env:GITHUB_TOKEN" }
$release = Invoke-RestMethod -Uri 'https://api.github.com/repos/ReagentX/imessage-exporter/releases/latest' -Headers $headers
$asset = $release.assets | Where-Object { $_.name -match 'windows.*\.exe$' } | Select-Object -First 1
if (-not $asset) { throw "No Windows .exe in imessage-exporter release $($release.tag_name)" }
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile (Join-Path $Dist 'imessage-exporter.exe') -UseBasicParsing
$ExporterTag = $release.tag_name
Write-Host "   imessage-exporter $ExporterTag ($($asset.name))"

Write-Host "== Adding licenses and notes"
Copy-Item LICENSE (Join-Path $Dist 'LICENSE.txt')
$notices = Get-Content THIRD-PARTY-NOTICES.md -Raw
$notices = $notices -replace '\{IMESSAGE_EXPORTER_VERSION\}', $ExporterTag
Set-Content -Path (Join-Path $Dist 'THIRD-PARTY-NOTICES.txt') -Value $notices -Encoding UTF8
Copy-Item 'assets\README.txt' (Join-Path $Dist 'README.txt')

Write-Host "== Self test"
$out = Join-Path $Here 'dist\selftest-out.txt'
$err = Join-Path $Here 'dist\selftest-err.txt'
$p = Start-Process -FilePath (Join-Path $Dist "$AppName.exe") -ArgumentList '--self-test' -Wait -PassThru -NoNewWindow `
     -RedirectStandardOutput $out -RedirectStandardError $err
Get-Content $out, $err -ErrorAction SilentlyContinue | Write-Host
if ($p.ExitCode -ne 0 -or -not (Select-String -Path $out -Pattern 'SELF TEST PASSED' -Quiet)) {
    throw "Self test failed (exit code $($p.ExitCode))"
}

Write-Host "== Zipping"
if (Test-Path $ZipPath) { Remove-Item $ZipPath }
Compress-Archive -Path $Dist -DestinationPath $ZipPath -CompressionLevel Optimal
$size = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
Write-Host "Built $ZipPath ($size MB)"
if ($env:GITHUB_OUTPUT) { "exporter_version=$ExporterTag" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8 }
