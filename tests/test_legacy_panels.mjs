import test from 'node:test';
import assert from 'node:assert/strict';
import { permissionOption, permissionValue, PERMISSION_OPTIONS } from '../src/components/toolPermissions.js';
import { privateLanHost, printerWebUrl } from '../src/components/printerHost.js';

test('stored permission values map to the three backend policies', () => {
  const stored = { a: 'deny', b: true, c: false, d: 'allow_within_scope', legacy_generated_cad: true };
  assert.equal(permissionOption(stored, 'a'), 'never');
  assert.equal(permissionOption(stored, 'b'), 'ask');
  assert.equal(permissionOption(stored, 'c'), 'allow');
  assert.equal(permissionOption(stored, 'd'), 'allow');
  assert.equal(permissionOption(stored, 'legacy_generated_cad'), 'ask');
});

test('missing keys show the backend default', () => {
  assert.equal(permissionOption({}, 'legacy_generated_cad'), 'never');
  assert.equal(permissionOption({}, 'write_file'), 'ask');
  assert.equal(permissionOption(undefined, 'legacy_generated_cad'), 'never');
  assert.equal(permissionOption(null, 'read_file'), 'ask');
  // Inherited properties are not stored values.
  assert.equal(permissionOption(Object.create({ write_file: false }), 'write_file'), 'ask');
});

test('unrecognised stored values ask, like the backend', () => {
  assert.equal(permissionOption({ x: 'maybe' }, 'x'), 'ask');
  assert.equal(permissionOption({ legacy_generated_cad: null }, 'legacy_generated_cad'), 'ask');
});

test('options send the exact values the settings schema accepts', () => {
  assert.equal(permissionValue('never'), 'deny');
  assert.equal(permissionValue('ask'), true);
  assert.equal(permissionValue('allow'), false);
  assert.throws(() => permissionValue('sometimes'));
  assert.deepEqual(PERMISSION_OPTIONS.map(option => option.label), ['Never', 'Ask first', 'Allow']);
  for (const option of PERMISSION_OPTIONS) assert.equal(permissionOption({ k: option.value }, 'k'), option.id);
});

test('printer web URLs are built only for private-LAN hosts', () => {
  for (const host of ['192.168.1.50', '10.0.0.2', '172.16.4.1', '172.31.255.254', 'voron', 'printer.local', 'K1.LAN', 'octo.home.arpa', ' 192.168.0.9 '])
    assert.ok(printerWebUrl(host), host);
  assert.equal(printerWebUrl('K1.LAN'), 'http://k1.lan');
  for (const host of ['8.8.8.8', '172.32.0.1', '127.0.0.1', '169.254.1.1', '192.168.1.256', '192.168.01.5', '0.0.0.0',
    'localhost', 'example.com', 'printer.test', 'evil.com/.local', 'a@192.168.1.5', '192.168.1.5:80', '192.168.1.5/x',
    'printer.local.evil.com', '[::1]', '', null, undefined, 42, '.local', '-bad.local', '1234'])
    assert.equal(printerWebUrl(host), null, String(host));
  assert.equal(privateLanHost('Printer.Local'), 'printer.local');
});
