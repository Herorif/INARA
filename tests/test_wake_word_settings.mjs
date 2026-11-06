import test from 'node:test';
import assert from 'node:assert/strict';
import {
  WAKE_SENSITIVITIES, WAKE_SWITCH_LABEL, WAKE_WORD_HELP, WAKE_WORD_LABEL,
  sensitivityHelp, sensitivityPatch, wakeStatusText, wakeWordChoice, wakeWordPatch,
} from '../src/features/settings/wakeWordModel.js';
import { segmentItems } from '../src/features/settings/segmentedControlModel.js';
import { VOICE_MODES } from '../src/features/settings/voiceSettingsModel.js';

test('saved "Hey Jarvis" values read with the core defaults', () => {
  assert.deepEqual(wakeWordChoice(null), { enabled: true, sensitivity: 'normal' });
  assert.deepEqual(wakeWordChoice({}), { enabled: true, sensitivity: 'normal' });
  assert.deepEqual(wakeWordChoice({ wake_word: false, wake_sensitivity: 'high' }), { enabled: false, sensitivity: 'high' });
  assert.deepEqual(wakeWordChoice({ wake_word: 'false', wake_sensitivity: 'loud' }), { enabled: true, sensitivity: 'normal' });
  assert.deepEqual(wakeWordChoice({ wake_word: 0, wake_sensitivity: 'Low' }), { enabled: true, sensitivity: 'normal' });
  assert.deepEqual(wakeWordChoice({ wake_sensitivity: 'constructor' }), { enabled: true, sensitivity: 'normal' });
  assert.deepEqual(wakeWordChoice({ wake_sensitivity: 'low' }), { enabled: true, sensitivity: 'low' });
});

test('copy and the help for each sensitivity', () => {
  assert.equal(WAKE_WORD_LABEL, 'Listen for "Hey Jarvis"');
  assert.equal(WAKE_SWITCH_LABEL, 'Listen for "Hey Jarvis"');
  assert.equal(WAKE_WORD_HELP, 'Say "Hey Jarvis" to talk to JARVIS from anywhere, even with this window closed. The microphone stays on to listen for the phrase, and nothing leaves this PC until JARVIS hears it.');
  assert.deepEqual(WAKE_SENSITIVITIES.map(item => [item.id, item.label]), [['low', 'Low'], ['normal', 'Normal'], ['high', 'High']]);
  assert.equal(sensitivityHelp('low'), 'Responds only to a clear "Hey Jarvis". Fewest false starts.');
  assert.equal(sensitivityHelp('normal'), 'Balanced for a typical room.');
  assert.equal(sensitivityHelp('high'), 'Hears you from further away, but may start by mistake more often.');
  assert.equal(sensitivityHelp('bogus'), 'Balanced for a typical room.');
});

test('the status line for each state', () => {
  assert.equal(wakeStatusText({ state: 'listening', message: null }), 'Listening for "Hey Jarvis".');
  assert.equal(wakeStatusText({ state: 'paused', message: null }), 'Paused while gaming mode is on.');
  assert.equal(wakeStatusText({ state: 'unavailable', message: 'No microphone is connected.' }), 'No microphone is connected.');
  assert.equal(wakeStatusText({ state: 'unavailable', message: null }), '');
  assert.equal(wakeStatusText({ state: 'off', message: null }), '');
  assert.equal(wakeStatusText(null), '');
  assert.equal(wakeStatusText({ state: 'toString' }), '');
});

test('choosing the value already saved saves nothing', () => {
  const on = wakeWordChoice({ wake_word: true, wake_sensitivity: 'normal' });
  assert.equal(wakeWordPatch(on, true), null);
  assert.deepEqual(wakeWordPatch(on, false), { voice: { wake_word: false } });
  assert.deepEqual(wakeWordPatch(wakeWordChoice({ wake_word: false }), true), { voice: { wake_word: true } });
  assert.equal(wakeWordPatch(on, 'off'), null);
  assert.equal(sensitivityPatch(on, 'normal'), null);
  assert.equal(sensitivityPatch(on, 'loud'), null);
  assert.deepEqual(sensitivityPatch(on, 'high'), { voice: { wake_sensitivity: 'high' } });
  // A missing value reads as the default, so choosing the default saves nothing.
  assert.equal(sensitivityPatch(wakeWordChoice({}), 'normal'), null);
});

test('SegmentedControl maps options to checked radios', () => {
  assert.deepEqual(segmentItems(WAKE_SENSITIVITIES, 'high'), [
    { id: 'low', label: 'Low', checked: false },
    { id: 'normal', label: 'Normal', checked: false },
    { id: 'high', label: 'High', checked: true },
  ]);
  assert.deepEqual(segmentItems(VOICE_MODES, 'push_to_talk'), [
    { id: 'push_to_talk', label: 'Push to talk', checked: true },
    { id: 'conversation', label: 'Conversation', checked: false },
  ]);
  assert.deepEqual(segmentItems(VOICE_MODES, 'bogus').filter(item => item.checked), []);
  assert.deepEqual(segmentItems(null, 'x'), []);
});
