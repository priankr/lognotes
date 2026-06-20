# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the legacy Tk LogNotes app (release, --noconsole).
#
# Superseded by the Electron build (build/LogNotes.spec packages the sidecar).
# Kept locally for reference; produces a standalone Tk app.
#
# Build:
#     pyinstaller build/LogNotes-tk.spec --clean --noconfirm
#
# Output:
#     dist/LogNotes-tk/LogNotes-tk.exe  (plus bundled runtime)

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files

PROJECT_ROOT = Path(SPECPATH).parent

block_cipher = None

datas = [
    (str(PROJECT_ROOT / "src" / "ui" / "assets"), "src/ui/assets"),
]
binaries = []
hiddenimports = [
    "sounddevice",
    "sounddevice._sounddevice",
    "silero_vad",
    "pystray._win32",
    "ttkbootstrap",
]

# Collect everything for native-DLL-heavy deps. Saves hours of whack-a-mole.
# To enable Parakeet support, add "onnxruntime", "onnx_asr" here and rebuild
# (also uncomment the registry entry + requirements.txt line).
_BUNDLE_PKGS = (
    "sounddevice", "faster_whisper", "ctranslate2", "torch", "torchaudio",
)
for pkg in _BUNDLE_PKGS:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        # onnx_asr is optional at build time — skip if not installed.
        print(f"[spec] collect_all skipped {pkg}: {e}")

datas += collect_data_files("ttkbootstrap")


a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LogNotes-tk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / "src" / "ui" / "assets" / "logo.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LogNotes-tk",
)
