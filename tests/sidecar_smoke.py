"""Manual end-to-end smoke test for the sidecar WebSocket protocol.

Launches sidecar.py with the runtime disabled (no hotkey grab, no model load),
connects as a client, and exercises the request/response + event protocol.

Run: venv\\Scripts\\python.exe tests\\sidecar_smoke.py
Exits non-zero on any assertion failure.
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import websockets

_ROOT = Path(__file__).resolve().parent.parent
PORT = 8779  # fixed port for the test


async def _request(ws, req_id, method, params=None):
    await ws.send(json.dumps({"id": req_id, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(await ws.recv())
        # Skip unsolicited events; wait for our response id.
        if msg.get("id") == req_id:
            return msg


async def run_client():
    uri = f"ws://127.0.0.1:{PORT}"
    async with websockets.connect(uri) as ws:
        # First frame on connect should be the "ready" event snapshot.
        first = json.loads(await ws.recv())
        assert first.get("event") == "ready", f"expected ready event, got {first}"
        print("ready event OK:", first["data"])

        # getConfig
        r = await _request(ws, 1, "getConfig")
        assert "result" in r, r
        assert "whisper_model" in r["result"], r["result"]
        print("getConfig OK:", r["result"]["whisper_model"])

        # getModels
        r = await _request(ws, 2, "getModels")
        models = r["result"]
        assert isinstance(models, list) and models, models
        assert "id" in models[0] and "display" in models[0], models[0]
        print("getModels OK:", [m["id"] for m in models])

        # getActivity (empty at start)
        r = await _request(ws, 3, "getActivity")
        assert r["result"] == [], r["result"]
        print("getActivity OK (empty)")

        # isBusy
        r = await _request(ws, 4, "isBusy")
        assert r["result"] == {"busy": False}, r["result"]
        print("isBusy OK:", r["result"])

        # setConfig round-trips + emits a configChanged event
        r = await _request(ws, 5, "setConfig", {"key": "overlay_corner", "value": "top-left"})
        assert r["result"]["ok"] is True, r["result"]
        assert r["result"]["value"] == "top-left", r["result"]
        r = await _request(ws, 6, "getConfig")
        assert r["result"]["overlay_corner"] == "top-left", r["result"]
        print("setConfig round-trip OK")

        # unknown method -> error response
        r = await _request(ws, 7, "bogusMethod")
        assert "error" in r and "unknown method" in r["error"], r
        print("unknown-method error OK:", r["error"])

        # setConfig with an invalid value -> error (server-side validation)
        r = await _request(ws, 9, "setConfig", {"key": "theme", "value": "purple"})
        assert "error" in r and "invalid value" in r["error"], r
        print("setConfig validation OK:", r["error"])

        # configChanged event is pushed unsolicited after a setConfig. Trigger
        # another change and confirm the event arrives (drains the broadcast
        # path, including the loop's call_soon_threadsafe hop on the server).
        await ws.send(json.dumps({"id": 8, "method": "setConfig",
                                  "params": {"key": "theme", "value": "light"}}))
        got_event = False
        for _ in range(10):
            msg = json.loads(await ws.recv())
            if msg.get("event") == "configChanged" and msg["data"]["key"] == "theme":
                got_event = True
                break
        assert got_event, "did not receive configChanged event"
        print("configChanged event OK")

        # Inject a test activity entry -> should emit activityChanged and show
        # up in getActivity. Exercises the activity event broadcast path.
        r = await _request(ws, 10, "_injectTestActivity", {"text": "smoke entry"})
        new_id = r["result"]["id"]
        got_activity_event = False
        for _ in range(10):
            msg = json.loads(await ws.recv())
            if msg.get("event") == "activityChanged":
                ids = [e["id"] for e in msg["data"]["entries"]]
                if new_id in ids:
                    got_activity_event = True
                    break
        assert got_activity_event, "did not receive activityChanged event"
        r = await _request(ws, 11, "getActivity")
        assert any(e["id"] == new_id for e in r["result"]), r["result"]
        print("activity inject + activityChanged event OK")

        # getLogs returns the startup buffer; each entry has text + level.
        r = await _request(ws, 12, "getLogs")
        logs = r["result"]
        assert isinstance(logs, list) and logs, "getLogs should be non-empty"
        assert "text" in logs[0] and "level" in logs[0], logs[0]
        print(f"getLogs OK ({len(logs)} lines)")

    print("\nALL SIDECAR PROTOCOL CHECKS PASSED")


async def main():
    tmpdir = tempfile.TemporaryDirectory()
    env = dict(os.environ)
    env["LOGNOTES_SIDECAR_NO_RUNTIME"] = "1"
    env["LOGNOTES_SIDECAR_PORT"] = str(PORT)
    # Isolate config so setConfig calls below never touch the real user config.
    env["LOGNOTES_CONFIG_FILE"] = os.path.join(tmpdir.name, "config.json")

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "sidecar.py",
        cwd=str(_ROOT), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )

    # Wait for the PORT handshake line so we know it is listening.
    try:
        for _ in range(200):  # up to ~20s for cold imports (torch)
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
            if not line:
                break
            text = line.decode(errors="replace").strip()
            if text.startswith("PORT "):
                print("sidecar announced:", text)
                break
        else:
            raise RuntimeError("sidecar never announced PORT")

        await run_client()
        return 0
    finally:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
        tmpdir.cleanup()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
