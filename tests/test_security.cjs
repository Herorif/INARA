const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const security = require('../electron/security.cjs');

const indexUrl = pathToFileURL(path.join(__dirname, '..', 'dist/index.html')).href;
const prod = { dev: false, indexUrl };
const dev = { dev: true, indexUrl };

const HOSTS = [
  '10.0.0.5', '10.255.255.255', '172.16.0.1', '172.31.255.254', '192.168.1.20', ' 192.168.1.20 ',
  '172.15.0.1', '172.32.0.1', '192.169.0.1', '8.8.8.8', '127.0.0.1', '0.0.0.0', '10.0.0', '10.0.0.256', '010.0.0.1',
  'printer', 'PRINTER', 'printer.local', 'hp-office.lan', 'printer.home', 'printer.internal', 'printer.home.arpa',
  'localhost', 'printer.example.com', 'local', '.local', 'printer..local', '-bad.local', '12345', '', null, 42,
  'evil.com/x', 'a b', '[fd00::1]', 'printer.local.',
];

test('private-LAN host check mirrors the renderer printer policy exactly', async () => {
  const renderer = await import(pathToFileURL(path.join(__dirname, '..', 'src/components/printerHost.js')).href);
  for (const host of HOSTS) assert.equal(security.privateLanHost(host), renderer.privateLanHost(host), String(host));
  for (const host of HOSTS) {
    const url = renderer.printerWebUrl(host);
    if (url) assert.equal(security.externalUrl(url), `${url}/`, url);
  }
});

test('openExternal allows https anywhere and http only on the private LAN', () => {
  assert.equal(security.externalUrl('https://example.com/docs?q=1'), 'https://example.com/docs?q=1');
  assert.equal(security.externalUrl('http://192.168.1.20'), 'http://192.168.1.20/');
  assert.equal(security.externalUrl('http://10.0.0.5:8080/status'), 'http://10.0.0.5:8080/status');
  assert.equal(security.externalUrl('http://printer.local/'), 'http://printer.local/');
  assert.equal(security.externalUrl('http://PRINTER/'), 'http://printer/');
  for (const blocked of [
    'http://example.com', 'http://8.8.8.8', 'http://127.0.0.1:8000', 'http://localhost:5173', 'http://[fd00::1]/',
    'http://172.32.0.1', 'http://printer.example.com', 'file:///C:/Windows/System32/calc.exe', 'javascript:alert(1)',
    'ms-settings:privacy', 'mailto:a@example.com', 'ftp://192.168.1.20', 'not a url', '', null, undefined, 42, {},
  ]) assert.equal(security.externalUrl(blocked), null, String(blocked));
});

test('openExternal wrapper passes only the normalized allowed URL and logs denials', () => {
  const opened = [], logged = [];
  const shell = { openExternal: url => { opened.push(url); return Promise.resolve(); } };
  security.openExternal(shell, 'http://192.168.1.20', message => logged.push(message));
  assert.equal(security.openExternal(shell, 'http://example.com', message => logged.push(message)), undefined);
  assert.equal(security.openExternal(shell, { href: 'https://x' }, message => logged.push(message)), undefined);
  assert.deepEqual(opened, ['http://192.168.1.20/']);
  assert.equal(logged.length, 2);
  assert.match(logged[0], /Blocked external URL: http:\/\/example\.com/);
});

test('app page matches only the built index.html in production and the Vite origin in dev', () => {
  assert.equal(security.isAppUrl(indexUrl, prod), true);
  assert.equal(security.isAppUrl(`${indexUrl}?x=1#/panel`, prod), true);
  assert.equal(security.isAppUrl(indexUrl.replace('index.html', 'other.html'), prod), false);
  assert.equal(security.isAppUrl('file:///C:/Windows/index.html', prod), false);
  assert.equal(security.isAppUrl('http://localhost:5173/', prod), false);
  assert.equal(security.isAppUrl('http://localhost:5173/', dev), true);
  assert.equal(security.isAppUrl('http://localhost:5173/src/main.jsx?t=1', dev), true);
  assert.equal(security.isAppUrl('http://localhost:5174/', dev), false);
  assert.equal(security.isAppUrl('http://127.0.0.1:5173/', dev), false);
  assert.equal(security.isAppUrl('http://localhost:5173.evil.com/', dev), false);
  assert.equal(security.isAppUrl(indexUrl, dev), false);
  // Unparseable input denies instead of throwing.
  for (const value of ['::::', '', 'http://[', null, undefined, 7]) {
    assert.equal(security.isAppUrl(value, prod), false);
    assert.equal(security.isAppUrl(value, dev), false);
  }
});

test('permission requests allow only camera/microphone and speaker selection for the app main frame', () => {
  const request = overrides => security.permissionRequestAllowed({ permission: 'media', requestingUrl: indexUrl, mediaTypes: ['audio'], isMainFrame: true, ...overrides }, prod);
  assert.equal(request({}), true);
  assert.equal(request({ mediaTypes: ['video'] }), true);
  assert.equal(request({ mediaTypes: ['audio', 'video'] }), true);
  assert.equal(request({ isMainFrame: undefined }), true);
  assert.equal(request({ mediaTypes: [] }), false);
  assert.equal(request({ mediaTypes: undefined }), false);
  assert.equal(request({ mediaTypes: ['audio', 'screen'] }), false);
  assert.equal(request({ isMainFrame: false }), false);
  assert.equal(request({ requestingUrl: 'https://example.com/' }), false);
  assert.equal(request({ requestingUrl: 'file:///C:/elsewhere/index.html' }), false);
  assert.equal(request({ requestingUrl: undefined }), false);
  for (const permission of ['notifications', 'geolocation', 'midi', 'midiSysex', 'clipboard-read', 'clipboard-sanitized-write',
    'display-capture', 'fullscreen', 'pointerLock', 'keyboardLock', 'openExternal', 'mediaKeySystem', 'idle-detection',
    'window-management', 'storage-access', 'fileSystem', 'unknown']) {
    assert.equal(request({ permission }), false, permission);
  }
  assert.equal(request({ permission: 'speaker-selection', mediaTypes: undefined }), true);
  assert.equal(request({ permission: 'speaker-selection', requestingUrl: 'https://example.com/' }), false);
  assert.equal(request({ permission: 'speaker-selection', isMainFrame: false }), false);
  assert.equal(security.permissionRequestAllowed({ permission: 'media', requestingUrl: 'http://localhost:5173/', mediaTypes: ['audio'] }, dev), true);
  assert.equal(security.permissionRequestAllowed({ permission: 'media', requestingUrl: 'http://localhost:5173/', mediaTypes: ['audio'] }, prod), false);
});

test('permission checks allow only audio/video media and speaker selection for the app main frame', () => {
  const check = overrides => security.permissionCheckAllowed({ permission: 'media', requestingUrl: indexUrl, mediaType: 'video', isMainFrame: true, ...overrides }, prod);
  assert.equal(check({}), true);
  assert.equal(check({ mediaType: 'audio' }), true);
  assert.equal(check({ mediaType: 'unknown' }), false);
  assert.equal(check({ mediaType: undefined }), false);
  assert.equal(check({ isMainFrame: false }), false);
  assert.equal(check({ requestingUrl: 'https://example.com/' }), false);
  assert.equal(check({ permission: 'speaker-selection', mediaType: undefined }), true);
  assert.equal(check({ permission: 'speaker-selection', requestingUrl: 'file:///C:/elsewhere/index.html' }), false);
  for (const permission of ['notifications', 'geolocation', 'hid', 'serial', 'usb', 'clipboard-read', 'background-sync', 'midi']) {
    assert.equal(check({ permission }), false, permission);
  }
});

const fakeWindow = url => {
  const mainFrame = { url };
  return { destroyed: false, isDestroyed() { return this.destroyed; }, webContents: { mainFrame } };
};

test('IPC sender must be the workspace top frame showing the app page', () => {
  const window = fakeWindow(indexUrl);
  const event = { sender: window.webContents, senderFrame: window.webContents.mainFrame };
  assert.equal(security.trustedSender(event, window, prod), true);
  assert.equal(security.trustedSender({ ...event, senderFrame: { url: indexUrl } }, window, prod), false);
  assert.equal(security.trustedSender({ ...event, senderFrame: null }, window, prod), false);
  assert.equal(security.trustedSender({ ...event, sender: {} }, window, prod), false);
  assert.equal(security.trustedSender(event, null, prod), false);
  assert.equal(security.trustedSender(undefined, window, prod), false);
  window.webContents.mainFrame.url = 'https://example.com/';
  assert.equal(security.trustedSender(event, window, prod), false);
  window.webContents.mainFrame.url = indexUrl;
  window.destroyed = true;
  assert.equal(security.trustedSender(event, window, prod), false);
});

test('installed handlers deny other webContents and log denied requests', () => {
  const window = fakeWindow(indexUrl), handlers = {}, logged = [];
  const session = {
    setPermissionRequestHandler: handler => { handlers.request = handler; },
    setPermissionCheckHandler: handler => { handlers.check = handler; },
  };
  security.installPermissionHandlers(session, () => window, prod, message => logged.push(message));
  const decide = (contents, permission, details) => {
    let result;
    handlers.request(contents, permission, value => { result = value; }, details);
    return result;
  };
  const media = { requestingUrl: indexUrl, mediaTypes: ['audio'], isMainFrame: true };
  assert.equal(decide(window.webContents, 'media', media), true);
  assert.equal(decide({}, 'media', media), false);
  assert.equal(decide(null, 'media', media), false);
  assert.equal(decide(window.webContents, 'notifications', { requestingUrl: indexUrl }), false);
  assert.equal(decide(window.webContents, 'media', undefined), false);
  assert.deepEqual(logged, ['Denied permission request: media', 'Denied permission request: media',
    'Denied permission request: notifications', 'Denied permission request: media']);
  assert.equal(handlers.check(window.webContents, 'media', 'file:///', { requestingUrl: indexUrl, mediaType: 'audio', isMainFrame: true }), true);
  assert.equal(handlers.check(window.webContents, 'notifications', 'file:///', { requestingUrl: indexUrl }), false);
  assert.equal(handlers.check(null, 'media', 'file:///', { requestingUrl: indexUrl, mediaType: 'audio' }), false);
  assert.equal(handlers.check(window.webContents, 'media', 'file:///', undefined), false);
  window.destroyed = true;
  assert.equal(decide(window.webContents, 'media', media), false);
});
