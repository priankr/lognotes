# CLAUDE.md

**Repository:** https://github.com/priankr/lognotes

Local speech-to-text dictation app. Push-to-talk hotkey → Whisper transcribes → optional Ollama grammar cleanup → paste at cursor. Tkinter/ttkbootstrap UI with Settings / Activity / Logs tabs and a draggable recording overlay.

## Running

- **Dev:** `venv\Scripts\activate` then `python main.py`.
- **Packaged:** `dist\LogNotes\LogNotes.exe` after running `build\build.ps1`.
- **Ollama** must be running separately (`ollama serve`) for grammar cleanup.

## Layout

- [main.py](main.py) — `LogNotesController` orchestrates recorder → VAD → Whisper → grammar → paste.
- [src/audio/](src/audio/) — `AudioRecorder` (sounddevice), `VoiceActivityDetector` (Silero via torch.hub).
- [src/transcription/whisper.py](src/transcription/whisper.py) — faster-whisper; supports segment streaming for checkpoint pasting.
- [src/processing/grammar.py](src/processing/grammar.py) — Ollama client with prompt-injection sanitization.
- [src/input/](src/input/) — `HotkeyListener` (pynput), `paste_text`.
- [src/ui/](src/ui/) — `LogNotesApp` (main window, tabs, overlay, tray, config), `ActivityStore` + `ActivityTab` (session-scoped, in-memory).
- [src/paths.py](src/paths.py) — dev-vs-frozen asset resolution + user data/cache dirs.
- [build/](build/) — PyInstaller specs, `build.ps1`, Inno Setup.

## Key Behaviors

- **Checkpoint pasting** — segments are pasted as sentence-boundary chunks so partial output is preserved if processing fails mid-stream.
- **Activity tab** — every session transcription retained in RAM (audio + text), retryable with a different Whisper model. Nothing persisted to disk; cleared on app close.
- **Config** lives at `%APPDATA%\LogNotes\config.json` (shared between dev and packaged runs). All values are whitelist-validated on load.
- **Model caches** at `%LOCALAPPDATA%\LogNotes\cache\{hf,torch}`; `HF_HOME`/`TORCH_HOME` set in [main.py](main.py) before torch imports.

## Conventions

- All markdown section headings use title case (e.g. "Hotkey Not Working", not "Hotkey not working"). This applies to README.md and all files under `documentation/`.

## Details

- MVP pipeline, security model, config schema → [documentation/mvpImplementation.md](documentation/mvpImplementation.md).
- Packaging, PyInstaller gotchas, installer, path layout → [documentation/desktopAppConfiguration.md](documentation/desktopAppConfiguration.md).

## Gotchas

- `sys.stdout` / `sys.stderr` are `None` under `--noconsole`; [main.py](main.py) replaces them with `io.StringIO` sinks so libraries that call `.write()` (torch.hub) don't crash.
- Do **not** add `test` or `unittest` to PyInstaller `excludes` — torch imports `unittest` at runtime.
- Rebuilding fails if a packaged `LogNotes.exe` is still running (locked DLLs). Close it first.
- `build.ps1` must stay ASCII-only — Windows PowerShell 5.1 mis-parses UTF-8 without a BOM.
