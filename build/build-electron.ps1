# Build LogNotes (the Electron app): PyInstaller back end -> electron-builder.
#
# This is the canonical build. The back end is packaged from sidecar.py into
# dist\LogNotes\ and bundled into the Electron installer. The legacy Tk build
# is build\build.ps1 (dist\LogNotes-tk\).
#
# ASCII-only (Windows PowerShell 5.1 mis-parses UTF-8 without a BOM).
#
# Usage (from the project root):
#     powershell -ExecutionPolicy Bypass -File build\build-electron.ps1
#
# Output:
#     dist\LogNotes\                   PyInstaller onedir back-end bundle
#     dist-electron\LogNotes Setup *.exe   NSIS installer (one combined artifact)
#
# Prerequisites:
#     - Python venv with requirements installed + pyinstaller
#     - Node + npm (electron-builder is a devDependency in electron/)
#
# Notes:
#     - Close any running LogNotes.exe first; running processes lock bundled
#       DLLs and the rebuild fails with "Access denied".
#     - The back-end bundle is large (torch-dominated, ~800 MB); the final
#       installer is correspondingly large.

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ElectronDir = Join-Path $ProjectRoot "electron"
$VenvPython  = Join-Path $ProjectRoot "venv\Scripts\python.exe"

Write-Host "== LogNotes Electron build ==" -ForegroundColor Cyan

if (-not (Test-Path $VenvPython)) {
    throw "venv python not found at $VenvPython. Create the venv and install requirements first."
}

# 1. Build the Python back end with PyInstaller.
# --workpath build\build keeps all intermediates under build/build/ (the single
# gitignored intermediate dir), matching build.ps1, instead of the default
# build/<name>/.
Write-Host "[1/3] Building back end with PyInstaller..." -ForegroundColor Yellow
& $VenvPython -m PyInstaller (Join-Path $ProjectRoot "build\LogNotes.spec") --clean --noconfirm --distpath "$ProjectRoot\dist" --workpath "$ProjectRoot\build\build"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller back-end build failed." }

$SidecarExe = Join-Path $ProjectRoot "dist\LogNotes\LogNotes.exe"
if (-not (Test-Path $SidecarExe)) { throw "Expected back-end exe not found at $SidecarExe." }
Write-Host "      back end -> $SidecarExe" -ForegroundColor Green

# 2. Ensure electron deps are installed.
Write-Host "[2/3] Installing Electron dependencies..." -ForegroundColor Yellow
Push-Location $ElectronDir
try {
    if (-not (Test-Path (Join-Path $ElectronDir "node_modules"))) {
        # --use-system-ca works around corporate SSL inspection (same class of
        # issue handled for HuggingFace in whisper.py).
        $env:NODE_OPTIONS = "--use-system-ca"
        npm install
        if ($LASTEXITCODE -ne 0) { throw "npm install failed." }
    }

    # 3. Two-stage package so we can embed the icon ourselves.
    #
    # signAndEditExecutable=false (in package.json) keeps electron-builder from
    # editing the exe -- which it can't do here because exe-editing pulls in the
    # winCodeSign package whose macOS symlinks Windows refuses to extract without
    # Developer Mode. The cost is that electron-builder no longer embeds the app
    # icon/version info. So we:
    #   3a. build the unpacked dir (--dir),
    #   3b. embed the icon + version info into LogNotes.exe via rcedit,
    #   3c. package the NSIS installer from that prepackaged dir.
    # CSC_IDENTITY_AUTO_DISCOVERY=false also disables signing (we ship unsigned,
    # same as the Tk build).
    $env:CSC_IDENTITY_AUTO_DISCOVERY = "false"

    Write-Host "[3/3] Packaging (stage a: unpacked dir)..." -ForegroundColor Yellow
    & (Join-Path $ElectronDir "node_modules\.bin\electron-builder.cmd") --dir
    if ($LASTEXITCODE -ne 0) { throw "electron-builder --dir failed." }

    $Unpacked = Join-Path $ProjectRoot "dist-electron\win-unpacked"
    $AppExe   = Join-Path $Unpacked "LogNotes.exe"
    $IconIco  = Join-Path $ProjectRoot "src\ui\assets\logo.ico"
    if (-not (Test-Path $AppExe)) { throw "Unpacked app exe not found at $AppExe." }

    Write-Host "      stage b: embedding icon + version info via rcedit..." -ForegroundColor Yellow
    $RcEdit = Join-Path $ElectronDir "node_modules\rcedit\bin\rcedit-x64.exe"
    & $RcEdit $AppExe `
        --set-icon $IconIco `
        --set-version-string "ProductName" "LogNotes" `
        --set-version-string "FileDescription" "LogNotes" `
        --set-version-string "CompanyName" "LogNotes"
    if ($LASTEXITCODE -ne 0) { throw "rcedit icon embed failed." }

    Write-Host "      stage c: packaging NSIS installer from edited dir..." -ForegroundColor Yellow
    & (Join-Path $ElectronDir "node_modules\.bin\electron-builder.cmd") --prepackaged $Unpacked
    if ($LASTEXITCODE -ne 0) { throw "electron-builder --prepackaged failed." }
}
finally {
    Pop-Location
}

Write-Host "== Done ==" -ForegroundColor Cyan
Write-Host "Installer output: dist-electron\" -ForegroundColor Green
