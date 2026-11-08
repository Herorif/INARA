import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import {
  ACCESS_OPTIONS, EMPTY_ACTION, HTTP_NOTE, INTRO, LEGACY_NOTE, TOKEN_STEPS, URL_PLACEHOLDER,
  cardView, connectedLine, countText, homeView, normalizeDevices, normalizeStatus, tileView,
  withAccess, withDevice,
} from '../src/features/home/homeModel.js';
import { createHomeClient } from '../src/features/home/homeClient.js';
import { registerHomeEvents } from '../src/services/events/home.js';
import { approvalView } from '../src/components/approvalView.js';

const raw = (patch = {}) => ({
  connected: false, url: null, host: null, insecure: false, devices: null, rooms: null, grouped_by: null,
  legacy_token_ignored: false, last_error: null, ...patch,
});
const connected = raw({ connected: true, url: 'http://homeassistant.local:8123', host: 'homeassistant.local', insecure: true,
  devices: 11, rooms: 3, grouped_by: 'area' });
const device = (patch) => ({
  entity_id: 'light.living_ceiling', name: 'Ceiling light', domain: 'light', room: 'Living room', state: 'on',
  state_text: 'On · 70%', available: true, access: 'can', toggle: true, on: true, dimmable: true, brightness: 70,
  climate: null, ...patch,
});
// The mockup's rooms.
const MOCKUP = {
  rooms: ['Living room', 'Bedroom', 'Entrance'],
  grouped_by: 'area',
  devices: [
    device({}),
    device({ entity_id: 'light.floor_lamp', name: 'Floor lamp', state: 'off', state_text: 'Off', on: false, brightness: null }),
    device({ entity_id: 'media_player.tv', name: 'TV', domain: 'media_player', state: 'playing', state_text: 'Playing', dimmable: false, brightness: null }),
    device({ entity_id: 'climate.bedroom_ac', name: 'Air conditioner', domain: 'climate', room: 'Bedroom', state: 'cool', state_text: 'Cooling',
      toggle: false, on: null, dimmable: false, brightness: null, climate: { target: 24, current: 26, unit: '°C', mode: 'Cool' } }),
    device({ entity_id: 'fan.bedroom_fan', name: 'Ceiling fan', domain: 'fan', room: 'Bedroom', state: 'off', state_text: 'Off', on: false, dimmable: false, brightness: null }),
    device({ entity_id: 'lock.front_door', name: 'Front door', domain: 'lock', room: 'Entrance', state: 'locked', state_text: 'Locked',
      access: 'ask', toggle: false, on: null, dimmable: false, brightness: null }),
    device({ entity_id: 'light.porch', name: 'Porch light', room: 'Entrance', state: 'off', state_text: 'Off', on: false, dimmable: false, brightness: null }),
    device({ entity_id: 'alarm_control_panel.house', name: 'Alarm', domain: 'alarm_control_panel', room: 'Entrance', state: 'armed_away',
      state_text: 'Armed (away)', access: 'off', toggle: false, on: null, dimmable: false, brightness: null }),
    device({ entity_id: 'cover.gate', name: 'Gate', domain: 'cover', room: 'Entrance', state: 'closed', state_text: 'Closed',
      access: 'ask', toggle: false, on: null, dimmable: false, brightness: null }),
  ],
};

test('the card copy matches the approved design', () => {
  assert.equal(INTRO, 'Lets JARVIS see and control the lights, switches, fans, climate and other devices in your Home Assistant. The token stays encrypted on this PC.');
  assert.equal(URL_PLACEHOLDER, 'http://homeassistant.local:8123');
  assert.equal(HTTP_NOTE, "This address isn't encrypted; use it only on your home network.");
  assert.equal(LEGACY_NOTE, 'An old token in settings was ignored; paste it again here to store it encrypted.');
  assert.deepEqual(TOKEN_STEPS, [
    'In Home Assistant, open your profile.',
    'Open the Security tab.',
    'Under Long-lived access tokens, select Create token and name it JARVIS.',
    'Copy the token and paste it here.',
  ]);
  assert.deepEqual(ACCESS_OPTIONS.map((option) => option.label), ['JARVIS can control', 'Always asks', 'Off limits']);
});

test('not connected: intro, the form, the http note only for http, and Connect needs both fields', () => {
  const status = normalizeStatus(raw());
  const empty = cardView(status, {});
  assert.equal(empty.phase, 'ready');
  assert.deepEqual(empty.chip, { label: 'Not connected', tone: 'idle' });
  assert.equal(empty.intro, INTRO);
  assert.equal(empty.form, true);
  assert.equal(empty.httpNote, null);
  assert.deepEqual(empty.connect, { label: 'Connect', disabled: true });
  assert.equal(empty.disconnect, null);
  const http = cardView(status, { url: 'http://homeassistant.local:8123', token: 'abc' });
  assert.equal(http.httpNote, HTTP_NOTE);
  assert.equal(http.connect.disabled, false);
  assert.equal(cardView(status, { url: 'https://ha.example.com', token: 'abc' }).httpNote, null);
  assert.equal(cardView(status, { url: 'http://x', token: 'abc', online: false }).connect.disabled, true);
  assert.deepEqual(cardView(status, { url: 'http://x', token: 'abc', busy: true }).connect, { label: 'Connecting…', disabled: true });
  assert.equal(cardView(null, { url: 'http://x', token: 'abc' }).connect.disabled, true);
  assert.equal(cardView(status, { error: "Home Assistant didn't accept this token." }).error, "Home Assistant didn't accept this token.");
});

test('the old settings token notice shows while the core reports it', () => {
  assert.equal(cardView(normalizeStatus(raw({ legacy_token_ignored: true }))).legacy, LEGACY_NOTE);
  assert.equal(cardView(normalizeStatus(raw())).legacy, null);
});

test('connected: the host and counts line, Disconnect and no form', () => {
  const card = cardView(normalizeStatus(connected), {});
  assert.equal(card.phase, 'connected');
  assert.deepEqual(card.chip, { label: 'Connected', tone: 'ok' });
  assert.equal(card.account, 'Connected to homeassistant.local · 11 devices in 3 rooms');
  assert.equal(card.form, false);
  assert.equal(card.intro, null);
  assert.equal(card.connect, null);
  assert.deepEqual(card.disconnect, { label: 'Disconnect', disabled: false });
  assert.equal(connectedLine(normalizeStatus({ ...connected, devices: null })), 'Connected to homeassistant.local');
  assert.equal(countText(1, 1), '1 device in 1 room');
  assert.equal(countText(5, 0), '5 devices');
});

test('normalizeStatus rejects what the core never sends', () => {
  assert.equal(normalizeStatus(null), null);
  assert.equal(normalizeStatus({}), null);
  assert.equal(normalizeStatus({ connected: 'yes' }), null);
  const odd = normalizeStatus(raw({ devices: -1, rooms: 1.5, grouped_by: 'x', last_error: { code: 1 } }));
  assert.deepEqual([odd.devices, odd.rooms, odd.groupedBy, odd.error], [null, null, null, null]);
});

test('the Home view groups the mockup rooms with their tiles', () => {
  const view = homeView(normalizeStatus(connected), normalizeDevices(MOCKUP), { online: true });
  assert.equal(view.line, 'Connected to homeassistant.local · 11 devices in 3 rooms');
  assert.deepEqual(view.refresh, { label: 'Refresh', disabled: false });
  assert.deepEqual(view.rooms.map((room) => [room.name, room.tiles.map((tile) => tile.name)]), [
    ['Living room', ['Ceiling light', 'Floor lamp', 'TV']],
    ['Bedroom', ['Air conditioner', 'Ceiling fan']],
    ['Entrance', ['Front door', 'Porch light', 'Alarm', 'Gate']],
  ]);
  const [ceiling, floor, tv] = view.rooms[0].tiles;
  assert.deepEqual(ceiling.toggle, { on: true, label: 'Turn off Ceiling light', disabled: false });
  assert.deepEqual(ceiling.brightness, { value: 70, label: 'Ceiling light brightness', disabled: false });
  assert.equal(floor.brightness, null);
  assert.equal(floor.toggle.label, 'Turn on Floor lamp');
  assert.equal(tv.stateText, 'Playing');
  const [ac] = view.rooms[1].tiles;
  assert.deepEqual(ac.climate, { setPoint: '24 °C', mode: 'Cool' });
  assert.equal(ac.toggle, null);
  assert.equal(ac.stateText, 'Cooling');
  const [door, porch, alarm, gate] = view.rooms[2].tiles;
  assert.deepEqual([door.stateText, door.access.text, door.access.tone, door.toggle], ['Locked', 'Always asks', 'warn', null]);
  assert.deepEqual([alarm.stateText, alarm.access.text, alarm.access.tone], ['Armed (away)', 'Off limits', 'danger']);
  assert.deepEqual([gate.stateText, gate.access.text], ['Closed', 'Always asks']);
  assert.deepEqual(porch.access, { text: 'JARVIS can control', tone: 'normal', value: 'can' });
  assert.equal(porch.brightness, null);
  assert.equal(door.icon, 'lock');
  assert.equal(door.menuLabel, 'JARVIS access for Front door');
});

test('a tile control in flight disables only that tile', () => {
  const view = homeView(normalizeStatus(connected), normalizeDevices(MOCKUP), { pending: { 'light.living_ceiling': true } });
  assert.equal(view.rooms[0].tiles[0].toggle.disabled, true);
  assert.equal(view.rooms[0].tiles[1].toggle.disabled, false);
});

test('not connected: a short empty state with Connect Home Assistant', () => {
  const view = homeView(normalizeStatus(raw()), null, {});
  assert.equal(view.connected, false);
  assert.equal(view.empty.action, EMPTY_ACTION);
  assert.equal(EMPTY_ACTION, 'Connect Home Assistant');
  assert.equal(view.refresh, null);
  assert.deepEqual(view.rooms, []);
  assert.equal(homeView(null, null).empty, null);
});

test('device updates and access changes replace only that device', () => {
  const list = normalizeDevices(MOCKUP);
  const updated = withDevice(list, device({ entity_id: 'light.floor_lamp', name: 'Floor lamp', state: 'on', state_text: 'On · 100%', on: true, brightness: 100 }));
  assert.equal(updated.devices[1].stateText, 'On · 100%');
  assert.equal(updated.devices[0], list.devices[0]);
  assert.equal(withDevice(list, { entity_id: 'bad' }), list);
  const access = withAccess(list, 'cover.gate', 'off');
  assert.equal(access.devices.find((item) => item.entityId === 'cover.gate').access, 'off');
  assert.equal(withAccess(list, 'cover.gate', 'maybe'), list);
});

test('normalizeDevices drops malformed devices', () => {
  const list = normalizeDevices({ rooms: ['A', 3], devices: [device({}), device({ entity_id: 'Bad.Id' }), device({ domain: 'sensor' }), device({ access: 'x' }), null] });
  assert.equal(list.devices.length, 1);
  assert.deepEqual(list.rooms, ['A']);
  assert.equal(normalizeDevices({}), null);
  assert.equal(tileView(list.devices[0]).icon, 'light');
});

class FakeSocket extends EventEmitter {
  constructor(answers) { super(); this.connected = true; this.sent = []; this.answers = answers; }
  emit(event, data, ack) {
    if (typeof ack !== 'function') return super.emit(event, data);
    this.sent.push([event, data]);
    setImmediate(() => ack(this.answers[event] ?? { ok: true }));
    return true;
  }
}

test('the client sends the token only to home_connect and validates replies', async () => {
  const socket = new FakeSocket({
    home_connect: { ok: true, home: connected },
    home_devices: { ok: true, home: connected, ...MOCKUP },
    home_set_access: { ok: true, entity_id: 'cover.gate', access: 'off' },
    home_control_direct: { ok: true, device: device({}) },
    home_disconnect: { ok: false, code: 'storage_error', message: 'Protected storage could not be opened.' },
  });
  const client = createHomeClient(socket);
  const status = await client.connect(' http://homeassistant.local:8123 ', ' token ');
  assert.equal(status.connected, true);
  assert.deepEqual(socket.sent[0], ['home_connect', { url: 'http://homeassistant.local:8123', token: 'token' }]);
  const { list } = await client.devices();
  assert.equal(list.devices.length, 9);
  assert.deepEqual(await client.setAccess('cover.gate', 'off'), { entityId: 'cover.gate', access: 'off' });
  await client.control('light.living_ceiling', 'set_brightness', 40);
  await client.control('light.living_ceiling', 'turn_off');
  assert.deepEqual(socket.sent.slice(-2), [
    ['home_control_direct', { entity_id: 'light.living_ceiling', action: 'set_brightness', value: 40 }],
    ['home_control_direct', { entity_id: 'light.living_ceiling', action: 'turn_off' }],
  ]);
  await assert.rejects(client.disconnect(), /Protected storage could not be opened/);
  assert.ok(socket.sent.slice(1).every(([, data]) => !JSON.stringify(data).includes('token')));
  client.dispose();
});

test('home_status events update the store and a disconnected status clears devices', () => {
  const socket = new FakeSocket({ home_status: { ok: true, home: connected } });
  const handlers = {};
  const state = { homeDevices: { devices: [] } };
  const store = { setState: (patch) => Object.assign(state, patch) };
  const unsubs = [];
  registerHomeEvents({ onSocket: (event, handler) => { handlers[event] = handler; return () => {}; }, socket, store, unsubs });
  assert.equal(unsubs.length, 3);
  handlers.home_status(connected);
  assert.equal(state.homeStatus.connected, true);
  assert.deepEqual(state.homeDevices, { devices: [] });
  handlers.home_status({ bogus: true });
  assert.equal(state.homeStatus.connected, true);
  handlers.home_status(raw());
  assert.equal(state.homeStatus.connected, false);
  assert.equal(state.homeDevices, null);
});

test('the home_control approval card reads the core sentence with its action', () => {
  const card = approvalView({ id: 'a', tool: 'home_control', args: { entity_id: 'lock.front_door', action: 'unlock', value: null,
    device: 'Front door', approval: 'Unlock Front door?', approve_label: 'Unlock' } });
  assert.deepEqual(card, {
    kind: 'home_control', title: 'Unlock Front door?',
    summary: 'JARVIS continues only after you approve. Denying leaves this action undone.',
    approveLabel: 'Unlock', denyLabel: 'Not now', details: null,
  });
  assert.equal(approvalView({ id: 'b', tool: 'home_control', args: { approval: 'x', approve_label: 'Explode' } }).kind, 'generic');
  assert.equal(approvalView({ id: 'c', tool: 'home_control', args: { entity_id: 'lock.a' } }).kind, 'generic');
});
