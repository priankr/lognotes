"""Path helpers for dev and frozen (PyInstaller) builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "LogNotes"


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def resource_path(rel: str) -> Path:
    """Resolve a bundled resource path.

    When frozen, resolves against PyInstaller's `_MEIPASS`. In dev, resolves
    against the project root (parent of this file's `src/` directory).
    """
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent
    return base / rel


def user_data_dir() -> Path:
    """%APPDATA%\\LogNotes on Windows, ~/.config/LogNotes elsewhere."""
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_cache_dir() -> Path:
    """%LOCALAPPDATA%\\LogNotes\\cache on Windows, ~/.cache/LogNotes elsewhere."""
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        path = root / APP_NAME / "cache"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Caches" / APP_NAME
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path
