import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import {
  BRAIN_CHECK_BUSY, BRAIN_CHECK_BUTTON, BRAIN_CHECK_HELP, BRAIN_CHECK_LABEL,
  brainCheckLine, brainCheckLines, checkSeconds, weatherCheckLine,
} from '../src/features/settings/aiSettingsModel.js';
import { createSecretsClient, isBrainCheck } from '../src/transport/secretsClient.ts';

const brain = (extra = {}) => ({ ok: true, provider: 'claude', model: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5', effort: 'medium', ms: 1800, ...extra });
const weather = (extra = {}) => ({ ok: true, place: 'Kuala Lumpur, Malaysia', ms: 400, ...extra });

test('check row text', () => {
  assert.equal(BRAIN_CHECK_LABEL, 'Check the brain');
  assert.equal(BRAIN_CHECK_HELP, 'Sends one short test message and a weather lookup, and shows how long each took.');
  assert.equal(BRAIN_CHECK_BUTTON, 'Run a check');
  assert.equal(BRAIN_CHECK_BUSY, 'Checking…');
});

test('seconds read plainly', () => {
  assert.equal(checkSeconds(1800), '1.8 s');
  assert.equal(checkSeconds(400), '0.4 s');
  assert.equal(checkSeconds(12345), '12.3 s');
  assert.equal(checkSeconds(40), 'under 0.1 s');
  assert.equal(checkSeconds(undefined), '');
  assert.equal(checkSeconds(-1), '');
});

test('brain line names the model, the effort and the time', () => {
  assert.deepEqual(brainCheckLine(brain()), { tone: 'ok', text: 'Claude Sonnet 5.5 · Medium effort answered in 1.8 s' });
  assert.deepEqual(brainCheckLine(brain({ provider: 'gemini', model: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash', effort: null })),
    { tone: 'ok', text: 'Gemini 3.8 Flash answered in 1.8 s' });
  assert.equal(brainCheckLine(brain({ label: null })).text, 'claude-sonnet-5-5 · Medium effort answered in 1.8 s');
  assert.deepEqual(brainCheckLine(brain({ ok: false, code: 'provider_not_configured', message: 'Add an Anthropic key.' })),
    { tone: 'warn', text: 'Add an Anthropic key.' });
  assert.equal(brainCheckLine(brain({ ok: false, message: '' })).tone, 'warn');
  assert.equal(brainCheckLine(undefined).tone, 'warn');
});

test('weather line names the place, or says why it did not run', () => {
  assert.deepEqual(weatherCheckLine(weather()), { tone: 'ok', text: 'Weather for Kuala Lumpur, Malaysia in 0.4 s' });
  assert.deepEqual(weatherCheckLine({ ok: false, skipped: true, code: 'need_place', message: 'Set your home town above to include a weather check.' }),
    { tone: 'idle', text: 'Set your home town above to include a weather check.' });
  assert.deepEqual(weatherCheckLine({ ok: false, code: 'unavailable', message: "The weather service couldn't be reached.", ms: 9000 }),
    { tone: 'warn', text: "The weather service couldn't be reached." });
  assert.deepEqual(brainCheckLines({ brain: brain(), weather: weather() }).map((line) => line.tone), ['ok', 'ok']);
  assert.equal(brainCheckLines(null).length, 2);
});

class Socket extends EventEmitter {
  connected = true;
  requests = [];
  emit(event, ...args) {
    if (event === 'brain_check') { this.requests.push({ event, data: args[0], ack: args[1] }); return true; }
    return super.emit(event, ...args);
  }
}

test('brainCheck sends an empty request and validates the answer', async () => {
  const socket = new Socket();
  const client = createSecretsClient(socket);
  const done = client.brainCheck();
  assert.deepEqual(socket.requests[0].data, {});
  socket.requests[0].ack({ ok: true, brain: brain(), weather: weather() });
  assert.deepEqual(await done, { brain: brain(), weather: weather() });
  const broken = client.brainCheck();
  socket.requests[1].ack({ ok: true, brain: { ok: 'yes' }, weather: weather() });
  await assert.rejects(broken, { code: 'invalid_response' });
  const refused = client.brainCheck();
  socket.requests[2].ack({ ok: false, code: 'permission_denied', message: 'This action belongs to the desktop owner.' });
  await assert.rejects(refused, { code: 'permission_denied' });
  assert.equal(isBrainCheck({ brain: brain({ ms: -5 }), weather: weather() }), false);
  assert.equal(isBrainCheck({ brain: brain(), weather: { ok: false, skipped: true, code: 'need_place', message: 'x' } }), true);
  client.dispose();
});
