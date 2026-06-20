#!/usr/bin/env python3
"""
LogNotes (legacy Tk front end) - Local speech-to-text with grammar cleanup.

Kept locally for reference. The canonical product is the Electron app
(electron/ + sidecar.py); both share LogNotesController, which now lives in
src/controller.py.

Press the configured hotkey to start recording, release to stop. The
transcribed and cleaned text is pasted at your cursor.
"""

import io
import os
import sys
import logging

# Under --noconsole (pythonw/PyInstaller windowed), sys.stdout/stderr are None.
# Libraries that call sys.stdout.write() (torch.hub, tqdm, etc.) will crash.
# Replace with sinks that discard output but expose the expected stream API.
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

# Redirect model caches into the user cache dir BEFORE importing torch/whisper
# (the controller import below pulls in the ML stack).
from src.paths import user_cache_dir

_cache = user_cache_dir()
os.environ.setdefault("HF_HOME", str(_cache / "hf"))
os.environ.setdefault("TORCH_HOME", str(_cache / "torch"))

logger = logging.getLogger(__name__)

from src.controller import LogNotesController
from src.ui import LogNotesApp


def run(controller: LogNotesController) -> None:
    """Run the application with the Tk front end."""
    # Create UI and wire the controller to it.
    app = LogNotesApp()
    controller.attach(app, app.config_store, app.activity_store)

    # Set up callbacks
    app.on_hotkey_changed = controller._on_hotkey_changed
    app.on_model_changed = controller._on_model_changed
    app.on_grammar_toggled = controller._on_grammar_toggled
    app.on_theme_changed = controller._on_theme_changed
    app.on_push_to_talk_mode_changed = controller._on_push_to_talk_mode_changed
    app.on_toggle_recording = controller.toggle_recording
    app.on_retry_transcription = controller.retry_transcription
    app.is_busy = controller.is_busy

    controller.start_runtime()

    # Run UI main loop
    try:
        app.mainloop()
    finally:
        controller.shutdown()


def main():
    """Entry point."""
    import signal

    # Allow Ctrl+C to work — only meaningful when attached to a terminal.
    # A --noconsole frozen exe has no stdin and the handler is pointless (and
    # on Windows, setting SIGINT without a console can fail).
    if sys.stdin is not None and sys.stdin.isatty():
        try:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
        except (ValueError, OSError):
            pass

    controller = LogNotesController()
    run(controller)


if __name__ == "__main__":
    main()
