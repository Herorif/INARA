import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import {
  HEARTBEAT_MS, MAX_VIEWS, SETUP_STEPS, appUrl, cleanSteps, embedOrigin, embedUrl, normalizeStatus,
  normalizeTour, normalizeViewRequest, pageView,
} from '../src/features/world/worldModel.js';
import { createWorldBridge } from '../src/features/world/worldBridge.js';
import { createWorldClient } from '../src/features/world/worldClient.js';
import { registerWorldEvents } from '../src/features/world/worldEvents.js';
import { features, heavyFeatures } from '../src/app/features.js';
import { featureWorkspace } from '../src/app/workspaceNavigation.js';

const require = createRequire(import.meta.url);
const security = require('../electron/security.cjs');
const ORIGIN = 'http://127.0.0.1:4173';
const ID = 'a'.repeat(32);
const VIEW = { camera: { lat: 3.139, lon: 101.6869, altitude_m: 60000, heading_deg: 0, pitch_deg: -90 }, layers: ['flights'] };
const raw = (patch = {}) => ({
  state: 'stopped', reason: null, message: null, port: 4173, url: ORIGIN, enabled: true,
  tour: { active: false, title: null, caption: null }, diagnostics: null, ...patch,
});
const status = patch => normalizeStatus(raw(patch));

// --- the page model ----------------------------------------------------------------------------
test('normalizeStatus keeps only what the core sends', () => {
  assert.deepEqual(status({ state: 'error', message: 'Port 4173 is in use by another program.',
    diagnostics: { exit_code: 1, stderr: 'x'.repeat(4000) } }), {
    state: 'error', reason: null, message: 'Port 4173 is in use by another program.', port: 4173, enabled: true,
    tour: { active: false, title: null, caption: null }, diagnostics: { exitCode: 1, stderr: 'x'.repeat(1500) },
  });
  assert.equal(status({ state: 'not_installed', reason: 'dist_missing' }).reason, 'dist_missing');
  assert.equal(status({ reason: 'elsewhere' }).reason, null);
  for (const bad of [null, [], raw({ state: 'running' }), raw({ port: 8000 }), raw({ port: 80 }), raw({ port: '4173' }),
    raw({ enabled: 'yes' })]) assert.equal(normalizeStatus(bad), null);
});

test('normalizeTour and normalizeViewRequest', () => {
  assert.deepEqual(normalizeTour({ active: true, title: ' Flights over KL ', caption: 'Here is KLIA.' }),
    { active: true, title: 'Flights over KL', caption: 'Here is KLIA.' });
  assert.deepEqual(normalizeTour({ active: false, title: 'ignored' }), { active: false, title: null, caption: null });
  assert.equal(normalizeTour({ active: 'yes' }), null);
  assert.deepEqual(normalizeViewRequest({ id: ID, view: VIEW, title: null }), { id: ID, view: VIEW, title: null });
  for (const bad of [{ id: 'short', view: VIEW }, { id: ID, view: [] }, { id: ID, view: null }, { id: ID.toUpperCase(), view: VIEW }]) {
    assert.equal(normalizeViewRequest(bad), null);
  }
});

test('the page shows each state with its chip', () => {
  const chip = value => [value.phase, value.chip.label, value.chip.tone];
  assert.deepEqual(chip(pageView({ status: null })), ['starting', 'Starting', 'accent']);
  assert.deepEqual(chip(pageView({ status: status({ state: 'not_installed', reason: 'node_missing' }) })), ['not_installed', 'Not set up', 'idle']);
  assert.deepEqual(chip(pageView({ status: status({ state: 'stopped' }) })), ['starting', 'Starting', 'accent']);
  assert.deepEqual(chip(pageView({ status: status({ state: 'starting' }) })), ['starting', 'Starting', 'accent']);
  assert.deepEqual(chip(pageView({ status: status({ state: 'ready' }) })), ['ready', 'Ready', 'ok']);
  assert.deepEqual(chip(pageView({ status: status({ state: 'error', message: 'Boom.' }) })), ['error', 'Error', 'danger']);
  const driving = pageView({ status: status({ state: 'ready' }), tour: { active: true, title: 'Flights over KL', caption: 'Look east.' } });
  assert.deepEqual(chip(driving), ['ready', 'JARVIS is driving', 'accent']);
  assert.deepEqual(driving.tourBar, { label: 'TOUR · Flights over KL', caption: 'Look east.' });
});

test('the page view: messages, the frame and the buttons', () => {
  const starting = pageView({ status: status({ state: 'starting' }) });
  assert.equal(starting.message, 'Starting the globe on this PC…');
  assert.equal(starting.frameUrl, null);
  assert.deepEqual([starting.canOpen, starting.canStop], [false, true]);
  const ready = pageView({ status: status({ state: 'ready', port: 4180 }) });
  assert.equal(ready.frameUrl, 'http://127.0.0.1:4180/?embed=1');
  assert.equal(ready.origin, 'http://127.0.0.1:4180');
  assert.deepEqual([ready.message, ready.canOpen, ready.canStop, ready.tourBar], [null, true, true, null]);
  const busy = pageView({ status: status({ state: 'error', message: 'Port 4173 is in use by another program.' }) });
  assert.equal(busy.message, 'Port 4173 is in use by another program.');
  assert.deepEqual([busy.canOpen, busy.canStop, busy.frameUrl], [false, false, null]);
  const failed = pageView({ status: status({ state: 'ready' }), failure: 'World view is turned off in settings.' });
  assert.deepEqual([failed.phase, failed.message, failed.frameUrl], ['error', 'World view is turned off in settings.', null]);
  const notInstalled = pageView({ status: status({ state: 'not_installed', reason: 'root_missing' }) });
  assert.deepEqual([notInstalled.message, notInstalled.canOpen, notInstalled.canStop], [null, false, false]);
  assert.equal(pageView({ status: status({ state: 'ready' }), tour: { active: true, title: null, caption: null } }).tourBar.label, 'TOUR · World');
});

test('addresses are loopback only', () => {
  assert.equal(embedUrl(4173), 'http://127.0.0.1:4173/?embed=1');
  assert.equal(appUrl(4173), 'http://127.0.0.1:4173/');
  assert.equal(embedOrigin(4173), ORIGIN);
  for (const bad of [8000, 80, 70000, '4173', null]) assert.equal(embedUrl(bad), null);
  assert.equal(HEARTBEAT_MS, 30000);
  assert.ok(SETUP_STEPS.some(step => step.includes('install-world-view.ps1 -WhatIf')));
});

test('cleanSteps bounds what goes back to the core', () => {
  assert.deepEqual(cleanSteps([{ step: 'camera', ok: true, extra: 1 }, { step: 'x', ok: 'yes' }, { step: ' ', ok: true },
    { step: 'follow', ok: false, error: ' gone ' }, null]), [{ step: 'camera', ok: true }, { step: 'follow', ok: false, error: 'gone' }]);
  assert.equal(cleanSteps(Array.from({ length: 100 }, () => ({ step: 's', ok: true }))).length, 64);
  assert.deepEqual(cleanSteps('nope'), []);
});

// --- the message bridge ------------------------------------------------------------------------
const frameWindow = () => {
  const posted = [];
  return { posted, postMessage(message, origin) { posted.push([message, origin]); } };
};

test('the bridge ignores messages from any other window or origin', () => {
  const frame = frameWindow();
  const applied = [];
  const bridge = createWorldBridge({ origin: ORIGIN, target: () => frame, onApplied: value => applied.push(value) });
  bridge.show(ID, VIEW);
  const other = frameWindow();
  for (const event of [
    { source: other, origin: ORIGIN, data: { type: 'gev:ready' } },
    { source: frame, origin: 'http://127.0.0.1:4174', data: { type: 'gev:ready' } },
    { source: frame, origin: 'http://localhost:4173', data: { type: 'gev:ready' } },
    { source: frame, origin: 'null', data: { type: 'gev:ready' } },
    { source: null, origin: ORIGIN, data: { type: 'gev:ready' } },
    { source: frame, origin: ORIGIN, data: 'gev:ready' },
    { source: frame, origin: ORIGIN, data: { type: 'gev:other' } },
  ]) assert.equal(bridge.accept(event), null);
  assert.equal(bridge.ready, false);
  assert.deepEqual(frame.posted, []);
  // A forged answer from elsewhere never reaches the core.
  assert.equal(bridge.accept({ source: other, origin: ORIGIN, data: { type: 'gev:view-applied', id: ID, ok: true, steps: [] } }), null);
  assert.deepEqual(applied, []);
});

test('views wait for gev:ready, go to the exact origin and are answered once', () => {
  const frame = frameWindow();
  const applied = [];
  let readies = 0;
  const bridge = createWorldBridge({ origin: ORIGIN, target: () => frame, onApplied: value => applied.push(value), onReady: () => readies++ });
  bridge.show(ID, VIEW);
  assert.deepEqual(frame.posted, []);
  assert.deepEqual(bridge.accept({ source: frame, origin: ORIGIN, data: { type: 'gev:ready' } }), { type: 'ready' });
  assert.equal(readies, 1);
  assert.deepEqual(frame.posted, [[{ type: 'gev:view', id: ID, view: VIEW }, ORIGIN]]);
  bridge.show(ID, VIEW); // the same id again is ignored
  assert.equal(frame.posted.length, 1);
  // An answer for a view this bridge never sent is ignored.
  assert.equal(bridge.accept({ source: frame, origin: ORIGIN, data: { type: 'gev:view-applied', id: 'b'.repeat(32), ok: true } }), null);
  const steps = [{ step: 'set_layer_visibility', ok: true }, { step: 'camera', ok: true }];
  bridge.accept({ source: frame, origin: ORIGIN, data: { type: 'gev:view-applied', id: ID, ok: true, steps } });
  bridge.accept({ source: frame, origin: ORIGIN, data: { type: 'gev:view-applied', id: ID, ok: true, steps } });
  assert.deepEqual(applied, [{ id: ID, ok: true, steps }]);
  // Once ready, a new view goes straight out.
  const next = 'c'.repeat(32);
  bridge.show(next, VIEW);
  assert.deepEqual(frame.posted[1], [{ type: 'gev:view', id: next, view: VIEW }, ORIGIN]);
  bridge.accept({ source: frame, origin: ORIGIN, data: { type: 'gev:view-applied', id: next, ok: false, error: 'Unknown layer' } });
  assert.deepEqual(applied[1], { id: next, ok: false, steps: [{ step: 'view', ok: false, error: 'Unknown layer' }] });
});

test('a view-applied ok with a failed step reads as not ok', () => {
  const frame = frameWindow();
  const applied = [];
  const bridge = createWorldBridge({ origin: ORIGIN, target: () => frame, onApplied: value => applied.push(value) });
  bridge.accept({ source: frame, origin: ORIGIN, data: { type: 'gev:ready' } });
  bridge.show(ID, VIEW);
  bridge.accept({ source: frame, origin: ORIGIN, data: { type: 'gev:view-applied', id: ID, ok: true, steps: [{ step: 'follow', ok: false }] } });
  assert.equal(applied[0].ok, false);
});

test('without a frame the bridge sends nothing', () => {
  let current = null;
  const frame = frameWindow();
  const bridge = createWorldBridge({ origin: ORIGIN, target: () => current, onApplied: () => {} });
  bridge.show(ID, VIEW);
  assert.equal(bridge.accept({ source: frame, origin: ORIGIN, data: { type: 'gev:ready' } }), null);
  current = frame;
  bridge.accept({ source: frame, origin: ORIGIN, data: { type: 'gev:ready' } });
  assert.equal(frame.posted.length, 1);
  bridge.reset();
  assert.equal(bridge.ready, false);
});

// --- events, client and registration ------------------------------------------------------------
class FakeSocket extends EventEmitter {
  constructor(answers) { super(); this.connected = true; this.sent = []; this.answers = answers; }
  emit(event, data, ack) {
    if (typeof ack !== 'function') return super.emit(event, data);
    this.sent.push([event, data]);
    setImmediate(() => ack(this.answers[event] ?? { ok: true }));
    return true;
  }
}

const fakeStore = () => {
  let state = {};
  return { getState: () => state, setState: patch => { state = { ...state, ...(typeof patch === 'function' ? patch(state) : patch) }; } };
};

test('world events fill the store; a disconnect drops queued views', () => {
  const handlers = {};
  const store = fakeStore();
  const unsubs = [];
  registerWorldEvents({ onSocket: (event, handler) => { handlers[event] = handler; return () => {}; }, store, unsubs });
  assert.equal(unsubs.length, 4);
  handlers.world_status(raw({ state: 'ready', tour: { active: true, title: 'T', caption: 'C' } }));
  assert.equal(store.getState().worldStatus.state, 'ready');
  assert.deepEqual(store.getState().worldTour, { active: true, title: 'T', caption: 'C' });
  handlers.world_status({ state: 'nonsense' });
  assert.equal(store.getState().worldStatus.state, 'ready');
  handlers.world_tour({ active: false });
  assert.equal(store.getState().worldTour.active, false);
  handlers.world_view({ id: ID, view: VIEW, title: 'KL' });
  handlers.world_view({ id: 'bad', view: VIEW });
  assert.deepEqual(store.getState().worldViews, [{ id: ID, view: VIEW, title: 'KL' }]);
  assert.equal(store.getState().worldFocus, ID);
  for (let index = 0; index < 6; index++) handlers.world_view({ id: String(index).repeat(32), view: VIEW });
  assert.equal(store.getState().worldViews.length, MAX_VIEWS);
  handlers.disconnect();
  assert.deepEqual([store.getState().worldViews, store.getState().worldFocus], [[], null]);
});

test('the client reports the page and validates replies', async () => {
  const socket = new FakeSocket({
    world_status: { ok: true, world: raw() },
    world_start: { ok: true, world: raw({ state: 'starting' }) },
    world_stop: { ok: true, world: { state: 'gone' } },
    world_tour_stop: { ok: true, tour: { active: false, title: null, caption: null } },
  });
  const client = createWorldClient(socket);
  assert.equal((await client.status(true)).state, 'stopped');
  await client.status(false);
  await client.status();
  assert.equal((await client.start()).state, 'starting');
  await assert.rejects(client.stop(), { code: 'invalid_response' });
  await client.viewResult(ID, true, [{ step: 'camera', ok: true }]);
  assert.deepEqual(await client.tourStop(), { active: false, title: null, caption: null });
  assert.deepEqual(socket.sent, [
    ['world_status', { page: true }], ['world_status', { page: false }], ['world_status', {}], ['world_start', {}],
    ['world_stop', {}], ['world_view_result', { id: ID, ok: true, steps: [{ step: 'camera', ok: true }] }], ['world_tour_stop', {}],
  ]);
  client.dispose();
});

test('World is a heavy Studio feature next to Web', () => {
  const world = features.find(feature => feature.id === 'world');
  assert.deepEqual([world.title, world.flag, world.heavy], ['World', 'showWorldView', true]);
  assert.ok(heavyFeatures.has('world'));
  assert.equal(featureWorkspace('world'), 'studio');
  const deck = readFileSync(new URL('../src/app/CommandDeck.jsx', import.meta.url), 'utf8');
  assert.match(deck, /\['browser','Web'\],\['world','World'\],\['activity','Artifacts'\]/);
});

// --- the renderer's CSP and Open in browser -----------------------------------------------------
test('the workspace CSP frames only the globe, and the overlay frames nothing', () => {
  const config = readFileSync(new URL('../vite.config.js', import.meta.url), 'utf8');
  assert.match(config, /const WORLD_VIEW_FRAME = 'http:\/\/127\.0\.0\.1:4173'/);
  assert.match(config, /'index\.html': WORKSPACE_CONTENT_SECURITY_POLICY, 'overlay\.html': OVERLAY_CONTENT_SECURITY_POLICY/);
  assert.equal((config.match(/frame-src/g) || []).length, 1);
});

test('Open in browser allows exactly the globe on loopback', () => {
  assert.equal(security.externalUrl('http://127.0.0.1:4173/'), 'http://127.0.0.1:4173/');
  assert.equal(security.externalUrl('http://127.0.0.1:4180'), 'http://127.0.0.1:4180/');
  for (const bad of ['http://127.0.0.1:8000/', 'http://127.0.0.1:4173/api/setup/keys', 'http://127.0.0.1:4173/?embed=1',
    'http://127.0.0.1:4173/#x', 'http://user:pw@127.0.0.1:4173/', 'http://127.0.0.1/', 'http://127.0.0.1:80/',
    'http://localhost:4173/', 'http://127.0.0.2:4173/', 'file:///C:/x.html']) {
    assert.equal(security.externalUrl(bad), null, bad);
  }
});
