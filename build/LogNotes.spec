# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for LogNotes (the Electron app's Python back end).
#
# This is the canonical LogNotes build. It packages sidecar.py, which the
# Electron front end spawns and drives. The legacy Tk build lives in
# LogNotes-tk.spec (kept locally for reference).
#
# Build:
#     pyinstaller build/LogNotes.spec --clean --noconfirm
#
# Output:
#     dist/LogNotes/LogNotes.exe  (plus bundled runtime)
#
# Mirrors the Tk spec's native-DLL collection for the torch/whisper stack and
# the "do not exclude unittest" rule, but the entry point is sidecar.py and
# websockets is added. console=True so the `PORT <n>` handshake line the
# Electron parent reads is emitted on a real stdout.
#
# The sidecar imports LogNotesController from src/controller.py (Tk-free), so it
# no longer pulls in tkinter/LogNotesApp. The ttkbootstrap hiddenimport and the
# src/ui/assets data below are now belt-and-suspenders (the logo is referenced
# via src/paths) and could be trimmed if a future cleanup verifies they are
# unused; left in place to avoid destabilizing a working build.

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
    "ttkbootstrap",
    "websockets",
]

# Collect everything for native-DLL-heavy deps. Saves hours of whack-a-mole.
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
        print(f"[spec] collect_all skipped {pkg}: {e}")

datas += collect_data_files("ttkbootstrap")


a = Analysis(
    [str(PROJECT_ROOT / "sidecar.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Do NOT exclude unittest — torch.utils._config_module imports it at runtime.
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
    name="LogNotes",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=True: the Electron parent reads the `PORT <n>` line from stdout.
    console=True,
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
    name="LogNotes",
)
