const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const root = path.resolve(__dirname, '..');
const development = process.env.INARA_DEV_SERVER === '1';
const python = path.join(root, development ? '.venv/Scripts/python.exe' : '.venv/Scripts/pythonw.exe');
if (!fs.existsSync(python)) throw Error('Run scripts/bootstrap.ps1 first.');
const child = spawn(python, [path.join(root, 'backend/resident_main.py')], {
  cwd: root, detached: !development, stdio: development ? 'inherit' : 'ignore', windowsHide: true,
  env: { ...process.env, ELECTRON_RUN_AS_NODE: '' }
});
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
if (!development) child.unref();
