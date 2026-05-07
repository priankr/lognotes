import numpy as np
from faster_whisper import WhisperModel
from typing import Optional, Iterator

from .device import detect as detect_device


class WhisperTranscriber:
    """Transcribes audio using faster-whisper (local Whisper inference).

    Auto-detects CUDA via ctranslate2 and prefers GPU float16 over CPU int8
    when available. Pass device="cpu" to force CPU.
    """

    def __init__(
        self,
        model_size: str = "base",
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
    ):
        self.model_size = model_size
        if device is None or compute_type is None:
            auto_device, auto_compute = _auto_device()
            self.device = device or auto_device
            self.compute_type = compute_type or auto_compute
        else:
            self.device = device
            self.compute_type = compute_type
        self._model: Optional[WhisperModel] = None

    def _load_model(self) -> None:
        if self._model is None:
            import logging
            log = logging.getLogger(__name__)
            log.info(
                f"Loading Whisper model '{self.model_size}' "
                f"(device={self.device}, compute_type={self.compute_type})..."
            )
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
            log.info("Whisper model loaded.")

    def transcribe(self, audio: np.ndarray, language: Optional[str] = "en") -> str:
        if len(audio) == 0:
            return ""
        return " ".join(self.transcribe_segments(audio, language=language))

    def transcribe_segments(
        self, audio: np.ndarray, language: Optional[str] = "en"
    ) -> Iterator[str]:
        if len(audio) == 0:
            return

        self._load_model()

        segments, _info = self._model.transcribe(
            audio,
            language=language,
            # Dictation is latency-sensitive; beam_size=1 is materially faster
            # with acceptable quality trade-off for this use case.
            beam_size=1,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            ),
        )

        for segment in segments:
            text = segment.text.strip()
            if text:
                yield text

    def change_model(self, model_size: str) -> None:
        if model_size != self.model_size:
            self.model_size = model_size
            self._model = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None


def _auto_device() -> tuple[str, str]:
    info = detect_device()
    if info.ctranslate2_cuda:
        return "cuda", "float16"
    return "cpu", "int8"
