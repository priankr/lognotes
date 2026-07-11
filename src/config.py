"""Application configuration: schema, validation, load, and save.

Extracted from the Tk UI so the same config logic backs both the existing
Tkinter front end and a future headless sidecar. No Tk imports here.

The schema, whitelist validation, and `os.open(..., 0o600)` save semantics are
preserved exactly as they were in ``LogNotesApp``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional

from .paths import user_data_dir
from .transcription import (
    DEFAULT_ID as _DEFAULT_MODEL_ID,
    all_ids as _all_model_ids,
    normalize_id as _normalize_model_id,
    is_known_id as _is_known_model,
)

logger = logging.getLogger(__name__)


DEFAULT_CONFIG: dict[str, Any] = {
    "hotkey": "ctrl+shift+d",
    "whisper_model": _DEFAULT_MODEL_ID,
    "theme": "dark",
    "push_to_talk_mode": "hold",
    "overlay_corner": "bottom-right",
    "silence_timeout_seconds": 60,
}

# Auto-stop (toggle mode) silence window, in seconds. Clamped to a sane range so
# a bad config can't disable the feature outright or trip it near-instantly.
SILENCE_TIMEOUT_MIN = 10
SILENCE_TIMEOUT_MAX = 300

# Security: whitelist of allowed values.
ALLOWED_WHISPER_MODELS = set(_all_model_ids())
ALLOWED_MODIFIERS = {"ctrl", "shift", "alt", "cmd"}
ALLOWED_CORNERS = {"top-left", "top-right", "bottom-left", "bottom-right"}

# Config file path. LOGNOTES_CONFIG_FILE overrides it — used by tests and the
# sidecar's NO_RUNTIME mode to avoid touching the user's real config.
CONFIG_FILE = os.environ.get(
    "LOGNOTES_CONFIG_FILE", str(user_data_dir() / "config.json")
)


def validate_config(config: dict) -> dict:
    """Whitelist-validate a loaded config dict; invalid values fall back to defaults."""
    validated = DEFAULT_CONFIG.copy()

    raw_model = config.get("whisper_model")
    normalized = _normalize_model_id(raw_model)
    if normalized in ALLOWED_WHISPER_MODELS:
        if raw_model != normalized:
            logger.info(f"Migrated whisper_model '{raw_model}' -> '{normalized}'")
        validated["whisper_model"] = normalized
    else:
        logger.warning(f"Invalid whisper_model '{raw_model}', using default")

    hotkey = config.get("hotkey", "").lower()
    if hotkey:
        parts = hotkey.split("+")
        modifiers = [p for p in parts if p in ALLOWED_MODIFIERS]
        keys = [p for p in parts if p not in ALLOWED_MODIFIERS and p.isalnum() and len(p) <= 10]
        if modifiers and len(keys) == 1:
            validated["hotkey"] = "+".join(modifiers + keys)
        else:
            logger.warning(f"Invalid hotkey '{hotkey}', using default")

    if config.get("theme") in ["dark", "light"]:
        validated["theme"] = config["theme"]

    if config.get("push_to_talk_mode") in ["hold", "toggle"]:
        validated["push_to_talk_mode"] = config["push_to_talk_mode"]

    if config.get("overlay_corner") in ALLOWED_CORNERS:
        validated["overlay_corner"] = config["overlay_corner"]

    is_valid, normalized_timeout = _v_silence_timeout(config.get("silence_timeout_seconds"))
    if is_valid:
        validated["silence_timeout_seconds"] = normalized_timeout
    elif config.get("silence_timeout_seconds") is not None:
        logger.warning(
            f"Invalid silence_timeout_seconds '{config.get('silence_timeout_seconds')}', using default"
        )

    return validated


# Per-key validators returning (is_valid, normalized_value). Each mirrors the
# corresponding rule in validate_config so the whitelist lives conceptually in
# one place; these are the single-key form used by the sidecar's setConfig RPC.
def _v_whisper_model(value: Any) -> tuple[bool, Any]:
    # normalize_id() coerces *anything* unknown to the default, which is right
    # for migrating stale configs on load but wrong for a direct RPC set — we
    # don't want garbage silently becoming whisper-base. Accept only genuinely
    # recognized forms (current id, display name, or known legacy alias).
    if not isinstance(value, str) or not _is_known_model(value):
        return False, value
    return True, _normalize_model_id(value)


def _v_hotkey(value: Any) -> tuple[bool, Any]:
    if not isinstance(value, str):
        return False, value
    hotkey = value.lower()
    parts = hotkey.split("+")
    modifiers = [p for p in parts if p in ALLOWED_MODIFIERS]
    keys = [p for p in parts if p not in ALLOWED_MODIFIERS and p.isalnum() and len(p) <= 10]
    if modifiers and len(keys) == 1:
        return True, "+".join(modifiers + keys)
    return False, value


def _v_theme(value: Any) -> tuple[bool, Any]:
    return value in ("dark", "light"), value


def _v_ptt_mode(value: Any) -> tuple[bool, Any]:
    return value in ("hold", "toggle"), value


def _v_overlay_corner(value: Any) -> tuple[bool, Any]:
    return value in ALLOWED_CORNERS, value


def _v_silence_timeout(value: Any) -> tuple[bool, Any]:
    # Accept ints (and int-valued floats/strings) and clamp into range. bool is
    # an int subclass but is not a valid timeout, so reject it explicitly.
    if isinstance(value, bool):
        return False, value
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return False, value
    clamped = max(SILENCE_TIMEOUT_MIN, min(SILENCE_TIMEOUT_MAX, seconds))
    return True, clamped


_KEY_VALIDATORS = {
    "whisper_model": _v_whisper_model,
    "hotkey": _v_hotkey,
    "theme": _v_theme,
    "push_to_talk_mode": _v_ptt_mode,
    "overlay_corner": _v_overlay_corner,
    "silence_timeout_seconds": _v_silence_timeout,
}


def validate_value(key: str, value: Any) -> tuple[bool, Any]:
    """Validate a single config key/value against the whitelist rules.

    Returns ``(is_valid, normalized_value)``. Used by the sidecar's setConfig
    RPC so a malformed value from any client is rejected — matching the
    guarantees the Tk widgets used to enforce by construction.
    """
    validator = _KEY_VALIDATORS.get(key)
    if validator is None:
        return False, value
    return validator(value)


def load_config() -> dict:
    """Load and validate config from disk, or return defaults if absent/invalid."""
    config_path = Path(CONFIG_FILE)
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                loaded = json.load(f)
                return validate_config(loaded)
        except json.JSONDecodeError as e:
            logger.error(f"Config file has invalid JSON: {e}")
        except PermissionError as e:
            logger.error(f"Permission denied reading config: {e}")
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
    return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> None:
    """Write config to disk with restricted (0o600) permissions set at creation."""
    try:
        # Create the file with restricted permissions from the start so there is
        # no window between creation and chmod (race condition). O_TRUNC resets
        # an existing file; O_CREAT creates if absent.
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(CONFIG_FILE, flags, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save config: {e}")


class ConfigStore:
    """Mutable, file-backed config holder shared by any front end.

    Wraps the module-level functions so consumers can read/update/persist
    without touching Tk. ``LogNotesApp`` and the future sidecar both hold one
    of these instead of owning config logic themselves.
    """

    def __init__(self, data: Optional[dict] = None):
        self._data: dict = data if data is not None else load_config()
        self._on_change: Optional[Callable[[str, Any], None]] = None

    def subscribe(self, callback: Callable[[str, Any], None]) -> None:
        """Register a callback invoked as ``callback(key, value)`` after each set+save."""
        self._on_change = callback

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Update a key in memory and persist the whole config to disk."""
        self._data[key] = value
        save_config(self._data)
        if self._on_change is not None:
            try:
                self._on_change(key, value)
            except Exception as e:
                logger.warning(f"Config change callback failed for '{key}': {e}")

    def as_dict(self) -> dict:
        """Return a shallow copy of the current config."""
        return self._data.copy()

    # Dict-compatibility shims so existing call sites that treated config as a
    # plain dict keep working unchanged.
    def copy(self) -> dict:
        return self._data.copy()

    def save(self) -> None:
        """Persist the current config to disk."""
        save_config(self._data)
