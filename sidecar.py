#!/usr/bin/env python3
"""LogNotes headless sidecar.

Runs the full capture pipeline (hotkey -> recorder -> Whisper -> paste) with no
UI, exposing a small JSON-over-WebSocket API on loopback so an
Electron front end can drive it and receive pushed status/activity events.

This is the back-end half of the app; the Electron front end is the client.
The legacy Tk app (main.py) runs standalone and shares LogNotesController.

Protocol (newline framing not needed — WebSocket is message-framed):
  Request:  {"id": <int>, "method": <str>, "params": {...}}
  Response: {"id": <int>, "result": <any>}  |  {"id": <int>, "error": <str>}
  Event:    {"event": <str>, "data": {...}}   (server -> client, unsolicited)

Bind is 127.0.0.1 on an ephemeral port; the chosen port is printed as a
`PORT <n>` line on stdout so a parent process (Electron) can read it.
"""

import io
import os
import sys
import asyncio
import json
import logging
import threading
import time
from collections import deque
from typing import Any, Optional

# Same --noconsole stdout/stderr guards as main.py: libraries (torch.hub, tqdm)
# call sys.stdout.write() and crash if it is None under a windowed frozen build.
# We keep the *real* stdout for the PORT handshake line below, then guard.
_real_stdout = sys.stdout
if sys.stdout is None:
    sys.stdout = io.StringIO()
    _real_stdout = sys.stdout
if sys.stderr is None:
    sys.stderr = io.StringIO()

# Redirect model caches into the user cache dir BEFORE importing torch/whisper.
from src.paths import user_cache_dir

_cache = user_cache_dir()
os.environ.setdefault("HF_HOME", str(_cache / "hf"))
os.environ.setdefault("TORCH_HOME", str(_cache / "torch"))
# huggingface_hub defaults to symlinking blobs into the snapshot dir, which on
# Windows needs Developer Mode or admin (else WinError 1314). Force copies so
# any HuggingFace model download works on a standard user account.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# Use the OS certificate store (Windows) for TLS so model downloads work behind
# corporate SSL-inspection proxies, whose CA is trusted by the OS but not by
# certifi's bundle. Must run before requests/huggingface_hub import. Best-effort:
# a stock network is unaffected, and a failure here must not block startup.
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

logger = logging.getLogger(__name__)

import websockets

from src.controller import LogNotesController
from src.config import ConfigStore, validate_value as config_validate_value
from src.activity import ActivityStore, ActivityEntry
from src.transcription import MODELS as TRANSCRIPTION_MODELS


def _entry_to_dict(entry: ActivityEntry) -> dict:
    """Serialize an ActivityEntry for the wire — metadata + text only.

    Privacy: the raw audio (np.ndarray) is never serialized. It stays in the
    sidecar's RAM, exactly as in the Tk app.
    """
    return {
        "id": entry.id,
        "timestamp": entry.timestamp.isoformat(),
        "text": entry.text,
        "whisper_model": entry.whisper_model,
        "paste_succeeded": entry.paste_succeeded,
        "error": entry.error,
        "duration_seconds": round(entry.duration_seconds, 2),
    }


class _LogBroadcastHandler(logging.Handler):
    """Logging handler that streams records to clients as `logLine` events.

    Mirrors the Tk app's _LogHandler (timestamp + level + name + message) but
    pushes over the WebSocket instead of a ScrolledText widget. A re-entrancy
    guard prevents a log emitted while broadcasting from looping back in.
    """

    def __init__(self, server: "SidecarServer"):
        super().__init__()
        self._server = server
        self._emitting = False
        self.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
            datefmt="%H:%M:%S",
        ))

    def emit(self, record: logging.LogRecord) -> None:
        if self._emitting:
            return
        self._emitting = True
        try:
            line = {"text": self.format(record), "level": record.levelname.lower()}
            self._server.record_log(line)
            self._server.broadcast_event("logLine", line)
        except Exception:
            pass  # never let logging crash the app
        finally:
            self._emitting = False


class HeadlessBridge:
    """UIBridge implementation that forwards UI calls as WebSocket events.

    The controller calls these from background threads (pynput, preload,
    processing), so each forwards onto the asyncio loop thread-safely.
    """

    def __init__(self, server: "SidecarServer"):
        self._server = server
        self.status: str = "ready"
        self.status_message: str = "Ready"

    def set_status(self, status: str, message: Optional[str] = None) -> None:
        default_messages = {
            "ready": "Ready",
            "recording": "Recording...",
            "processing": "Processing...",
        }
        display_message = message or default_messages.get(status, status)
        self.status = status
        self.status_message = display_message
        self._server.broadcast_event(
            "status", {"status": status, "message": display_message}
        )

    def show_audio_error(self, message: str) -> None:
        self._server.broadcast_event("audioError", {"message": message})


class SidecarServer:
    """Owns the controller + stores and serves the WebSocket API."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self._host = host
        self._port = port
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._clients: set = set()

        self._controller = LogNotesController()
        self._config = ConfigStore()  # loads + validates from disk
        self._activity = ActivityStore()
        self._bridge = HeadlessBridge(self)

        # Bounded log history so a client that connects later still sees recent
        # lines (the Tk app kept them in the ScrolledText widget).
        self._log_buffer: deque = deque(maxlen=500)
        self._log_handler = _LogBroadcastHandler(self)

        # Forward config + activity changes to clients.
        self._config.subscribe(self._on_config_change)
        self._activity.subscribe(self._on_activity_change)

    # ----------------------------- lifecycle ----------------------------- #

    def record_log(self, line: dict) -> None:
        """Append a formatted log line to the bounded history buffer."""
        self._log_buffer.append(line)

    async def serve(self) -> None:
        self._loop = asyncio.get_running_loop()

        # Stream all logs to clients. Attach to the root logger so every module
        # is captured (same scope as the Tk _LogHandler).
        root = logging.getLogger()
        root.addHandler(self._log_handler)
        if root.level > logging.INFO or root.level == logging.NOTSET:
            root.setLevel(logging.INFO)

        # Wire the controller to this headless front end and bring the pipeline
        # up. start_runtime() spawns its own threads (hotkey, preload).
        self._controller.attach(self._bridge, self._config, self._activity)
        # LOGNOTES_SIDECAR_NO_RUNTIME lets protocol tests exercise the API
        # without grabbing the global hotkey or loading multi-GB ASR models.
        if os.environ.get("LOGNOTES_SIDECAR_NO_RUNTIME") != "1":
            self._controller.start_runtime()
        else:
            logger.info("Runtime start skipped (LOGNOTES_SIDECAR_NO_RUNTIME=1)")

        async with websockets.serve(self._handle_client, self._host, self._port) as server:
            # Discover the actual bound port (the OS picks one when port=0) and
            # hand it to the parent process.
            bound = self._bound_port(server)
            self._port = bound
            self._announce_port(bound)
            logger.info(f"Sidecar listening on ws://{self._host}:{bound}")
            await asyncio.Future()  # run forever

    @staticmethod
    def _bound_port(server) -> int:
        """Read the actual listening port from the server's bound socket."""
        for sock in server.sockets:
            addr = sock.getsockname()
            # IPv4: (host, port); IPv6: (host, port, flowinfo, scopeid)
            if len(addr) >= 2:
                return addr[1]
        raise RuntimeError("could not determine bound port")

    def _announce_port(self, port: int) -> None:
        try:
            _real_stdout.write(f"PORT {port}\n")
            _real_stdout.flush()
        except Exception:
            pass

    # ----------------------------- client I/O ---------------------------- #

    async def _handle_client(self, websocket) -> None:
        self._clients.add(websocket)
        # On connect, push a snapshot so the UI renders current state.
        await self._send(websocket, {
            "event": "ready",
            "data": {
                "status": self._bridge.status,
                "message": self._bridge.status_message,
            },
        })
        try:
            async for raw in websocket:
                await self._on_message(websocket, raw)
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)

    async def _on_message(self, websocket, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await self._send(websocket, {"id": None, "error": "invalid JSON"})
            return

        req_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}

        try:
            result = await self._dispatch(method, params)
            await self._send(websocket, {"id": req_id, "result": result})
        except Exception as e:
            logger.warning(f"Method '{method}' failed: {e}")
            await self._send(websocket, {"id": req_id, "error": str(e)})

    async def _dispatch(self, method: str, params: dict) -> Any:
        """Map an RPC method to a controller/store action.

        Blocking calls (retry kicks off a background thread itself, so these
        are all fast) run inline on the loop.
        """
        if method == "getConfig":
            return self._config.as_dict()

        if method == "setConfig":
            key = params["key"]
            value = params["value"]
            # Validate before persisting — the Tk widgets enforced this by
            # construction; over RPC we must check explicitly.
            is_valid, normalized = config_validate_value(key, value)
            if not is_valid:
                raise ValueError(f"invalid value for '{key}': {value!r}")
            self._config.set(key, normalized)
            # Live-apply the same controller hooks the Tk UI triggers.
            self._apply_config_side_effects(key, normalized)
            return {"ok": True, "value": normalized}

        if method == "getModels":
            return [{"id": m.id, "display": m.display} for m in TRANSCRIPTION_MODELS]

        if method == "getActivity":
            return [_entry_to_dict(e) for e in self._activity.entries_newest_first()]

        if method == "retryTranscription":
            self._controller.retry_transcription(params["id"], params["model"])
            return {"started": True}

        if method == "deleteActivity":
            self._activity.delete(params["id"])
            return {"ok": True}

        if method == "clearActivity":
            self._activity.clear()
            return {"ok": True}

        if method == "toggleRecording":
            self._controller.toggle_recording()
            return {"ok": True}

        if method == "isBusy":
            return {"busy": self._controller.is_busy()}

        if method == "getLogs":
            return list(self._log_buffer)

        if method == "clearLogs":
            self._log_buffer.clear()
            return {"ok": True}

        if method == "_injectTestActivity":
            # Test-only: add a fake entry so the Activity UI can be exercised
            # headlessly without audio/models. Gated to NO_RUNTIME mode so it is
            # never reachable in a real run.
            if os.environ.get("LOGNOTES_SIDECAR_NO_RUNTIME") != "1":
                raise ValueError("test method not available")
            import numpy as np
            entry = self._activity.add(
                audio=np.zeros(int(16000 * float(params.get("seconds", 1.0))), dtype="float32"),
                text=params.get("text", "test transcription"),
                whisper_model=params.get("model", "whisper-base"),
                paste_succeeded=True,
            )
            return {"id": entry.id}

        raise ValueError(f"unknown method: {method}")

    def _apply_config_side_effects(self, key: str, value: Any) -> None:
        """Re-run the controller hooks that a setting change should trigger.

        Mirrors the on_*_changed callbacks the Tk UI wires up so behavior is
        identical regardless of front end.
        """
        if key == "hotkey":
            self._controller._on_hotkey_changed(value)
        elif key == "whisper_model":
            self._controller._on_model_changed(value)

    # ----------------------------- broadcast ----------------------------- #

    def broadcast_event(self, event: str, data: dict) -> None:
        """Push an event to all clients. Safe to call from any thread."""
        if self._loop is None:
            return
        message = {"event": event, "data": data}
        self._loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(self._broadcast(message))
        )

    async def _broadcast(self, message: dict) -> None:
        if not self._clients:
            return
        payload = json.dumps(message)
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def _send(self, websocket, message: dict) -> None:
        await websocket.send(json.dumps(message))

    # --------------------------- change hooks ---------------------------- #

    def _on_config_change(self, key: str, value: Any) -> None:
        self.broadcast_event("configChanged", {"key": key, "value": value})

    def _on_activity_change(self) -> None:
        # The store does not say what changed; send the current snapshot.
        self.broadcast_event(
            "activityChanged",
            {"entries": [_entry_to_dict(e) for e in self._activity.entries_newest_first()]},
        )

    def shutdown(self) -> None:
        self._controller.shutdown()


def _start_parent_watchdog() -> None:
    """Exit the sidecar if the parent (Electron) process disappears.

    The Electron main process kills the sidecar on every graceful exit path, but
    if it is *hard*-killed (Task Manager, OS, crash) no JS handler runs and the
    sidecar would be orphaned — holding its WebSocket port and breaking the next
    launch's handshake. This watchdog polls the parent PID and self-terminates
    when it is gone, guaranteeing no orphan regardless of how the parent dies.

    Activated only when LOGNOTES_PARENT_PID is set (i.e. spawned by Electron);
    a headless `python sidecar.py` run is unaffected.
    """
    raw = os.environ.get("LOGNOTES_PARENT_PID")
    if not raw:
        return
    try:
        parent_pid = int(raw)
    except ValueError:
        return

    def _alive(pid: int) -> bool:
        if sys.platform == "win32":
            # os.kill(pid, 0) is unreliable on Windows; query the process list.
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            h = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if not h:
                return False
            try:
                code = ctypes.c_ulong()
                if not ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
                    return False
                return code.value == STILL_ACTIVE
            finally:
                ctypes.windll.kernel32.CloseHandle(h)
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _watch() -> None:
        while True:
            time.sleep(2.0)
            if not _alive(parent_pid):
                logging.getLogger(__name__).info(
                    "Parent process %s gone — sidecar exiting.", parent_pid
                )
                os._exit(0)

    threading.Thread(target=_watch, daemon=True).start()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    host = os.environ.get("LOGNOTES_SIDECAR_HOST", "127.0.0.1")
    port = int(os.environ.get("LOGNOTES_SIDECAR_PORT", "0"))

    _start_parent_watchdog()

    server = SidecarServer(host=host, port=port)
    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
