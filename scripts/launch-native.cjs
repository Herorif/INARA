const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const root = path.resolve(__dirname, '..');
// Renamed from INARA on 5 Nov 2026: the pre-rename variable still works for one release.
const LEGACY_DEV_SERVER = 'INARA_DEV_SERVER';
if (process.env.JARVIS_DEV_SERVER === undefined && process.env[LEGACY_DEV_SERVER] !== undefined)
  console.warn(`${LEGACY_DEV_SERVER} is deprecated; set JARVIS_DEV_SERVER instead.`);
const development = (process.env.JARVIS_DEV_SERVER ?? process.env[LEGACY_DEV_SERVER]) === '1';
const python = path.join(root, development ? '.venv/Scripts/python.exe' : '.venv/Scripts/pythonw.exe');
if (!fs.existsSync(python)) throw Error('Run scripts/bootstrap.ps1 first.');
const child = spawn(python, [path.join(root, 'backend/resident_main.py')], {
  cwd: root, detached: !development, stdio: development ? 'inherit' : 'ignore', windowsHide: true,
  env: { ...process.env, ELECTRON_RUN_AS_NODE: '' }
});
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
if (!development) child.unref();
