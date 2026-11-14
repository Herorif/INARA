import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import {
  ADDRESS_LABEL, ADDRESS_NAME_HINT, ADDRESS_OPTIONS, addressHint, addressOption,
  activeModelText, brainOption, brainProblem, CLAUDE_WITHOUT_KEY, rejectedMessage, rpcFailureMessage,
  saveResultMessage, secretChip, testResultMessage,
} from '../src/features/settings/aiSettingsModel.js';
import { createSecretsClient } from '../src/transport/secretsClient.ts';

const status = (extra = {}) => ({ name: 'anthropic_api_key', label: 'Anthropic API key', configured: true, source: 'store', hint: '1234', verified_at: null, last_check: null, ...extra });
const check = (code) => ({ ok: code === 'ok', code, at: '2026-10-26T00:00:00+00:00' });

test('key status maps to the five chips', () => {
  assert.deepEqual(secretChip(undefined), { tone: 'idle', label: 'NOT SET', envOverride: false });
  assert.deepEqual(secretChip(status({ configured: false, source: null, hint: null })), { tone: 'idle', label: 'NOT SET', envOverride: false });
  assert.deepEqual(secretChip(status()), { tone: 'warn', label: 'SAVED · NOT VERIFIED', envOverride: false });
  assert.deepEqual(secretChip(status({ last_check: check('network_error') })), { tone: 'warn', label: 'SAVED · NOT VERIFIED', envOverride: false });
  assert.deepEqual(secretChip(status({ last_check: check('ok'), verified_at: 'x' })), { tone: 'ok', label: 'VERIFIED ··1234', envOverride: false, hint: '1234' });
  assert.equal(secretChip(status({ verified_at: 'x' })).label, 'VERIFIED ··1234');
  assert.deepEqual(secretChip(status({ last_check: check('invalid_key') })), { tone: 'danger', label: 'REJECTED', envOverride: false });
  // Env wins even when its last check failed.
  assert.deepEqual(secretChip(status({ source: 'env', last_check: check('invalid_key') })), { tone: 'accent', label: 'ENV OVERRIDE', envOverride: true });
});

test('save results are plain and say whether a key was kept', () => {
  assert.deepEqual(saveResultMessage('anthropic_api_key', status({ last_check: check('ok') })), { tone: 'ok', text: 'Key saved and verified.' });
  for (const code of ['network_error', 'tls_error', 'rate_limited', 'unexpected', 'something_new']) {
    assert.deepEqual(saveResultMessage('anthropic_api_key', status({ last_check: check(code) })),
      { tone: 'warn', text: "Couldn't reach the service — the key was saved but not verified." });
  }
  assert.deepEqual(rejectedMessage('anthropic_api_key', true), { tone: 'danger', text: 'This key was rejected by Anthropic. Your previous key was kept.' });
  assert.deepEqual(rejectedMessage('anthropic_api_key', false), { tone: 'danger', text: 'This key was rejected by Anthropic. It was not saved.' });
  assert.equal(rejectedMessage('gemini_api_key', false).text, 'This key was rejected by Google. It was not saved.');
  for (const message of [saveResultMessage('x', null), rejectedMessage('x', true), testResultMessage('gemini_api_key', status({ last_check: check('ok') }))]) {
    assert.doesNotMatch(message.text, /!/);
  }
});

test('test results mirror the core check messages', () => {
  assert.equal(testResultMessage('anthropic_api_key', status({ last_check: check('ok') })).text, 'Anthropic accepted this key.');
  assert.equal(testResultMessage('gemini_api_key', status({ last_check: check('invalid_key') })).text, 'This key was rejected by Google.');
  assert.equal(testResultMessage('gemini_api_key', status({ last_check: check('network_error') })).text, "Couldn't reach the service. Check your connection.");
});

test('transport failures never surface Studio wording', () => {
  for (const code of ['offline', 'disconnected', 'timeout', 'invalid_response', 'send_failed', 'scope_closed']) {
    assert.doesNotMatch(rpcFailureMessage({ code, message: 'Refresh revision history before using Studio.' }), /Studio|revision/);
  }
  assert.equal(rpcFailureMessage({ code: 'invalid_format', message: 'Anthropic keys start with sk-ant-.' }), 'Anthropic keys start with sk-ant-.');
  assert.equal(rpcFailureMessage(undefined), 'The request did not finish. Try again.');
});

test('brain helper text and Claude-without-key problem', () => {
  assert.equal(activeModelText({ setting: 'auto', provider: 'claude', model: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5', configured: true }), 'Using Claude Sonnet 5.5 · Medium effort');
  assert.equal(activeModelText({ setting: 'auto', provider: 'gemini', model: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash', configured: true }), 'Using Gemini (gemini-2.5-flash) (fallback)');
  assert.equal(activeModelText({ setting: 'gemini', provider: 'gemini', model: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash', configured: true }), 'Using Gemini (gemini-2.5-flash)');
  assert.equal(activeModelText(null), '');
  const noKey = { setting: 'claude', provider: 'claude', label: 'Claude Sonnet 5.5', configured: false };
  assert.equal(activeModelText(noKey), 'Using Claude Sonnet 5.5 · Medium effort (not configured)');
  assert.equal(brainProblem('claude', noKey), CLAUDE_WITHOUT_KEY);
  assert.equal(brainProblem('claude', { ...noKey, configured: true }), '');
  assert.equal(brainProblem('auto', noKey), '');
  assert.equal(brainOption({ brain: 'gemini' }), 'gemini');
  assert.equal(brainOption({ brain: 'bogus' }), 'auto');
  assert.equal(brainOption(null), 'auto');
});

class Socket extends EventEmitter {
  connected = true;
  requests = [];
  emit(event, ...args) {
    if (event.startsWith('secrets_') || event === 'capability_diagnostics' || event === 'update_settings') {
      this.requests.push({ event, data: args[0], ack: args[1] }); return true;
    }
    return super.emit(event, ...args);
  }
}

test('secrets client sends the value only on set and validates statuses', async () => {
  const socket = new Socket();
  const client = createSecretsClient(socket);
  const set = client.set('anthropic_api_key', 'sk-ant-test-value-000000000000');
  assert.deepEqual(socket.requests[0].data, { name: 'anthropic_api_key', value: 'sk-ant-test-value-000000000000', verify: true });
  socket.requests[0].ack({ ok: true, secret: status() });
  assert.equal((await set).hint, '1234');
  const rejected = client.set('anthropic_api_key', 'sk-ant-test-value-000000000000');
  socket.requests.at(-1).ack({ ok: false, code: 'key_rejected', message: 'This key was rejected by Anthropic.', check: check('invalid_key') });
  await assert.rejects(rejected, { code: 'key_rejected' });
  socket.requests.splice(1, 1);
  const tested = client.test('anthropic_api_key');
  assert.deepEqual(socket.requests[1].data, { name: 'anthropic_api_key' });
  socket.requests[1].ack({ ok: true, secret: { broken: true } });
  await assert.rejects(tested, { code: 'invalid_response' });
  const cleared = client.clear('gemini_api_key');
  socket.requests[2].ack({ ok: false, code: 'storage_error', message: 'Protected storage could not be opened. Your keys were not changed.' });
  await assert.rejects(cleared, { code: 'storage_error' });
  const listed = client.status();
  socket.requests[3].ack({ ok: true, secrets: [status(), status({ name: 'gemini_api_key', configured: false, source: null, hint: null })] });
  assert.equal((await listed).length, 2);
  const brain = client.brain();
  socket.requests[4].ack({ ok: true, brain: { setting: 'auto', provider: 'gemini', model: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash', configured: true } });
  assert.equal((await brain).provider, 'gemini');
  socket.connected = false;
  await assert.rejects(client.set('anthropic_api_key', 'sk-ant-x'), { code: 'offline' });
  assert.equal(socket.requests.length, 5, 'an offline set must not queue the value');
  client.dispose();
});

test('form of address: four options, sir by default, and the by-name hint', () => {
  assert.equal(ADDRESS_LABEL, 'How JARVIS addresses you');
  assert.deepEqual(ADDRESS_OPTIONS, [
    { id: 'sir', label: 'Sir' }, { id: 'maam', label: "Ma'am" }, { id: 'name', label: 'By name' }, { id: 'none', label: 'None' },
  ]);
  for (const id of ['sir', 'maam', 'name', 'none']) assert.equal(addressOption({ address: id }), id);
  assert.equal(addressOption({}), 'sir');
  assert.equal(addressOption({ address: 'madam' }), 'sir');
  assert.equal(addressOption(null), 'sir');
  assert.equal(ADDRESS_NAME_HINT, 'Add your name above to be addressed by name.');
  assert.equal(addressHint('name', ''), ADDRESS_NAME_HINT);
  assert.equal(addressHint('name', '   '), ADDRESS_NAME_HINT);
  assert.equal(addressHint('name', undefined), ADDRESS_NAME_HINT);
  assert.equal(addressHint('name', 'Hiro'), '');
  for (const id of ['sir', 'maam', 'none']) assert.equal(addressHint(id, ''), '');
});
