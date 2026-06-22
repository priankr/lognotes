# Configuration

> **Docs:** [Configuration](configuration.md) · [Troubleshooting](troubleshooting.md)

---

## Config File Location

| Platform | Path |
| --- | --- |
| Windows | `%APPDATA%\LogNotes\config.json` |
| macOS | `~/Library/Application Support/LogNotes/config.json` |
| Linux | `~/.config/LogNotes/config.json` |

The same file is shared across dev and packaged runs (and the legacy Tk build). Written with restricted permissions (0600 on Unix).

---

## Schema

```json
{
  "hotkey": "ctrl+shift+d",
  "whisper_model": "whisper-base",
  "theme": "dark",
  "push_to_talk_mode": "hold",
  "overlay_corner": "bottom-right"
}
```

---

## Settings

The app provides a UI to configure all settings — no manual file editing needed.

| Setting | How to use |
|---------|------------|
| **Hotkey** | Click "Change Hotkey" and press your desired key combination. |
| **Recording Mode** | Choose Hold mode (press and hold to record) or Toggle mode (press once to start, press again to stop). |
| **Transcription Model** | Choose Whisper base / small. `small` is the quality/speed sweet spot on CPU. All sizes are preloaded in the background on startup so switching is instant. |
| **Appearance** | Switch between dark mode (default) and light mode. Applied on next app restart. |
| **Overlay Corner** | Right-click the recording overlay to cycle corners. Drag to reposition manually. |

---

## JSON Key Reference

For manual edits or scripting.

| Key | Default | UI setting |
|-----|---------|------------|
| `hotkey` | `ctrl+shift+d` | Hotkey |
| `push_to_talk_mode` | `hold` | Recording Mode |
| `whisper_model` | `whisper-base` | Transcription Model |
| `theme` | `dark` | Appearance |
| `overlay_corner` | `bottom-right` | Overlay Corner |

---

## Validation

All values are whitelist-validated on load. Invalid values fall back to the defaults above with a warning logged.

| Key | Valid values |
|-----|-------------|
| `whisper_model` | `whisper-base`, `whisper-small`. Legacy bare sizes (`base`, `small`) and the removed `whisper-tiny` / `tiny` are migrated automatically (tiny → base). |
| `hotkey` | One or more modifiers (`ctrl`, `shift`, `alt`, `cmd`) plus one alphanumeric key, joined by `+`. |
| `theme` | `dark` or `light`. |
| `push_to_talk_mode` | `hold` or `toggle`. |
| `overlay_corner` | `top-left`, `top-right`, `bottom-left`, `bottom-right`. |
