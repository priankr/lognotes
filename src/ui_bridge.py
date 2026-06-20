"""The interface the controller uses to talk to a front end.

``LogNotesController`` is decoupled from Tkinter: instead of reaching into
``LogNotesApp`` directly, it holds a ``UIBridge``. The Tk app implements this
protocol today; the future Electron sidecar will implement the same contract
(forwarding ``set_status`` as a pushed event, etc.).

No Tk imports here — this module is safe to import from a headless sidecar.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class UIBridge(Protocol):
    """What the controller needs from any front end."""

    def set_status(self, status: str, message: Optional[str] = None) -> None:
        """Report a status change (ready / recording / processing).

        Implementations must be safe to call from a background thread.
        """
        ...

    def show_audio_error(self, message: str) -> None:
        """Surface a fatal audio-backend error to the user (non-crashing)."""
        ...
