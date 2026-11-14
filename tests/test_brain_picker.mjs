import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import {
  BRAIN_CHOICES, EFFORT_GEMINI_HELP, EFFORT_HELP, EFFORT_OPTIONS, GEMINI_LIST_FAILED,
  activeModelText, brainChoice, brainChoicePatch, effortDisabled, effortHelp, effortOption, effortPatch,
  geminiModelOptions, geminiModelPatch, geminiModelValue,
} from '../src/features/settings/aiSettingsModel.js';
import { createSecretsClient } from '../src/transport/secretsClient.ts';

test('the Brain select lists four choices in order', () => {
  assert.deepEqual(BRAIN_CHOICES.map((c) => [c.id, c.label]), [
    ['auto', 'Auto (Claude when a key is set)'],
    ['sonnet', 'Claude Sonnet 5.5 — smartest'],
    ['haiku', 'Claude Haiku 5.5 — fastest, cheapest'],
    ['gemini', 'Gemini'],
  ]);
  assert.deepEqual(EFFORT_OPTIONS.map((e) => e.label), ['Low', 'Medium', 'High']);
  assert.equal(GEMINI_LIST_FAILED, "Couldn't load the model list.");
});

test('settings map to a choice, including stale values', () => {
  assert.equal(brainChoice({ brain: 'auto', claude_model: 'claude-haiku-5-5' }), 'auto');
  assert.equal(brainChoice({ brain: 'claude', claude_model: 'claude-sonnet-5-5' }), 'sonnet');
  assert.equal(brainChoice({ brain: 'claude', claude_model: 'claude-haiku-5-5' }), 'haiku');
  assert.equal(brainChoice({ brain: 'claude' }), 'sonnet');
  assert.equal(brainChoice({ brain: 'claude', claude_model: 'claude-opus-9' }), 'sonnet');
  assert.equal(brainChoice({ brain: 'gemini', claude_model: 'claude-haiku-5-5' }), 'gemini');
  assert.equal(brainChoice({ brain: 'bogus' }), 'auto');
  assert.equal(brainChoice(null), 'auto');
  assert.equal(brainChoice(undefined), 'auto');
});

test('a choice maps to one settings patch', () => {
  const auto = { brain: 'auto', claude_model: 'claude-haiku-5-5' };
  assert.deepEqual(brainChoicePatch('sonnet', auto), { assistant: { brain: 'claude', claude_model: 'claude-sonnet-5-5' } });
  assert.deepEqual(brainChoicePatch('haiku', auto), { assistant: { brain: 'claude', claude_model: 'claude-haiku-5-5' } });
  assert.deepEqual(brainChoicePatch('gemini', auto), { assistant: { brain: 'gemini' } });
  // Auto keeps claude_model as it is.
  assert.deepEqual(brainChoicePatch('auto', { brain: 'claude', claude_model: 'claude-haiku-5-5' }), { assistant: { brain: 'auto' } });
  assert.deepEqual(brainChoicePatch('haiku', { brain: 'claude', claude_model: 'claude-sonnet-5-5' }), { assistant: { brain: 'claude', claude_model: 'claude-haiku-5-5' } });
  // Unchanged or unknown: nothing to save.
  assert.equal(brainChoicePatch('auto', auto), null);
  assert.equal(brainChoicePatch('sonnet', { brain: 'claude', claude_model: 'stale' }), null);
  assert.equal(brainChoicePatch('bogus', auto), null);
  // Round trip: every choice reads back as itself.
  for (const { id } of BRAIN_CHOICES) {
    const start = id === 'auto' ? { brain: 'gemini' } : { brain: 'auto' };
    assert.equal(brainChoice({ ...start, ...brainChoicePatch(id, start).assistant }), id);
  }
});

test('active model line: Claude with its effort, Gemini with its model', () => {
  const sonnet = { setting: 'claude', provider: 'claude', model: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5', configured: true, effort: 'medium' };
  assert.equal(activeModelText(sonnet), 'Using Claude Sonnet 5.5 · Medium effort');
  assert.equal(activeModelText({ ...sonnet, effort: 'high' }), 'Using Claude Sonnet 5.5 · High effort');
  assert.equal(activeModelText({ ...sonnet, model: 'claude-haiku-5-5', label: 'Claude Haiku 5.5', effort: 'low' }), 'Using Claude Haiku 5.5 · Low effort');
  // No effort in the snapshot: the saved one, else medium.
  assert.equal(activeModelText({ ...sonnet, effort: undefined }, { effort: 'low' }), 'Using Claude Sonnet 5.5 · Low effort');
  assert.equal(activeModelText({ ...sonnet, effort: 'xhigh' }, { effort: 'bogus' }), 'Using Claude Sonnet 5.5 · Medium effort');
  const gemini = { setting: 'gemini', provider: 'gemini', model: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash', configured: true, effort: 'high' };
  assert.equal(activeModelText(gemini), 'Using Gemini (gemini-3.8-flash)');
  assert.equal(activeModelText({ ...gemini, setting: 'auto' }), 'Using Gemini (gemini-3.8-flash) (fallback)');
  assert.equal(activeModelText({ ...sonnet, configured: false }), 'Using Claude Sonnet 5.5 · Medium effort (not configured)');
  assert.equal(activeModelText(null), '');
});

test('effort: medium by default, one patch per change, disabled when the brain is Gemini', () => {
  assert.equal(effortOption({}), 'medium');
  assert.equal(effortOption({ effort: 'max' }), 'medium');
  assert.equal(effortOption({ effort: 'high' }), 'high');
  assert.deepEqual(effortPatch('high', { effort: 'medium' }), { assistant: { effort: 'high' } });
  assert.deepEqual(effortPatch('low', {}), { assistant: { effort: 'low' } });
  assert.equal(effortPatch('medium', {}), null);
  assert.equal(effortPatch('max', {}), null);

  const claude = { provider: 'claude' }, gemini = { provider: 'gemini' };
  assert.equal(effortDisabled('gemini', claude, true), true);
  assert.equal(effortDisabled('claude', gemini, false), false);
  assert.equal(effortDisabled('auto', claude, false), false);
  assert.equal(effortDisabled('auto', gemini, true), true);
  // Before the snapshot loads, Auto follows the Anthropic key status.
  assert.equal(effortDisabled('auto', null, false), true);
  assert.equal(effortDisabled('auto', null, true), false);
  assert.equal(effortDisabled('auto', null, undefined), false);
  assert.equal(effortHelp(false), EFFORT_HELP);
  assert.equal(effortHelp(true), EFFORT_GEMINI_HELP);
  assert.equal(EFFORT_HELP, 'Higher effort thinks longer and costs more. Medium suits most requests.');
  assert.equal(EFFORT_GEMINI_HELP, 'Gemini manages its own thinking.');
});

test('gemini model list keeps the saved value', () => {
  const list = [{ id: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash' }, { id: 'gemini-3.8-pro', label: 'Gemini 3.8 Pro' }];
  assert.deepEqual(geminiModelOptions(list, 'gemini-3.8-pro'),
    [{ value: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash' }, { value: 'gemini-3.8-pro', label: 'Gemini 3.8 Pro' }]);
  assert.deepEqual(geminiModelOptions(list, 'gemini-2.5-flash')[0], { value: 'gemini-2.5-flash', label: 'gemini-2.5-flash' });
  assert.equal(geminiModelOptions(list, 'gemini-2.5-flash').length, 3);
  // Before the list loads, or when it failed: just the saved value.
  assert.deepEqual(geminiModelOptions(null, 'gemini-3.8-flash'), [{ value: 'gemini-3.8-flash', label: 'gemini-3.8-flash' }]);
  assert.deepEqual(geminiModelOptions(null, ''), []);
  // Malformed and duplicate entries are dropped; a blank label falls back to the id.
  assert.deepEqual(geminiModelOptions([null, { id: 'gpt-5' }, { id: 'gemini-x', label: ' ' }, { id: 'gemini-x', label: 'Again' }], ''),
    [{ value: 'gemini-x', label: 'gemini-x' }]);

  assert.equal(geminiModelValue({ gemini_model: 'gemini-3.8-pro' }, { gemini_model: 'gemini-3.8-flash' }), 'gemini-3.8-pro');
  assert.equal(geminiModelValue({}, { provider: 'claude', gemini_model: 'gemini-3.8-flash' }), 'gemini-3.8-flash');
  assert.equal(geminiModelValue({ gemini_model: '' }, { provider: 'gemini', model: 'gemini-3.8-flash' }), 'gemini-3.8-flash');
  assert.equal(geminiModelValue({ gemini_model: 'nope' }, null), '');
  assert.deepEqual(geminiModelPatch('gemini-3.8-pro', 'gemini-3.8-flash'), { assistant: { gemini_model: 'gemini-3.8-pro' } });
  assert.equal(geminiModelPatch('gemini-3.8-flash', 'gemini-3.8-flash'), null);
  assert.equal(geminiModelPatch('', 'gemini-3.8-flash'), null);
});

class Socket extends EventEmitter {
  connected = true;
  requests = [];
  emit(event, ...args) {
    if (event === 'brain_models') { this.requests.push({ event, data: args[0], ack: args[1] }); return true; }
    return super.emit(event, ...args);
  }
}

test('brainModels returns the lists and rejects a malformed answer', async () => {
  const socket = new Socket();
  const client = createSecretsClient(socket);
  const models = {
    claude: [{ id: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5', note: 'Smartest' }, { id: 'claude-haiku-5-5', label: 'Claude Haiku 5.5', note: 'Fastest, cheapest' }],
    gemini: [{ id: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash' }],
    efforts: ['low', 'medium', 'high'],
  };
  const ok = client.brainModels();
  assert.deepEqual(socket.requests[0].data, {});
  socket.requests[0].ack({ ok: true, ...models });
  assert.deepEqual(await ok, models);

  const broken = client.brainModels();
  socket.requests[1].ack({ ok: true, claude: models.claude, gemini: [{ id: 5 }], efforts: [] });
  await assert.rejects(broken, { code: 'invalid_response' });

  const failed = client.brainModels();
  socket.requests[2].ack({ ok: false, code: 'brain_models_unavailable', message: "The model list couldn't be loaded. Try again." });
  await assert.rejects(failed, { code: 'brain_models_unavailable' });
  client.dispose();
});
