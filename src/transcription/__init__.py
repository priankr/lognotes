from .base import Transcriber
from .registry import (
    MODELS,
    ModelSpec,
    DEFAULT_ID,
    all_ids,
    all_displays,
    display_for,
    get,
    normalize_id,
)
from .whisper import WhisperTranscriber


def create_transcriber(model_id: str) -> Transcriber:
    """Build the appropriate backend for a registry model id."""
    spec = get(model_id)
    if spec.backend == "whisper":
        return WhisperTranscriber(model_size=spec.backend_arg)
    if spec.backend == "parakeet":
        from .parakeet import ParakeetTranscriber
        return ParakeetTranscriber(model_id=spec.backend_arg)
    raise ValueError(f"Unknown backend: {spec.backend}")


__all__ = [
    "Transcriber",
    "WhisperTranscriber",
    "MODELS",
    "ModelSpec",
    "DEFAULT_ID",
    "all_ids",
    "all_displays",
    "display_for",
    "get",
    "normalize_id",
    "create_transcriber",
]
