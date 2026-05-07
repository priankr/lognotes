# LogNotes

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)
![Whisper](https://img.shields.io/badge/Whisper-faster--whisper-412991?style=flat)
![Ollama](https://img.shields.io/badge/Ollama-grammar%20cleanup-222222?style=flat)
![UI](https://img.shields.io/badge/UI-ttkbootstrap-0078D4?style=flat)
![Audio](https://img.shields.io/badge/Audio-sounddevice%20%7C%20Silero%20VAD-E95420?style=flat)
![Hotkeys](https://img.shields.io/badge/Hotkeys-pynput-4CAF50?style=flat)

LogNotes is a lightweight, local speech-to-text application that transcribes your recorded notes and pastes the result wherever your cursor is placed. It's primarily designed to "log" short notes. I use it quite often when instructing coding agents (e.g, when providing feedback, describing bugs, or outlining requirements).

The app uses Whisper for transcription and Ollama for optional grammar cleanup. NVIDIA Parakeet (via ONNX Runtime) is supported as an opt-in alternative. The current version is still very much a work in progress, but I'll definitely be working on further improvements.

## Inspiration

I built LogNotes because I wanted a free, fully local alternative to [Whispr Flow](https://whisperflow.app). I wanted something I could run on-device, without needing a subscription. The goal was to create the same core experience, even if it was a bit slower, and process voice recordings locally.

When looking into open source solutions, I came across [Handy](https://github.com/cjpais/Handy) by @cjpais. I used this app's code as a reference for several optimizations to make LogNotes faster and extensible. I would definitely recommend checking out this app as well. 

## Requirements

- Python 3.10+
- Ollama (optional)

## Installation

### 1. Clone and Set Up Virtual Environment

```bash
cd LogNotes
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Up Ollama (Optional, for Grammar Cleanup)

```bash
# Install Ollama from https://ollama.ai
# Then pull the model:
ollama pull llama3.2:1b
```

## Desktop App

The repo includes a pre-built Windows app at `dist/LogNotes/LogNotes.exe`.  If you've downloaded the code you can run it directly without a Python install.

For build instructions, platform-specific notes, and Mac setup see [documentation/desktopAppConfiguration.md](documentation/desktopAppConfiguration.md).

## Things To Know

- **Transcription Speed**: Typically bigger speech-to-text models will take a bit longer to transcribe the text, but they have better accuracy. I have optimized the speed as much as I can. It should be reasonably fast even on CPUs.
- **Hotkeys**: If you're using LogNotes primarily on a specific app (e.g., Cursor, Obsidian, Jira), make sure your hotkey doesn't conflict with any existing shortcuts in those apps.  
- **Windows App Builds**: If you make changes to the code and rebuild the Windows app it will take *several* minutes (just fyi).  
- **Antivirus Scans**: The first time you run the Windows app your antivirus software may need to scan it before you can use it. Once the scan is over just reopen the app and it should work as expected.  

## Key Features

- **Local Processing** - All transcription happens on your machine. Silence is automatically filtered out.
- **Flexible Recording Modes** - Choose between Hold mode (press and hold) or Toggle mode (click to start/stop). 
- **Grammar Cleanup** - Optional post-processing with local LLM (Ollama). When this is enabled the transcription speed may be noticeably lower. 
- **Whisper Transcription** - Choose between Whisper tiny / base / small. CUDA is auto-detected and used when available. 
- **Session Activity Tab** - Every transcription this session is retained in RAM so you can retry it with a different model, copy the text, or delete it. 
- **Always-Visible Recording Overlay** - Small borderless status indicator pinned to a screen corner; drag to reposition, right-click to cycle corners.
- **Checkpoint Pasting** - Sentences are pasted as soon as Whisper finishes each one, so partial text is preserved if processing fails mid-stream


### Key Security Features

- **No Audio Storage** - Recordings are held in memory only during the app session and never written to disk. The Activity tab keeps recent clips in RAM so you can retry a transcription with a different model. Everything is cleared on app close
- **Model Name Validation** - Ollama model names are validated against an allowed-characters pattern at both config load and runtime model switches.
- **Config Validation** - All configuration values are validated against whitelists on load; the Ollama host URL is verified to have a valid scheme and non-empty hostname.
- **Atomic Config Permissions** - The config file is created with `0o600` permissions in a single `os.open()` call, with no readable window between creation and `chmod`.
- **Bounded Activity Memory** - The session audio cap is enforced before adding each new entry, preventing a single long recording from temporarily spiking RAM past the limit.
- **Pinned Model Versions** - External model downloads use pinned versions.

## Usage

### Start the App

```bash
python main.py
```

### Recording

**Hold Mode (default):**
1. Open any text editor or input field where you want to paste text
2. Press and **hold** the hotkey (default: `Ctrl+Shift+D`)
3. Speak your text
4. **Release** the hotkey
5. Wait for processing - the transcribed text will be pasted at your cursor

**Toggle Mode:**
1. Open any text editor or input field where you want to paste text
2. Press the hotkey once to **start** recording
3. Speak your text
4. Press the hotkey again to **stop** recording
5. Wait for processing - the transcribed text will be pasted at your cursor

## Project Structure

```
LogNotes/
├── main.py                    # Entry point and controller
├── requirements.txt           # Python dependencies
├── src/
│   ├── paths.py              # User data / cache dir + bundled-asset resolution
│   ├── audio/
│   │   ├── recorder.py       # Microphone recording (sounddevice)
│   │   └── vad.py            # Voice activity detection (Silero)
│   ├── transcription/
│   │   ├── registry.py       # Model registry (id → display → backend)
│   │   ├── base.py           # Transcriber protocol
│   │   ├── device.py         # CUDA detection (ctranslate2 + onnxruntime)
│   │   ├── whisper.py        # Whisper backend (faster-whisper)
│   │   └── parakeet.py       # Parakeet backend (onnx-asr / ONNX Runtime)
│   ├── processing/
│   │   └── grammar.py        # Grammar cleanup (Ollama)
│   ├── input/
│   │   ├── hotkey.py         # Global hotkey listener (pynput)
│   │   └── paster.py         # Text pasting utility
│   └── ui/
│       ├── app.py            # ttkbootstrap GUI + log viewer + overlay
│       └── activity.py       # Session activity store and Activity tab
├── build/                    # PyInstaller specs + Inno Setup + build.ps1
└── documentation/
    ├── configuration.md             # Config file, schema, settings, validation
    ├── troubleshooting.md           # Common issues and fixes
    ├── desktopAppConfiguration.md   # Desktop packaging details
    └── mvpImplementation.md         # Architecture and implementation details
```

## Tech Stack

| Component | Library |
|-----------|---------|
| Transcription (default) | faster-whisper |
| Transcription (optional, opt-in) | onnx-asr + ONNX Runtime (Parakeet) |
| Voice Activity Detection | Silero VAD (via torch) |
| Audio Recording | sounddevice |
| Global Hotkeys | pynput |
| Text Pasting | pynput + pyperclip |
| Grammar Cleanup | Ollama Python client |
| UI | ttkbootstrap (modern themed Tkinter) |


## Documentation

- [Configuration](documentation/configuration.md) — Covers the config file location, full settings schema, valid values for each option, and the validation rules applied on load.
- [Troubleshooting](documentation/troubleshooting.md) — Step-by-step fixes for common issues including hotkeys not firing, audio problems, transcription quality, Ollama connectivity, and packaged build failures.
- [Desktop Packaging](documentation/desktopAppConfiguration.md) — Instructions for building the Windows `.exe` and Mac `.app`, PyInstaller spec details, Inno Setup installer configuration, and runtime path layout.
- [Implementation](documentation/mvpImplementation.md) — Deep dive into the architecture, component responsibilities, the checkpoint-pasting pipeline, security model, and known design decisions.

## Disclaimer

This project was built entirely with [Claude Code](https://claude.ai/code) and [OpenAI Codex](https://openai.com/codex). While the code has been reviewed, AI-generated code can contain bugs or issues that are easy to miss. If you spot anything significant, please open an issue. I'd genuinely appreciate it.

## License

MIT
