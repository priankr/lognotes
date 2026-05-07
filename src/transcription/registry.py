"""Transcription model registry.

Maps a stable model id (stored in config + activity entries) to a display
label, backend, and the backend-specific argument used to load it.

Ids chosen to be stable across sessions — renaming the display label is
safe, but changing an id requires a config migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Backend = Literal["whisper", "parakeet"]


@dataclass(frozen=True)
class ModelSpec:
    id: str
    display: str
    backend: Backend
    backend_arg: str  # size string for whisper, HF repo id for parakeet


MODELS: tuple[ModelSpec, ...] = (
    ModelSpec("whisper-tiny",  "Whisper tiny",  "whisper",  "tiny"),
    ModelSpec("whisper-base",  "Whisper base",  "whisper",  "base"),
    ModelSpec("whisper-small", "Whisper small", "whisper",  "small"),
    # Parakeet support is wired end-to-end (backend, device detection, PyInstaller
    # hooks) but disabled by default — in testing it offered no quality advantage
    # over Whisper small and carried a ~1.2 GB download. To enable:
    #   1. Uncomment the line below.
    #   2. Uncomment `onnx-asr[hub]` in requirements.txt and `pip install` it.
    #   3. (Packaged builds only) add "onnxruntime", "onnx_asr" to _BUNDLE_PKGS
    #      in build/LogNotes.spec and rebuild.
    # Other onnx-asr models also work here — supported ids include
    # nemo-parakeet-tdt-0.6b-v2/v3 and nemo-canary-*; see parakeet.py for the
    # backend_arg → onnx-asr id mapping.
    # ModelSpec("parakeet-v3", "Parakeet 0.6B v3 (multilingual)", "parakeet", "nvidia/parakeet-tdt-0.6b-v3"),
)

_BY_ID = {m.id: m for m in MODELS}
_BY_DISPLAY = {m.display: m for m in MODELS}

# Legacy aliases used before the registry existed or before ONNX Parakeet.
_LEGACY_ALIASES = {
    "tiny": "whisper-tiny",
    "base": "whisper-base",
    "small": "whisper-small",
    "medium": "whisper-base",  # medium/large were never in the dropdown; fall back
    "large": "whisper-base",
    # Parakeet was disabled by default after evaluation — migrate any stored
    # Parakeet ids to Whisper small (closest quality tier). If a user has
    # re-enabled the registry entry below, normalize_id() sees "parakeet-v3"
    # directly and these aliases are not hit.
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


def get(model_id: str) -> ModelSpec:
    return _BY_ID[normalize_id(model_id)]


def display_for(model_id: str) -> str:
    return get(model_id).display
