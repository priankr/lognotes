"""Transient status revert: 'Transcribed' settles back to 'Ready' after a delay.

Verifies the controller's post-transcription status behavior so the overlay /
status row don't get stuck on the success message.
"""

import sys
import time
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.controller import LogNotesController  # noqa: E402


class _StubUI:
    def __init__(self):
        self.calls = []

    def set_status(self, status, message=None):
        self.calls.append((status, message))

    def show_audio_error(self, message):
        pass


class TestStatusRevert(unittest.TestCase):
    def _controller(self):
        c = LogNotesController()
        c._ui = _StubUI()
        c.STATUS_REVERT_SEC = 0.15  # keep the test fast
        return c

    def test_transient_reverts_to_ready(self):
        c = self._controller()
        c._set_transient_status("Transcribed")
        self.assertEqual(c._ui.calls[-1], ("ready", "Transcribed"))
        time.sleep(0.3)
        self.assertEqual(c._ui.calls[-1], ("ready", "Ready"))

    def test_cancel_prevents_revert(self):
        c = self._controller()
        c._set_transient_status("Transcribed")
        c._cancel_status_revert()
        time.sleep(0.3)
        self.assertEqual(c._ui.calls, [("ready", "Transcribed")])

    def test_new_transient_supersedes_previous(self):
        c = self._controller()
        c._set_transient_status("Transcribed")
        c._set_transient_status("Transcribed again")
        # Only one revert should fire, settling once to Ready.
        time.sleep(0.3)
        self.assertEqual(c._ui.calls[-1], ("ready", "Ready"))
        self.assertEqual(c._ui.calls.count(("ready", "Ready")), 1)


if __name__ == "__main__":
    unittest.main()
