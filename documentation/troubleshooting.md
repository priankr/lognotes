# Troubleshooting

> **Docs:** [Configuration](configuration.md) · [Troubleshooting](troubleshooting.md) · [Desktop packaging](desktopAppConfiguration.md) · [Implementation](mvpImplementation.md)

---

## Hotkey Not Working

- Ensure no other app is using the same hotkey combination.
- Some apps (Discord overlays, GeForce Experience, antivirus software) intercept hotkeys at a lower level and will silently win. Try a less common combination like `Ctrl+Shift+Space` or `Alt+F9`.
- The Logs tab will show a "Hotkey registered" message on startup — if it's missing, the listener failed to start.
- On Windows, hotkeys cannot be captured from windows running at a higher privilege level (e.g. Task Manager). If your target window is elevated, try running LogNotes as administrator.

---

## Text Not Pasting

- Make sure a text input field is focused **before** releasing the hotkey — the app waits 0.5s for focus to return, but some apps take longer.
- Some elevated windows (Task Manager, UAC prompts, certain terminals) block simulated keystrokes from non-elevated processes. Run LogNotes as administrator to paste into them.
- The clipboard is automatically cleared 5 seconds after pasting for security — this is intentional. If you need to paste the same text again, use the **Copy** button in the Activity tab.
- Check the Logs tab for `paste_text` success or error messages to confirm whether the paste was attempted.

---

## No Audio Recorded

- Check **Windows Settings → System → Sound → Input** to confirm the correct microphone is selected as the default input device.
- Check **Windows Settings → Privacy & Security → Microphone** — LogNotes must have microphone access enabled.
- Speak at a normal volume; very quiet input may not register.
- The Logs tab will show "No audio recorded" if the recording captured complete silence, or an audio backend error if the microphone could not be opened.

---

## First Transcription Is Slow

- The Whisper model loads on first use (~2-5 seconds). Status will show "Loading models…" during this time.
- After the first load, all three Whisper sizes are warmed in the background so subsequent model switches are instant.
- This is a one-time cost per session — subsequent transcriptions are fast.

---

## Transcription Quality Is Poor

- Switch to a larger model: **tiny → base → small**. `small` offers the best quality/speed tradeoff on CPU.
- Speak closer to the microphone and reduce background noise.
- Speak at a natural pace — very fast or very slow speech can confuse the model.
- If grammar cleanup is enabled and changing the meaning of text, try disabling it in Settings.

---

## Overlay in Wrong Position / Hidden Behind Taskbar

- Right-click the overlay to cycle through the four corners.
- Left-click and drag to reposition manually.
- The corner is persisted in config; the exact drag position is not — it resets to the configured corner on restart.
- The overlay uses `SPI_GETWORKAREA` to avoid the taskbar, but secondary monitors with non-standard taskbar positions may still cause overlap. Switch corners to work around it.

---

## Ollama Not Available

- Ensure Ollama is running: `ollama serve` (check with `ollama list`).
- Confirm the model is pulled: `ollama pull llama3.2:1b`.
- If Ollama is running on a non-default port or host, update `ollama_host` in `%APPDATA%\LogNotes\config.json` — it is not exposed in the UI. See [configuration.md](configuration.md).
- Grammar cleanup is skipped silently when Ollama is unavailable — transcription still works normally.
- The Logs tab will show "Grammar cleanup enabled but Ollama is not available" when this happens.

---

## Retry Button in Activity Tab Doesn't Respond

- The app is still processing — clicks are dropped while busy. The status bar will show "Busy — retry again when ready".
- Selecting a model you have never used before triggers a one-time download from HuggingFace (up to several minutes on slow connections). Check the Logs tab for a "Retry starting…" entry to confirm it is running.
- Subsequent retries with the same model load from the local cache in a few seconds.

---

## High memory usage

- Torch and the Whisper models are large. With all three sizes warmed, expect ~1–2 GB RAM usage — this is normal.
- If memory is constrained, restart the app to clear warmed models, and only use one Whisper size.

---

## Config File Corrupted or Settings Behaving Unexpectedly

- Delete `%APPDATA%\LogNotes\config.json` and restart the app — it will be recreated with defaults.
- If you edit the file manually, ensure it is valid JSON. Invalid JSON causes the app to fall back to all defaults on next launch (an error is logged).
- See [configuration.md](configuration.md) for valid values per key.

---

## SmartScreen Warning on First Launch (Packaged Build)

- The unsigned build triggers "Windows protected your PC" — this is expected.
- Click **More info → Run anyway** to proceed.
- This warning only appears once per build. Code signing (~$100/yr OV cert) would eliminate it if distributing publicly.

---

## Packaged App Crashes Silently on Launch

- Rebuild with the debug spec to get a console with stderr output:
  ```powershell
  powershell -ExecutionPolicy Bypass -File build\build.ps1 -Debug
  dist\LogNotes-debug\LogNotes-debug.exe
  ```
- Common causes: missing DLL, missing hidden import, or a `sounddevice` / PortAudio payload issue. The console output will identify the failing module.
- See [desktopAppConfiguration.md](desktopAppConfiguration.md) for known packaging issues.

---

## Enabling Parakeet (Optional)

The Parakeet backend (NVIDIA's open ASR model family via ONNX Runtime) is wired end-to-end but disabled by default — in testing it offered no quality advantage over Whisper small while adding a ~1.2 GB first-run download. To enable:

1. Uncomment the `ModelSpec(...)` line for `parakeet-v3` in [src/transcription/registry.py](../src/transcription/registry.py).
2. Uncomment `onnx-asr[hub]>=0.6.0` in [requirements.txt](../requirements.txt) and run `pip install -r requirements.txt`.
3. **Packaged builds only:** add `"onnxruntime", "onnx_asr"` to `_BUNDLE_PKGS` in [build/LogNotes.spec](../build/LogNotes.spec) and rebuild.

Parakeet is only practical with CUDA — GPU is auto-detected at runtime. Other supported models (`nemo-parakeet-tdt-0.6b-v2`, `nemo-canary-*`) also work; see [src/transcription/parakeet.py](../src/transcription/parakeet.py) for the id mapping.
