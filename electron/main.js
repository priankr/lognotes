// Electron main process for LogNotes.
//
// Responsibilities (Phase 2 skeleton):
//   - spawn the Python sidecar and supervise its lifecycle
//   - read the `PORT <n>` handshake line from the sidecar's stdout
//   - hand that port to the renderer so it can open the WebSocket
//   - show the window only once the sidecar is up
//
// The renderer never spawns processes or talks to the sidecar directly; it
// goes through the preload bridge and IPC defined here.

const { app, BrowserWindow, ipcMain, screen, session, Tray, Menu, nativeImage } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const readline = require('readline');

// Windows ties taskbar grouping + pinned-shortcut identity to the AppUserModelID,
// which must match the installer's appId. Without it, a running window shows the
// generic Electron icon and a pinned shortcut can't activate the live instance.
const APP_USER_MODEL_ID = 'com.lognotes.app';
if (process.platform === 'win32') {
  app.setAppUserModelId(APP_USER_MODEL_ID);
}

// Single-instance: a second launch (e.g. clicking the pinned shortcut while the
// app is already running, possibly hidden to tray) must focus the existing
// window, not spin up another Electron + sidecar.
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
}

let mainWindow = null;
let overlayWindow = null;
let tray = null;
let isQuitting = false;
let sidecarProc = null;
let sidecarPort = null;

const OVERLAY_W = 132;
const OVERLAY_H = 38;
const OVERLAY_MARGIN = 12;

// ----------------------------------------------------------------------------
// Sidecar resolution
// ----------------------------------------------------------------------------

// In dev we run the sidecar from source via the project venv. When packaged
// (Phase 3) this will resolve to the bundled sidecar.exe under resourcesPath.
function resolveSidecarCommand() {
  const projectRoot = path.resolve(__dirname, '..');

  if (app.isPackaged) {
    // electron-builder bundles dist/LogNotes/ as an extraResource under
    // resources/sidecar/ (see electron/package.json build.extraResources).
    const exe = path.join(process.resourcesPath, 'sidecar', 'LogNotes.exe');
    return { command: exe, args: [], cwd: path.dirname(exe) };
  }

  // Dev: prefer the venv python so torch/whisper resolve.
  const venvPy = process.platform === 'win32'
    ? path.join(projectRoot, 'venv', 'Scripts', 'python.exe')
    : path.join(projectRoot, 'venv', 'bin', 'python');
  const python = fs.existsSync(venvPy) ? venvPy : 'python';

  return {
    command: python,
    args: [path.join(projectRoot, 'sidecar.py')],
    cwd: projectRoot,
  };
}

function startSidecar() {
  return new Promise((resolve, reject) => {
    const { command, args, cwd } = resolveSidecarCommand();
    console.log(`[main] spawning sidecar: ${command} ${args.join(' ')}`);

    sidecarProc = spawn(command, args, {
      cwd,
      env: { ...process.env, LOGNOTES_SIDECAR_PORT: '0' },
    });

    let settled = false;

    // Parse stdout line-by-line for the PORT handshake.
    const rl = readline.createInterface({ input: sidecarProc.stdout });
    rl.on('line', (line) => {
      const text = line.trim();
      if (text.startsWith('PORT ')) {
        sidecarPort = parseInt(text.slice(5), 10);
        console.log(`[main] sidecar announced port ${sidecarPort}`);
        if (!settled) {
          settled = true;
          resolve(sidecarPort);
        }
      } else if (text) {
        console.log(`[sidecar] ${text}`);
      }
    });

    sidecarProc.stderr.on('data', (d) => {
      process.stderr.write(`[sidecar:err] ${d}`);
    });

    sidecarProc.on('error', (err) => {
      if (!settled) {
        settled = true;
        reject(err);
      }
    });

    sidecarProc.on('exit', (code) => {
      console.log(`[main] sidecar exited with code ${code}`);
      sidecarProc = null;
      if (!settled) {
        settled = true;
        reject(new Error(`sidecar exited before handshake (code ${code})`));
      }
      // If the sidecar dies while running, tear the app down — the UI is
      // useless without it. Phase 2+ may add restart/backoff here.
      if (mainWindow) {
        mainWindow.webContents.send('sidecar-down');
      }
    });

    // Safety net: don't hang forever if the handshake never arrives.
    setTimeout(() => {
      if (!settled) {
        settled = true;
        reject(new Error('timed out waiting for sidecar handshake'));
      }
    }, 60000);
  });
}

function stopSidecar() {
  if (sidecarProc) {
    sidecarProc.kill();
    sidecarProc = null;
  }
}

// ----------------------------------------------------------------------------
// Window
// ----------------------------------------------------------------------------

function createWindow() {
  const iconPath = appIconPath();
  mainWindow = new BrowserWindow({
    width: 500,
    height: 750,
    resizable: false,
    show: false, // shown after the renderer signals it has connected
    icon: iconPath || undefined,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  // Closing the window hides to tray instead of quitting, so the global hotkey
  // keeps working in the background (matches the Tk app). Quit is explicit via
  // the tray menu.
  mainWindow.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ----------------------------------------------------------------------------
// Overlay (floating status pill)
// ----------------------------------------------------------------------------

function overlayPosition(corner) {
  const wa = screen.getPrimaryDisplay().workArea; // excludes taskbar
  const right = wa.x + wa.width - OVERLAY_W - OVERLAY_MARGIN;
  const bottom = wa.y + wa.height - OVERLAY_H - OVERLAY_MARGIN;
  const left = wa.x + OVERLAY_MARGIN;
  const top = wa.y + OVERLAY_MARGIN;
  switch (corner) {
    case 'top-left': return { x: left, y: top };
    case 'top-right': return { x: right, y: top };
    case 'bottom-left': return { x: left, y: bottom };
    default: return { x: right, y: bottom }; // bottom-right
  }
}

function createOverlay(corner = 'bottom-right') {
  const { x, y } = overlayPosition(corner);
  overlayWindow = new BrowserWindow({
    width: OVERLAY_W,
    height: OVERLAY_H,
    x, y,
    frame: false,
    transparent: true,
    resizable: false,
    movable: true,
    skipTaskbar: true,
    alwaysOnTop: true,
    focusable: false,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  overlayWindow.setAlwaysOnTop(true, 'screen-saver');
  overlayWindow.loadFile(path.join(__dirname, 'renderer', 'overlay.html'));

  // Show the overlay as soon as its content has loaded (it displays
  // "Starting..." until its own sidecar connection is up). showInactive() keeps
  // it from stealing focus from whatever the user is typing into. Showing on its
  // own load rather than the main window's handshake means it appears reliably
  // even if the main window is slow. did-finish-load is used (not ready-to-show)
  // because transparent frameless windows can be unreliable with ready-to-show
  // on Windows.
  const showOverlay = () => { if (overlayWindow) overlayWindow.showInactive(); };
  overlayWindow.webContents.once('did-finish-load', showOverlay);
  overlayWindow.on('closed', () => { overlayWindow = null; });
}

// Overlay asks to move itself to the next corner (right-click cycle); we persist
// via the same setConfig path the renderer uses, but positioning is local.
ipcMain.on('overlay-set-corner', (_e, corner) => {
  if (!overlayWindow) return;
  const { x, y } = overlayPosition(corner);
  overlayWindow.setPosition(x, y);
});

// ----------------------------------------------------------------------------
// Tray
// ----------------------------------------------------------------------------

function appIconPath() {
  const projectRoot = path.resolve(__dirname, '..');
  const candidates = app.isPackaged
    ? [
        path.join(process.resourcesPath, 'assets', 'logo.ico'),
        path.join(process.resourcesPath, 'assets', 'logo.png'),
      ]
    : [
        path.join(projectRoot, 'src', 'ui', 'assets', 'logo.ico'),
        path.join(projectRoot, 'src', 'ui', 'assets', 'logo.png'),
      ];
  return candidates.find((p) => fs.existsSync(p)) || null;
}

function showMainWindow() {
  if (!mainWindow) {
    createWindow();
    return;
  }
  mainWindow.show();
  mainWindow.focus();
}

function createTray() {
  const iconPath = appIconPath();
  // nativeImage tolerates a missing file by returning an empty image; Tray
  // still works (shows a blank icon) so a missing asset doesn't crash startup.
  let icon = iconPath ? nativeImage.createFromPath(iconPath) : nativeImage.createEmpty();
  // The source logo is 256x256; Windows trays expect ~16px. Resize so the icon
  // actually renders instead of showing blank.
  if (!icon.isEmpty()) {
    icon = icon.resize({ width: 16, height: 16 });
  }
  tray = new Tray(icon);
  tray.setToolTip('LogNotes');

  const menu = Menu.buildFromTemplate([
    { label: 'Show', click: showMainWindow },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);
  tray.setContextMenu(menu);
  tray.on('click', showMainWindow);
}

// Renderer asks for the sidecar port once it is ready to connect.
ipcMain.handle('get-sidecar-port', () => sidecarPort);

// Renderer signals it has connected. The window is already shown early for
// responsiveness; this is a no-op safety net to ensure it's visible. The overlay
// shows itself on its own 'ready-to-show' (see createOverlay).
ipcMain.on('renderer-ready', () => {
  if (mainWindow && !mainWindow.isVisible()) mainWindow.show();
});

// ----------------------------------------------------------------------------
// Lifecycle
// ----------------------------------------------------------------------------

// Security: deny every web permission except the clipboard, which the Activity
// "Copy" button uses. This app is a local control panel — it has no legitimate
// use for geolocation, camera, web-microphone, notifications, etc. Denying them
// stops Chromium from ever prompting the user (e.g. the "use your location"
// prompt) and shrinks the attack surface.
const ALLOWED_PERMISSIONS = new Set(['clipboard-read', 'clipboard-sanitized-write']);

function lockDownPermissions() {
  session.defaultSession.setPermissionRequestHandler((_wc, permission, cb) => {
    cb(ALLOWED_PERMISSIONS.has(permission));
  });
  session.defaultSession.setPermissionCheckHandler((_wc, permission) => {
    return ALLOWED_PERMISSIONS.has(permission);
  });
}

// A second launch attempt: surface the existing window instead of starting anew.
app.on('second-instance', () => {
  showMainWindow();
});

if (gotSingleInstanceLock) {
  app.whenReady().then(async () => {
    lockDownPermissions();

    // Create + show the window first so the user gets immediate feedback. The
    // first frozen-build launch can take many seconds to start the sidecar +
    // load models; without an early window the app looks broken and users click
    // again. The renderer shows "Connecting to sidecar..." until the handshake.
    createWindow();
    mainWindow.show();
    createOverlay();
    createTray();

    try {
      await startSidecar();
    } catch (err) {
      console.error(`[main] failed to start sidecar: ${err.message}`);
      // Window already shown; renderer reflects the error/connecting state.
    }

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
      else showMainWindow();
    });
  });
}

// With hide-to-tray, the main window hides rather than closes, so this normally
// won't fire. Guard it: only quit if there is no tray to live in.
app.on('window-all-closed', () => {
  if (!tray) {
    stopSidecar();
    if (process.platform !== 'darwin') app.quit();
  }
});

app.on('before-quit', () => {
  isQuitting = true;
  stopSidecar();
});
