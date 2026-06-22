"""Config round-trip and validation tests for src/config.py.

Covers the Phase 0 config extraction: load -> set -> save -> reload, the
0o600 permission semantics, and the whitelist validation rules. Uses a temp
file so the real %APPDATA%\\LogNotes\\config.json is never touched.

Run with: venv\\Scripts\\python.exe -m unittest discover -s tests
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Make the project root importable when run from anywhere.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src import config as app_config  # noqa: E402


class ConfigTestBase(unittest.TestCase):
    """Redirects CONFIG_FILE to a per-test temp path."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self._tmpdir.name, "config.json")
        # config.py reads the module-level CONFIG_FILE on every load/save, so
        # patching it here is enough to isolate from the real user config.
        self._patcher = mock.patch.object(app_config, "CONFIG_FILE", self.config_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()


class TestLoadSaveRoundTrip(ConfigTestBase):
    def test_load_returns_defaults_when_absent(self):
        self.assertFalse(os.path.exists(self.config_path))
        loaded = app_config.load_config()
        self.assertEqual(loaded, app_config.DEFAULT_CONFIG)

    def test_save_then_load_preserves_values(self):
        data = dict(app_config.DEFAULT_CONFIG)
        data["hotkey"] = "ctrl+alt+r"
        data["theme"] = "light"
        data["overlay_corner"] = "top-left"

        app_config.save_config(data)
        self.assertTrue(os.path.exists(self.config_path))

        reloaded = app_config.load_config()
        self.assertEqual(reloaded["hotkey"], "ctrl+alt+r")
        self.assertEqual(reloaded["theme"], "light")
        self.assertEqual(reloaded["overlay_corner"], "top-left")

    def test_saved_file_is_valid_json(self):
        app_config.save_config(dict(app_config.DEFAULT_CONFIG))
        with open(self.config_path) as f:
            on_disk = json.load(f)
        self.assertEqual(on_disk, app_config.DEFAULT_CONFIG)

    @unittest.skipUnless(sys.platform != "win32", "POSIX file modes only")
    def test_save_uses_restricted_permissions(self):
        app_config.save_config(dict(app_config.DEFAULT_CONFIG))
        mode = os.stat(self.config_path).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_load_corrupt_json_falls_back_to_defaults(self):
        with open(self.config_path, "w") as f:
            f.write("{ this is not valid json ")
        loaded = app_config.load_config()
        self.assertEqual(loaded, app_config.DEFAULT_CONFIG)


class TestValidation(ConfigTestBase):
    def test_garbage_falls_back_to_defaults(self):
        garbage = {
            "whisper_model": "bogus-model",
            "hotkey": "justakey",          # no modifier
            "theme": "purple",
            "push_to_talk_mode": "wat",
            "overlay_corner": "middle",
        }
        self.assertEqual(app_config.validate_config(garbage), app_config.DEFAULT_CONFIG)

    def test_valid_values_pass_through(self):
        good = {
            "whisper_model": "whisper-base",
            "hotkey": "ctrl+alt+r",
            "theme": "light",
            "push_to_talk_mode": "toggle",
            "overlay_corner": "top-left",
        }
        self.assertEqual(app_config.validate_config(good), good)

    def test_hotkey_requires_modifier_and_single_key(self):
        cfg = dict(app_config.DEFAULT_CONFIG)
        cfg["hotkey"] = "ctrl+shift"  # modifiers only, no main key
        self.assertEqual(
            app_config.validate_config(cfg)["hotkey"],
            app_config.DEFAULT_CONFIG["hotkey"],
        )


class TestValidateValue(ConfigTestBase):
    """Single-key validation used by the sidecar setConfig RPC."""

    def test_unknown_key_rejected(self):
        ok, _ = app_config.validate_value("not_a_real_key", "x")
        self.assertFalse(ok)

    def test_valid_values_accepted(self):
        cases = [
            ("whisper_model", "whisper-base", "whisper-base"),
            ("hotkey", "ctrl+alt+r", "ctrl+alt+r"),
            ("theme", "light", "light"),
            ("push_to_talk_mode", "toggle", "toggle"),
            ("overlay_corner", "top-left", "top-left"),
        ]
        for key, value, expected in cases:
            ok, norm = app_config.validate_value(key, value)
            self.assertTrue(ok, f"{key}={value!r} should be valid")
            self.assertEqual(norm, expected)

    def test_invalid_values_rejected(self):
        cases = [
            ("whisper_model", "bogus"),
            ("hotkey", "justakey"),          # no modifier
            ("hotkey", "ctrl+shift"),         # no main key
            ("theme", "purple"),
            ("push_to_talk_mode", "wat"),
            ("overlay_corner", "middle"),
        ]
        for key, value in cases:
            ok, _ = app_config.validate_value(key, value)
            self.assertFalse(ok, f"{key}={value!r} should be rejected")

    def test_hotkey_is_normalized(self):
        ok, norm = app_config.validate_value("hotkey", "CTRL+ALT+R")
        self.assertTrue(ok)
        self.assertEqual(norm, "ctrl+alt+r")


class TestConfigStore(ConfigTestBase):
    def test_set_persists_to_disk(self):
        store = app_config.ConfigStore(dict(app_config.DEFAULT_CONFIG))
        store["hotkey"] = "ctrl+alt+x"

        # A fresh load from disk should see the change (this is exactly the
        # "change a setting, restart, confirm it stuck" manual check).
        reloaded = app_config.load_config()
        self.assertEqual(reloaded["hotkey"], "ctrl+alt+x")

    def test_dict_compatibility_shims(self):
        store = app_config.ConfigStore(dict(app_config.DEFAULT_CONFIG))
        self.assertEqual(store["theme"], "dark")
        self.assertEqual(store.get("overlay_corner", "x"), "bottom-right")
        self.assertEqual(store.get("nonexistent", "fallback"), "fallback")
        self.assertEqual(store.copy(), app_config.DEFAULT_CONFIG)
        self.assertIsInstance(store.copy(), dict)

    def test_change_callback_fires_on_set(self):
        store = app_config.ConfigStore(dict(app_config.DEFAULT_CONFIG))
        seen = []
        store.subscribe(lambda key, value: seen.append((key, value)))
        store["theme"] = "light"
        self.assertEqual(seen, [("theme", "light")])

    def test_save_method_persists_current_state(self):
        store = app_config.ConfigStore(dict(app_config.DEFAULT_CONFIG))
        # Mutate via as_dict reference is not supported; use set, then verify save()
        # re-persists without a new set.
        store._data["theme"] = "light"  # simulate in-place change
        store.save()
        self.assertEqual(app_config.load_config()["theme"], "light")


if __name__ == "__main__":
    unittest.main()
