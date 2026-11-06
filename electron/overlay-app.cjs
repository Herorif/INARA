// The talking overlay: a small always-on-top, click-through, never-focused panel that shows the
// live JARVIS core and captions while a tray voice session runs. The core spawns
// electron/overlay-main.cjs, which validates the bootstrap and calls start(); the harness
// (scripts/verify-overlay.cjs) calls start() in-process. The token and caption text are never logged.
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { io } = require('socket.io-client');
const security = require('./security.cjs');
const policy = require('./overlay-policy.cjs');

const ROOT = path.resolve(__dirname, '..');
/** Quit when no valid snapshot arrives within this long of start. */
const FIRST_SNAPSHOT_MS = 10000;
/** A lost or refused core connection fades the window out over this long, then quits. */
const DISCONNECT_FADE_MS = 1000;
const FADE_STEP_MS = 50;
const ACK_TIMEOUT_MS = 5000;

/** Renderer IPC. Main → renderer: snapshot, level. Renderer → main: the rest. */
const CHANNELS = Object.freeze({
  snapshot: 'overlay-snapshot',
  level: 'overlay-level',
  ready: 'overlay-ready',
  pointer: 'overlay-pointer',
  stop: 'overlay-stop',
  open: 'overlay-open',
  done: 'overlay-done',
});

/** BrowserWindow options for the given bounds. `offscreen` is for the harness only. */
function windowOptions(bounds, { offscreen = false } = {}) {
  return {
    ...bounds,
    title: 'JARVIS',
    frame: false,
    transparent: true,
    backgroundColor: '#00000000',
    hasShadow: false,
    resizable: false,
    movable: false,
    focusable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    show: false,
    webPreferences: {
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'overlay-preload.js'),
      backgroundThrottling: false,
      ...(offscreen ? { offscreen: true } : {}),
    },
  };
}

/**
 * Starts one overlay for a validated bootstrap (see overlay-policy.cjs validateBootstrap).
 * options: { electron, quit(code), log(message), offscreen } — all optional; the defaults are the
 * production ones (the real electron module, app.exit, console.error).
 * Resolves to a controller: { window, bounds, options, socket, exited } where `exited` resolves
 * with the exit code once the overlay has asked to quit.
 */
async function start(bootstrap, options = {}) {
  const electron = options.electron || require('electron');
  const { app, BrowserWindow, screen } = electron;
  const log = options.log || (message => console.error(`JARVIS overlay: ${message}`));
  const quit = options.quit || (code => app.exit(code));
  if (!app.isReady()) {
    app.setPath('userData', bootstrap.profile);
    await app.whenReady();
  }

  const display = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  const bounds = policy.overlayBounds(display.workArea);
  const createOptions = windowOptions(bounds, { offscreen: !!options.offscreen });
  // A fresh copy: Electron adds its own fields to the object it is given.
  const window = new BrowserWindow(windowOptions(bounds, { offscreen: !!options.offscreen }));
  window.setAlwaysOnTop(true, 'screen-saver');
  window.setContentProtection(true);
  window.setIgnoreMouseEvents(true, { forward: true });

  const appPage = { dev: bootstrap.dev, indexUrl: pathToFileURL(path.join(ROOT, 'dist/overlay.html')).href };
  const trusted = event => security.trustedSender(event, window, appPage);
  const contents = window.webContents;
  let socket = null, latest = null, loaded = false, shown = false, finished = false, fading = null, firstSnapshot = null;
  let resolveExit;
  const exited = new Promise(resolve => { resolveExit = resolve; });
  const alive = () => !window.isDestroyed();
  const send = (channel, value) => { if (loaded && alive()) contents.send(channel, value); };

  const finish = (code, reason) => {
    if (finished) return;
    finished = true;
    clearTimeout(firstSnapshot);
    clearInterval(fading);
    if (reason) log(reason);
    socket?.disconnect();
    try { for (const channel of Object.values(CHANNELS)) contents.ipc.removeAllListeners(channel); } catch { /* already destroyed */ }
    if (alive()) window.destroy();
    resolveExit(code);
    quit(code);
  };
  // Lost or refused core: fade the window out over 1 s with no text change, then quit.
  const fadeThenFinish = (code, reason) => {
    if (finished || fading) return;
    if (!shown || !alive()) { finish(code, reason); return; }
    const begin = Date.now();
    fading = setInterval(() => {
      const progress = Math.min(1, (Date.now() - begin) / DISCONNECT_FADE_MS);
      if (alive()) window.setOpacity(1 - progress);
      if (progress >= 1) finish(code, reason);
    }, FADE_STEP_MS);
  };
  firstSnapshot = setTimeout(() => finish(1, 'no snapshot from the core within 10 s'), FIRST_SNAPSHOT_MS);

  // Deny every permission (no microphone, camera or notifications) and every new window.
  contents.session.setPermissionRequestHandler((_contents, permission, callback) => {
    log(`denied permission request: ${String(permission).slice(0, 40)}`);
    callback(false);
  });
  contents.session.setPermissionCheckHandler(() => false);
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
  contents.on('will-navigate', (event, url) => { if (!security.isAppUrl(url, appPage)) event.preventDefault(); });
  contents.on('render-process-gone', () => finish(1, 'renderer exited'));
  contents.on('did-finish-load', () => {
    loaded = true;
    if (latest) send(CHANNELS.snapshot, latest);
  });
  window.on('closed', () => finish(0));

  const relay = name => () => {
    if (!socket?.connected) return;
    socket.timeout(ACK_TIMEOUT_MS).emit(name, error => { if (error) log(`${name} was not acknowledged`); });
  };
  const handlers = {
    [CHANNELS.ready]: () => {
      if (shown || !alive()) return;
      shown = true;
      window.showInactive();
    },
    [CHANNELS.pointer]: (_event, inside) => {
      if (typeof inside !== 'boolean' || !alive()) return;
      if (inside) window.setIgnoreMouseEvents(false);
      else window.setIgnoreMouseEvents(true, { forward: true });
    },
    [CHANNELS.stop]: relay('overlay_stop'),
    [CHANNELS.open]: relay('overlay_open'),
    [CHANNELS.done]: () => finish(0),
  };
  for (const [channel, handler] of Object.entries(handlers)) {
    contents.ipc.on(channel, (event, ...args) => { if (trusted(event)) handler(event, ...args); });
  }

  socket = io(bootstrap.core, {
    auth: { token: bootstrap.token, client_id: bootstrap.clientId, role: 'overlay' },
    reconnection: false,
  });
  socket.on('connect_error', () => fadeThenFinish(1, 'core connection failed'));
  socket.on('disconnect', reason => {
    // The core closing the socket is a normal end; a dropped transport is not.
    if (!finished) fadeThenFinish(reason === 'io server disconnect' ? 0 : 1, 'core disconnected');
  });
  socket.on('voice_overlay', raw => {
    if (finished || fading) return;
    const snapshot = policy.sanitizeSnapshot(raw);
    if (!snapshot) { log('dropped an invalid snapshot'); return; }
    clearTimeout(firstSnapshot);
    latest = snapshot;
    send(CHANNELS.snapshot, snapshot);
  });
  socket.on('voice_level', raw => {
    if (finished || fading) return;
    const level = policy.sanitizeLevel(raw);
    if (level) send(CHANNELS.level, level);
  });

  const load = bootstrap.dev
    ? window.loadURL(`${security.DEV_ORIGIN}/overlay.html`)
    : window.loadFile(path.join(ROOT, 'dist/overlay.html'));
  load.catch(() => finish(1, 'the overlay page did not load'));

  return { window, bounds, options: createOptions, socket, exited, display };
}

module.exports = { start, windowOptions, CHANNELS, FIRST_SNAPSHOT_MS, DISCONNECT_FADE_MS };
