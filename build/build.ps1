param(
    [switch]$Debug,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

# This builds the legacy Tk app (dist/LogNotes-tk/). The Electron build
# (build/build-electron.ps1) writes dist/LogNotes/ — clean only our own output
# so the two builds do not wipe each other.
Write-Host "==> Cleaning previous Tk build output..." -ForegroundColor Cyan
if ($Debug) {
    if (Test-Path "$ProjectRoot\dist\LogNotes-tk-debug") { Remove-Item -Recurse -Force "$ProjectRoot\dist\LogNotes-tk-debug" }
} else {
    if (Test-Path "$ProjectRoot\dist\LogNotes-tk") { Remove-Item -Recurse -Force "$ProjectRoot\dist\LogNotes-tk" }
}
if (Test-Path "$ProjectRoot\build\build") { Remove-Item -Recurse -Force "$ProjectRoot\build\build" }

$Spec = if ($Debug) { "build\LogNotes-tk.debug.spec" } else { "build\LogNotes-tk.spec" }
Write-Host "==> Running PyInstaller ($Spec)..." -ForegroundColor Cyan
pyinstaller $Spec --clean --noconfirm --distpath "$ProjectRoot\dist" --workpath "$ProjectRoot\build\build"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

if ($Debug) {
    Write-Host "==> Debug build complete: dist/LogNotes-tk-debug/LogNotes-tk-debug.exe" -ForegroundColor Green
    exit 0
}

Write-Host "==> Build complete: dist/LogNotes-tk/LogNotes-tk.exe" -ForegroundColor Green

if ($SkipInstaller) { exit 0 }

$Iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue
if (-not $Iscc) {
    Write-Host "==> Inno Setup (iscc.exe) not found on PATH - skipping installer." -ForegroundColor Yellow
    Write-Host "    Install from https://jrsoftware.org/isdl.php to build the installer." -ForegroundColor Yellow
    exit 0
}

Write-Host "==> Running Inno Setup..." -ForegroundColor Cyan
& $Iscc.Source "$ProjectRoot\build\installer.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }

Write-Host "==> Installer built in build/Output/" -ForegroundColor Green
