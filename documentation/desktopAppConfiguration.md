# Desktop App Configuration

> **Docs:** [Configuration](configuration.md) · [Troubleshooting](troubleshooting.md) · [Desktop packaging](desktopAppConfiguration.md) · [Implementation](mvpImplementation.md)

## Build Instructions

### Windows

Produces a standalone `.exe` — no Python install required on the target machine.

**Prerequisites:** Python 3.10+, PyInstaller.

```powershell
pip install pyinstaller
powershell -ExecutionPolicy Bypass -File build\build.ps1
```

**Output:**

- `dist\LogNotes\LogNotes.exe` — run directly without an installer.
- `build\Output\LogNotes-Setup-<version>.exe` — installer with Start Menu entry and optional desktop shortcut. Requires [Inno Setup](https://jrsoftware.org/isdl.php) on `PATH`; skipped automatically if missing.

**Debug build** (adds a console window so you can see stderr on silent failures):

```powershell
powershell -ExecutionPolicy Bypass -File build\build.ps1 -Debug
dist\LogNotes-debug\LogNotes-debug.exe
```

**Updating:** close any running `LogNotes.exe` first (locked DLLs will block the build), then rebuild and re-run the installer. User config (`%APPDATA%\LogNotes\config.json`) and model cache (`%LOCALAPPDATA%\LogNotes\cache`) persist across upgrades.

**SmartScreen:** the unsigned build triggers "Windows protected your PC" on first launch — click **More info → Run anyway**.

**Ollama** is not bundled. Install it from [ollama.com](https://ollama.com), then `ollama pull llama3.2:1b`. The app connects to `http://localhost:11434` by default; change via `ollama_host` in `%APPDATA%\LogNotes\config.json`.

---

### Mac

Produces a standalone `.app` bundle — no Python install required on the target machine.

**Prerequisites:** Python 3.10+, PyInstaller.

```bash
pip install pyinstaller
pyinstaller --noconsole --onedir --name LogNotes \
  --add-data "src/ui/assets:src/ui/assets" \
  main.py
```

**Output:** `dist/LogNotes/LogNotes.app` — double-click to run.

Note: the `build/` directory contains Windows-specific tooling (`build.ps1`, `installer.iss`) and is not used on Mac. There is no Mac equivalent of the Inno Setup installer; distributing the `.app` folder directly (e.g. zipped) is the standard approach for unsigned apps.

**Accessibility permissions:** `pynput` requires Accessibility access to capture global hotkeys. On first run macOS will prompt you — grant access in **System Settings → Privacy & Security → Accessibility**. Without it the hotkey will not fire.

**Ollama** is not bundled. Install it from [ollama.com](https://ollama.com) and pull the model once:

```bash
ollama pull llama3.2:1b
```

Start Ollama before launching the app (`ollama serve`) if grammar cleanup is enabled.

---

## Runtime Layout

| Location | Contents |
| --- | --- |
| `%APPDATA%\LogNotes\config.json` | User settings. Shared between dev and packaged runs. See [configuration.md](configuration.md). |
| `%LOCALAPPDATA%\LogNotes\cache\hf` | HuggingFace model cache (Whisper). First-run download lands here. |
| `%LOCALAPPDATA%\LogNotes\cache\torch` | `torch.hub` cache (Silero VAD). |
| `%LOCALAPPDATA%\LogNotes\cache\logo.ico` | Generated window icon (bundle is read-only under `_MEIPASS`). |
| `{autopf}\LogNotes\` | Installer target — Program Files, no admin required. |

User data and model cache are intentionally preserved on uninstall.

---

## Code Changes

All in service of "runs correctly from both source and a frozen bundle."

### [src/paths.py](../src/paths.py) *(new)*

- `resource_path(rel)` — resolves bundled assets via `sys._MEIPASS` when
  frozen, project-root-relative in dev.
- `user_data_dir()` — `%APPDATA%\LogNotes`.
- `user_cache_dir()` — `%LOCALAPPDATA%\LogNotes\cache`.

### [main.py](../main.py)

- **stdout/stderr guards.** Under `--noconsole`, `sys.stdout` and `sys.stderr`
  are `None`. Any library that calls `.write()` (torch.hub, tqdm, etc.) would
  crash. Replaced with `io.StringIO` sinks at the top of the file — output
  discarded, API preserved. This fix was required for Silero VAD
  (`torch.hub.load`) to load in the frozen build.
- **Cache redirect.** `HF_HOME` and `TORCH_HOME` set to `user_cache_dir()`
  *before* any torch/whisper import.
- **SIGINT guard.** Only registers the signal handler when
  `sys.stdin is not None and sys.stdin.isatty()` — pointless and sometimes
  failing under `--noconsole`.

### [src/ui/app.py](../src/ui/app.py)

- `CONFIG_FILE` now resolves to `user_data_dir() / "config.json"`.
- Added `ollama_host` config key (default `http://localhost:11434`) with
  `http(s)://` URL validation in `_validate_config`.
- Asset lookups use `resource_path("src/ui/assets/logo.png")`.
- The generated `.ico` is cached in `user_cache_dir()` (the bundle is
  read-only when frozen).

### [src/processing/grammar.py](../src/processing/grammar.py)

- `GrammarProcessor.__init__` takes optional `host`. Passed through from
  config in [main.py](../main.py).

### [src/input/hotkey.py](../src/input/hotkey.py)

- Pre-existing bug surfaced during testing: `update_hotkey` wrote to
  `self._modifiers` / `self._key` but `_check_hotkey` reads
  `self._required_modifiers` / `self._required_key`, so hotkey changes were
  silently ignored. Fixed.

---

## Build Tooling

Layout under [build/](../build/):

| File | Purpose |
| --- | --- |
| `LogNotes.spec` | PyInstaller release spec, `console=False`. |
| `LogNotes.debug.spec` | Same with `console=True` for diagnosing silent failures. |
| `build.ps1` | Clean → PyInstaller → Inno Setup. Supports `-Debug` and `-SkipInstaller`. ASCII-only (Windows PowerShell 5.1 mis-parses UTF-8 without a BOM). |
| `installer.iss` | Inno Setup script. |

### Spec Highlights

- Uses `collect_all("faster_whisper" / "ctranslate2" / "torch" / "torchaudio")`
  rather than hand-curating `hiddenimports` + `collect-binaries`. This was
  essential — manual curation would have taken many iterations for the
  native-DLL-heavy stack.
- `datas=[('src/ui/assets', 'src/ui/assets')]` — bundles the logo.
- `excludes=["tkinter.test"]` only. Do **not** exclude `test` or `unittest` —
  `torch.utils._config_module` imports `unittest` at runtime; excluding it
  crashed the frozen build with `ModuleNotFoundError: No module named 'unittest'`.
- `console=False` for release; icon set to `src/ui/assets/logo.ico`.
- `COLLECT` (onedir), never `onefile` — onefile extracts to temp on every
  launch, which is slow and triggers antivirus.

Note: `-ExecutionPolicy Bypass` is per-invocation only and does not change the user/machine policy. Alternative: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then drop the flag.

Output: `dist\LogNotes\LogNotes.exe` (~800 MB, dominated by torch).

---

## Installer

[build/installer.iss](../build/installer.iss) — Inno Setup:

- `DefaultDirName={autopf}\LogNotes`
- `PrivilegesRequired=lowest` — runs without admin. Admin would break writes
  to `%APPDATA%` / `%LOCALAPPDATA%` when the app runs as the installing user.
- Start Menu shortcut always created; desktop shortcut optional (unchecked
  by default).
- Shortcuts use `logo.ico` from the bundled assets.
- Uninstaller removes program files but leaves user data + model cache in
  place. Standard practice.
- In-place upgrades over prior versions.

Build (requires [Inno Setup](https://jrsoftware.org/isdl.php) with `iscc.exe`
on `PATH`):

```powershell
iscc build\installer.iss
```

Or rely on [build/build.ps1](../build/build.ps1), which invokes `iscc`
automatically when present and skips gracefully when not.

Output: `build\Output\LogNotes-Setup-<version>.exe`.

---

## Running Python App Simultaneously

All code paths are additive. `python main.py` still works — `resource_path`
returns the dev-tree path when `sys.frozen` is false, and both dev and
packaged builds read/write the same `%APPDATA%\LogNotes\config.json`.
That shared config is usually what you want; if you ever need to isolate
dev, key `user_data_dir()` off `sys.frozen`.

---

## External Dependencies

**Ollama is not bundled.** It runs as a separate local service on
`http://localhost:11434` by default. The packaged app is just an HTTP client.

User must:

1. Install Ollama from [ollama.com](https://ollama.com).
2. `ollama pull llama3.2:1b` (or whichever model is configured).
3. Have Ollama running before launching the app.

The endpoint is configurable via `ollama_host` in
`%APPDATA%\LogNotes\config.json`.

**Whisper models** download on first use into the user cache dir. No bundling —
keeps the installer smaller, single code path, Activity-tab retry UX already
handles the first-run wait gracefully.

---

## Security Notes

Small local app, small surface:

- Spec `datas=` is explicit — no `.env` or secrets bundled.
- Ollama traffic stays on localhost.
- Installer and app run without admin.
- Silero VAD is pinned (`SILERO_VAD_VERSION = "v5.1"` in
  [src/audio/vad.py](../src/audio/vad.py#L12)) — a compromised upstream repo
  can't silently swap the model.
- Unsigned binaries will trigger SmartScreen ("More info → Run anyway") and
  may produce 1–3 heuristic VirusTotal false positives. Normal for unsigned
  PyInstaller output. Code signing (~$100/yr OV cert) would eliminate both;
  only worth it for public distribution.

---

## Known Packaging Issues 

Here are some issues encountered during previous builds for reference:

1. **`excludes=["test", "unittest"]` breaks torch.** Torch imports `unittest`
   at runtime via `torch.utils._config_module`. Keep only `tkinter.test`.
2. **`sys.stdout` / `sys.stderr` are `None` under `--noconsole`.** `torch.hub`
   and any progress-printing library will crash. Replace with `io.StringIO`
   sinks at the top of `main.py`.
3. **UTF-8 without BOM confuses Windows PowerShell 5.1.** Non-ASCII characters
   (em-dashes etc.) in `.ps1` files cause string-termination parser errors.
   Keep `build.ps1` ASCII-only.
4. **Running `LogNotes.exe` locks bundled DLLs.** Rebuilding fails with
   "Access to the path is denied" if the app is still running. Close it
   (or `taskkill`) before rebuilding.

---

## Deliverables

| Artifact | Path |
| --- | --- |
| Resource/path helpers | [src/paths.py](../src/paths.py) |
| stdout/stderr + env-var bootstrap | [main.py](../main.py) |
| Config path + ollama_host + asset paths | [src/ui/app.py](../src/ui/app.py) |
| Ollama host plumbing | [src/processing/grammar.py](../src/processing/grammar.py) |
| Hotkey update fix | [src/input/hotkey.py](../src/input/hotkey.py) |
| PyInstaller release spec | [build/LogNotes.spec](../build/LogNotes.spec) |
| PyInstaller debug spec | [build/LogNotes.debug.spec](../build/LogNotes.debug.spec) |
| Build script | [build/build.ps1](../build/build.ps1) |
| Inno Setup script | [build/installer.iss](../build/installer.iss) |
| User-facing docs | [README.md](../README.md) "Desktop App" section |
