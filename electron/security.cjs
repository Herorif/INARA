// Main-process security policy shared by both workspace hosts (native-main.cjs, desktop.js).
// Pure decision functions plus thin Electron wiring, so the policy is testable without Electron.

// --- Private-LAN hosts: mirrors src/components/printerHost.js (tests/test_security.cjs checks parity).
const OCTET = /^(?:0|[1-9]\d{0,2})$/;
const LABEL = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const LOCAL_SUFFIXES = ['local', 'lan', 'home', 'internal', 'home.arpa'];

function privateIPv4(host) {
  const parts = host.split('.');
  if (parts.length !== 4 || !parts.every(part => OCTET.test(part))) return false;
  const [a, b] = parts.map(Number);
  if (parts.some(part => Number(part) > 255)) return false;
  return a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168);
}

function localHostname(host) {
  if (host.length > 253 || host === 'localhost') return false;
  const labels = host.split('.');
  if (!labels.every(label => LABEL.test(label))) return false;
  if (labels.length === 1) return !/^\d+$/.test(host);
  return LOCAL_SUFFIXES.some(suffix => host.endsWith(`.${suffix}`) && host.length > suffix.length + 1);
}

/** Normalized host when it is a private-LAN IPv4 address or a local hostname, otherwise null. */
function privateLanHost(host) {
  if (typeof host !== 'string') return null;
  const value = host.trim().toLowerCase();
  if (!value) return null;
  if (/^[\d.]+$/.test(value)) return privateIPv4(value) ? value : null;
  return localHostname(value) ? value : null;
}

const parse = value => {
  if (typeof value !== 'string') return null;
  try { return new URL(value); } catch { return null; }
};

/**
 * World view's "Open in browser" (docs/WORLD_VIEW.md): exactly http://127.0.0.1:<port>/, the
 * God's Eye View app on a loopback port other than the core's 8000. No path, query or sign-in.
 */
function worldViewUrl(url) {
  const port = Number(url.port);
  return url.protocol === 'http:' && url.hostname === '127.0.0.1' && /^\d{4,5}$/.test(url.port)
    && port >= 1024 && port <= 65535 && port !== 8000 && url.pathname === '/'
    && !url.search && !url.hash && !url.username && !url.password;
}

/** shell.openExternal policy: https anywhere, http only to private-LAN hosts and World view. Returns the normalized URL or null. */
function externalUrl(value) {
  const url = parse(value);
  if (!url) return null;
  if (url.protocol === 'https:') return url.href;
  if (url.protocol === 'http:' && privateLanHost(url.hostname)) return url.href;
  if (worldViewUrl(url)) return url.href;
  return null;
}

// --- App origin: the built file:// page in production, the Vite dev origin in development.
const DEV_ORIGIN = 'http://localhost:5173';

/** app = { dev: boolean, indexUrl: pathToFileURL(dist/index.html).href }. */
function isAppUrl(value, app) {
  const url = parse(value);
  if (!url) return false;
  if (app.dev) return url.origin === DEV_ORIGIN;
  // Query and fragment may vary; scheme, host and path must be exactly dist/index.html.
  return url.protocol === 'file:' && `file://${url.host}${url.pathname}` === app.indexUrl;
}

// --- Permissions: only for the app page's main frame. 'media' is camera/microphone capture;
// 'speaker-selection' is audio output, which Chromium checks for the push-to-talk AudioContext
// (denying it stalls the AudioWorklet). Notifications, geolocation, MIDI, clipboard etc. are denied.
const MEDIA_TYPES = new Set(['audio', 'video']);
const appFrame = (requestingUrl, isMainFrame, app) => isMainFrame !== false && isAppUrl(requestingUrl, app);

function permissionRequestAllowed({ permission, requestingUrl, mediaTypes, isMainFrame }, app) {
  if (!appFrame(requestingUrl, isMainFrame, app)) return false;
  if (permission === 'speaker-selection') return true;
  return permission === 'media' && Array.isArray(mediaTypes) && mediaTypes.length > 0 && mediaTypes.every(type => MEDIA_TYPES.has(type));
}

function permissionCheckAllowed({ permission, requestingUrl, mediaType, isMainFrame }, app) {
  if (!appFrame(requestingUrl, isMainFrame, app)) return false;
  if (permission === 'speaker-selection') return true;
  return permission === 'media' && MEDIA_TYPES.has(mediaType);
}

/** IPC sender: the top frame of the workspace window, showing the app page. */
function trustedSender(event, window, app) {
  if (!window || window.isDestroyed() || !event || event.sender !== window.webContents) return false;
  const frame = event.senderFrame;
  return !!frame && frame === window.webContents.mainFrame && isAppUrl(frame.url, app);
}

/** Installs the request and check handlers on the workspace session. getWindow returns the current workspace window. */
function installPermissionHandlers(session, getWindow, app, log = console.warn) {
  const owned = contents => {
    const window = getWindow();
    return !!contents && !!window && !window.isDestroyed() && contents === window.webContents;
  };
  session.setPermissionRequestHandler((contents, permission, callback, details = {}) => {
    const allowed = owned(contents) && permissionRequestAllowed({
      permission, requestingUrl: details.requestingUrl, mediaTypes: details.mediaTypes, isMainFrame: details.isMainFrame,
    }, app);
    if (!allowed) log(`Denied permission request: ${permission}`);
    callback(allowed);
  });
  session.setPermissionCheckHandler((contents, permission, _origin, details = {}) => owned(contents) && permissionCheckAllowed({
    permission, requestingUrl: details.requestingUrl, mediaType: details.mediaType, isMainFrame: details.isMainFrame,
  }, app));
}

/** Opens url externally when the policy allows it; logs and ignores everything else. */
function openExternal(shell, value, log = console.warn) {
  const url = externalUrl(value);
  if (!url) {
    log(`Blocked external URL: ${typeof value === 'string' ? value.slice(0, 200) : typeof value}`);
    return undefined;
  }
  return shell.openExternal(url);
}

module.exports = {
  DEV_ORIGIN,
  privateLanHost,
  externalUrl,
  isAppUrl,
  permissionRequestAllowed,
  permissionCheckAllowed,
  trustedSender,
  installPermissionHandlers,
  openExternal,
};
