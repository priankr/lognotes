"""Common Transcriber protocol implemented by each backend."""

from __future__ import annotations

from typing import Iterator, Optional, Protocol

import numpy as np


class Transcriber(Protocol):
    """Minimal interface the controller depends on."""

    def transcribe(self, audio: np.ndarray, language: Optional[str] = "en") -> str: ...

    def transcribe_segments(
        self, audio: np.ndarray, language: Optional[str] = "en"
    ) -> Iterator[str]: ...

    def change_model(self, model_id: str) -> None: ...

    @property
    def is_loaded(self) -> bool: ...
