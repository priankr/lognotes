import pyperclip
import time
import platform
from pynput.keyboard import Controller, Key


# Global keyboard controller
_keyboard = Controller()


def paste_text(text: str, method: str = "clipboard", clear_clipboard: bool = True) -> bool:
    """Paste text at the current cursor position.

    Args:
        text: Text to paste
        method: Paste method ("clipboard" or "typewrite")
        clear_clipboard: Whether to clear the clipboard after pasting.
            Set to False when pasting multiple chunks in sequence to avoid
            the 5-second delay between each chunk.

    Returns:
        True if successful, False otherwise
    """
    if not text:
        return False

    try:
        if method == "clipboard":
            return _paste_via_clipboard(text, clear_clipboard=clear_clipboard)
        elif method == "typewrite":
            return _paste_via_typewrite(text)
        else:
            return _paste_via_clipboard(text, clear_clipboard=clear_clipboard)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Paste failed: {e}")
        return False


def _paste_via_clipboard(text: str, clear_clipboard: bool = True) -> bool:
    """Paste text using clipboard and Ctrl+V.

    Args:
        text: Text to paste
        clear_clipboard: Whether to clear the clipboard after pasting.

    Returns:
        True if successful
    """
    # Copy new text to clipboard
    pyperclip.copy(text)

    # try/finally guarantees clipboard is cleared even if an exception occurs
    # during the paste simulation (e.g. pynput error, thread interrupt).
    try:
        # Wait for the user's original window to regain focus
        time.sleep(0.5)

        # Simulate Ctrl+V paste using pynput
        if platform.system() == "Darwin":  # macOS
            with _keyboard.pressed(Key.cmd):
                _keyboard.press('v')
                _keyboard.release('v')
        else:  # Windows/Linux
            with _keyboard.pressed(Key.ctrl):
                _keyboard.press('v')
                _keyboard.release('v')

        if not clear_clipboard:
            # Without this, the next chunk's pyperclip.copy() overwrites the
            # clipboard before the target app has processed the Ctrl+V event,
            # causing it to paste the wrong chunk. The clear_clipboard=True
            # path is fine — its 5s cleanup sleep provides sufficient headroom.
            time.sleep(0.15)

        return True
    finally:
        if clear_clipboard:
            # Security: Clear clipboard after paste to prevent data leakage.
            # Delay lets the target application finish reading the clipboard.
            time.sleep(5)
            try:
                pyperclip.copy('')
            except Exception:
                pass  # Non-critical if clearing fails


def _paste_via_typewrite(text: str, interval: float = 0.02) -> bool:
    """Paste text by simulating keystrokes using pynput.

    Note: This method is slower but works in more applications.

    Args:
        text: Text to paste
        interval: Delay between keystrokes

    Returns:
        True if successful
    """
    try:
        for char in text:
            _keyboard.type(char)
            time.sleep(interval)
        return True
    except Exception:
        # Fallback to clipboard method
        return _paste_via_clipboard(text)
