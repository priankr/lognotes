// Renderer: connect to the sidecar, render live status, and drive the Settings
// tab (config read/write over RPC). Activity/Logs/overlay come in later phases.

const els = {
  dot: document.getElementById('status-dot'),
  statusText: document.getElementById('status-text'),
  statusDetail: document.getElementById('status-detail'),
  port: document.getElementById('port'),
  conn: document.getElementById('conn'),
  hotkeyDisplay: document.getElementById('hotkey-display'),
  hotkeyChange: document.getElementById('hotkey-change'),
  hotkeyError: document.getElementById('hotkey-error'),
  modelSelect: document.getElementById('model-select'),
  grammarToggle: document.getElementById('grammar-toggle'),
  ollamaModel: document.getElementById('ollama-model'),
  activityList: document.getElementById('activity-list'),
  activityClear: document.getElementById('activity-clear'),
  logsOutput: document.getElementById('logs-output'),
  logsCopy: document.getElementById('logs-copy'),
  logsClear: document.getElementById('logs-clear'),
};

// id -> display name, populated from getModels; used to label activity rows.
const modelDisplay = new Map();
// Full model list for the retry menu.
let allModels = [];

let ws = null;
let nextId = 1;
const pending = new Map();

// Guard so programmatic value-setting during load doesn't fire change handlers
// that would echo back to the sidecar.
let loadingConfig = false;

function setStatus(state, message, detail) {
  els.dot.setAttribute('data-state', state);
  if (message) els.statusText.textContent = message;
  els.statusDetail.textContent = detail || '';
}

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

function handleMessage(msg) {
  if (msg.id != null && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    if ('error' in msg) reject(new Error(msg.error));
    else resolve(msg.result);
    return;
  }

  if (msg.event === 'ready') {
    setStatus(msg.data.status || 'ready', msg.data.message || 'Ready');
  } else if (msg.event === 'status') {
    setStatus(msg.data.status, msg.data.message);
  } else if (msg.event === 'audioError') {
    setStatus('error', 'Audio input unavailable', msg.data.message);
  } else if (msg.event === 'configChanged') {
    // Another client (or a side effect) changed config — reflect it.
    applyConfigField(msg.data.key, msg.data.value);
  } else if (msg.event === 'activityChanged') {
    renderActivity(msg.data.entries);
  } else if (msg.event === 'logLine') {
    appendLog(msg.data);
  }
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

function wireTabs() {
  for (const btn of document.querySelectorAll('.tab')) {
    btn.addEventListener('click', () => {
      if (btn.disabled) return;
      for (const b of document.querySelectorAll('.tab')) {
        b.classList.toggle('active', b === btn);
      }
      const target = btn.getAttribute('data-tab');
      for (const panel of document.querySelectorAll('.panel')) {
        panel.classList.toggle('hidden', panel.id !== `panel-${target}`);
      }
    });
  }
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

function applyConfigField(key, value) {
  loadingConfig = true;
  try {
    switch (key) {
      case 'hotkey':
        els.hotkeyDisplay.textContent = String(value).toUpperCase();
        break;
      case 'whisper_model':
        els.modelSelect.value = value;
        break;
      case 'enable_grammar':
        els.grammarToggle.checked = !!value;
        break;
      case 'ollama_model':
        els.ollamaModel.textContent = `Model: ${value}`;
        break;
      case 'push_to_talk_mode':
        for (const r of document.querySelectorAll('input[name="ptt"]')) {
          r.checked = r.value === value;
        }
        break;
      case 'theme':
        for (const r of document.querySelectorAll('input[name="theme"]')) {
          r.checked = r.value === value;
        }
        break;
    }
  } finally {
    loadingConfig = false;
  }
}

async function loadSettings() {
  const [config, models] = await Promise.all([
    request('getConfig'),
    request('getModels'),
  ]);

  // Populate model dropdown + lookup maps.
  allModels = models;
  modelDisplay.clear();
  els.modelSelect.innerHTML = '';
  for (const m of models) {
    modelDisplay.set(m.id, m.display);
    const opt = document.createElement('option');
    opt.value = m.id;
    opt.textContent = m.display;
    els.modelSelect.appendChild(opt);
  }

  for (const key of Object.keys(config)) {
    applyConfigField(key, config[key]);
  }

  // Initial activity + logs snapshots.
  const [entries, logs] = await Promise.all([
    request('getActivity'),
    request('getLogs'),
  ]);
  renderActivity(entries);
  renderLogs(logs);
}

async function saveConfig(key, value) {
  try {
    const result = await request('setConfig', { key, value });
    return result.value !== undefined ? result.value : value;
  } catch (e) {
    setStatus('error', 'Setting rejected', `${key}: ${e.message}`);
    throw e;
  }
}

// Map a KeyboardEvent.code/key to the app's hotkey token (matches the names
// used by the Python HotkeyListener: ctrl/shift/alt/cmd + single chars / names).
function eventToToken(e) {
  const code = e.code;
  if (code.startsWith('Control')) return 'ctrl';
  if (code.startsWith('Shift')) return 'shift';
  if (code.startsWith('Alt')) return 'alt';
  if (code.startsWith('Meta')) return 'cmd';
  // Letters: KeyA -> a
  if (/^Key[A-Z]$/.test(code)) return code.slice(3).toLowerCase();
  // Digits: Digit1 -> 1
  if (/^Digit[0-9]$/.test(code)) return code.slice(5);
  // Common named keys.
  const named = {
    Space: 'space', Enter: 'enter', Tab: 'tab', Backspace: 'backspace',
    Escape: 'esc',
  };
  if (named[code]) return named[code];
  if (/^F[0-9]{1,2}$/.test(code)) return code.toLowerCase(); // F1..F12
  return null;
}

const MODIFIER_TOKENS = new Set(['ctrl', 'shift', 'alt', 'cmd']);

function wireHotkeyCapture() {
  let listening = false;
  const pressed = new Set();

  function stop() {
    listening = false;
    pressed.clear();
    els.hotkeyChange.textContent = 'Change Hotkey';
    els.hotkeyChange.classList.remove('listening');
    window.removeEventListener('keydown', onKeyDown, true);
    window.removeEventListener('keyup', onKeyUp, true);
  }

  function updatePreview() {
    const mods = [...pressed].filter((t) => MODIFIER_TOKENS.has(t)).sort();
    const keys = [...pressed].filter((t) => !MODIFIER_TOKENS.has(t));
    const combo = [...mods, ...keys].join('+');
    if (combo) els.hotkeyDisplay.textContent = combo.toUpperCase();
  }

  async function finalize() {
    const mods = [...pressed].filter((t) => MODIFIER_TOKENS.has(t)).sort();
    const keys = [...pressed].filter((t) => !MODIFIER_TOKENS.has(t));
    if (mods.length === 0 || keys.length !== 1) {
      els.hotkeyError.textContent = 'Need a modifier (Ctrl/Alt/Shift) + one key.';
      return; // keep listening
    }
    const combo = [...mods, keys[0]].join('+');
    stop();
    try {
      const norm = await saveConfig('hotkey', combo);
      els.hotkeyDisplay.textContent = String(norm).toUpperCase();
      els.hotkeyError.textContent = '';
    } catch {
      els.hotkeyError.textContent = 'Invalid hotkey — rejected by the app.';
    }
  }

  function onKeyDown(e) {
    if (!listening) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.key === 'Escape') { stop(); return; }
    const token = eventToToken(e);
    if (!token) return;
    pressed.add(token);
    updatePreview();
  }

  function onKeyUp(e) {
    if (!listening) return;
    e.preventDefault();
    e.stopPropagation();
    const token = eventToToken(e);
    // Finalize when a non-modifier key is released, matching the Tk dialog.
    if (token && !MODIFIER_TOKENS.has(token)) {
      finalize();
    }
  }

  els.hotkeyChange.addEventListener('click', () => {
    if (listening) { stop(); return; }
    listening = true;
    pressed.clear();
    els.hotkeyError.textContent = '';
    els.hotkeyChange.textContent = 'Press combination… (Esc to cancel)';
    els.hotkeyChange.classList.add('listening');
    // Drop focus so Space/Enter don't re-trigger this button while capturing.
    els.hotkeyChange.blur();
    window.addEventListener('keydown', onKeyDown, true);
    window.addEventListener('keyup', onKeyUp, true);
  });
}

function wireSettingsHandlers() {
  wireHotkeyCapture();

  els.modelSelect.addEventListener('change', () => {
    if (loadingConfig) return;
    saveConfig('whisper_model', els.modelSelect.value).catch(() => {});
  });

  els.grammarToggle.addEventListener('change', () => {
    if (loadingConfig) return;
    saveConfig('enable_grammar', els.grammarToggle.checked).catch(() => {});
  });

  for (const r of document.querySelectorAll('input[name="ptt"]')) {
    r.addEventListener('change', () => {
      if (loadingConfig || !r.checked) return;
      saveConfig('push_to_talk_mode', r.value).catch(() => {});
    });
  }

  for (const r of document.querySelectorAll('input[name="theme"]')) {
    r.addEventListener('change', () => {
      if (loadingConfig || !r.checked) return;
      saveConfig('theme', r.value).catch(() => {});
    });
  }
}

// ---------------------------------------------------------------------------
// Activity
// ---------------------------------------------------------------------------

const TEXT_PREVIEW_CHARS = 80;
const expanded = new Set(); // entry ids shown in full

function fmtTime(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' });
  } catch {
    return iso;
  }
}

function renderActivity(entries) {
  const list = els.activityList;
  list.innerHTML = '';

  if (!entries || entries.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'hint';
    empty.textContent = 'No transcriptions yet this session.';
    list.appendChild(empty);
    return;
  }

  for (const entry of entries) {
    list.appendChild(renderRow(entry));
  }
}

function renderRow(entry) {
  const row = document.createElement('div');
  row.className = 'activity-row';

  // Header: meta + action buttons.
  const header = document.createElement('div');
  header.className = 'activity-header';

  const display = modelDisplay.get(entry.whisper_model) || entry.whisper_model;
  let meta = `${fmtTime(entry.timestamp)} · ${display}`;
  if (entry.error) meta += ' · error';
  else if (!entry.paste_succeeded) meta += ' · not pasted';
  const metaEl = document.createElement('span');
  metaEl.className = 'activity-meta';
  metaEl.textContent = meta;
  header.appendChild(metaEl);

  const actions = document.createElement('span');
  actions.className = 'activity-actions';

  // Copy
  const copyBtn = document.createElement('button');
  copyBtn.className = 'icon';
  copyBtn.title = 'Copy text';
  copyBtn.textContent = '⧉';
  copyBtn.addEventListener('click', () => copyText(entry.text));
  actions.appendChild(copyBtn);

  // Retry (model menu)
  const retryWrap = document.createElement('span');
  retryWrap.className = 'retry-wrap';
  const retryBtn = document.createElement('button');
  retryBtn.className = 'icon';
  retryBtn.title = 'Retry with a model';
  retryBtn.textContent = '↻';
  const menu = document.createElement('div');
  menu.className = 'retry-menu hidden';
  for (const m of allModels) {
    const item = document.createElement('button');
    item.className = 'retry-item';
    item.textContent = m.display;
    item.addEventListener('click', () => {
      menu.classList.add('hidden');
      retryEntry(entry.id, m.id);
    });
    menu.appendChild(item);
  }
  retryBtn.addEventListener('click', () => menu.classList.toggle('hidden'));
  retryWrap.appendChild(retryBtn);
  retryWrap.appendChild(menu);
  actions.appendChild(retryWrap);

  // Delete
  const delBtn = document.createElement('button');
  delBtn.className = 'icon';
  delBtn.title = 'Delete';
  delBtn.textContent = '✕';
  delBtn.addEventListener('click', () => deleteEntry(entry.id));
  actions.appendChild(delBtn);

  header.appendChild(actions);
  row.appendChild(header);

  // Body text (with show-more truncation).
  const bodyText = entry.error || entry.text || '(no text)';
  const isExpanded = expanded.has(entry.id);
  const truncated = bodyText.length > TEXT_PREVIEW_CHARS;
  const shown = (isExpanded || !truncated)
    ? bodyText
    : bodyText.slice(0, TEXT_PREVIEW_CHARS) + '…';

  const body = document.createElement('div');
  body.className = 'activity-body' + (entry.error ? ' is-error' : '');
  body.textContent = shown;
  row.appendChild(body);

  if (truncated) {
    const link = document.createElement('a');
    link.className = 'show-more';
    link.textContent = isExpanded ? 'show less' : 'show more';
    link.addEventListener('click', () => {
      if (expanded.has(entry.id)) expanded.delete(entry.id);
      else expanded.add(entry.id);
      // Re-render just needs current data; request a fresh snapshot.
      request('getActivity').then(renderActivity).catch(() => {});
    });
    row.appendChild(link);
  }

  return row;
}

async function copyText(text) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    setStatus(statusState(), 'Copied to clipboard');
  } catch (e) {
    setStatus('error', 'Copy failed', e.message);
  }
}

async function retryEntry(id, model) {
  // Gate on busy at click time, mirroring the Tk behavior.
  try {
    const { busy } = await request('isBusy');
    if (busy) {
      setStatus(statusState(), 'Busy — retry again when ready');
      return;
    }
    await request('retryTranscription', { id, model });
    // The sidecar copies the result to the clipboard; status updates arrive
    // via pushed status events.
  } catch (e) {
    setStatus('error', 'Retry failed', e.message);
  }
}

async function deleteEntry(id) {
  try {
    await request('deleteActivity', { id });
  } catch (e) {
    setStatus('error', 'Delete failed', e.message);
  }
}

function statusState() {
  return els.dot.getAttribute('data-state') || 'ready';
}

// ---------------------------------------------------------------------------
// Logs
// ---------------------------------------------------------------------------

const MAX_LOG_LINES = 1000;

function appendLog(line) {
  const atBottom =
    els.logsOutput.scrollHeight - els.logsOutput.scrollTop - els.logsOutput.clientHeight < 30;

  const span = document.createElement('span');
  span.className = `log-line log-${line.level || 'info'}`;
  span.textContent = line.text + '\n';
  els.logsOutput.appendChild(span);

  // Cap rendered lines so a long session doesn't grow unbounded.
  while (els.logsOutput.childElementCount > MAX_LOG_LINES) {
    els.logsOutput.removeChild(els.logsOutput.firstChild);
  }

  if (atBottom) els.logsOutput.scrollTop = els.logsOutput.scrollHeight;
}

function renderLogs(lines) {
  els.logsOutput.innerHTML = '';
  for (const line of lines) appendLog(line);
}

function wireLogsHandlers() {
  els.logsClear.addEventListener('click', () => {
    els.logsOutput.innerHTML = '';
    request('clearLogs').catch(() => {});
  });
  els.logsCopy.addEventListener('click', async () => {
    const text = els.logsOutput.textContent;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setStatus(statusState(), 'Logs copied');
    } catch (e) {
      setStatus('error', 'Copy failed', e.message);
    }
  });
}

// ---------------------------------------------------------------------------
// Connection
// ---------------------------------------------------------------------------

// The main process shows the window before the sidecar finishes starting, so
// the port may not exist yet on a cold (frozen) launch. Poll until it does,
// keeping the "Connecting..." status visible, rather than failing immediately.
async function waitForPort(timeoutMs = 120000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const port = await window.lognotes.getSidecarPort();
    if (port) return port;
    els.conn.textContent = 'starting sidecar…';
    await new Promise((r) => setTimeout(r, 500));
  }
  return null;
}

async function connect() {
  const port = await waitForPort();
  if (!port) {
    setStatus('error', 'Sidecar unavailable', 'The back end did not start in time.');
    els.conn.textContent = 'failed';
    return;
  }
  els.port.textContent = String(port);

  ws = new WebSocket(`ws://127.0.0.1:${port}`);

  ws.onopen = async () => {
    els.conn.textContent = 'connected';
    window.lognotes.signalReady();
    try {
      await loadSettings();
    } catch (e) {
      setStatus('error', 'Failed to load settings', e.message);
    }
  };

  ws.onmessage = (ev) => {
    try {
      handleMessage(JSON.parse(ev.data));
    } catch (e) {
      console.error('bad message', e, ev.data);
    }
  };

  ws.onclose = () => {
    els.conn.textContent = 'closed';
    setStatus('error', 'Disconnected', 'Lost connection to the sidecar.');
  };

  ws.onerror = () => {
    els.conn.textContent = 'error';
  };
}

window.lognotes.onSidecarDown(() => {
  setStatus('error', 'Sidecar stopped', 'The back-end process exited.');
  els.conn.textContent = 'down';
});

function wireActivityHandlers() {
  els.activityClear.addEventListener('click', () => {
    request('clearActivity').catch((e) =>
      setStatus('error', 'Clear failed', e.message));
  });
}

wireTabs();
wireSettingsHandlers();
wireActivityHandlers();
wireLogsHandlers();
connect().catch((e) => setStatus('error', 'Connection failed', e.message));
