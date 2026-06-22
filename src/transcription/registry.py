"""Transcription model registry.

Maps a stable model id (stored in config + activity entries) to a display
label, backend, and the backend-specific argument used to load it.

Ids chosen to be stable across sessions — renaming the display label is
safe, but changing an id requires a config migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Backend = Literal["whisper"]


@dataclass(frozen=True)
class ModelSpec:
    id: str
    display: str
    backend: Backend
    backend_arg: str  # Whisper size string (e.g. "base")


MODELS: tuple[ModelSpec, ...] = (
    ModelSpec("whisper-base",  "Whisper base",  "whisper",  "base"),
    ModelSpec("whisper-small", "Whisper small", "whisper",  "small"),
)

_BY_ID = {m.id: m for m in MODELS}
_BY_DISPLAY = {m.display: m for m in MODELS}

# Legacy aliases for model ids that no longer have a registry entry, so stored
# configs from older versions still resolve instead of erroring.
_LEGACY_ALIASES = {
    # Whisper tiny was removed (quality too low to be useful) — migrate any
    # stored tiny reference to base, the new smallest tier.
    "tiny": "whisper-base",
    "whisper-tiny": "whisper-base",
    "base": "whisper-base",
    "small": "whisper-small",
    "medium": "whisper-base",  # medium/large were never in the dropdown; fall back
    "large": "whisper-base",
    # Parakeet was evaluated and removed (no quality gain over Whisper small,
    # plus large download + Windows symlink/SSL friction). Migrate any stored
    # Parakeet ids to the closest Whisper tier.
    "parakeet-110m": "whisper-small",
    "parakeet-0.6b": "whisper-small",
    "parakeet-v3": "whisper-small",
}

DEFAULT_ID = "whisper-base"


def all_ids() -> list[str]:
    return [m.id for m in MODELS]


def all_displays() -> list[str]:
    return [m.display for m in MODELS]


def normalize_id(value: str | None) -> str:
    """Return a valid model id, falling back to DEFAULT_ID.

    Accepts current ids, display names, and legacy bare whisper sizes.
    """
    if not value:
        return DEFAULT_ID
    if value in _BY_ID:
        return value
    if value in _BY_DISPLAY:
        return _BY_DISPLAY[value].id
    if value in _LEGACY_ALIASES:
        return _LEGACY_ALIASES[value]
    return DEFAULT_ID


def is_known_id(value: str | None) -> bool:
    """True if `value` is a recognized model reference (id, display, or alias).

    Unlike normalize_id(), this does NOT coerce unknown values to the default —
    it reports whether the value is genuinely recognized. Used to reject garbage
    on a direct config set rather than silently falling back.
    """
    return bool(value) and (
        value in _BY_ID or value in _BY_DISPLAY or value in _LEGACY_ALIASES
    )


def get(model_id: str) -> ModelSpec:
    return _BY_ID[normalize_id(model_id)]


def display_for(model_id: str) -> str:
    return get(model_id).display
