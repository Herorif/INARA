// Real Electron/backend lifecycle test. All data is isolated; windows/balloons stay hidden.
const {
  app,
  BrowserWindow,
  Tray
} = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const {
  execFileSync
} = require('child_process');
const assert = require('assert/strict');
const root = path.join(__dirname, '..');
const outputBase = path.join(root, '.runtime', 'resident-qa');
const output = path.join(outputBase, `run-${Date.now()}`);
fs.mkdirSync(output, {
  recursive: true
});
app.setPath('userData', output);
process.env.INARA_DATA_DIR = path.join(output, 'database');
process.env.INARA_SETTINGS_FILE = path.join(output, 'settings.json');
process.env.INARA_PROJECT_ROOT = path.join(output, 'workspace');
process.env.INARA_LEGACY_DATA_DIR = path.join(output, 'legacy');
process.env.INARA_PYTHON = path.join(root, '.venv/Scripts/python.exe');
process.env.INARA_DEV_SERVER = '0';
BrowserWindow.prototype.show = function () {};
let balloons = 0;
Tray.prototype.displayBalloon = function () {
  balloons++;
};
const desktop = require('../electron/desktop');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const until = async (predicate, timeout = 25000) => {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await sleep(200);
  }
  throw new Error('Integration condition timed out');
};
const status = () => new Promise(resolve => {
  const request = http.get('http://127.0.0.1:8000/status', response => {
    let body = '';
    response.on('data', chunk => body += chunk);
    response.on('end', () => {
      try {
        resolve(JSON.parse(body));
      } catch {
        resolve(null);
      }
    });
  });
  request.on('error', () => resolve(null));
  request.setTimeout(1000, () => request.destroy());
});
app.whenReady().then(async () => {
  try {
    await until(() => desktop.controller.state.phase === 'ready');
    await until(() => fs.existsSync(path.join(output, 'resident-identity.json')));
    const identity = JSON.parse(fs.readFileSync(path.join(output, 'resident-identity.json')));
    const pid = desktop.backendPID();
    const before = app.getAppMetrics().map(metric => ({
      pid: metric.pid,
      memoryMB: metric.memory.workingSetSize / 1024
    }));
    desktop.controller.close();
    await until(() => !desktop.window());
    await until(async () => (await status())?.resources.state === 'resident');
    const residentMetrics = app.getAppMetrics().map(metric => ({
      pid: metric.pid,
      memoryMB: metric.memory.workingSetSize / 1024
    }));
    const python = code => execFileSync(process.env.INARA_PYTHON, ['-c', code], {
      cwd: root,
      env: {
        ...process.env,
        PYTHONPATH: path.join(root, 'backend')
      },
      encoding: 'utf8',
      windowsHide: true
    });
    python("import time; from core.reminder_store import ReminderStore; ReminderStore().add_reminder('INARA lifecycle QA',time.time()-1)");
    await until(() => balloons > 0);
    const deliveries = JSON.parse(python(`import json; from core.reminder_store import ReminderStore; print(json.dumps(ReminderStore().open_deliveries('${identity.id}')))`));
    assert.equal(deliveries.length, 1);
    assert.equal(deliveries[0].state, 'acknowledged');
    desktop.controller.open();
    await until(() => !!desktop.window());
    assert.equal(desktop.backendPID(), pid);
    desktop.controller.mode(true);
    await until(async () => (await status())?.resources.state === 'gaming');
    const backendMemory = execFileSync('powershell.exe', ['-NoProfile', '-Command', `(Get-Process -Id ${pid}).WorkingSet64 / 1MB`], {
      encoding: 'utf8',
      windowsHide: true
    }).trim();
    fs.writeFileSync(path.join(outputBase, 'verification.json'), JSON.stringify({
      closeReopenSameBackend: true,
      residentReminderAcknowledged: true,
      gamingEnforced: true,
      before,
      residentMetrics,
      backendWorkingSetMB: Number(backendMemory),
      note: 'One startup snapshot, not a ten-minute idle/gaming benchmark.'
    }, null, 2));
    await desktop.controller.quit();
    await until(async () => !(await status()), 5000);
    console.log('Native resident close/reopen, reminder receipt, gaming policy and explicit quit passed.');
    app.exit(0);
  } catch (error) {
    console.error(error);
    await desktop.controller.quit();
    app.exit(1);
  }
});
