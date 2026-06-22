# CLAUDE.md

**Repository:** https://github.com/priankr/lognotes

Local speech-to-text dictation app. Push-to-talk hotkey → Whisper transcribes → paste at cursor. Settings / Activity / Logs tabs and a draggable recording overlay.

LogNotes is a **hybrid app**: an **Electron front end** (UI) over a **Python back end** (the "sidecar") that runs the ML pipeline and OS integration. They are separate processes talking over a loopback WebSocket. The ML stack stays in Python because there is no production-quality JS equivalent.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full architecture (pipeline, IPC protocol, module layout, packaging, security).

## Running

- **App (Electron):** `cd electron && npm start` — spawns the Python back end ([sidecar.py](sidecar.py)) and connects over a loopback WebSocket.
- **Back end alone (headless):** `python sidecar.py`.
- **Packaged:** `build\build-electron.ps1` → `dist-electron\LogNotes Setup *.exe` (bundles the back end as `dist\LogNotes\LogNotes.exe`).

## Layout

- [src/controller.py](src/controller.py) — `LogNotesController`, the front-end-agnostic orchestrator (recorder → Whisper → paste). Talks to the UI only via an injected `UIBridge` / `ConfigStore` / `ActivityStore`.
- [sidecar.py](sidecar.py) — `SidecarServer`: WebSocket + RPC server wrapping the controller; `HeadlessBridge` forwards UI calls as events.
- [src/ui_bridge.py](src/ui_bridge.py) — `UIBridge` protocol the controller talks through.
- [src/config.py](src/config.py) — schema, whitelist validation, `0o600` save, `ConfigStore`.
- [src/activity.py](src/activity.py) — in-memory `ActivityStore` (session-scoped, audio in RAM only).
- [src/transcription/](src/transcription/) — faster-whisper, model registry, CUDA detection.
- [src/audio/](src/audio/) — `AudioRecorder` (sounddevice).
- [src/input/](src/input/) — `HotkeyListener` (pynput), `paste_text` / `copy_to_clipboard`.
- [src/paths.py](src/paths.py) — dev-vs-frozen asset resolution + user data/cache dirs.
- [electron/](electron/) — `main.js` (process spawn, tray, lifecycle), `preload.js` (bridge), `renderer/` (tabs + overlay).
- [build/](build/) — PyInstaller specs + `build-electron.ps1` (Electron build).

> A legacy Tkinter UI ([src/ui/](src/ui/), entry [main.py](main.py)) is kept for reference and shares `LogNotesController`. The Electron app is canonical.

## Key Behaviors

- **Checkpoint pasting** — segments are pasted as sentence-boundary chunks so partial output is preserved if processing fails mid-stream.
- **Activity tab** — every session transcription retained in RAM (audio + text), retryable with a different Whisper model. Nothing persisted to disk; cleared on app close. Audio is never serialized over IPC — only metadata + text.
- **Config** lives at `%APPDATA%\LogNotes\config.json` (shared between dev and packaged runs). All values are whitelist-validated on load; `setConfig` over IPC re-validates per key.
- **Model caches** at `%LOCALAPPDATA%\LogNotes\cache\{hf,torch}`; `HF_HOME`/`TORCH_HOME` set in the entry point ([sidecar.py](sidecar.py) / [main.py](main.py)) before torch imports.

## Conventions

- All markdown section headings use title case (e.g. "Hotkey Not Working", not "Hotkey not working"). This applies to README.md and all files under `documentation/`.

## Gotchas

- `sys.stdout` / `sys.stderr` are `None` under `--noconsole`; the entry points replace them with `io.StringIO` sinks so libraries that call `.write()` (torch.hub) don't crash. The frozen back end uses `console=True` so its `PORT <n>` handshake reaches a real stdout.
- Do **not** add `test` or `unittest` to PyInstaller `excludes` — torch imports `unittest` at runtime.
- Rebuilding fails if a running `LogNotes.exe` is still holding `dist-electron\win-unpacked\` (locked files). Close the app (and any orphaned back ends) first.
- electron-builder can't edit the exe to embed the icon on this setup (winCodeSign symlink failure); the build embeds the icon via `rcedit` in a three-stage build. See [ARCHITECTURE.md](ARCHITECTURE.md) packaging notes.
- `build.ps1` / `build-electron.ps1` must stay ASCII-only — Windows PowerShell 5.1 mis-parses UTF-8 without a BOM.

## Tests

`venv\Scripts\python.exe -m unittest discover -s tests` — config validation, status revert, and the sidecar protocol smoke test.
