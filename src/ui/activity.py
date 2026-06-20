"""Activity tab widget: renders the session transcription history.

The store itself (``ActivityStore`` / ``ActivityEntry``) is Tk-free and lives
in ``src/activity.py`` so the headless sidecar can use it. It is re-exported
here for backward compatibility with existing imports.

Audio for each entry is held in memory only for the app session and is
discarded on exit. Nothing is written to disk.
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Callable, Optional

import ttkbootstrap as ttk

from ..activity import ActivityEntry, ActivityStore  # re-exported
from ..transcription import MODELS as TRANSCRIPTION_MODELS, display_for as _display_for_model

logger = logging.getLogger(__name__)


TEXT_PREVIEW_CHARS = 80


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
