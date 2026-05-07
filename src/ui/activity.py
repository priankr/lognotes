"""Activity tab: session history of transcriptions with retry capability.

Audio for each entry is held in memory only for the app session and is
discarded on exit. Nothing is written to disk.
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

import numpy as np
import ttkbootstrap as ttk

from ..transcription import MODELS as TRANSCRIPTION_MODELS, display_for as _display_for_model

logger = logging.getLogger(__name__)


# Cap total retained audio by seconds (not entry count) so a long session
# with short clips stays cheap while a session with long clips is still bounded.
MAX_AUDIO_SECONDS = 15 * 60  # 15 minutes
SAMPLE_RATE = 16000
TEXT_PREVIEW_CHARS = 80


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


class ActivityTab:
    """Renders the Activity tab contents into the given parent frame."""

    def __init__(
        self,
        parent: ttk.Frame,
        store: ActivityStore,
        on_retry: Callable[[int, str], None],
        on_copy: Callable[[str], None],
        is_busy: Callable[[], bool],
    ):
        self._parent = parent
        self._store = store
        self._on_retry = on_retry
        self._on_copy = on_copy
        self._is_busy = is_busy
        self._expanded: set[int] = set()

        self._build()
        self._store.subscribe(self._schedule_refresh)

    def _build(self) -> None:
        toolbar = ttk.Frame(self._parent, padding=(10, 8, 10, 4))
        toolbar.pack(fill=tk.X)

        ttk.Label(toolbar, text="Session Activity", font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        ttk.Button(
            toolbar, text="Clear", bootstyle="secondary", width=7,
            command=self._store.clear,
        ).pack(side=tk.RIGHT)

        hint = ttk.Label(
            self._parent,
            text="Transcriptions from this session. Cleared on app close.",
            font=("Segoe UI", 8), foreground="gray",
            padding=(10, 0, 10, 4),
        )
        hint.pack(fill=tk.X)

        outer = ttk.Frame(self._parent, padding=(10, 0, 10, 10))
        outer.pack(fill=tk.BOTH, expand=True)

        bg = ttk.Style().lookup("TFrame", "background") or "#222222"
        self._canvas = tk.Canvas(outer, highlightthickness=0, bd=0, bg=bg)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scroll.set)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._list_frame = ttk.Frame(self._canvas)
        self._list_window = self._canvas.create_window((0, 0), window=self._list_frame, anchor="nw")

        def _on_list_configure(_e):
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))

        def _on_canvas_resize(e):
            self._canvas.itemconfig(self._list_window, width=e.width)

        self._list_frame.bind("<Configure>", _on_list_configure)
        self._canvas.bind("<Configure>", _on_canvas_resize)

        def _on_wheel(e):
            self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        self._canvas.bind("<MouseWheel>", _on_wheel)
        self._list_frame.bind("<MouseWheel>", _on_wheel)

        self._empty_label: Optional[ttk.Label] = None
        self._render()

    def _schedule_refresh(self) -> None:
        self._parent.after(0, self._render)

    def _render(self) -> None:
        for child in self._list_frame.winfo_children():
            child.destroy()

        entries = self._store.entries_newest_first()
        if not entries:
            ttk.Label(
                self._list_frame,
                text="No transcriptions yet this session.",
                foreground="gray", padding=(10, 20),
            ).pack(anchor=tk.W)
            return

        for entry in entries:
            self._render_row(entry)

    def _render_row(self, entry: ActivityEntry) -> None:
        row = ttk.Frame(self._list_frame, padding=(6, 6))
        row.pack(fill=tk.X, pady=(0, 4))

        header = ttk.Frame(row)
        header.pack(fill=tk.X)

        ts_str = entry.timestamp.strftime("%I:%M:%S %p").lstrip("0")
        meta = f"{ts_str}  ·  {_display_for_model(entry.whisper_model)}"
        if entry.error:
            meta += "  ·  error"
        elif not entry.paste_succeeded:
            meta += "  ·  not pasted"
        ttk.Label(header, text=meta, font=("Segoe UI", 8), foreground="gray").pack(side=tk.LEFT)

        menu_btn = ttk.Button(header, text="▾", width=2, bootstyle="secondary")
        menu = tk.Menu(menu_btn, tearoff=0)

        retry_menu = tk.Menu(menu, tearoff=0)
        for spec in TRANSCRIPTION_MODELS:
            retry_menu.add_command(
                label=spec.display,
                command=lambda mid=spec.id, eid=entry.id: self._on_retry(eid, mid),
            )
        menu.add_cascade(label="Retry transcript", menu=retry_menu)
        menu.add_command(label="Delete", command=lambda eid=entry.id: self._store.delete(eid))

        def _popup(_e=None, b=menu_btn, m=menu):
            x = b.winfo_rootx()
            y = b.winfo_rooty() + b.winfo_height()
            m.tk_popup(x, y)

        menu_btn.configure(command=_popup)
        menu_btn.pack(side=tk.RIGHT)

        copy_btn = ttk.Button(
            header, text="⧉", width=2, bootstyle="secondary",
            command=lambda t=entry.text: self._on_copy(t),
        )
        copy_btn.pack(side=tk.RIGHT, padx=(0, 4))

        body_text = entry.error or entry.text or "(no text)"
        is_expanded = entry.id in self._expanded
        truncated = len(body_text) > TEXT_PREVIEW_CHARS

        display = body_text if (is_expanded or not truncated) else (body_text[:TEXT_PREVIEW_CHARS] + "…")
        body = ttk.Label(
            row, text=display, wraplength=430, justify="left",
            foreground="#ff6b6b" if entry.error else None,
        )
        body.pack(anchor=tk.W, fill=tk.X, pady=(4, 0))

        if truncated:
            link = ttk.Label(
                row,
                text="show less" if is_expanded else "show more",
                foreground="#42a5f5", cursor="hand2",
                font=("Segoe UI", 8, "underline"),
            )
            link.pack(anchor=tk.W, pady=(2, 0))

            def _toggle(_e=None, eid=entry.id):
                if eid in self._expanded:
                    self._expanded.discard(eid)
                else:
                    self._expanded.add(eid)
                self._render()

            link.bind("<Button-1>", _toggle)

        ttk.Separator(self._list_frame, orient="horizontal").pack(fill=tk.X)
