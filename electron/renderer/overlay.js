// Overlay window: connects to the sidecar and reflects live status as a small
// always-on-top pill. Right-click cycles the corner (persisted via setConfig).

const dot = document.getElementById('dot');
const label = document.getElementById('label');
const pill = document.getElementById('pill');

let ws = null;
let nextId = 1;
const pending = new Map();

const LABELS = {
  ready: 'Ready',
  recording: 'Recording',
  processing: 'Processing',
  error: 'Error',
};
const CORNERS = ['top-left', 'top-right', 'bottom-right', 'bottom-left'];
let currentCorner = 'bottom-right';

function request(method, params = {}) {
  return new Promise((resolve, reject) => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      reject(new Error('not connected'));
      return;
    }
    const id = nextId++;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
}

// The overlay shows only the canonical short state label (Ready / Recording /
// Processing), never the verbose status message. Detail like "models will load
// on first use" belongs in the in-window status box, not the pinned pill.
function setState(state) {
  dot.setAttribute('data-state', state);
  label.textContent = LABELS[state] || state;
}

function handle(msg) {
  if (msg.id != null && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    if ('error' in msg) reject(new Error(msg.error));
    else resolve(msg.result);
    return;
  }
  if (msg.event === 'ready') {
    setState(msg.data.status || 'ready');
  } else if (msg.event === 'status') {
    setState(msg.data.status);
  } else if (msg.event === 'audioError') {
    setState('error');
  } else if (msg.event === 'configChanged' && msg.data.key === 'overlay_corner') {
    currentCorner = msg.data.value;
    window.lognotes.setOverlayCorner(currentCorner);
  }
}

// Right-click cycles the corner: persist via setConfig (which emits
// configChanged), and ask main to reposition immediately.
pill.addEventListener('contextmenu', (e) => {
  e.preventDefault();
  const idx = CORNERS.indexOf(currentCorner);
  const next = CORNERS[(idx + 1) % CORNERS.length];
  currentCorner = next;
  window.lognotes.setOverlayCorner(next);
  request('setConfig', { key: 'overlay_corner', value: next }).catch(() => {});
});

// The port may not exist yet on a cold launch (main shows windows before the
// sidecar finishes starting). Poll until it does instead of erroring out.
async function waitForPort(timeoutMs = 120000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const port = await window.lognotes.getSidecarPort();
    if (port) return port;
    await new Promise((r) => setTimeout(r, 500));
  }
  return null;
}

async function connect() {
  const port = await waitForPort();
  if (!port) {
    setState('error');
    return;
  }
  ws = new WebSocket(`ws://127.0.0.1:${port}`);
  ws.onopen = async () => {
    try {
      const cfg = await request('getConfig');
      if (cfg && cfg.overlay_corner) {
        currentCorner = cfg.overlay_corner;
        window.lognotes.setOverlayCorner(currentCorner);
      }
    } catch { /* keep default corner */ }
  };
  ws.onmessage = (ev) => {
    try { handle(JSON.parse(ev.data)); } catch { /* ignore */ }
  };
  ws.onclose = () => setState('error');
}

window.lognotes.onSidecarDown(() => setState('error'));
connect();
