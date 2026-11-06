// Quick assistant switching (electron/quick-mode.cjs): the window applies a mode only when it
// changes, so the page echoing a switch back can never loop (the live-run Ctrl+Shift+Space bug).
const test = require('node:test');
const assert = require('node:assert/strict');
const { createQuickMode } = require('../electron/quick-mode.cjs');

test('a mode is applied once, and repeating it does nothing', () => {
  const applied = [];
  const quick = createQuickMode(false, value => applied.push(value));
  assert.equal(quick.get(), false);
  assert.equal(quick.set(true), true);
  assert.equal(quick.set(true), false);
  assert.equal(quick.set(false), true);
  assert.equal(quick.set(false), false);
  assert.deepEqual(applied, [true, false]);
  assert.equal(quick.get(), false);
});

test('the initial mode counts as applied; only booleans true mean quick', () => {
  const applied = [];
  const quick = createQuickMode(true, value => applied.push(value));
  assert.equal(quick.set(true), false);
  assert.equal(quick.set('yes'), true); // not true: full size
  assert.equal(quick.set(undefined), false);
  assert.deepEqual(applied, [false]);
});

test('the page echoing every switch back ends after one switch', () => {
  // Simulates the window and the page: each switch the window applies is sent to the page,
  // and the old page sent the same value straight back. That used to loop forever.
  const sent = [];
  let quick;
  const page = value => { sent.push(value); quick.set(value); }; // the echo
  quick = createQuickMode(false, value => page(value));
  quick.set(true); // Ctrl+Shift+Space
  assert.deepEqual(sent, [true]);
  quick.set(false); // the quick assistant's close button
  assert.deepEqual(sent, [true, false]);
});
