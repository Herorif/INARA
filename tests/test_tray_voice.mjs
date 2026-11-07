import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import {
  createAudioDevicesClient, devicePatch, isAudioDeviceSelection, parseAudioDevices, parseWakeWordStatus,
} from '../src/transport/audioDevicesClient.ts';
import {
  DEVICE_KINDS, TRAY_KINDS, TRAY_VOICE_HELP, deviceNote, deviceOptions, savedDevice, selectedValue, selectionFor,
} from '../src/features/settings/trayVoiceDevicesModel.js';
import { createSubscriptions } from '../src/services/subscriptions.js';
import { registerConversationEvents } from '../src/services/events/conversation.js';

const WASAPI = 'Windows WASAPI';
const entry = (name, extra = {}) => ({ name, host_api: WASAPI, default: false, channels: 2, sample_rate: 48000, ...extra });
const report = (extra = {}) => ({
  ok: true, available: true, code: null, message: null, host_api: WASAPI,
  inputs: [entry('Microphone Array (Realtek(R) Audio)', { default: true }), entry('Microphone (Yeti Orb)', { channels: 1 })],
  outputs: [entry('Speakers (Realtek(R) Audio)', { default: true }), entry('Headphones (USB)', { sample_rate: 44100 })],
  ...extra,
});

class Socket extends EventEmitter {
  connected = true;
  requests = [];
  emit(event, data, ack) {
    if (typeof ack !== 'function') return super.emit(event, data);
    this.requests.push({ event, data, ack });
    return true;
  }
}

test('the device list is validated before the UI sees it', () => {
  const parsed = parseAudioDevices(report());
  assert.equal(parsed.inputs.length, 2);
  assert.deepEqual(parsed.outputs[1], entry('Headphones (USB)', { sample_rate: 44100 }));
  assert.deepEqual(parseAudioDevices({ ...report(), available: false, code: 'audio_unavailable', message: 'Install it.', host_api: null, inputs: [], outputs: [] }).message, 'Install it.');
  for (const bad of [
    null, [], { ...report(), available: 'yes' }, { ...report(), inputs: {} },
    { ...report(), inputs: [entry('')] }, { ...report(), inputs: [entry('Bad\nname')] },
    { ...report(), outputs: [entry('x', { channels: 0 })] }, { ...report(), outputs: [entry('x', { sample_rate: 1.5 })] },
    { ...report(), outputs: [{ ...entry('x'), default: 1 }] }, { ...report(), code: 7 },
    { ...report(), available: false }, // unavailable yet listing devices
    { ...report(), inputs: Array.from({ length: 65 }, (_, index) => entry(`Mic ${index}`)) },
  ]) assert.equal(parseAudioDevices(bad), null, JSON.stringify(bad)?.slice(0, 80));
});

test('the client lists devices over one RPC and rejects an incomplete reply', async () => {
  const socket = new Socket();
  const client = createAudioDevicesClient(socket);
  const listing = client.list();
  const request = socket.requests.at(-1);
  assert.equal(request.event, 'audio_devices');
  assert.deepEqual(request.data, {});
  request.ack(report());
  assert.equal((await listing).host_api, WASAPI);
  const broken = client.list();
  socket.requests.at(-1).ack({ ok: true, available: true });
  await assert.rejects(broken, { code: 'invalid_response' });
  const refused = client.list();
  socket.requests.at(-1).ack({ ok: false, code: 'authentication_required', message: 'Use the authorized desktop channel.' });
  await assert.rejects(refused, { code: 'authentication_required' });
  client.dispose();
});

test('the "Hey Jarvis" status is validated before the UI sees it', () => {
  assert.deepEqual(parseWakeWordStatus({ ok: true, state: 'listening', message: null }), { state: 'listening', message: null });
  assert.deepEqual(parseWakeWordStatus({ ok: true, state: 'unavailable', message: 'No microphone.' }),
    { state: 'unavailable', message: 'No microphone.' });
  for (const bad of [
    null, [], {}, { state: 'listening' }, { state: 'on', message: null }, { state: 'paused', message: 3 },
    { state: 'unavailable', message: 'x'.repeat(501) }, { state: ['off'], message: null },
  ]) assert.equal(parseWakeWordStatus(bad), null, JSON.stringify(bad));
});

test('the client reads the "Hey Jarvis" status over one RPC and rejects a malformed reply', async () => {
  const socket = new Socket();
  const client = createAudioDevicesClient(socket);
  const reading = client.wakeWordStatus();
  const request = socket.requests.at(-1);
  assert.equal(request.event, 'wake_word_status');
  assert.deepEqual(request.data, {});
  request.ack({ ok: true, state: 'paused', message: null });
  assert.deepEqual(await reading, { state: 'paused', message: null });
  const broken = client.wakeWordStatus();
  socket.requests.at(-1).ack({ ok: true, state: 'sleeping', message: null });
  await assert.rejects(broken, { code: 'invalid_response' });
  const refused = client.wakeWordStatus();
  socket.requests.at(-1).ack({ ok: false, code: 'authentication_required', message: 'Use the authorized desktop channel.' });
  await assert.rejects(refused, { code: 'authentication_required' });
  client.dispose();
  await assert.rejects(client.wakeWordStatus(), { code: 'scope_closed' });
  const offline = createAudioDevicesClient(Object.assign(new Socket(), { connected: false }));
  await assert.rejects(offline.wakeWordStatus(), { code: 'offline' });
  offline.dispose();
});

test('tray voice help mentions "Hey Jarvis"', () => {
  assert.equal(TRAY_VOICE_HELP, 'Used when you talk to JARVIS from the tray or say "Hey Jarvis". The microphone pauses while JARVIS speaks.');
});

test('a device is saved by name and host API, or as the system default', () => {
  assert.deepEqual(devicePatch('microphone', 'default'), { voice: { local_microphone: 'default' } });
  assert.deepEqual(devicePatch('speaker', { name: 'Headphones (USB)', host_api: WASAPI }),
    { voice: { local_speaker: { name: 'Headphones (USB)', host_api: WASAPI } } });
  assert.throws(() => devicePatch('speaker', { name: 'x', host_api: WASAPI, index: 2 }), { code: 'invalid_arguments' });
  assert.throws(() => devicePatch('speaker', 3), { code: 'invalid_arguments' });
  assert.equal(isAudioDeviceSelection('Default'), false);
});

test('Preferences options: system default, the listed devices, and a saved device not connected', () => {
  const { inputs } = report();
  assert.deepEqual(DEVICE_KINDS.map(item => item.label), ['Microphone', 'Speaker']);
  assert.equal(savedDevice(null, 'microphone'), 'default');
  assert.equal(savedDevice({ local_microphone: { name: 3 } }, 'microphone'), 'default');
  const yeti = { name: 'Microphone (Yeti Orb)', host_api: WASAPI };
  assert.deepEqual(savedDevice({ local_microphone: yeti }, 'microphone'), yeti);
  assert.deepEqual(deviceOptions(inputs, 'default').map(item => item.label),
    ['System default', 'Microphone Array (Realtek(R) Audio)', 'Microphone (Yeti Orb)']);
  assert.equal(selectedValue(inputs, 'default'), 'default');
  assert.equal(selectedValue(inputs, yeti), 'device:1');
  assert.deepEqual(selectionFor(inputs, 'default', 'device:1'), yeti);
  assert.equal(selectionFor(inputs, yeti, 'device:1'), null); // unchanged
  assert.equal(selectionFor(inputs, yeti, 'default'), 'default');
  assert.equal(selectionFor(inputs, yeti, 'device:9'), null);
  assert.equal(deviceNote(inputs, yeti, 'microphone', true), '');
  const gone = { name: 'Old USB mic', host_api: WASAPI };
  const options = deviceOptions(inputs, gone);
  assert.deepEqual(options.at(-1), { value: 'saved', label: 'Old USB mic (not connected)' });
  assert.equal(selectedValue(inputs, gone), 'saved');
  assert.equal(selectionFor(inputs, gone, 'saved'), null);
  assert.equal(deviceNote(inputs, gone, 'microphone', true),
    'This microphone is not connected; JARVIS uses the Windows default until it is.');
  assert.equal(deviceNote(inputs, gone, 'speaker', true),
    'This speaker is not connected; tray voice uses the system default until it is.');
  assert.deepEqual(deviceOptions(inputs, 'default', 'microphone').map(item => item.label),
    ['Automatic (follows Windows)', 'Microphone Array (Realtek(R) Audio)', 'Microphone (Yeti Orb)']);
  assert.deepEqual(TRAY_KINDS.map(item => item.kind), ['speaker']);
  assert.equal(deviceNote(inputs, gone, 'microphone', false), '');
});

test('the workspace switches to the conversation tray voice used while it was closed', () => {
  const socket = new EventEmitter(), scope = createSubscriptions(socket), adopted = [];
  let state = { currentProject: 'temp', conversationId: 'stale-id', backendConnected: true, adoptConversation: id => adopted.push(id) };
  const store = { getState: () => state, setState: value => { state = { ...state, ...value }; } };
  registerConversationEvents({ onSocket: scope.on, store, unsubs: [], resumeConversation: () => {}, conversationForProject: project => `${project}-id` });
  socket.emit('conversation_restored', { project: 'temp', conversation_id: 'stale-id', messages: [] });
  assert.deepEqual(adopted, []);
  const tray = '0b7e2f9e-4c55-4a36-9b8e-2f4f5d0f3f01';
  socket.emit('conversation_restored', { project: 'temp', conversation_id: 'stale-id', messages: [], latest_conversation_id: tray });
  assert.deepEqual(adopted, [tray]);
  // A restoration for another conversation never switches.
  socket.emit('conversation_restored', { project: 'temp', conversation_id: 'other', messages: [], latest_conversation_id: tray });
  assert.deepEqual(adopted, [tray]);
  scope.dispose();
});
