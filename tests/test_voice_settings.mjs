import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import {
  DEFAULT_VOICE, PREVIEW_NO_KEY, PreviewPlayer, SUGGESTED_VOICES, VOICE_DESCRIPTORS, VOICE_MODES,
  decodePcm16, modeHelp, previewFailureMessage, voiceChoice, voiceGroups,
} from '../src/features/settings/voiceSettingsModel.js';
import {
  AUTO_START_WINDOW_MS, defaultVoiceMode, holdButtonTone, shouldStartConversation,
} from '../src/features/voice/defaultMode.js';
import { createSecretsClient, isVoicePreview } from '../src/transport/secretsClient.ts';

test('voices group into the suggested nine, then the other 21 alphabetically', () => {
  const { suggested, other } = voiceGroups();
  assert.deepEqual(suggested.map(item => item.name),
    ['Kore', 'Despina', 'Erinome', 'Sulafat', 'Aoede', 'Leda', 'Zephyr', 'Autonoe', 'Callirrhoe']);
  assert.deepEqual(suggested.map(item => item.descriptor),
    ['Firm', 'Smooth', 'Clear', 'Warm', 'Breezy', 'Youthful', 'Bright', 'Bright', 'Easy-going']);
  assert.equal(other.length, 21);
  assert.equal(suggested.length + other.length, Object.keys(VOICE_DESCRIPTORS).length);
  assert.equal(Object.keys(VOICE_DESCRIPTORS).length, 30);
  assert.deepEqual(other.map(item => item.name), [...other.map(item => item.name)].sort((a, b) => a.localeCompare(b)));
  assert.ok(other.every(item => !SUGGESTED_VOICES.includes(item.name) && item.descriptor));
  assert.deepEqual(other.find(item => item.name === 'Gacrux'), { name: 'Gacrux', descriptor: 'Mature', isDefault: false });
  // Only Kore is marked Default.
  assert.deepEqual([...suggested, ...other].filter(item => item.isDefault).map(item => item.name), [DEFAULT_VOICE]);
});

test('saved voice settings map with the core fallbacks', () => {
  assert.deepEqual(voiceChoice(null), { name: 'Kore', mode: 'push_to_talk' });
  assert.deepEqual(voiceChoice({ name: 'Gacrux', mode: 'conversation' }), { name: 'Gacrux', mode: 'conversation' });
  assert.deepEqual(voiceChoice({ name: 'kore', mode: 'always' }), { name: 'Kore', mode: 'push_to_talk' });
  assert.deepEqual(voiceChoice({ name: 'constructor' }), { name: 'Kore', mode: 'push_to_talk' });
  assert.deepEqual(VOICE_MODES.map(item => item.label), ['Push to talk', 'Conversation']);
  assert.equal(modeHelp('push_to_talk'), 'Hold the hotkey or button while you speak.');
  assert.equal(modeHelp('conversation'), 'Talk hands-free; JARVIS listens until you stop the conversation.');
});

test('preview failures read plainly', () => {
  assert.equal(previewFailureMessage({ code: 'provider_not_configured', message: 'x' }), PREVIEW_NO_KEY);
  assert.equal(previewFailureMessage({ code: 'offline' }), 'JARVIS core is offline. Reconnect and try again.');
  assert.equal(previewFailureMessage({ code: 'invalid_response', message: 'Refresh revision history.' }), 'The voice preview could not play. Try again.');
  assert.equal(previewFailureMessage({ code: 'provider_rate_limited', message: 'Gemini is limiting requests right now.' }), 'Gemini is limiting requests right now.');
  assert.equal(previewFailureMessage(null), 'The voice preview could not play. Try again.');
});

test('PCM16 little-endian decodes to floats', () => {
  const bytes = Uint8Array.from([0x00, 0x00, 0xff, 0x7f, 0x00, 0x80, 0x00, 0x40, 0x01]);
  const samples = decodePcm16(Buffer.from(bytes).toString('base64'));
  assert.equal(samples.length, 4);
  assert.deepEqual([...samples], [0, 32767 / 32768, -1, 0.5]);
});

class FakeContext {
  static made = [];
  constructor() { this.sources = []; this.closed = false; this.destination = {}; FakeContext.made.push(this); }
  async resume() {}
  createBuffer(channels, length, rate) {
    return { channels, length, rate, copyToChannel(samples) { this.samples = samples; } };
  }
  createBufferSource() {
    const source = { started: false, stopped: false, connect() {}, disconnect() {}, start() { this.started = true; }, stop() { this.stopped = true; } };
    this.sources.push(source);
    return source;
  }
  async close() { this.closed = true; }
}

const sample = (rate = 24000) => ({ name: 'x', cached: false, sample_rate: rate, pcm_base64: Buffer.from(new Uint8Array(480)).toString('base64') });

test('preview player plays one voice at a time and stops on close', async () => {
  FakeContext.made = [];
  const fetched = [];
  const states = [];
  const player = new PreviewPlayer({ fetch: async name => { fetched.push(name); return sample(); }, onChange: state => states.push(state), AudioContext: FakeContext });
  await player.toggle('Kore');
  const context = FakeContext.made[0];
  assert.equal(player.state.playing, 'Kore');
  assert.equal(context.sources[0].started, true);
  assert.equal(context.sources[0].buffer.rate, 24000);
  assert.equal(context.sources[0].buffer.length, 240);
  assert.deepEqual(states[0], { playing: null, loading: 'Kore', error: null });
  // Another voice replaces the first.
  await player.toggle('Leda');
  assert.equal(context.sources[0].stopped, true);
  assert.equal(player.state.playing, 'Leda');
  // The same voice again stops it.
  await player.toggle('Leda');
  assert.equal(context.sources[1].stopped, true);
  assert.equal(player.state.playing, null);
  assert.deepEqual(fetched, ['Kore', 'Leda']);
  // Ending naturally clears the playing state.
  await player.play('Kore');
  context.sources[2].onended();
  assert.equal(player.state.playing, null);
  await player.play('Kore');
  player.close();
  assert.equal(context.sources[3].stopped, true);
  assert.equal(context.closed, true);
  assert.equal(FakeContext.made.length, 1, 'one AudioContext per player');
});

test('a preview superseded while loading never plays, and failures surface', async () => {
  FakeContext.made = [];
  let release;
  const slow = new Promise(resolve => { release = resolve; });
  const player = new PreviewPlayer({
    fetch: async name => {
      if (name === 'Kore') { await slow; return sample(); }
      if (name === 'Puck') throw Object.assign(new Error('Gemini is limiting requests right now.'), { code: 'provider_rate_limited' });
      return sample(16000);
    },
    AudioContext: FakeContext,
  });
  const first = player.play('Kore');
  assert.equal(player.state.loading, 'Kore');
  await player.play('Despina');
  release();
  await first;
  const context = FakeContext.made[0];
  assert.equal(context.sources.length, 1);
  assert.equal(context.sources[0].buffer.rate, 16000);
  assert.equal(player.state.playing, 'Despina');
  await player.play('Puck');
  assert.deepEqual(player.state, { playing: null, loading: null, error: { name: 'Puck', message: 'Gemini is limiting requests right now.' } });
  // Stop while loading cancels the pending preview.
  const pending = new PreviewPlayer({ fetch: () => slow.then(sample), AudioContext: FakeContext });
  const loading = pending.play('Kore');
  pending.stop();
  await loading;
  assert.equal(pending.state.playing, null);
  const noAudio = new PreviewPlayer({ fetch: async () => sample(), AudioContext: undefined });
  noAudio.Context = undefined;
  await noAudio.play('Kore');
  assert.equal(noAudio.state.error.message, 'This device could not play the preview.');
});

class Socket extends EventEmitter {
  connected = true;
  requests = [];
  emit(event, ...args) {
    if (event === 'voice_preview') { this.requests.push({ event, data: args[0], ack: args[1] }); return true; }
    return super.emit(event, ...args);
  }
}

test('voice preview client validates the sample', async () => {
  const socket = new Socket();
  const client = createSecretsClient(socket);
  const ok = client.voicePreview('Kore');
  assert.deepEqual(socket.requests[0].data, { name: 'Kore' });
  socket.requests[0].ack({ ok: true, ...sample(), name: 'Kore' });
  assert.equal((await ok).sample_rate, 24000);
  const wrong = client.voicePreview('Leda');
  socket.requests[1].ack({ ok: true, ...sample(), name: 'Kore' });
  await assert.rejects(wrong, { code: 'invalid_response' });
  const missing = client.voicePreview('Leda');
  socket.requests[2].ack({ ok: false, code: 'provider_not_configured', message: PREVIEW_NO_KEY });
  await assert.rejects(missing, { code: 'provider_not_configured', message: PREVIEW_NO_KEY });
  assert.equal(isVoicePreview({ ...sample(4000), name: 'Kore' }), false);
  assert.equal(isVoicePreview({ ...sample(), name: 'Kore', pcm_base64: 'not base64!' }), false);
  client.dispose();
});

test('the default voice mode drives the Quick assistant', () => {
  assert.equal(defaultVoiceMode({ voice: { mode: 'conversation' } }), 'conversation');
  assert.equal(defaultVoiceMode({ voice: { mode: 'bogus' } }), 'push_to_talk');
  assert.equal(defaultVoiceMode(null), 'push_to_talk');
  assert.equal(holdButtonTone('push_to_talk'), 'btn--primary');
  assert.equal(holdButtonTone('conversation'), 'btn--secondary');
  const ready = { mode: 'conversation', started: false, elapsed: 100, connected: true, gaming: false, locked: false, restoring: false, liveState: 'off', speechState: 'idle' };
  assert.equal(shouldStartConversation(ready), true);
  assert.equal(shouldStartConversation({ ...ready, speechState: 'answered' }), true);
  for (const change of [
    { mode: 'push_to_talk' }, { started: true }, { elapsed: AUTO_START_WINDOW_MS + 1 }, { connected: false },
    { gaming: true }, { locked: true }, { restoring: true }, { liveState: 'connecting' }, { speechState: 'review' },
  ]) assert.equal(shouldStartConversation({ ...ready, ...change }), false, JSON.stringify(change));
});
