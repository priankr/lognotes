from pynput import keyboard
from typing import Callable, Optional, Set
import threading


class HotkeyListener:
    """Listens for global keyboard shortcuts."""

    # Map string names to pynput key names for comparison
    MODIFIER_NAMES = {"ctrl", "shift", "alt", "cmd"}

    def __init__(
        self,
        hotkey: str = "ctrl+shift+d",
        on_press: Optional[Callable[[], None]] = None,
        on_release: Optional[Callable[[], None]] = None,
        debug: bool = False
    ):
        """Initialize hotkey listener.

        Args:
            hotkey: Hotkey string (e.g., "ctrl+shift+d")
            on_press: Callback when hotkey is pressed
            on_release: Callback when hotkey is released
            debug: Enable debug output
        """
        self._hotkey_str = hotkey.lower()
        self._on_press = on_press
        self._on_release = on_release
        self._debug = debug
        self._listener: Optional[keyboard.Listener] = None
        self._pressed_keys: Set[str] = set()  # Store as normalized strings
        self._hotkey_active = False
        self._lock = threading.Lock()

        # Parse hotkey into required keys
        self._required_modifiers, self._required_key = self._parse_hotkey(self._hotkey_str)

        if self._debug:
            print(f"Hotkey parsed: modifiers={self._required_modifiers}, key={self._required_key}")

    def _parse_hotkey(self, hotkey_str: str) -> tuple:
        """Parse hotkey string into modifiers and main key.

        Returns:
            Tuple of (set of modifier names, main key character)
        """
        parts = hotkey_str.lower().split("+")
        modifiers = set()
        main_key = None

        for part in parts:
            part = part.strip()
            if part in self.MODIFIER_NAMES:
                modifiers.add(part)
            else:
                main_key = part

        return modifiers, main_key

    def _key_to_string(self, key) -> Optional[str]:
        """Convert a pynput key to a normalized string."""
        # Handle modifier keys
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            return "ctrl"
        if key in (keyboard.Key.shift_l, keyboard.Key.shift_r):
            return "shift"
        if key in (keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr):
            return "alt"
        if key in (keyboard.Key.cmd, keyboard.Key.cmd_r):
            return "cmd"

        # Handle regular keys
        if hasattr(key, 'char') and key.char:
            char = key.char
            # Convert control characters back to letters (Ctrl+A=\x01, Ctrl+D=\x04, etc.)
            if len(char) == 1 and ord(char) < 32:
                # Control character: convert to letter (0x01='a', 0x04='d', etc.)
                char = chr(ord(char) + 96)
            return char.lower()

        # Handle special keys (space, enter, etc.)
        if hasattr(key, 'name'):
            return key.name.lower()

        return None

    def _check_hotkey(self) -> bool:
        """Check if the hotkey combination is currently pressed."""
        # Check all required modifiers are pressed
        for mod in self._required_modifiers:
            if mod not in self._pressed_keys:
                return False

        # Check main key is pressed
        if self._required_key and self._required_key not in self._pressed_keys:
            return False

        return True

    def _on_key_press(self, key):
        """Handle key press event."""
        key_str = self._key_to_string(key)

        if self._debug:
            print(f"Key press: {key} -> {key_str}")

        if key_str is None:
            return

        with self._lock:
            self._pressed_keys.add(key_str)

            if self._debug:
                print(f"Pressed keys: {self._pressed_keys}")

            # Check if hotkey combination is now active
            if not self._hotkey_active and self._check_hotkey():
                self._hotkey_active = True
                if self._on_press:
                    threading.Thread(target=self._on_press, daemon=True).start()

    def _on_key_release(self, key):
        """Handle key release event."""
        key_str = self._key_to_string(key)

        if self._debug:
            print(f"Key release: {key} -> {key_str}")

        if key_str is None:
            return

        with self._lock:
            self._pressed_keys.discard(key_str)

            # Check if hotkey was released
            if self._hotkey_active and not self._check_hotkey():
                self._hotkey_active = False
                if self._on_release:
                    threading.Thread(target=self._on_release, daemon=True).start()

    def start(self) -> None:
        """Start listening for the hotkey."""
        if self._listener is not None:
            return

        self._listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release
        )
        self._listener.start()

    def stop(self) -> None:
        """Stop listening for the hotkey."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
            self._pressed_keys.clear()
            self._hotkey_active = False

    def update_hotkey(self, hotkey: str) -> None:
        """Update the hotkey combination.

        Args:
            hotkey: New hotkey string (e.g., "ctrl+alt+r")
        """
        with self._lock:
            self._hotkey_str = hotkey.lower()
            self._required_modifiers, self._required_key = self._parse_hotkey(self._hotkey_str)
            self._hotkey_active = False
            self._pressed_keys.clear()

    @property
    def hotkey(self) -> str:
        """Get current hotkey string."""
        return self._hotkey_str

    @property
    def is_running(self) -> bool:
        """Check if listener is running."""
        return self._listener is not None and self._listener.is_alive()
