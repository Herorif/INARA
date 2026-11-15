import test from 'node:test';
import assert from 'node:assert/strict';
import {
  EXPORT_FAILED, EXPORT_LABEL, EXPORTING_LABEL, HEADING, TEXT_HELP, TEXT_LABEL,
  diagnosticsChoice, exportResult, includeTextPatch,
} from '../src/features/settings/diagnosticsModel.js';

test('include_text reads as off unless it is exactly true', () => {
  for (const value of [null, undefined, {}, 'x', { include_text: 'true' }, { include_text: 1 }, { include_text: false }]) {
    assert.deepEqual(diagnosticsChoice(value), { includeText: false });
  }
  assert.deepEqual(diagnosticsChoice({ include_text: true, folder: '' }), { includeText: true });
});

test('the switch patches only a real change', () => {
  const off = diagnosticsChoice({});
  assert.deepEqual(includeTextPatch(off, true), { diagnostics: { include_text: true } });
  assert.equal(includeTextPatch(off, false), null);
  assert.equal(includeTextPatch(off, 'on'), null);
  assert.deepEqual(includeTextPatch(diagnosticsChoice({ include_text: true }), false), { diagnostics: { include_text: false } });
});

test('the export result shows the path or the core message', () => {
  const path = 'C:\\repo\\.runtime\\live-logs\\diagnostics-20261115-093005.zip';
  assert.deepEqual(exportResult({ ok: true, path }), { tone: 'ok', text: `Saved to ${path}`, path });
  assert.deepEqual(exportResult({ ok: false, message: 'Diagnostics couldn’t be saved. Check that the folder can be written to.' }),
    { tone: 'danger', text: 'Diagnostics couldn’t be saved. Check that the folder can be written to.' });
  const error = new Error('The core did not respond.');
  assert.deepEqual(exportResult(error), { tone: 'danger', text: 'The core did not respond.' });
  for (const bad of [null, undefined, { ok: true }, { ok: true, path: '' }, 'ok']) {
    assert.deepEqual(exportResult(bad), { tone: 'danger', text: EXPORT_FAILED });
  }
});

test('copy', () => {
  assert.equal(HEADING, 'Diagnostics');
  assert.equal(EXPORT_LABEL, 'Export diagnostics');
  assert.equal(EXPORTING_LABEL, 'Exporting…');
  assert.equal(TEXT_LABEL, 'Include message text in traces');
  assert.equal(TEXT_HELP, 'Off by default. Turn on only while you need help with a problem.');
});
