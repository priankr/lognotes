#!/usr/bin/env python3
"""LogNotesController — the front-end-agnostic orchestrator.

Drives the recorder -> VAD -> Whisper -> grammar -> paste pipeline and talks to
whichever front end is attached (the Tk app or the Electron sidecar) only through
an injected UIBridge / ConfigStore / ActivityStore. No Tk imports here, so the
Electron sidecar can import it without pulling in Tkinter via the Tk entry point.

The stdout/stderr guards and cache redirect that must run before torch is
imported live in the entry points (main.py, sidecar.py), which import this module
after performing that bootstrap.
"""

import threading
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

from src.audio import AudioRecorder, VoiceActivityDetector
from src.audio.recorder import AudioBackendUnavailableError
from src.transcription import Transcriber, create_transcriber, get as get_model_spec, normalize_id
from src.transcription.registry import MODELS as _REGISTERED_MODELS
from src.processing import GrammarProcessor
from src.input import HotkeyListener, paste_text, copy_to_clipboard
from src.config import ConfigStore
from src.ui_bridge import UIBridge
from src.activity import ActivityStore


class LogNotesController:
    """Main controller that orchestrates all components."""

    GRAMMAR_AVAILABILITY_TTL_SEC = 30.0

    def __init__(self):
        # Core components
        self._recorder = AudioRecorder()
        self._vad = VoiceActivityDetector()
        self._transcriber: Optional[Transcriber] = None
        self._transcriber_model_id: Optional[str] = None
        # Cache of warmed, ready-to-use transcriber instances keyed by model id.
        # Populated eagerly on startup for Whisper sizes so retries in the
        # Activity tab don't pay the 2-5s model-load cost.
        self._warm_transcribers: dict[str, Transcriber] = {}
        self._warm_lock = threading.Lock()
        self._grammar: Optional[GrammarProcessor] = None
        self._grammar_available: Optional[bool] = None
        self._grammar_available_checked_at: float = 0.0
        self._hotkey: Optional[HotkeyListener] = None
        self._audio_error_notified = False

        # Front-end dependencies (injected via attach()). The controller talks
        # to the UI only through these, never into a Tk window directly.
        self._ui: Optional[UIBridge] = None
        self._config: Optional[ConfigStore] = None
        self._activity: Optional[ActivityStore] = None

        # Transient-status revert timer: after a successful transcription the
        # status shows "Transcribed" briefly, then settles back to "Ready".
        # Cancelled if a new recording/processing starts within the window.
        self._status_revert_timer: Optional[threading.Timer] = None

        # State
        self._processing_lock = threading.Lock()
        self._is_processing = False

    def _handle_audio_backend_error(self, error: Exception) -> None:
        """Report a missing or broken audio backend without crashing the app."""
        message = str(error)
        logger.error(message)

        if self._ui is not None:
            self._ui.set_status("ready", "Audio input unavailable")

        if self._ui is None or self._audio_error_notified:
            return

        self._audio_error_notified = True
        self._ui.show_audio_error(message)

    STATUS_REVERT_SEC = 5.0

    def _cancel_status_revert(self) -> None:
        """Cancel any pending revert-to-Ready timer."""
        if self._status_revert_timer is not None:
            self._status_revert_timer.cancel()
            self._status_revert_timer = None

    def _set_transient_status(self, message: str) -> None:
        """Show a transient ready-state message, then settle to 'Ready'.

        Used for the post-transcription confirmation so the status (and the
        overlay) don't get stuck on the success message.
        """
        self._cancel_status_revert()
        self._ui.set_status("ready", message)

        def _revert():
            # Only settle to Ready if nothing else changed the state since.
            self._status_revert_timer = None
            self._ui.set_status("ready", "Ready")

        self._status_revert_timer = threading.Timer(self.STATUS_REVERT_SEC, _revert)
        self._status_revert_timer.daemon = True
        self._status_revert_timer.start()

    def _init_transcriber(self, model_id: str):
        """Initialize or switch the active transcriber.

        Checks the warm cache first — if we've already loaded this model
        this session, reuse the instance (instant switch). Otherwise build
        a new one and stash it in the cache.
        """
        model_id = normalize_id(model_id)

        with self._warm_lock:
            cached = self._warm_transcribers.get(model_id)

        if cached is not None:
            self._transcriber = cached
            self._transcriber_model_id = model_id
            return

        transcriber = create_transcriber(model_id)
        with self._warm_lock:
            # Double-check — another thread may have warmed it in the meantime.
            existing = self._warm_transcribers.get(model_id)
            if existing is not None:
                transcriber = existing
            else:
                self._warm_transcribers[model_id] = transcriber

        self._transcriber = transcriber
        self._transcriber_model_id = model_id

    def _warm_other_models(self, primary_model_id: str):
        """Sequentially load every other registered Whisper model in the
        background so Activity-tab retries are instant.

        Runs after the primary model is ready. One model at a time to avoid
        thrashing RAM or stalling the primary path. Parakeet (if enabled by
        the user) is skipped — its download is large and loading is slow
        enough that we don't want it in an automatic warm-up.
        """
        for spec in _REGISTERED_MODELS:
            if spec.id == primary_model_id:
                continue
            if spec.backend != "whisper":
                continue
            with self._warm_lock:
                if spec.id in self._warm_transcribers:
                    continue
            try:
                logger.info(f"Warming model in background: {spec.id}")
                instance = create_transcriber(spec.id)
                if hasattr(instance, "load"):
                    instance.load()
                with self._warm_lock:
                    self._warm_transcribers.setdefault(spec.id, instance)
                logger.info(f"Warmed: {spec.id}")
            except Exception as e:
                logger.warning(f"Background warm-up failed for {spec.id}: {e}")

    def _init_grammar(self, model: str = "llama3.2:1b"):
        """Initialize the grammar processor."""
        if self._grammar is None:
            host = self._config.get("ollama_host")
            self._grammar = GrammarProcessor(model=model, host=host)
            self._grammar_available = None
            self._grammar_available_checked_at = 0.0

    def _grammar_is_available(self, force_refresh: bool = False) -> bool:
        """Check Ollama availability with a short-lived in-memory cache."""
        if self._grammar is None:
            return False

        now = time.perf_counter()
        should_refresh = (
            force_refresh
            or self._grammar_available is None
            or (now - self._grammar_available_checked_at) > self.GRAMMAR_AVAILABILITY_TTL_SEC
        )
        if not should_refresh:
            return bool(self._grammar_available)

        self._grammar_available = self._grammar.is_available()
        self._grammar_available_checked_at = now
        return bool(self._grammar_available)

    def _prepare_audio_for_model(self, audio, model_id: str):
        """Apply backend-specific pre-processing before transcription."""
        model_spec = get_model_spec(model_id)

        # faster-whisper already runs VAD internally in whisper.py.
        if model_spec.backend == "whisper":
            return audio

        self._ui.set_status("processing", "Filtering silence...")
        original_samples = len(audio)
        try:
            filtered = self._vad.filter_silence(audio)
            self._vad.reset()
            logger.info(
                f"VAD: {original_samples} samples in, "
                f"{len(filtered)} samples after silence filter "
                f"({len(filtered)/16000:.1f}s of speech)"
            )
            return filtered
        except Exception as e:
            logger.warning(f"VAD failed, using raw audio: {e}")
            return audio

    def _on_hotkey_press(self):
        """Handle hotkey press - start or stop recording depending on mode."""
        if self._is_processing:
            return

        # A new interaction supersedes any pending "Transcribed -> Ready" revert.
        self._cancel_status_revert()

        try:
            if self._config["push_to_talk_mode"] == "toggle":
                if self._recorder.is_recording:
                    self._stop_and_process()
                else:
                    self._ui.set_status("recording", "Recording...")
                    self._recorder.start()
            else:
                self._ui.set_status("recording", "Recording...")
                self._recorder.start()
        except AudioBackendUnavailableError as e:
            self._handle_audio_backend_error(e)

    def toggle_recording(self) -> None:
        """Public entry point for a UI-driven start/stop (toggle button / RPC).

        Same semantics as a hotkey press; front ends call this instead of
        reaching into the private handler.
        """
        self._on_hotkey_press()

    def _on_hotkey_release(self):
        """Handle hotkey release - stop recording and process (hold mode only)."""
        if self._config["push_to_talk_mode"] == "toggle":
            return  # Toggle mode handles stop on next press

        if not self._recorder.is_recording:
            return

        self._stop_and_process()

    def _stop_and_process(self):
        """Stop recording and kick off audio processing."""
        if not self._recorder.is_recording:
            return

        self._recorder.stop()
        self._ui.set_status("processing", "Processing...")

        # Process in background thread
        threading.Thread(target=self._process_audio, daemon=True).start()

    def _process_audio(self):
        """Process recorded audio through the pipeline.

        Uses sentence-boundary checkpoint pasting: segments are accumulated
        until a sentence boundary is detected, then cleaned and pasted
        immediately. This ensures partial results are not lost if an error
        occurs mid-transcription.
        """
        with self._processing_lock:
            if self._is_processing:
                return
            self._is_processing = True

        try:
            total_t0 = time.perf_counter()
            preprocess_ms = 0.0
            grammar_ms = 0.0
            paste_ms = 0.0
            self._ui.set_status("processing", "Processing audio...")

            # Get recorded audio
            capture_t0 = time.perf_counter()
            audio = self._recorder.get_audio()
            capture_ms = (time.perf_counter() - capture_t0) * 1000.0
            if len(audio) == 0:
                logger.info("No audio recorded")
                self._ui.set_status("ready", "No audio recorded")
                return

            # Keep a reference to raw audio for the Activity tab (session-scoped, in-memory only).
            retained_audio = audio
            model_id = normalize_id(self._config["whisper_model"])

            # Apply backend-specific pre-processing.
            preprocess_t0 = time.perf_counter()
            audio = self._prepare_audio_for_model(audio, model_id)
            preprocess_ms = (time.perf_counter() - preprocess_t0) * 1000.0

            if len(audio) == 0:
                logger.info("No speech detected after preprocessing")
                self._ui.set_status("ready", "No speech detected")
                return

            # Initialise components
            self._ui.set_status("processing", "Transcribing...")
            self._init_transcriber(model_id)
            grammar_enabled = self._config["enable_grammar"]
            grammar_available = False

            if grammar_enabled:
                self._init_grammar(self._config["ollama_model"])
                grammar_available = self._grammar_is_available()
                if not grammar_available:
                    logger.warning("Grammar cleanup enabled but Ollama is not available - skipping")

            # --- Checkpoint pasting ---
            # Accumulate Whisper segments into sentence-sized chunks, then
            # paste each chunk as soon as it ends at a sentence boundary.
            # This means partial output is saved even if processing fails later.
            SENTENCE_ENDINGS = ".?!"
            chunk_segments: list[str] = []
            chunks_pasted = 0
            total_chars = 0
            all_flushed: list[str] = []
            any_paste_failed = False

            logger.info("Starting segment-by-segment transcription")

            transcribe_t0 = time.perf_counter()
            for segment_text in self._transcriber.transcribe_segments(audio):
                chunk_segments.append(segment_text)
                combined = " ".join(chunk_segments)

                # Flush when the accumulated text ends at a sentence boundary
                if combined.rstrip() and combined.rstrip()[-1] in SENTENCE_ENDINGS:
                    grammar_t0 = time.perf_counter()
                    flushed = self._flush_chunk(
                        combined, grammar_enabled, grammar_available
                    )
                    grammar_ms += (time.perf_counter() - grammar_t0) * 1000.0
                    paste_t0 = time.perf_counter()
                    success = paste_text(flushed, clear_clipboard=False)
                    paste_ms += (time.perf_counter() - paste_t0) * 1000.0
                    all_flushed.append(flushed)
                    if success:
                        chunks_pasted += 1
                        total_chars += len(flushed)
                        logger.info(
                            f"Pasted chunk {chunks_pasted} "
                            f"({len(flushed)} chars)"
                        )
                    else:
                        any_paste_failed = True
                        logger.error(f"Failed to paste chunk {chunks_pasted + 1}")
                    chunk_segments = []

            # Flush any remaining segments that didn't end on a sentence boundary
            if chunk_segments:
                combined = " ".join(chunk_segments)
                grammar_t0 = time.perf_counter()
                flushed = self._flush_chunk(
                    combined, grammar_enabled, grammar_available
                )
                grammar_ms += (time.perf_counter() - grammar_t0) * 1000.0
                paste_t0 = time.perf_counter()
                success = paste_text(flushed, clear_clipboard=True)  # final chunk: clear clipboard
                paste_ms += (time.perf_counter() - paste_t0) * 1000.0
                all_flushed.append(flushed)
                if success:
                    chunks_pasted += 1
                    total_chars += len(flushed)
                    logger.info(
                        f"Pasted final chunk ({len(flushed)} chars)"
                    )
                else:
                    any_paste_failed = True
                    logger.error("Failed to paste final chunk")

            combined_text = " ".join(all_flushed).strip()
            transcribe_ms = (time.perf_counter() - transcribe_t0) * 1000.0

            if total_chars == 0:
                logger.info("No text transcribed from audio")
                self._ui.set_status("ready", "No text transcribed")
                self._record_activity(
                    retained_audio, combined_text,
                    grammar_enabled and grammar_available,
                    paste_succeeded=False,
                    error="No text transcribed",
                )
                return

            logger.info(
                f"Done - {total_chars} chars pasted in {chunks_pasted} chunk(s)"
            )
            logger.info(
                "Timing (ms): "
                f"capture={capture_ms:.0f}, preprocess={preprocess_ms:.0f}, "
                f"transcribe={transcribe_ms:.0f}, grammar={grammar_ms:.0f}, "
                f"paste={paste_ms:.0f}, total={(time.perf_counter() - total_t0) * 1000.0:.0f}, "
                f"model={model_id}"
            )
            self._set_transient_status("Transcribed")
            self._record_activity(
                retained_audio, combined_text,
                grammar_enabled and grammar_available,
                paste_succeeded=not any_paste_failed,
            )

        except Exception as e:
            logger.error(f"Processing error: {e}", exc_info=True)
            self._ui.set_status("ready", f"Error: {str(e)[:50]}")

        finally:
            self._is_processing = False

    def _flush_chunk(
        self,
        text: str,
        grammar_enabled: bool,
        grammar_available: bool
    ) -> str:
        """Apply grammar cleanup to a text chunk if enabled, else return as-is."""
        if not grammar_enabled or not grammar_available:
            return text
        try:
            self._ui.set_status("processing", "Fixing grammar...")
            cleaned = self._grammar.cleanup(text)
            logger.info(
                f"Grammar cleanup: {len(text)} -> {len(cleaned)} chars"
            )
            return cleaned
        except Exception as e:
            logger.warning(f"Grammar cleanup failed for chunk, using raw text: {e}")
            return text

    def _record_activity(
        self,
        audio,
        text: str,
        grammar_applied: bool,
        paste_succeeded: bool,
        error: Optional[str] = None,
    ):
        """Push a completed transcription into the activity store."""
        try:
            self._activity.add(
                audio=audio,
                text=text,
                whisper_model=self._config["whisper_model"],
                grammar_applied=grammar_applied,
                paste_succeeded=paste_succeeded,
                error=error,
            )
        except Exception as e:
            logger.warning(f"Failed to record activity entry: {e}")

    def is_busy(self) -> bool:
        """True while recording or processing — used to gate retries."""
        return self._is_processing or self._recorder.is_recording

    def retry_transcription(self, entry_id: int, model: str):
        """Re-run transcription on a stored entry using a (possibly different) model.

        Runs in a background thread. Updates the entry text in the store and
        copies the new text to the clipboard. Does NOT paste — user chooses
        where the text goes.
        """
        if self.is_busy():
            logger.warning(
                f"Retry blocked — app busy "
                f"(processing={self._is_processing}, recording={self._recorder.is_recording})"
            )
            return

        entry = self._activity.get(entry_id)
        if entry is None:
            logger.warning(f"Retry: entry {entry_id} not found")
            return
        logger.info(f"Retry starting: entry {entry_id}, model '{model}' (may take a while if model not yet downloaded)")

        threading.Thread(
            target=self._run_retry, args=(entry_id, model), daemon=True,
        ).start()

    def _run_retry(self, entry_id: int, model: str):
        with self._processing_lock:
            if self._is_processing:
                logger.info("Retry aborted — processing started elsewhere")
                return
            self._is_processing = True

        try:
            entry = self._activity.get(entry_id)
            if entry is None:
                return

            self._ui.set_status("processing", f"Retrying with {model}...")
            model_id = normalize_id(model)
            try:
                self._init_transcriber(model_id)
            except Exception as e:
                logger.error(f"Retry: failed to load model '{model}': {e}")
                self._activity.update(
                    entry_id, error=f"Model load failed: {e}",
                )
                self._ui.set_status("ready", f"Retry failed: {model} unavailable")
                return

            parts: list[str] = []
            try:
                audio = self._prepare_audio_for_model(entry.audio, model_id)
                if len(audio) == 0:
                    self._activity.update(entry_id, error="No speech detected")
                    self._ui.set_status("ready", "Retry found no speech")
                    return
                for seg in self._transcriber.transcribe_segments(audio):
                    parts.append(seg)
            except Exception as e:
                logger.error(f"Retry: transcription failed: {e}")
                self._activity.update(entry_id, error=f"Transcription failed: {e}")
                self._ui.set_status("ready", "Retry failed")
                return

            new_text = " ".join(parts).strip()

            if entry.grammar_applied and self._grammar and self._grammar_is_available():
                try:
                    new_text = self._grammar.cleanup(new_text)
                except Exception as e:
                    logger.warning(f"Retry: grammar cleanup failed: {e}")

            self._activity.update(
                entry_id, text=new_text, whisper_model=model_id, error=None,
            )

            if new_text:
                copy_to_clipboard(new_text)

            self._ui.set_status("ready", f"Retry done ({model_id}) - copied")
            logger.info(f"Retry complete: entry {entry_id}, model {model_id}, {len(new_text)} chars")

            # Restore the user's configured model for live dictation
            configured = self._config["whisper_model"]
            if configured != model_id:
                try:
                    self._init_transcriber(configured)
                except Exception as e:
                    logger.warning(f"Could not restore model to {configured}: {e}")
        finally:
            self._is_processing = False

    def _on_hotkey_changed(self, new_hotkey: str):
        """Handle hotkey change from UI."""
        if self._hotkey:
            self._hotkey.update_hotkey(new_hotkey)
            logger.info(f"Hotkey updated to: {new_hotkey}")

    def _on_model_changed(self, new_model: str):
        """Handle transcription model change from UI."""
        logger.info(f"Transcription model will change to: {new_model}")
        try:
            self._init_transcriber(new_model)
        except Exception as e:
            logger.warning(f"Could not pre-initialize model '{new_model}': {e}")

    def _on_grammar_toggled(self, enabled: bool):
        """Handle grammar toggle from UI."""
        if not enabled:
            return
        try:
            self._init_grammar(self._config["ollama_model"])
            self._grammar_is_available(force_refresh=True)
        except Exception as e:
            logger.warning(f"Could not initialize grammar after toggle: {e}")

    def _on_theme_changed(self, theme: str):
        """Handle theme change from UI."""
        pass  # Will apply on restart

    def _on_push_to_talk_mode_changed(self, mode: str):
        """Handle push-to-talk mode change from UI."""
        pass  # Config is already saved by UI

    def attach(self, ui: UIBridge, config: ConfigStore, activity: ActivityStore) -> None:
        """Inject the front-end dependencies.

        The controller talks to the UI only through these (a UIBridge, a
        ConfigStore, an ActivityStore) so it has no direct Tk coupling. Any
        front end — the Tk app or the headless sidecar — wires itself in here.
        """
        self._ui = ui
        self._config = config
        self._activity = activity

    def start_runtime(self) -> None:
        """Start hotkey capture and background model preload.

        Front-end agnostic: assumes ``attach()`` has been called. Both the Tk
        ``run()`` and the sidecar call this to bring the capture pipeline up.
        """
        if self._ui is None or self._config is None:
            raise RuntimeError("start_runtime() called before attach()")

        if not self._recorder.is_available and self._recorder.availability_error:
            self._handle_audio_backend_error(
                AudioBackendUnavailableError(self._recorder.availability_error)
            )

        # Set up hotkey listener.
        # In toggle mode, both press and release trigger the same action.
        if self._config["push_to_talk_mode"] == "toggle":
            self._hotkey = HotkeyListener(
                hotkey=self._config["hotkey"],
                on_press=self._on_hotkey_press,
                on_release=lambda: None,  # Ignore release in toggle mode
                debug=False
            )
        else:
            self._hotkey = HotkeyListener(
                hotkey=self._config["hotkey"],
                on_press=self._on_hotkey_press,
                on_release=self._on_hotkey_release,
                debug=False
            )
        self._hotkey.start()

        # Pre-load models in background (optional, improves first-use latency).
        # Phase 1: load the configured model + grammar so live capture is ready.
        # Phase 2: warm the remaining Whisper sizes so Activity-tab retries with
        # a different model don't pay the cold-load cost.
        def preload():
            primary_id = normalize_id(self._config["whisper_model"])
            try:
                self._ui.set_status("processing", "Loading models...")
                self._init_transcriber(primary_id)
                # Actually load the WhisperModel into memory now so the first
                # transcription doesn't pay the 5-8s cold-load cost.
                if hasattr(self._transcriber, "load"):
                    self._transcriber.load()
                self._init_grammar(self._config["ollama_model"])
                self._grammar_is_available(force_refresh=True)
                self._ui.set_status("ready", "Ready")
            except Exception as e:
                logger.warning(f"Preload warning: {e}")
                self._ui.set_status("ready", "Ready (models will load on first use)")

            self._warm_other_models(primary_id)

        threading.Thread(target=preload, daemon=True).start()

    def shutdown(self) -> None:
        """Stop the hotkey listener and release the audio device."""
        self._cancel_status_revert()
        if self._hotkey is not None:
            self._hotkey.stop()
        self._recorder.close()

