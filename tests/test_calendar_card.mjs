import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import {
  CONSOLE_URL, INTRO, SETUP_STEPS, SWITCHES, WAITING, cardView, normalizeStatus, safeAuthUrl, setupReady,
} from '../src/features/calendar/calendarModel.js';
import { createCalendarClient } from '../src/features/calendar/calendarClient.js';
import { registerCalendarEvents } from '../src/services/events/calendar.js';
import { approvalView } from '../src/components/approvalView.js';

const raw = (patch = {}) => ({
  connected: false, email: null, calendar: 'primary', setup_needed: true, connecting: false,
  switches: { read_events: true, share_free_busy: true, add_events: true }, last_error: null, ...patch,
});
const view = (patch, ui) => cardView(normalizeStatus(raw(patch)), ui);

test('not connected with setup needed: intro, one-time setup and a disabled Connect', () => {
  const card = view({});
  assert.equal(card.phase, 'setup');
  assert.deepEqual(card.chip, { label: 'Not connected', tone: 'idle' });
  assert.equal(card.intro, INTRO);
  assert.match(INTRO, /^Lets JARVIS see your day, tell callers when you're free, and add bookings with your approval\./);
  assert.equal(card.setup, true);
  assert.deepEqual(card.connect, { label: 'Connect Google Calendar', disabled: true });
  assert.deepEqual(card.switches, []);
  assert.equal(card.disconnect, null);
  assert.equal(card.waiting, null);
});

test('not connected with the client set: Connect is the primary action', () => {
  const card = view({ setup_needed: false });
  assert.equal(card.phase, 'ready');
  assert.equal(card.setup, false);
  assert.deepEqual(card.connect, { label: 'Connect Google Calendar', disabled: false });
  assert.equal(view({ setup_needed: false }, { online: false }).connect.disabled, true);
  assert.equal(view({ setup_needed: false }, { busy: true }).connect.disabled, true);
});

test('waiting for sign-in shows the waiting line and Cancel instead of Connect', () => {
  const card = view({ setup_needed: false, connecting: true });
  assert.equal(card.phase, 'waiting');
  assert.equal(WAITING, 'Waiting for Google sign-in in your browser…');
  assert.deepEqual(card.waiting, { text: WAITING, cancel: 'Cancel', disabled: false });
  assert.equal(card.connect, null);
});

test('connected: account line, the three switches with their copy and Disconnect', () => {
  const card = view({ connected: true, email: 'you@gmail.com', setup_needed: false,
    switches: { read_events: true, share_free_busy: false, add_events: true } });
  assert.equal(card.phase, 'connected');
  assert.deepEqual(card.chip, { label: 'Connected', tone: 'ok' });
  assert.equal(card.account, 'Connected as you@gmail.com · primary calendar');
  assert.equal(card.intro, null);
  assert.deepEqual(card.switches.map((row) => [row.label, row.detail, row.checked]), [
    ['Read my events', "For the morning briefing and when you ask what's on.", true],
    ["Tell callers when I'm free", 'Times only, never what the event is.', false],
    ['Add events', 'JARVIS always asks first, including for confirmed bookings.', true],
  ]);
  assert.deepEqual(card.disconnect, { label: 'Disconnect', disabled: false });
  assert.equal(card.connect, null);
});

test('errors show inline: the local action error first, then the core last_error', () => {
  const error = { code: 'access_denied', message: "Google sign-in was cancelled, so your calendar wasn't connected." };
  assert.equal(view({ setup_needed: false, last_error: error }).error, error.message);
  assert.equal(view({ setup_needed: false, last_error: error }, { error: 'Local failure.' }).error, 'Local failure.');
  assert.equal(view({}).error, '');
});

test('status validation rejects malformed payloads and never trusts an odd email', () => {
  assert.equal(normalizeStatus(null), null);
  assert.equal(normalizeStatus({ connected: 'yes' }), null);
  assert.equal(normalizeStatus(raw({ connected: true, email: '<script>' })).email, null);
  assert.equal(normalizeStatus(raw({ connected: false, email: 'you@gmail.com' })).email, null);
  assert.equal(normalizeStatus(raw({ connecting: true, connected: true })).connecting, false);
  assert.deepEqual(normalizeStatus(raw({ switches: { read_events: 'no' } })).switches,
    { read_events: true, share_free_busy: true, add_events: true });
  assert.equal(cardView(null).phase, 'loading');
});

test('only Google sign-in URLs are opened; setup steps match the guide', () => {
  assert.equal(safeAuthUrl('https://accounts.google.com/o/oauth2/v2/auth?x=1'), 'https://accounts.google.com/o/oauth2/v2/auth?x=1');
  for (const url of ['http://accounts.google.com/o', 'https://accounts.google.com.evil.test/', 'https://example.com', 'javascript:alert(1)', 7])
    assert.equal(safeAuthUrl(url), null);
  assert.equal(CONSOLE_URL, 'https://console.cloud.google.com/apis/credentials');
  assert.equal(SETUP_STEPS.length, 6);
  assert.deepEqual(SWITCHES.map((row) => row.id), ['read_events', 'share_free_busy', 'add_events']);
  assert.equal(setupReady(' id ', 'secret'), true);
  assert.equal(setupReady('id', '  '), false);
});

class Socket extends EventEmitter {
  connected = true;
  requests = [];
  emit(event, data, ack) {
    if (typeof ack === 'function') { this.requests.push({ event, data, ack }); return true; }
    return super.emit(event, data);
  }
}

test('the client sends only the calendar and secrets routes and validates replies', async () => {
  const socket = new Socket(), client = createCalendarClient(socket);
  const pending = client.connect();
  assert.deepEqual([socket.requests[0].event, socket.requests[0].data], ['calendar_connect', {}]);
  socket.requests[0].ack({ ok: true, auth_url: 'https://accounts.google.com/o/oauth2/v2/auth?a=1', calendar: raw({ connecting: true }) });
  const { status, authUrl } = await pending;
  assert.equal(status.connecting, true);
  assert.match(authUrl, /^https:\/\/accounts\.google\.com\//);
  const toggled = client.setSwitch('add_events', false);
  assert.deepEqual(socket.requests[1].data, { add_events: false });
  socket.requests[1].ack({ ok: true, calendar: { nope: true } });
  await assert.rejects(toggled, { code: 'invalid_response' });
  const saving = client.saveClient(' 1-a.apps.googleusercontent.com ', 'GOCSPX-x');
  socket.requests[2].ack({ ok: true, secret: {} });
  await new Promise((resolve) => setImmediate(resolve));
  socket.requests[3].ack({ ok: true, secret: {} });
  await new Promise((resolve) => setImmediate(resolve));
  socket.requests[4].ack({ ok: true, calendar: raw({ setup_needed: false }) });
  assert.equal((await saving).setupNeeded, false);
  assert.deepEqual(socket.requests.slice(2, 5).map((r) => [r.event, r.data.name]), [
    ['secrets_set', 'google_oauth_client_id'], ['secrets_set', 'google_oauth_client_secret'], ['calendar_status', undefined]]);
  assert.equal(socket.requests[2].data.value, '1-a.apps.googleusercontent.com');
  client.dispose();
});

test('the events module stores pushed and refreshed status', () => {
  const socket = new Socket(), handlers = {}, unsubs = [];
  let state = {};
  const store = { setState: (patch) => { state = { ...state, ...patch }; } };
  registerCalendarEvents({ onSocket: (event, handler) => { handlers[event] = handler; return () => {}; }, socket, store, unsubs });
  assert.equal(unsubs.length, 3);
  handlers.calendar_status(raw({ connected: true, email: 'you@gmail.com', setup_needed: false }));
  assert.equal(state.calendarStatus.email, 'you@gmail.com');
  handlers.calendar_status({ broken: true });
  assert.equal(state.calendarStatus.connected, true);
  handlers.connect();
  assert.equal(socket.requests[0].event, 'calendar_status');
  socket.requests[0].ack({ ok: true, calendar: raw() });
  assert.equal(state.calendarStatus.connected, false);
});

test('the approval card for calendar_add_event shows the core sentence', () => {
  const approval = 'Add “Lunch with Aisyah” to your calendar, Monday 9 November 13:00 to 14:00?';
  assert.deepEqual(
    approvalView({ id: 'a', tool: 'calendar_add_event', args: { summary: 'Lunch with Aisyah', start: 'x', end: 'y', approval } }),
    { kind: 'calendar_event', title: 'Add to calendar', summary: approval, approveLabel: 'Add', denyLabel: 'Not now', details: null });
  assert.equal(approvalView({ id: 'b', tool: 'calendar_add_event', args: { summary: 'x' } }).kind, 'generic');
});
