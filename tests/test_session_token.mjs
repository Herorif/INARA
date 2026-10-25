import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {build, loadConfigFromFile} from 'vite';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CANARY = 'CANARY-dev-session-token-7f3e9a';
const ENV = 'VITE_INARA_SESSION_TOKEN';

// Bundle only the socket module (in memory) with the token present in the build environment.
const bundle = async (t, mode) => {
  const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'inara-socket-build-'));
  // Vite derives import.meta.env.DEV from NODE_ENV, which a production build sets process-wide.
  const previous = {[ENV]: process.env[ENV], NODE_ENV: process.env.NODE_ENV};
  process.env[ENV] = CANARY;
  process.env.NODE_ENV = mode;
  t.after(() => {
    for (const [key, value] of Object.entries(previous)) if (value === undefined) delete process.env[key]; else process.env[key] = value;
    fs.rmSync(outDir, {recursive: true, force: true});
  });
  const result = await build({
    configFile: false, root, mode, logLevel: 'silent',
    build: {write: false, outDir, emptyOutDir: false, rollupOptions: {input: path.join(root, 'src/services/socket.js')}},
  });
  return [result].flat().flatMap(item => item.output).map(chunk => chunk.code || String(chunk.source)).join('\n');
};

test('production build of socket.js drops VITE_INARA_SESSION_TOKEN even when it is set', async t => {
  const code = await bundle(t, 'production');
  assert.ok(code.includes('client_id'), 'bundled the socket module');
  assert.equal(code.includes(CANARY), false);
  assert.equal(code.includes(ENV), false);
});

test('development bundle still carries the dev token (guard is import.meta.env.DEV)', async t => {
  assert.ok((await bundle(t, 'development')).includes(CANARY));
});

test('vite.config blanks the token for builds and only reads it when serving', async t => {
  const previous = process.env[ENV];
  process.env[ENV] = CANARY;
  t.after(() => { if (previous === undefined) delete process.env[ENV]; else process.env[ENV] = previous; });
  const load = command => loadConfigFromFile({command, mode: command === 'build' ? 'production' : 'development'},
    path.join(root, 'vite.config.js'), root, 'silent');
  const built = await load('build'), served = await load('serve');
  assert.equal(built.config.define[`import.meta.env.${ENV}`], '""');
  assert.equal(served.config.define[`import.meta.env.${ENV}`], JSON.stringify(CANARY));
  const source = fs.readFileSync(path.join(root, 'src/services/socket.js'), 'utf8');
  assert.match(source, /import\.meta\.env\.DEV \? import\.meta\.env\.VITE_INARA_SESSION_TOKEN : ''/);
  assert.match(source, /window\.electronAPI\?\.sessionToken \|\| devSessionToken/);
});
