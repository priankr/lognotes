"""Session-scoped, in-memory store of transcription activity.

UI-agnostic and Tk-free so the headless sidecar can import it without pulling
in Tkinter. The Tk Activity-tab widget (``ActivityTab``) lives in
``src/ui/activity.py`` and consumes this store.

Audio for each entry is held in memory only for the app session and is
discarded on exit. Nothing is written to disk.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)


# Cap total retained audio by seconds (not entry count) so a long session
# with short clips stays cheap while a session with long clips is still bounded.
MAX_AUDIO_SECONDS = 15 * 60  # 15 minutes
SAMPLE_RATE = 16000


@dataclass
class ActivityEntry:
    id: int
    timestamp: datetime
    audio: np.ndarray
    text: str
    whisper_model: str
    grammar_applied: bool
    paste_succeeded: bool
    error: Optional[str] = field(default=None)

    @property
    def duration_seconds(self) -> float:
        return len(self.audio) / SAMPLE_RATE if len(self.audio) else 0.0


class ActivityStore:
    """In-memory, session-scoped store of activity entries.

    UI-agnostic: subscribers register a callback that fires on any change.
    """

    def __init__(self, max_audio_seconds: float = MAX_AUDIO_SECONDS):
        self._entries: list[ActivityEntry] = []
        self._next_id = 1
        self._max_audio_seconds = max_audio_seconds
        self._lock = threading.Lock()
        self._subscribers: list[Callable[[], None]] = []

    def subscribe(self, cb: Callable[[], None]) -> None:
        self._subscribers.append(cb)

    def _notify(self) -> None:
        for cb in self._subscribers:
            try:
                cb()
            except Exception as e:
                logger.warning(f"Activity subscriber failed: {e}")

    def add(
        self,
        audio: np.ndarray,
        text: str,
        whisper_model: str,
        grammar_applied: bool,
        paste_succeeded: bool,
        error: Optional[str] = None,
    ) -> ActivityEntry:
        with self._lock:
            entry = ActivityEntry(
                id=self._next_id,
                timestamp=datetime.now(),
                audio=audio,
                text=text,
                whisper_model=whisper_model,
                grammar_applied=grammar_applied,
                paste_succeeded=paste_succeeded,
                error=error,
            )
            self._next_id += 1
            # Evict before appending so the cap is never temporarily exceeded
            # by the incoming entry.
            self._evict_if_needed()
            self._entries.append(entry)
        self._notify()
        return entry

    def update(self, entry_id: int, *, text: Optional[str] = None,
               whisper_model: Optional[str] = None,
               error: Optional[str] = None) -> None:
        with self._lock:
            for e in self._entries:
                if e.id == entry_id:
                    if text is not None:
                        e.text = text
                    if whisper_model is not None:
                        e.whisper_model = whisper_model
                    e.error = error
                    break
        self._notify()

    def delete(self, entry_id: int) -> None:
        with self._lock:
            self._entries = [e for e in self._entries if e.id != entry_id]
        self._notify()

    def get(self, entry_id: int) -> Optional[ActivityEntry]:
        with self._lock:
            for e in self._entries:
                if e.id == entry_id:
                    return e
        return None

    def entries_newest_first(self) -> list[ActivityEntry]:
        with self._lock:
            return list(reversed(self._entries))

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
        self._notify()

    def _evict_if_needed(self) -> None:
        total = sum(e.duration_seconds for e in self._entries)
        while total > self._max_audio_seconds and self._entries:
            dropped = self._entries.pop(0)
            total -= dropped.duration_seconds
