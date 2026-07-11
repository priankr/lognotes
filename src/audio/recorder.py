import logging
import time
import numpy as np
import threading
from queue import Empty, Queue
from typing import Any, Optional

try:
    import sounddevice as sd
    _SOUNDDEVICE_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:
    sd = None
    _SOUNDDEVICE_IMPORT_ERROR = exc

logger = logging.getLogger(__name__)


class AudioBackendUnavailableError(RuntimeError):
    """Raised when the microphone backend is unavailable."""


class AudioRecorder:
    """Records audio from the microphone for transcription."""

    SAMPLE_RATE = 16000  # Whisper requires 16kHz
    CHANNELS = 1  # Mono
    DTYPE = np.float32
    BLOCK_SIZE = 1024  # Samples per block

    # RMS amplitude below which a block counts as silence, for the auto-stop
    # timer. float32 mic input is normalized to [-1, 1]; normal speech sits well
    # above this and room tone / breath noise below it. A rough energy gate is
    # all the auto-stop needs — it doesn't have to be a real VAD.
    SILENCE_RMS_THRESHOLD = 0.01

    def __init__(self):
        self._audio_queue: Queue = Queue()
        self._is_recording: bool = False
        self._stream: Optional[Any] = None
        self._lock = threading.Lock()
        self._availability_error: Optional[str] = None
        # Monotonic timestamp of the last block that carried voice. Seeded on
        # start() so a slow-to-begin speaker gets the full silence window before
        # the first check. Read by seconds_since_voice() for the auto-stop timer.
        self._last_voice_time: float = 0.0

        if sd is None:
            details = str(_SOUNDDEVICE_IMPORT_ERROR) if _SOUNDDEVICE_IMPORT_ERROR else "unknown error"
            self._availability_error = (
                "Audio recording is unavailable because the 'sounddevice' package "
                f"could not be loaded: {details}"
            )

    def _ensure_available(self) -> None:
        """Raise a descriptive error when the audio backend is missing."""
        if self._availability_error:
            raise AudioBackendUnavailableError(self._availability_error)

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status):
        """Callback for audio stream - stores chunks in queue."""
        if status:
            logger.warning(f"Audio stream status: {status}")
        if self._is_recording:
            self._audio_queue.put(indata.copy())
            # Track voice activity for the silence auto-stop timer. A cheap RMS
            # gate is enough here and keeps the callback fast.
            rms = float(np.sqrt(np.mean(np.square(indata))))
            if rms >= self.SILENCE_RMS_THRESHOLD:
                self._last_voice_time = time.monotonic()

    def start(self) -> None:
        """Start recording audio from the microphone."""
        self._ensure_available()
        with self._lock:
            if self._is_recording:
                return

            # Clear any old audio data
            while True:
                try:
                    self._audio_queue.get_nowait()
                except Empty:
                    break

            # Seed to now so the auto-stop timer measures silence from the start
            # of this recording, giving the user the full window to begin.
            self._last_voice_time = time.monotonic()
            self._is_recording = True
            if self._stream is None:
                self._stream = sd.InputStream(
                    samplerate=self.SAMPLE_RATE,
                    channels=self.CHANNELS,
                    dtype=self.DTYPE,
                    blocksize=self.BLOCK_SIZE,
                    callback=self._audio_callback
                )
            self._stream.start()
            logger.info("Recording started")

    def stop(self) -> None:
        """Stop recording audio."""
        with self._lock:
            if not self._is_recording:
                return

            self._is_recording = False
            if self._stream:
                self._stream.stop()
            logger.info("Recording stopped")

    def close(self) -> None:
        """Release audio resources."""
        with self._lock:
            self._is_recording = False
            if self._stream:
                self._stream.stop()
                self._stream.close()
                self._stream = None

    def get_audio(self) -> np.ndarray:
        """Get all recorded audio as a single numpy array.

        Returns:
            numpy array of audio samples (float32, mono, 16kHz)
        """
        chunks = []
        while True:
            try:
                chunks.append(self._audio_queue.get_nowait())
            except Empty:
                break

        if not chunks:
            return np.array([], dtype=self.DTYPE)

        # Concatenate all chunks and flatten to 1D
        audio = np.concatenate(chunks, axis=0).flatten()
        return audio

    @property
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._is_recording

    def seconds_since_voice(self) -> float:
        """Seconds since the last block that carried voice, for the auto-stop timer.

        Measured from the start of the current recording if no voice has been
        seen yet (start() seeds the timestamp).
        """
        return time.monotonic() - self._last_voice_time

    @property
    def is_available(self) -> bool:
        """Check whether audio capture can be used in this process."""
        return self._availability_error is None

    @property
    def availability_error(self) -> Optional[str]:
        """Return the backend error, if audio capture is unavailable."""
        return self._availability_error

    @staticmethod
    def list_devices() -> None:
        """Print available audio input devices."""
        if sd is None:
            details = str(_SOUNDDEVICE_IMPORT_ERROR) if _SOUNDDEVICE_IMPORT_ERROR else "unknown error"
            raise AudioBackendUnavailableError(
                "Cannot list audio devices because 'sounddevice' is unavailable: "
                f"{details}"
            )
        print(sd.query_devices())
