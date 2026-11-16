// S7.5 screen help (docs/SCREEN_HELP.md): the approval card and the capture notice.
import test from 'node:test';
import assert from 'node:assert/strict';
import { approvalView } from '../src/components/approvalView.js';
import { SCREEN_LOOK_MS, SCREEN_LOOK_TEXT, screenLookVisible } from '../src/features/screen/screenLookModel.js';

test('the look_at_screen card names the whole screen or the active window', () => {
  const whole = approvalView({ id: 'a', tool: 'look_at_screen', args: { question: "what's this error?", region: 'whole' } });
  assert.deepEqual(whole, {
    kind: 'screen_look', title: 'Look at your screen?',
    summary: "JARVIS takes one screenshot of the whole screen to answer you. It goes only to your AI provider and isn't saved.",
    approveLabel: 'Allow once', denyLabel: 'Not now', details: null,
  });
  const window = approvalView({ id: 'b', tool: 'look_at_screen', args: { question: 'what is this?', region: 'window' } });
  assert.equal(window.summary, "JARVIS takes one screenshot of the active window to answer you. It goes only to your AI provider and isn't saved.");
  // No region (or anything unexpected) means the whole screen, as the core's default.
  assert.match(approvalView({ id: 'c', tool: 'look_at_screen', args: {} }).summary, /of the whole screen/);
  assert.equal(approvalView({ id: 'd', tool: 'look_at_screen' }).details, null);
});

test('the notice shows while capturing for at most one second', () => {
  assert.equal(SCREEN_LOOK_TEXT, 'Looking at your screen…');
  assert.ok(SCREEN_LOOK_MS <= 1000);
  assert.equal(screenLookVisible({ state: 'capturing', region: 'whole' }), true);
  assert.equal(screenLookVisible({ state: 'done' }), false);
  for (const value of [null, undefined, {}, { state: 'other' }, 'capturing']) assert.equal(screenLookVisible(value), null);
});
