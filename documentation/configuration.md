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
  "enable_grammar": true,
  "ollama_model": "llama3.2:1b",
  "ollama_host": "http://localhost:11434",
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
| **Transcription Model** | Choose Whisper tiny / base / small. `small` is the quality/speed sweet spot on CPU. All sizes are preloaded in the background on startup so switching is instant. |
| **Grammar Cleanup** | Enable to post-process transcribed text with Ollama. Skipped silently if Ollama is unavailable. |
| **Appearance** | Switch between dark mode (default) and light mode. Applied on next app restart. |
| **Overlay Corner** | Right-click the recording overlay to cycle corners. Drag to reposition manually. |

---

## JSON Key Reference

For manual edits or scripting. The `ollama_model` and `ollama_host` keys are not exposed in the UI and must be set by editing the file directly.

| Key | Default | UI setting |
|-----|---------|------------|
| `hotkey` | `ctrl+shift+d` | Hotkey |
| `push_to_talk_mode` | `hold` | Recording Mode |
| `whisper_model` | `whisper-base` | Transcription Model |
| `enable_grammar` | `true` | Grammar Cleanup |
| `ollama_model` | `llama3.2:1b` | — |
| `ollama_host` | `http://localhost:11434` | — |
| `theme` | `dark` | Appearance |
| `overlay_corner` | `bottom-right` | Overlay Corner |

---

## Validation

All values are whitelist-validated on load. Invalid values fall back to the defaults above with a warning logged.

| Key | Valid values |
|-----|-------------|
| `whisper_model` | `whisper-tiny`, `whisper-base`, `whisper-small`. Legacy bare sizes (`tiny`, `base`, `small`) are migrated automatically. |
| `hotkey` | One or more modifiers (`ctrl`, `shift`, `alt`, `cmd`) plus one alphanumeric key, joined by `+`. |
| `ollama_model` | Alphanumeric, dots, colons, hyphens only. Max 100 characters. |
| `ollama_host` | Must start with `http://` or `https://`. Max 256 characters. |
| `enable_grammar` | Boolean (`true` / `false`). |
| `theme` | `dark` or `light`. |
| `push_to_talk_mode` | `hold` or `toggle`. |
| `overlay_corner` | `top-left`, `top-right`, `bottom-left`, `bottom-right`. |
