# LogNotes - Implementation Documentation

> **Docs:** [Configuration](configuration.md) · [Troubleshooting](troubleshooting.md) · [Desktop packaging](desktopAppConfiguration.md) · [Implementation](mvpImplementation.md)

## Overview

A lightweight, local speech-to-text dictation app that transcribes voice input and pastes the result at the cursor position. Uses Whisper for transcription (NVIDIA Parakeet is supported as an opt-in backend, disabled by default) and Ollama (llama3.2:1b) for grammar cleanup.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  LogNotesApp (ttkbootstrap)                     │
│  ┌───────────────── Manual Tab Bar ─────────────────┐           │
│  │   [Settings]  [Activity]  [Logs]                  │           │
│  ├───────────────────────────────────────────────────┤           │
│  │ Settings (scrollable Canvas):                     │           │
│  │   Logo │ Hotkey | Status | Model | Grammar | ... │           │
│  │ Activity: session history + retry/copy/delete     │           │
│  │ Logs: ScrolledText fed by _LogHandler             │           │
│  └───────────────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────────┘
        │                                  ▲
        ▼                                  │ status updates (thread-safe via after())
┌─────────────────────────────────────────────────────────────────┐
│          Recording Overlay (Toplevel, overrideredirect)          │
│   ● Ready   — pinned to screen corner, draggable, right-click   │
│              cycles corners, taskbar-safe via SPI_GETWORKAREA    │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                     LogNotesController                          │
│  Streaming pipeline:                                             │
│  [Audio] → [backend-specific preprocess] → [ASR segments] →      │
│    buffer until sentence boundary (.?!) →                        │
│    [Ollama cleanup] → [paste chunk, no clipboard-clear] →        │
│    ... → final chunk clears clipboard                            │
└─────────────────────────────────────────────────────────────────┘
```

## Tech Stack

| Component | Library | Purpose |
|-----------|---------|---------|
| Transcription (Whisper) | `faster-whisper` | Local Whisper inference (tiny/base/small) |
| Transcription (Parakeet, opt-in) | `onnx-asr[hub]` + `onnxruntime` | Parakeet 0.6B v3 multilingual via ONNX Runtime — disabled by default |
| GPU detection | `ctranslate2` + `onnxruntime` probes | Auto-select CUDA at runtime when available |
| Voice Activity Detection | `silero-vad` via torch | Backend-specific silence filtering (used for non-Whisper backends) |
| Audio Recording | `sounddevice` | Cross-platform microphone input |
| Global Hotkeys | `pynput` | System-wide keyboard shortcuts |
| Grammar Cleanup | `ollama` Python client | Local LLM via Ollama API |
| Text Pasting | `pynput` + `pyperclip` | Clipboard and Ctrl+V simulation |
| UI Framework | `ttkbootstrap` (`darkly` / `flatly`) | Modern themed Tk GUI |

## Project Structure

```
dictation-app/
├── main.py                 # Entry point, LogNotesController
├── requirements.txt        # Python dependencies
├── config.json            # User settings (hotkey, model preferences)
│
├── src/
│   ├── __init__.py
│   ├── audio/
│   │   ├── __init__.py
│   │   ├── recorder.py     # AudioRecorder class
│   │   └── vad.py          # VoiceActivityDetector class
│   │
│   ├── transcription/
│   │   ├── __init__.py     # create_transcriber() factory
│   │   ├── base.py         # Transcriber protocol
│   │   ├── registry.py     # ModelSpec + MODELS tuple (single source of truth)
│   │   ├── device.py       # CUDA detection (ctranslate2 + onnxruntime)
│   │   ├── whisper.py      # WhisperTranscriber (faster-whisper, CUDA auto)
│   │   └── parakeet.py     # ParakeetTranscriber (onnx-asr, lazy import)
│   │
│   ├── processing/
│   │   ├── __init__.py
│   │   └── grammar.py      # GrammarProcessor class
│   │
│   ├── input/
│   │   ├── __init__.py
│   │   ├── hotkey.py       # HotkeyListener class
│   │   └── paster.py       # paste_text() function
│   │
│   └── ui/
│       ├── __init__.py
│       ├── app.py          # LogNotesApp, HotkeyCapture classes
│       └── activity.py     # ActivityStore, ActivityEntry, ActivityTab
│
└── documentation/
    └── mvpImplementation.md
```

## Component Details

### AudioRecorder (`src/audio/recorder.py`)

Records audio from the microphone using `sounddevice`.

- Sample rate: 16kHz (Whisper requirement)
- Mono channel, float32 format
- Non-blocking recording with callback
- Reuses a warm `InputStream` across recordings to reduce start/stop overhead
- Thread-safe start/stop/get_audio methods plus explicit `close()` cleanup
- If `sounddevice` is missing in a packaged build, the recorder reports itself
  unavailable and the controller surfaces a user-visible error instead of
  crashing during startup

```python
class AudioRecorder:
    def start() -> None      # Begin recording
    def stop() -> None       # Stop recording
    def get_audio() -> np.ndarray  # Get recorded audio
    def is_recording -> bool # Check recording state
```

### VoiceActivityDetector (`src/audio/vad.py`)

Filters silence from audio using Silero VAD model.

- Lazy loads model from torch.hub on first use
- **Pinned to version v5.1** for supply chain security
- Configurable speech probability threshold
- Returns only speech segments concatenated
- Proper error handling with informative logging
- Invoked only for backends that need external preprocessing; Whisper uses its
  internal `faster-whisper` VAD instead of stacking a second pass

```python
class VoiceActivityDetector:
    def filter_silence(audio: np.ndarray) -> np.ndarray
    def reset() -> None  # Reset model state
```

### Transcription Backends (`src/transcription/`)

The app supports multiple ASR backends behind a shared `Transcriber` protocol. A registry maps a stable id (stored in config + activity entries) to a display name, backend, and backend-specific load argument.

**`registry.py`** — single source of truth:

```python
MODELS = (
    ModelSpec("whisper-tiny",  "Whisper tiny",  "whisper",  "tiny"),
    ModelSpec("whisper-base",  "Whisper base",  "whisper",  "base"),
    ModelSpec("whisper-small", "Whisper small", "whisper",  "small"),
    # ModelSpec("parakeet-v3", "Parakeet 0.6B v3 (multilingual)", "parakeet", "nvidia/parakeet-tdt-0.6b-v3"),
)
```

Adding another ASR model is a one-line append — the Settings dropdown, Activity retry menu, config whitelist, and `create_transcriber()` factory all read from this tuple. Legacy ids (`tiny`, `parakeet-110m`, `parakeet-v3`) are remapped via `_LEGACY_ALIASES` — anything Parakeet maps to `whisper-small` so disabled-by-default doesn't strand old configs.

**`device.py`** — single shared probe: tries `ctranslate2.get_cuda_device_count()` and `"CUDAExecutionProvider" in onnxruntime.get_available_providers()` once per process (`@lru_cache`) and exposes a `DeviceInfo` consumed by both backends.

**`WhisperTranscriber`** - `faster-whisper`, eagerly loaded on startup via `load()`, yields segments for checkpoint pasting. Auto-selects `("cuda", "float16")` when CUDA is detected, else `("cpu", "int8")`. Uses `beam_size=1` for lower dictation latency and relies on `faster-whisper`'s internal VAD instead of a separate controller-side VAD pass. If model load fails with an SSL/certificate error (e.g. corporate proxy with SSL inspection), `_load_model` retries with `local_files_only=True` to load from the local cache without contacting HuggingFace.

**`ParakeetTranscriber`** — onnx-asr (lazy import). Maps the registry `backend_arg` (`nvidia/parakeet-tdt-0.6b-v3`) to the onnx-asr id `nemo-parakeet-tdt-0.6b-v3` and constructs an ORT session with `[CUDAExecutionProvider, CPUExecutionProvider]` when GPU is available, else CPU only. onnx-asr returns full transcripts per call; we split on sentence boundaries to feed the checkpoint-paste pipeline natural chunks. Models cache under `%LOCALAPPDATA%\LogNotesApp\cache\hf` via `HF_HOME`.

**Models considered and dropped:**
- *Parakeet 0.6B v2 on NeMo* — Quality wasn't measurably better than Whisper small on our samples and processing time was much longer. NeMo's float32 PyTorch path has no CPU quantization story.
- *Parakeet 110M* — kept briefly as a CPU-friendly option, then dropped because `onnx-asr` does not currently ship a 110M ONNX export. Whisper tiny/base fill the fast-CPU tier.
- *Parakeet 0.6B v3 (ONNX)* — Quality wasn't measurably better than Whisper small on our samples and processing time was much longer. Disabled in the default registry but kept wired end-to-end (backend, device detection, commented `ModelSpec`) so enabling is a three-line change.

```python
class Transcriber(Protocol):
    def transcribe(audio: np.ndarray, language: str = "en") -> str
    def transcribe_segments(audio: np.ndarray, language: str = "en") -> Iterator[str]
    def change_model(arg: str) -> None
    @property
    def is_loaded -> bool

def create_transcriber(model_id: str) -> Transcriber  # factory in __init__.py
```

### GrammarProcessor (`src/processing/grammar.py`)

Cleans up transcription using Ollama.

- Connects to local Ollama server
- Uses llama3.2:1b by default
- Low temperature (0.1) for consistent output
- Graceful fallback if Ollama unavailable
- Availability checks are cached briefly in-memory to avoid probing Ollama on every utterance
- **Prompt injection protection** via structural isolation (Ollama system/prompt separation)

```python
class GrammarProcessor:
    def cleanup(text: str) -> str
    def is_available() -> bool
    def change_model(model: str) -> None  # raises ValueError on invalid name
```

**Security - Prompt Isolation:**
Instructions are passed via Ollama's `system` parameter; the user text is the entire `prompt` field. This is true structural isolation — the model processes them in separate roles, so transcribed text cannot be interpreted as instructions regardless of content. No delimiter tricks are needed, and no extra tokens are generated from tag-closing behavior. Input is also length-capped at 10,000 characters before sending.

`change_model()` validates the new model name against the same allowed-characters pattern used by config validation, raising `ValueError` on invalid input.

**System prompt:**
```
Fix the grammar and punctuation of transcribed speech.
Do not change the meaning or add new information.
Do not add any explanations or comments.
Only output the corrected text, nothing else.
```

**User prompt:** the raw transcribed text (no wrapper).

### HotkeyListener (`src/input/hotkey.py`)

Listens for global keyboard shortcuts using pynput.

- Supports modifier combinations (Ctrl, Shift, Alt, Cmd)
- Handles Windows control character issue (Ctrl+D = \x04)
- Separate callbacks for press and release events
- Thread-safe key state tracking

```python
class HotkeyListener:
    def start() -> None
    def stop() -> None
    def update_hotkey(hotkey: str) -> None
```

**Key implementation detail:** On Windows, when Ctrl is held, letter keys return control characters (e.g., Ctrl+D = `\x04`). The listener converts these back to letters using `chr(ord(char) + 96)`.

### paste_text (`src/input/paster.py`)

Pastes text at the cursor position.

- Copies text to clipboard via pyperclip
- Waits 0.5s for original window to regain focus
- Simulates Ctrl+V using pynput keyboard controller
- **Security:** Clears clipboard 5 seconds after paste to prevent data leakage

```python
def paste_text(text: str, method: str = "clipboard", clear_clipboard: bool = True) -> bool
```

Note: `clear_clipboard=False` is used for mid-stream chunks to avoid the 5s clear between sentences; the final chunk uses `True`. The clipboard copy and clear are wrapped in `try/finally` so clearing is guaranteed even if an exception occurs during paste simulation. When `clear_clipboard=False`, a 150ms post-Ctrl+V sleep ensures the target application reads the clipboard before the next chunk's `pyperclip.copy()` overwrites it.

### LogNotesApp (`src/ui/app.py`)

Tkinter-based configuration UI.

**Features:**
- Manual tab bar (buttons + separator + pack_forget switcher) for Settings / Activity / Logs — avoids ttk.Notebook layout quirks
- Scrollable Settings tab via Canvas + Scrollbar; scrollregion height is clamped to `max(bbox_h, canvas_h)` so the viewport never renders blank space above the content
- Status indicator (green=ready, red=recording, yellow=processing); thread-safe via `after(0, ...)`
- Hotkey display and change dialog
- Whisper model dropdown, grammar toggle, recording-mode selector, theme selector
- Toggle-mode ▶/⏹ icons as a click alternative to the hotkey
- **Activity tab**: Session-scoped transcription history backed by `ActivityStore` (see below). Each entry shows timestamp, model used (rendered via the registry display name), and truncated text with show-more expansion; per-row Copy button and overflow menu for Retry (all registered models) and Delete. Cleared on app close.
- **Log viewer tab**: `_LogHandler(logging.Handler)` streams records into a ScrolledText widget, colored by level; Copy and Clear buttons
- **Recording overlay**: borderless Toplevel (`overrideredirect`, `-topmost`, `-alpha`) showing a colored status dot; drag to move, right-click cycles corners; corner persisted in config, position computed from `SystemParametersInfoW(SPI_GETWORKAREA)` for taskbar-safe anchoring

**Security - Config Validation:**
All loaded configuration values are whitelist-validated on load; invalid values fall back to secure defaults with a warning logged. See [configuration.md](configuration.md) for the full validation rules per key.

`ollama_host` is validated with `urllib.parse.urlparse()` — scheme must be `http` or `https` and `netloc` must be non-empty, preventing malformed URLs like `"https://"` from passing.

`_save_config()` creates the config file with `os.open(..., 0o600)` so restricted permissions are set atomically at creation time, not in a follow-up `chmod` call that would leave a readable window.

### ActivityStore & ActivityTab (`src/ui/activity.py`)

Session-scoped in-memory store for transcription history, plus the Tk widget that renders it.

- **`ActivityEntry`**: dataclass holding a monotonic id, timestamp, raw audio (`np.ndarray`, pre-VAD), current text, model used, grammar flag, paste outcome, and optional error.
- **`ActivityStore`**: thread-safe list of entries with an observer callback (`subscribe`) so the UI refreshes when data changes. Capped by **total retained audio-seconds** (15 min default), not entry count — long sessions with short clips stay cheap; long clips are still bounded. Eviction is FIFO.
- **`ActivityTab`**: renders newest-first; each row has a Copy button and a dropdown with Retry across all registered models and Delete. Busy-state is checked at click time, not render time, so the menu never goes stale.

```python
class ActivityStore:
    def add(audio, text, whisper_model, grammar_applied, paste_succeeded, error=None) -> ActivityEntry
    def update(entry_id, *, text=None, whisper_model=None, error=None) -> None
    def delete(entry_id) -> None
    def get(entry_id) -> Optional[ActivityEntry]
    def clear() -> None
    def entries_newest_first() -> list[ActivityEntry]
    def subscribe(cb: Callable[[], None]) -> None
```

**Privacy:** Audio lives in RAM only. `LogNotesApp._quit()` calls `activity_store.clear()` before destroying the window; nothing is written to disk.

### LogNotesController (`main.py`)

Main controller that orchestrates all components.

**State machine:**

Hold mode:
```
IDLE → (hotkey pressed) → RECORDING → (hotkey released) → PROCESSING → IDLE
```

Toggle mode:
```
IDLE → (hotkey/icon pressed) → RECORDING → (hotkey/icon pressed again) → PROCESSING → IDLE
```

Stop logic is shared via `_stop_and_process()`, called by both `_on_hotkey_press` (toggle) and `_on_hotkey_release` (hold).

**Processing pipeline (checkpoint pasting):**
1. Get audio from the recorder.
2. Select the active backend from the model registry.
3. Run backend-specific preprocessing:
   For Whisper, skip controller-side VAD and hand raw audio to `faster-whisper`.
   For other backends such as Parakeet, run Silero VAD first.
4. Iterate `transcribe_segments()` output and accumulate text until the buffer ends in `.?!`.
5. Flush each chunk:
   (Optional) grammar cleanup with Ollama, using cached availability state.
   Paste chunk with `clear_clipboard=False`.
6. Paste the final leftover chunk with `clear_clipboard=True`.
7. Record an `ActivityEntry` with the original session audio, final text, model id, and paste outcome so retries can reuse the same input.
8. Emit per-phase timing logs for `capture`, `preprocess`, `transcribe`, `grammar`, `paste`, and `total` so packaged-build performance can be compared directly.

**Retry flow:** `retry_transcription(entry_id, model)` spawns a background thread that normalizes the requested model id, applies the same backend-specific preprocessing used by live dictation, re-runs `transcribe_segments()` on the stored audio, re-applies grammar cleanup if it was used originally, updates the entry, and copies the new text to the clipboard (no auto-paste). The user's configured live model is restored after the retry. `is_busy()` (true when recording or processing) gates both live capture and retries through the shared `_processing_lock`; clicks during a busy window are logged and surfaced in the status bar.

## Configuration

See [configuration.md](configuration.md) for the config file location, full schema, settings reference, and validation rules.

## Dependencies

### requirements.txt

```
faster-whisper>=1.0.0
sounddevice>=0.4.6
numpy>=1.24.0
scipy>=1.10.0
torch>=2.0.0
torchaudio>=2.0.0
pynput>=1.7.6
pyperclip>=1.8.2
ollama>=0.1.0
ttkbootstrap>=1.20.0
pillow>=10.0.0
# onnx-asr[hub]>=0.6.0   # commented — uncomment to enable Parakeet
```

**No build toolchain required.** The ONNX migration removed NeMo and its `editdistance` transitive dependency, so a stock Python 3.10+ install on Windows works without MSVC Build Tools. For GPU acceleration, install `onnxruntime-gpu` (if Parakeet is enabled) and a CUDA-enabled `ctranslate2` build separately; both backends auto-detect at runtime via `src/transcription/device.py` and fall back to CPU otherwise.

Note: `pyautogui` was removed from final implementation — `pynput` handles keyboard simulation. `pystray` is imported lazily for the optional system tray icon in `LogNotesApp._setup_tray`; if it is not installed, the rest of the app still works.

## Known Issues & Solutions

### 1. Hotkey Not Detected on Windows

**Problem:** Ctrl+letter combinations return control characters.

**Solution:** Convert control characters back to letters in `_key_to_string()`.

### 2. Text Not Pasting at Cursor

**Problem:** App window may have focus during processing.

**Solution:** Added 0.5s delay before paste to allow focus return.

### 3. Ctrl+C Doesn't Stop the App

**Problem:** pynput captures all keyboard input including Ctrl+C.

**Solution:** Added `signal.signal(signal.SIGINT, signal.SIG_DFL)` in main().

### 4. First Transcription Slow

**Problem:** `preload()` created `WhisperTranscriber` wrapper objects but never called `WhisperModel()` on them, so the app showed "Ready" while models were still unloaded. The first transcription paid the full cold-load cost (5–8 s for small).

**Solution:** Added a public `load()` method to `WhisperTranscriber` that calls `_load_model()`. Both `preload()` and `_warm_other_models()` now call it so all models are in memory before the user's first recording. A short-lived cached Ollama availability probe prevents a network check on every utterance when grammar is enabled.

### 5. Repeated Recording Startup Overhead

**Problem:** Opening and closing the microphone stream for every utterance adds avoidable latency.

**Solution:** Keep a warm `sounddevice.InputStream` across recordings and close it only on shutdown.

### 6. Toggle Mode Hotkey Press Could Not Stop Recording

**Problem:** `_on_hotkey_press` delegated to `_on_hotkey_release` to stop recording, but `_on_hotkey_release` immediately returned early in toggle mode.

**Solution:** Extracted shared `_stop_and_process()` method. `_on_hotkey_press` calls it directly when toggle mode detects an active recording.

### 7. Duplicate VAD on the Whisper Path

**Problem:** Running controller-side Silero VAD before `faster-whisper` adds a second silence-filtering pass and extra tensor work.

**Solution:** Make preprocessing backend-specific so Whisper uses only `faster-whisper` VAD, while external VAD remains available for non-Whisper backends.

### 8. Blank Space at Top of Settings Tab

**Problem:** Canvas rendered a gap above content when scrollregion height < viewport height.

**Solution:** Clamp scrollregion to `sr_h = max(bbox[3], canvas.winfo_height())` and recompute on `<Configure>` of both the inner frame and the canvas.

### 9. Overlay Overlapping Windows Taskbar

**Problem:** Using screen dimensions anchors the overlay under the taskbar.
**Solution:** Query `SystemParametersInfoW(SPI_GETWORKAREA)` via ctypes to get the usable work area.

### 10. Packaged App Crashes on Startup with `No module named 'sounddevice'`

**Problem:** A frozen build can be missing the `sounddevice` runtime payload even though microphone code imports it at startup.

**Solution:** `AudioRecorder` now imports `sounddevice` defensively and reports unavailability through `AudioBackendUnavailableError`, while the controller shows a UI error instead of crashing. PyInstaller builds also bundle the `sounddevice` runtime payload and PortAudio DLLs.

### 11. First Chunk Missing from Multi-Sentence Paste

**Problem:** In checkpoint pasting, `_paste_via_clipboard` returned immediately after firing the Ctrl+V key event when `clear_clipboard=False`. The next chunk's `pyperclip.copy()` ran before the target application had processed the keystroke, overwriting the clipboard. The first chunk's Ctrl+V event then read the second chunk's content, causing the first sentence to appear only in clipboard history while remaining sentences were pasted.

**Solution:** Added a 150ms post-Ctrl+V sleep in `_paste_via_clipboard` when `clear_clipboard=False`, giving the target application time to read the clipboard before it is overwritten. The `clear_clipboard=True` path is unaffected — its 5s cleanup sleep already provides sufficient headroom.

### 12. SSL Certificate Error Prevents Model Load on Corporate Networks

**Problem:** `faster-whisper` contacts HuggingFace Hub to verify the model revision on every `WhisperModel()` call, even when the model is already cached locally. On networks with SSL inspection (e.g. corporate proxies that present their own certificate), this fails with `CERTIFICATE_VERIFY_FAILED`, causing transcription to error out.

**Solution:** `_load_model` catches SSL/certificate errors and retries `WhisperModel()` with `local_files_only=True`, bypassing the remote revision check and loading directly from the local cache. If the model is not cached and SSL is broken, the error propagates normally.

## Security Features

The application implements several security hardening measures:

| Feature | Location | Description |
|---------|----------|-------------|
| Session-Only Audio | `recorder.py`, `ui/activity.py` | Audio is held in RAM only — during recording, and for the session history in the Activity tab. Cleared on app exit; never written to disk |
| Prompt Isolation | `grammar.py` | LLM instructions are passed via Ollama's `system` parameter; transcribed text is the bare `prompt` field. The model processes them in separate roles so user content cannot be interpreted as instructions. Input length capped at 10,000 chars |
| Model Name Validation | `grammar.py` | `change_model()` validates names against the allowed-characters pattern before accepting them |
| Config Validation | `app.py` | Whitelists valid values for all settings; `ollama_host` verified with `urlparse` (scheme + non-empty netloc required) |
| Atomic Config Permissions | `app.py` | Config file created with `os.open(..., 0o600)` so permissions are set at creation, not in a separate `chmod` call |
| Guaranteed Clipboard Clearing | `paster.py` | Clipboard cleared in a `finally` block so it always runs even if paste simulation raises an exception |
| Bounded Activity Memory | `activity.py` | Audio eviction runs before adding a new entry so peak RAM never temporarily exceeds the cap |
| Pinned Model Versions | `vad.py` | Silero VAD pinned to v5.1 |
| Proper Error Logging | All modules | Uses Python logging instead of print statements |

## Potential Future Enhancements

- [ ] Audio feedback (beep on start/stop)
- [ ] Persisted transcription history across sessions
- [ ] Multiple language support
- [ ] System tray mode for background operation
