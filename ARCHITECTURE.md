# Architecture

LogNotes is a local speech-to-text dictation app: a push-to-talk hotkey records
audio, Whisper transcribes it, and the result is pasted at the cursor. This
document describes how the app is built.

## High-Level Shape

LogNotes is a **hybrid app**: an **Electron front end** for the UI and a
**Python back end** (the "sidecar") for the ML pipeline and OS integration. They
run as separate processes and communicate over a loopback WebSocket.

The split exists because the valuable part of the app — Whisper
inference (`ctranslate2` / `faster-whisper`), global hotkeys (`pynput`),
and paste-at-cursor — has no
production-quality JavaScript equivalent, so it stays in Python. Electron owns
only the UI (windows, tabs, overlay, tray). Electron does not change transcription
latency; the pipeline is identical to what a pure-Python build would run.

```
┌──────────────────────────────────────────────────────────────┐
│                      Electron (Node)                         │
│  main process (electron/main.js):                            │
│    - spawns + supervises the Python back end                 │
│    - reads its `PORT <n>` stdout handshake, hands it to the   │
│      renderers over IPC                                       │
│    - owns Tray, app lifecycle, single-instance lock          │
│  renderers (contextIsolation on, nodeIntegration off):       │
│    - main window: Settings / Activity / Logs tabs            │
│    - overlay: separate frameless always-on-top status pill   │
│    each renderer opens its OWN WebSocket to the back end      │
└──────────────────────────────────────────────────────────────┘
        │  loopback WebSocket (127.0.0.1, ephemeral port)  ▲ events
        ▼                                                  │
┌──────────────────────────────────────────────────────────────┐
│             Python back end (sidecar.py)                     │
│    SidecarServer + LogNotesController (src/controller.py)     │
│    - hotkey (pynput), recorder, Whisper ASR, paste           │
│    - ConfigStore, ActivityStore, log ring buffer             │
└──────────────────────────────────────────────────────────────┘
```

## The Transcription Pipeline

The controller ([src/controller.py](src/controller.py)) orchestrates the same
streaming pipeline regardless of which front end is attached:

1. **Capture** — the hotkey press starts the recorder; release (hold mode) or a
   second press (toggle mode) stops it.
2. **Transcribe** — Whisper (`faster-whisper`, with its internal VAD) yields text
   segments as they decode.
3. **Checkpoint paste** — segments are accumulated until a sentence boundary
   (`.?!`), then that chunk is pasted immediately. This means partial output
   survives if processing fails mid-stream.
4. **Clipboard hygiene** — mid-stream chunks paste without clearing the clipboard
   (a 150 ms guard prevents the next chunk overwriting before the target app
   reads it); the final chunk clears the clipboard 5 s after paste.
5. **Record activity** — the session audio + final text are stored in memory for
   the Activity tab (retryable with a different model).

## Process & IPC

**Transport.** A loopback-only WebSocket on `127.0.0.1`, ephemeral port. The back
end binds port 0 (OS-assigned), prints `PORT <n>` on stdout; the Electron main
process reads that line and hands the port to each renderer via the preload
bridge. WebSocket (not request/response) is used because the back end **pushes**
status, activity, config, and log events to the UI.

**Protocol.** JSON messages, WebSocket-framed:

```
Request:  {"id": <int>, "method": <str>, "params": {...}}
Response: {"id": <int>, "result": <any>}  |  {"id": <int>, "error": <str>}
Event:    {"event": <str>, "data": {...}}            (server -> client)
```

**Request methods** (handled in [sidecar.py](sidecar.py)): `getConfig`,
`setConfig` (whitelist-validated, persisted, side effects applied), `getModels`,
`getActivity`, `retryTranscription`, `deleteActivity`, `clearActivity`,
`toggleRecording`, `isBusy`, `getLogs`, `clearLogs`.

**Pushed events:** `ready` (per-client snapshot on connect), `status`,
`configChanged`, `activityChanged`, `audioError`, `logLine`.

**Privacy.** Activity audio stays in RAM in the back end and is never serialized
over the wire — only metadata + text. Nothing is written to disk; the session
clears on quit.

## Module Layout

The controller is front-end-agnostic: it talks to the UI only through an injected
`UIBridge` / `ConfigStore` / `ActivityStore`, so it has no Tk or Electron
coupling and the back end imports no UI framework.

| Area | Files | Role |
| --- | --- | --- |
| Orchestrator | [src/controller.py](src/controller.py) | `LogNotesController` — the pipeline; talks to the UI via injected interfaces. |
| UI contract | [src/ui_bridge.py](src/ui_bridge.py) | `UIBridge` protocol (`set_status`, `show_audio_error`). |
| Config | [src/config.py](src/config.py) | Schema, whitelist validation, `0o600` save, `ConfigStore`, single-key `validate_value()`. |
| Activity | [src/activity.py](src/activity.py) | In-memory `ActivityStore` + `ActivityEntry` (audio held in RAM only). |
| Transcription | [src/transcription/](src/transcription/) | `whisper.py` (faster-whisper), `registry.py` (model registry), `device.py` (CUDA detection). |
| Audio | [src/audio/](src/audio/) | `recorder.py` (sounddevice). |
| Input | [src/input/](src/input/) | `hotkey.py` (pynput global hotkey), `paster.py` (paste-at-cursor + clipboard). |
| Paths | [src/paths.py](src/paths.py) | dev-vs-frozen asset resolution + user data/cache dirs. |
| Back-end server | [sidecar.py](sidecar.py) | `SidecarServer` (WebSocket + RPC) and `HeadlessBridge` (UIBridge → events). |
| Electron main | [electron/main.js](electron/main.js) | Process spawn/supervision, windows, tray, lifecycle. |
| Preload | [electron/preload.js](electron/preload.js) | Hardened `contextBridge` surface. |
| Renderer | [electron/renderer/](electron/renderer/) | `index.html`/`renderer.js` (tabs), `overlay.html`/`overlay.js` (pill). |

> A legacy Tkinter UI ([src/ui/](src/ui/), driven by [main.py](main.py)) is kept
> in the tree for reference. It shares `LogNotesController` with the Electron back
> end. The shipped product is the Electron app.

## Front-End Behavior

- **Two independent renderers.** The main window and the overlay each open their
  own WebSocket. The overlay shows only the short state label (Ready / Recording /
  Processing); verbose detail stays in the main window's status box.
- **Responsive startup.** The main window is shown immediately on launch (before
  the back end finishes starting), so a slow first launch doesn't look frozen; the
  renderer polls for the back-end port until it's up.
- **Single instance.** `requestSingleInstanceLock()` + a `second-instance`
  handler surface the existing window instead of spawning a duplicate.
  `setAppUserModelId` ties the window + pinned taskbar shortcut to the app
  identity on Windows.
- **Hide to tray.** Closing the window hides it to the tray so the global hotkey
  keeps working; Quit (tray menu) stops the back end — no orphaned process.
- **Hardening.** `contextIsolation: true`, `nodeIntegration: false`, a typed
  preload bridge, and a permission handler that denies all web permissions except
  clipboard.

## Transcription Backends

Models live in a registry ([src/transcription/registry.py](src/transcription/registry.py))
mapping a stable id to a display name, backend, and load argument:

- **Whisper**: `whisper-base`, `whisper-small` via faster-whisper.
  Auto-selects CUDA float16 when available, else CPU int8.

All Whisper sizes are warmed in the background at startup so Activity-tab retries
with a different model are instant.

## Configuration & Caches

- **Config:** `%APPDATA%\LogNotes\config.json`, whitelist-validated on load,
  written with `0o600` permissions. See
  [documentation/configuration.md](documentation/configuration.md) for the schema.
- **Model caches:** `%LOCALAPPDATA%\LogNotes\cache\{hf,torch}`. `HF_HOME` /
  `TORCH_HOME` are set in the entry point (`sidecar.py` / `main.py`) before torch
  is imported.

## Packaging

A single NSIS installer that bundles the Python back end inside it.

- The back end is frozen with PyInstaller ([build/LogNotes.spec](build/LogNotes.spec),
  entry point `sidecar.py`) into `dist/LogNotes/LogNotes.exe`.
- electron-builder ([electron/package.json](electron/package.json)) bundles that
  as an `extraResource` and produces the installer in `dist-electron/`.
- [build/build-electron.ps1](build/build-electron.ps1) orchestrates the build.
- User config/cache paths are identical to any prior install, so settings and
  downloaded models carry over.

See [documentation/troubleshooting.md](documentation/troubleshooting.md) for
build and runtime troubleshooting.

## Security Model

- **Audio is session-only** — held in RAM, never written to disk, cleared on exit.
- **Config validation** — all values whitelist-validated; config file created `0o600`.
- **Clipboard hygiene** — clipboard cleared after paste; clearing is guaranteed
  even if paste raises.
- **Electron hardening** — context isolation, no node integration, all web
  permissions denied except clipboard.
- **Local only** — no network traffic except local model downloads; no telemetry;
  the app and installer run without admin.
