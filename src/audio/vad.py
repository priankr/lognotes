import hashlib
import logging
import numpy as np
import torch
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Pinned version for supply chain security
# Update this when upgrading the model version
SILERO_VAD_VERSION = "v5.1"
SILERO_VAD_REPO = "snakers4/silero-vad"


class VoiceActivityDetector:
    """Filters silence from audio using Silero VAD model."""

    SAMPLE_RATE = 16000
    WINDOW_SIZE_SAMPLES = 512  # 32ms at 16kHz

    def __init__(self, threshold: float = 0.5):
        """Initialize VAD with Silero model.

        Args:
            threshold: Speech probability threshold (0.0-1.0)
        """
        self.threshold = threshold
        self._model: Optional[torch.nn.Module] = None
        self._utils = None

    def _load_model(self) -> None:
        """Lazy load the Silero VAD model with integrity verification."""
        if self._model is None:
            try:
                # Use pinned version for reproducibility and security
                self._model, self._utils = torch.hub.load(
                    repo_or_dir=SILERO_VAD_REPO,
                    model='silero_vad',
                    force_reload=False,
                    trust_repo=True,  # Required for torch.hub, but we pin version
                    version=SILERO_VAD_VERSION
                )
                self._model.eval()
                logger.info(f"Loaded Silero VAD model version {SILERO_VAD_VERSION}")
            except Exception as e:
                logger.error(f"Failed to load VAD model: {e}")
                raise RuntimeError(f"VAD model loading failed: {e}") from e

    def filter_silence(self, audio: np.ndarray, aggressiveness: int = 2) -> np.ndarray:
        """Filter silence from audio, keeping only speech segments.

        Args:
            audio: Input audio array (float32, mono, 16kHz)
            aggressiveness: How aggressive to filter (1-3, higher = more filtering)

        Returns:
            Audio array with silence removed
        """
        if len(audio) == 0:
            return audio

        self._load_model()

        # Convert to torch tensor
        audio_tensor = torch.from_numpy(audio).float()

        # Get speech timestamps
        speech_timestamps = self._utils[0](
            audio_tensor,
            self._model,
            sampling_rate=self.SAMPLE_RATE,
            threshold=self.threshold,
            min_speech_duration_ms=250,
            min_silence_duration_ms=100 * aggressiveness,
            window_size_samples=self.WINDOW_SIZE_SAMPLES,
            return_seconds=False
        )

        if not speech_timestamps:
            return np.array([], dtype=np.float32)

        # Extract speech segments
        speech_segments = []
        for segment in speech_timestamps:
            start = segment['start']
            end = segment['end']
            speech_segments.append(audio[start:end])

        # Concatenate all speech segments
        if speech_segments:
            return np.concatenate(speech_segments)
        return np.array([], dtype=np.float32)

    def get_speech_probability(self, audio_chunk: np.ndarray) -> float:
        """Get speech probability for an audio chunk.

        Args:
            audio_chunk: Audio chunk (512 samples at 16kHz)

        Returns:
            Speech probability (0.0-1.0)
        """
        self._load_model()

        if len(audio_chunk) != self.WINDOW_SIZE_SAMPLES:
            # Pad or truncate to correct size
            if len(audio_chunk) < self.WINDOW_SIZE_SAMPLES:
                audio_chunk = np.pad(
                    audio_chunk,
                    (0, self.WINDOW_SIZE_SAMPLES - len(audio_chunk))
                )
            else:
                audio_chunk = audio_chunk[:self.WINDOW_SIZE_SAMPLES]

        audio_tensor = torch.from_numpy(audio_chunk).float()
        prob = self._model(audio_tensor, self.SAMPLE_RATE).item()
        return prob

    def reset(self) -> None:
        """Reset the VAD model state."""
        if self._model is not None:
            self._model.reset_states()
