// On-demand workspace. The native Python host owns the core, tray and lifetime.
const { app, BrowserWindow, ipcMain, shell, powerMonitor } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { io } = require('socket.io-client');
const { bindCaptureLifecycle } = require('./capture-lifecycle.cjs');
const root = path.resolve(__dirname, '..');
const bootstrap = JSON.parse(fs.readFileSync(0, 'utf8'));
if (!/^[a-f0-9]{64}$/.test(bootstrap.token) || !path.isAbsolute(bootstrap.profile)) throw Error('Invalid native bootstrap');
app.setPath('userData', bootstrap.profile);
let window, control, state = bootstrap.state, closing = false;
const trusted = event => window && !window.isDestroyed() && event.sender === window.webContents && event.senderFrame === window.webContents.mainFrame;
const publish = value => {
  state = value;
  if (window && !window.isDestroyed()) window.webContents.send('resident-state', state);
};
const rpc = data => new Promise((resolve, reject) => {
  if (!control?.connected) return reject(Error('Native core unavailable'));
  control.timeout(5000).emit('desktop_control', data, (error, result) => {
    if (error || !result?.ok) reject(Error(result?.error || 'Native action timed out'));
    else { publish(result.state); resolve(result.state); }
  });
});
async function register(id) {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) return false;
  if (bootstrap.clientId && bootstrap.clientId !== id) return false;
  if (!control) {
    bootstrap.clientId = id;
    control = io('http://127.0.0.1:8000', { auth: { token: bootstrap.token, client_id: id, role: 'workspace' }, reconnection: false });
    control.on('resident_state', publish);
    control.on('workspace_focus', () => { if (window?.isMinimized()) window.restore(); window?.show(); window?.focus(); });
    // Used by the isolated lifecycle verification; same behavior as the titlebar.
    control.on('workspace_close', () => window?.close());
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(Error('Native core connection timed out')), 6000);
      control.once('connect', () => { clearTimeout(timeout); resolve(); });
      control.once('connect_error', error => { clearTimeout(timeout); reject(error); });
    });
  }
  await rpc({ action: 'register' });
  return true;
}
app.whenReady().then(async () => {
  window = new BrowserWindow({ width: 1440, height: 940, minWidth: 390, minHeight: 560,
    frame: false, show: false, title: 'INARA · Command deck', backgroundColor: '#080d18',
    icon: path.join(root, 'assets/icons/inara.png'),
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, backgroundThrottling: !bootstrap.hide, offscreen: !!bootstrap.hide, preload: path.join(__dirname, 'preload.js') } });
  bindCaptureLifecycle(window, powerMonitor);
  ipcMain.on('desktop-bootstrap', event => { event.returnValue = trusted(event) ? { token: bootstrap.token, clientId: bootstrap.clientId } : {}; });
  ipcMain.on('window-minimize', event => { if (trusted(event)) window.minimize(); });
  ipcMain.on('window-maximize', event => { if (trusted(event)) window.isMaximized() ? window.unmaximize() : window.maximize(); });
  ipcMain.on('window-close', event => { if (trusted(event)) window.close(); });
  ipcMain.on('app-quit', event => { if (trusted(event)) rpc({ action: 'quit' }).catch(() => {}); });
  ipcMain.handle('resident-register', (event, id) => trusted(event) ? register(id) : false);
  ipcMain.handle('resident-status', event => trusted(event) ? state : null);
  ipcMain.handle('resident-gaming', (event, gaming) => trusted(event) ? rpc({ action: 'gaming', gaming }) : null);
  ipcMain.handle('resident-metrics', event => trusted(event) ? {
    electronMemoryMB: app.getAppMetrics().reduce((sum, metric) => sum + (metric.memory?.workingSetSize || 0), 0) / 1024,
    electronPIDs: app.getAppMetrics().map(metric => metric.pid), host: 'native-windows'
  } : null);
  ipcMain.handle('open-external', (event, url) => {
    if (!trusted(event) || typeof url !== 'string') return;
    try { if (['http:', 'https:'].includes(new URL(url).protocol)) return shell.openExternal(url); } catch { /* invalid URL */ }
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event, url) => {
    const allowed = bootstrap.dev ? new URL(url).origin === 'http://localhost:5173' : url.split(/[?#]/)[0] === pathToFileURL(path.join(root, 'dist/index.html')).href;
    if (!allowed) event.preventDefault();
  });
  window.on('close', event => {
    if (closing) return;
    event.preventDefault(); closing = true;
    rpc({ action: 'close' }).catch(() => {}).finally(() => { control?.disconnect(); window.destroy(); app.quit(); });
  });
  if (bootstrap.dev) await window.loadURL('http://localhost:5173');
  else await window.loadFile(path.join(root, 'dist/index.html'));
  if (!bootstrap.hide) window.show();
  publish(state);
}).catch(error => { console.error(error.message); app.exit(1); });
app.on('window-all-closed', () => { control?.disconnect(); app.quit(); });
