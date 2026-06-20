// Preload bridge: the only surface exposed to the renderer.
//
// contextIsolation is on and nodeIntegration is off, so the renderer has no
// direct Node access. We expose a minimal, explicit API: get the sidecar port
// and signal readiness. The renderer opens the WebSocket itself (browsers have
// native WebSocket), keeping this bridge tiny.

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('lognotes', {
  getSidecarPort: () => ipcRenderer.invoke('get-sidecar-port'),
  signalReady: () => ipcRenderer.send('renderer-ready'),
  onSidecarDown: (cb) => {
    ipcRenderer.on('sidecar-down', () => cb());
  },
  // Overlay: ask main to reposition the overlay window to a named corner.
  setOverlayCorner: (corner) => ipcRenderer.send('overlay-set-corner', corner),
});
