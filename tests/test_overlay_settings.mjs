import test from 'node:test';
import assert from 'node:assert/strict';
import {
  OVERLAY_HELP, OVERLAY_LABEL, overlayChoice, overlayPatch,
} from '../src/features/settings/overlaySettingsModel.js';

test('the saved overlay value reads with the core default', () => {
  assert.deepEqual(overlayChoice(null), { enabled: true });
  assert.deepEqual(overlayChoice(undefined), { enabled: true });
  assert.deepEqual(overlayChoice({}), { enabled: true });
  assert.deepEqual(overlayChoice({ overlay: false }), { enabled: false });
  assert.deepEqual(overlayChoice({ overlay: true }), { enabled: true });
});

test('non-boolean overlay values read as on', () => {
  assert.deepEqual(overlayChoice({ overlay: 'false' }), { enabled: true });
  assert.deepEqual(overlayChoice({ overlay: 0 }), { enabled: true });
  assert.deepEqual(overlayChoice({ overlay: null }), { enabled: true });
  assert.deepEqual(overlayChoice('voice'), { enabled: true });
});

test('patches save only a real change', () => {
  const on = overlayChoice({ overlay: true });
  assert.equal(overlayPatch(on, true), null);
  assert.deepEqual(overlayPatch(on, false), { voice: { overlay: false } });
  assert.deepEqual(overlayPatch(overlayChoice({ overlay: false }), true), { voice: { overlay: true } });
  assert.equal(overlayPatch(on, 'off'), null);
  assert.equal(overlayPatch(on, 0), null);
  assert.equal(overlayPatch(overlayChoice({}), true), null);
});

test('copy', () => {
  assert.equal(OVERLAY_LABEL, 'Show JARVIS while you talk');
  assert.equal(OVERLAY_HELP, 'A small panel above the taskbar shows what you and JARVIS say when you talk from the tray or say "Hey Jarvis". It never takes the keyboard, is hidden from screen sharing, and closes itself when you’re done.');
});
