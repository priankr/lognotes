"""NVIDIA Parakeet transcriber via onnx-asr.

Uses ONNX Runtime instead of NeMo — dramatically faster on CPU, much
smaller dependency footprint, and supports CUDA acceleration through
onnxruntime-gpu's CUDAExecutionProvider.

Unlike Whisper, Parakeet returns a single transcript per call (no native
segment streaming). `transcribe_segments` splits the final transcript on
sentence boundaries so the controller's checkpoint-paste pipeline still
gets natural chunks.
"""

from __future__ import annotations

import logging
import re
from typing import Iterator, Optional

import numpy as np

from .device import detect as detect_device

logger = logging.getLogger(__name__)

_SENTENCE_SPLIT = re.compile(r"(?<=[.?!])\s+")

# onnx-asr model identifiers are prefixed; we keep registry ids stable and
# map them here.
_ONNX_ASR_IDS = {
    "nvidia/parakeet-tdt-0.6b-v3": "nemo-parakeet-tdt-0.6b-v3",
}


class ParakeetTranscriber:
    """Transcribes audio using Parakeet ONNX models via onnx-asr."""

    def __init__(self, model_id: str = "nvidia/parakeet-tdt-0.6b-v3"):
        self.model_id = model_id
        self._model = None
        self._loaded_providers: list[str] = []

    def _load_model(self) -> None:
        if self._model is not None:
            return

        try:
            import onnx_asr
        except ImportError as e:
            raise RuntimeError(
                "onnx-asr is not installed. Install onnx-asr[hub] to use Parakeet models."
            ) from e

        onnx_asr_name = _ONNX_ASR_IDS.get(self.model_id, self.model_id)
        providers = _providers_for_device()

        logger.info(
            f"Loading Parakeet ONNX model '{onnx_asr_name}' "
            f"with providers={[p if isinstance(p, str) else p[0] for p in providers]}..."
        )
        self._model = onnx_asr.load_model(onnx_asr_name, providers=providers)
        self._loaded_providers = [p if isinstance(p, str) else p[0] for p in providers]
        logger.info("Parakeet model loaded.")

    def transcribe(self, audio: np.ndarray, language: Optional[str] = "en") -> str:
        if len(audio) == 0:
            return ""
        self._load_model()

        audio = np.asarray(audio, dtype=np.float32)
        # onnx-asr expects a 1-D float32 numpy array at 16 kHz.
        text = self._model.recognize(audio)
        if isinstance(text, list):
            text = " ".join(t for t in text if t)
        return (text or "").strip()

    def transcribe_segments(
        self, audio: np.ndarray, language: Optional[str] = "en"
    ) -> Iterator[str]:
        text = self.transcribe(audio, language=language)
        if not text:
            return
        for part in _SENTENCE_SPLIT.split(text):
            part = part.strip()
            if part:
                yield part

    def change_model(self, model_id: str) -> None:
        if model_id != self.model_id:
            self.model_id = model_id
            self._model = None
            self._loaded_providers = []

    @property
    def is_loaded(self) -> bool:
        return self._model is not None


def _providers_for_device() -> list:
    """Build ONNX Runtime provider list, preferring CUDA if available."""
    info = detect_device()
    if info.onnx_cuda:
        return [("CUDAExecutionProvider", {"device_id": 0}), "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]
