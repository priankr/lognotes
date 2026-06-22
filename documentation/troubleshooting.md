# Troubleshooting

> **Docs:** [Configuration](configuration.md) · [Troubleshooting](troubleshooting.md)

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

- Switch to a larger model: **base → small**. `small` offers the best quality/speed tradeoff on CPU.
- Speak closer to the microphone and reduce background noise.
- Speak at a natural pace — very fast or very slow speech can confuse the model.

---

## Overlay in Wrong Position / Hidden Behind Taskbar

- Right-click the overlay to cycle through the four corners.
- Left-click and drag to reposition manually.
- The corner is persisted in config; the exact drag position is not — it resets to the configured corner on restart.
- The overlay is positioned within the primary display's work area to avoid the taskbar, but secondary monitors with non-standard taskbar positions may still cause overlap. Switch corners to work around it.

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

## Packaged App Opens but Stays "Connecting to Sidecar…"

The window appears but never reaches "Ready" — the Electron front end can't reach
the Python back end.

- Run the bundled back end directly to see its error. It is built with a console,
  so it prints what fails:
  ```powershell
  "%LOCALAPPDATA%\Programs\LogNotes\resources\sidecar\LogNotes.exe"
  ```
  (Path varies with the install location; look under the install dir's
  `resources\sidecar\`.) A healthy run prints a `PORT <n>` line.
- Common causes: a missing DLL / hidden import, or a `sounddevice` / PortAudio
  payload issue. The console output identifies the failing module.
- First launch is slow (models load); give it time before assuming it is stuck.
- Make sure no orphaned `LogNotes.exe` from a previous run is interfering
  (Task Manager).
