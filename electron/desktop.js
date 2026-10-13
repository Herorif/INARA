const {
  app,
  BrowserWindow,
  ipcMain,
  dialog,
  Tray,
  Menu,
  nativeImage,
  globalShortcut,
  Notification,
  shell
} = require('electron');
const path = require('path');
const {
  spawn
} = require('child_process');
const http = require('http');
const fs = require('fs');
const {
  randomBytes,
  randomUUID
} = require('crypto');
const {
  pathToFileURL
} = require('url');
const {
  io
} = require('socket.io-client');
const {
  ResidentController,
  waitForBackend
} = require('./resident');
const root = path.join(__dirname, '..');
const token = process.env.INARA_SESSION_TOKEN || randomBytes(32).toString('hex');
const instanceId = randomUUID();
const dev = process.env.INARA_DEV_SERVER === '1';
let mainWindow,
  backend,
  tray,
  residentSocket,
  identity,
  preferencesPath,
  booting = false;
let hotkeyReady = false;
const notificationIds = new Set();
app.setAppUserModelId('INARA.Desktop');
const ownsInstance = app.requestSingleInstanceLock();
if (!ownsInstance) app.quit();
function publish(state) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('resident-state', {
    ...state,
    hotkeyReady
  });
  if (residentSocket?.connected) residentSocket.emit('set_resource_state', {
    state: state.gaming ? 'gaming' : state.visible ? 'chat' : 'resident'
  });
  if (tray) {
    tray.setToolTip(`INARA · ${state.phase === 'failed' ? 'Backend unavailable' : state.gaming ? 'Gaming mode' : state.visible ? 'Workspace open' : 'Resident'}`);
    tray.setContextMenu(Menu.buildFromTemplate([{
      label: 'Open INARA',
      click: () => controller.open()
    }, {
      label: 'Gaming mode',
      type: 'checkbox',
      checked: state.gaming,
      click: item => setGaming(item.checked)
    }, {
      label: 'Retry backend',
      enabled: state.phase === 'failed',
      click: startBackend
    }, {
      type: 'separator'
    }, {
      label: 'Quit INARA',
      click: quit
    }]));
  }
}
function openWindow() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
    return;
  }
  if (!dev && !fs.existsSync(path.join(root, 'dist/index.html'))) {
    controller.fail('Frontend missing. Run npm run build.');
    dialog.showErrorBox('INARA frontend missing', controller.state.error);
    return;
  }
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 940,
    minWidth: 390,
    minHeight: 560,
    title: 'INARA · Command deck',
    frame: false,
    show: false,
    backgroundColor: '#080d18',
    icon: path.join(root, 'assets/icons/inara.png'),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      preload: path.join(__dirname, 'preload.js')
    }
  });
  const window = mainWindow;
  window.webContents.setWindowOpenHandler(() => ({
    action: 'deny'
  }));
  window.webContents.on('will-navigate', (event, url) => {
    const allowed = dev ? url.startsWith('http://localhost:5173/') : url.split(/[?#]/)[0] === pathToFileURL(path.join(root, 'dist/index.html')).href;
    if (!allowed) event.preventDefault();
  });
  window.on('closed', () => {
    if (mainWindow === window) mainWindow = null;
  });
  const load = dev ? window.loadURL('http://localhost:5173') : window.loadFile(path.join(root, 'dist/index.html'));
  load.then(() => {
    if (!window.isDestroyed()) {
      window.show();
      publish(controller.state);
    }
  }).catch(() => {
    controller.fail('The workspace could not load. Rebuild and reopen from the tray.');
    dialog.showErrorBox('INARA workspace unavailable', controller.state.error);
    window.destroy();
  });
}
function closeWindow() {
  residentSocket?.emit('set_resource_state', {
    state: controller.state.gaming ? 'gaming' : 'resident'
  });
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.close();
}
async function stopBackend() {
  const child = backend;
  residentSocket?.emit('shutdown');
  if (child && child.exitCode === null) {
    await new Promise(resolve => {
      const fallback = setTimeout(() => {
        if (child.exitCode === null && Number.isInteger(child.pid) && child.pid > 0) {
          if (process.platform === 'win32') spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], {
            windowsHide: true
          });else child.kill('SIGTERM');
        }
        resolve();
      }, 2000);
      child.once('exit', () => {
        clearTimeout(fallback);
        resolve();
      });
    });
  }
  residentSocket?.disconnect();
  backend = null;
}
const controller = new ResidentController({
  open: openWindow,
  close: closeWindow,
  stop: stopBackend,
  publish
});
async function quit() {
  await controller.quit();
  app.quit();
}
function saveIdentity() {
  fs.mkdirSync(path.dirname(preferencesPath), {
    recursive: true
  });
  fs.writeFileSync(`${preferencesPath}.tmp`, JSON.stringify(identity));
  fs.renameSync(`${preferencesPath}.tmp`, preferencesPath);
}
function setGaming(gaming) {
  if (identity) {
    identity.gaming = Boolean(gaming);
    saveIdentity();
  }
  controller.mode(gaming);
}
function startResidentSocket() {
  if (!identity || controller.state.phase !== 'ready') return;
  residentSocket?.disconnect();
  residentSocket = io('http://127.0.0.1:8000', {
    auth: {
      token,
      client_id: identity.id,
      role: 'resident'
    },
    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000
  });
  residentSocket.on('connect', () => publish(controller.state));
  residentSocket.on('reminder_triggered', data => {
    if (!data.delivery_id || controller.state.visible || controller.state.gaming) return;
    if (notificationIds.has(data.delivery_id)) {
      residentSocket.emit('acknowledge_reminder', {
        delivery_id: data.delivery_id
      });
      return;
    }
    const acknowledge = () => {
      notificationIds.add(data.delivery_id);
      if (notificationIds.size > 512) notificationIds.delete(notificationIds.values().next().value);
      residentSocket.emit('acknowledge_reminder', {
        delivery_id: data.delivery_id
      });
    };
    if (process.platform === 'win32' && tray) {
      tray.displayBalloon({
        title: 'INARA reminder',
        content: 'A reminder is ready. Open your command deck to view it.',
        respectQuietTime: true
      });
      acknowledge();
    } else if (Notification.isSupported()) {
      const notice = new Notification({
        title: 'INARA reminder',
        body: 'Open your command deck to view it.'
      });
      notice.on('show', acknowledge);
      notice.on('click', () => controller.open());
      notice.show();
    }
  });
}
function probe() {
  return new Promise(resolve => {
    const request = http.get('http://127.0.0.1:8000/status', response => {
      let body = '';
      response.on('data', chunk => {
        body += chunk;
        if (body.length > 16384) request.destroy();
      });
      response.on('end', () => {
        try {
          const status = JSON.parse(body);
          resolve(response.statusCode === 200 && status.instance_id === instanceId);
        } catch {
          resolve(false);
        }
      });
    });
    request.setTimeout(1000, () => request.destroy());
    request.on('error', () => resolve(false));
  });
}
async function startBackend() {
  if (booting || backend && backend.exitCode === null) return;
  booting = true;
  controller.update({
    phase: 'starting',
    error: null
  });
  const python = process.env.INARA_PYTHON || path.join(root, '.venv', 'Scripts', 'python.exe');
  backend = spawn(python, [path.join(root, 'backend/server.py')], {
    cwd: root,
    windowsHide: true,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      INARA_SESSION_TOKEN: token,
      INARA_INSTANCE_ID: instanceId
    }
  });
  const child = backend;
  let spawnFailed = false;
  child.stdout.on('data', data => process.stdout.write(data));
  child.stderr.on('data', data => process.stderr.write(data));
  child.on('error', () => {
    spawnFailed = true;
    controller.fail('Python could not start. Run scripts/bootstrap.ps1 first.');
  });
  child.on('exit', () => {
    residentSocket?.disconnect();
    if (!controller.quitting) controller.fail('Backend stopped. Check setup/storage and retry from the tray.');
  });
  try {
    await waitForBackend(probe, {
      alive: () => !spawnFailed && child.exitCode === null
    });
    controller.ready();
    startResidentSocket();
  } catch (error) {
    controller.fail(error.message);
    if (child.exitCode === null) child.kill();
  } finally {
    booting = false;
  }
}
const trusted = event => mainWindow && event.sender === mainWindow.webContents;
if (ownsInstance) app.whenReady().then(() => {
  preferencesPath = path.join(app.getPath('userData'), 'resident-identity.json');
  try {
    identity = JSON.parse(fs.readFileSync(preferencesPath, 'utf8'));
    if (!/^[0-9a-f-]{36}$/i.test(identity.id)) identity = null;
  } catch {
    identity = null;
  }
  if (identity) controller.mode(identity.gaming);
  tray = new Tray(nativeImage.createFromPath(path.join(root, 'assets/icons/inara.png')));
  tray.on('click', () => controller.open());
  tray.on('balloon-click', () => controller.open());
  hotkeyReady = globalShortcut.register('CommandOrControl+Shift+Space', () => controller.open());
  ipcMain.on('desktop-bootstrap', event => {
    event.returnValue = trusted(event) ? { token, clientId: identity?.id || '' } : {};
  });
  ipcMain.on('window-minimize', event => {
    if (trusted(event)) mainWindow.minimize();
  });
  ipcMain.on('window-maximize', event => {
    if (trusted(event)) mainWindow.isMaximized() ? mainWindow.unmaximize() : mainWindow.maximize();
  });
  ipcMain.on('window-close', event => {
    if (trusted(event)) controller.close();
  });
  ipcMain.on('app-quit', event => {
    if (trusted(event)) quit();
  });
  ipcMain.handle('resident-register', (event, id) => {
    if (!trusted(event) || !/^[0-9a-f-]{36}$/i.test(id)) return false;
    if (!identity) {
      identity = {
        id,
        gaming: controller.state.gaming
      };
      saveIdentity();
      startResidentSocket();
    }
    return identity.id === id;
  });
  ipcMain.handle('resident-status', event => trusted(event) ? {
    ...controller.state,
    hotkeyReady
  } : null);
  ipcMain.handle('resident-gaming', (event, value) => {
    if (trusted(event) && typeof value === 'boolean') setGaming(value);
  });
  ipcMain.handle('resident-metrics', event => trusted(event) ? {
    electronMemoryMB: app.getAppMetrics().reduce((total, metric) => total + (metric.memory?.workingSetSize || 0), 0) / 1024,
    backendPID: backend?.pid || null,
    electronPIDs: app.getAppMetrics().map(metric => metric.pid)
  } : null);
  ipcMain.handle('open-external', (event, url) => {
    if (!trusted(event) || typeof url !== 'string') return;
    try {
      if (['https:', 'http:'].includes(new URL(url).protocol)) return shell.openExternal(url);
    } catch {/* invalid URL */}
  });
  publish(controller.state);
  controller.open();
  startBackend();
});
app.on('second-instance', () => controller.open());
app.on('activate', () => {
  if (app.isReady()) controller.open();
});
app.on('window-all-closed', () => {
  if (!controller.quitting) controller.update({
    visible: false
  });
});
app.on('before-quit', event => {
  if (!controller.quitting) {
    event.preventDefault();
    quit();
  }
});
app.on('will-quit', () => {
  globalShortcut.unregisterAll();
  tray?.destroy();
});
// Main-process integration harness; never exposed through the renderer bridge.
module.exports = {
  controller,
  backendPID: () => backend?.pid,
  window: () => mainWindow
};
