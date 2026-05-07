# -*- mode: python ; coding: utf-8 -*-
# Debug spec: identical to LogNotes.spec but console=True so stderr is
# visible. Use this when the release exe launches but silently fails (missing
# DLL, hidden import). Build:
#     pyinstaller build/LogNotes.debug.spec --clean --noconfirm

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files

PROJECT_ROOT = Path(SPECPATH).parent

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

_BUNDLE_PKGS = (
    "sounddevice", "faster_whisper", "ctranslate2", "torch", "torchaudio",
    # Add "onnxruntime", "onnx_asr" to enable bundled Parakeet support.
)
for pkg in _BUNDLE_PKGS:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f"[spec] collect_all skipped {pkg}: {e}")

datas += collect_data_files("ttkbootstrap")


a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter.test"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LogNotes-debug",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    icon=str(PROJECT_ROOT / "src" / "ui" / "assets" / "logo.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="LogNotes-debug",
)
