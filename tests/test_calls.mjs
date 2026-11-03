import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import {
  CANCEL_FORWARDING, DELETE_CONFIRM, answeringProblem, approveErrorMessage, callChip, callTitle, callsFailureMessage, callsSettings,
  detailMeta, emptyState, filterCalls, formatCallTime, formatDuration, forwardingCodes, messageRows, needsCallbackApproval,
  progressText, setupComplete, setupRows, summaryText, urgencyChip, validatePublicAddress, validateWhole, validPin,
} from '../src/features/calls/callsModel.js';
import { saveResultMessage, secretChip, testResultMessage } from '../src/features/settings/aiSettingsModel.js';
import { createCallsClient, isCallDetail, isCallProgress, isCallSummary, parseCallsStatus } from '../src/transport/callsClient.ts';
import { searchCommands } from '../src/app/features.js';
import { startPresencePing } from '../src/features/calls/presence.js';
import { featureWorkspace, workspaceTitles } from '../src/app/workspaceNavigation.js';

const summary = (extra = {}) => ({
  id: 'rec-1', direction: 'inbound', mode: 'screening', counterpart_masked: '+60 12-•••• 6789', name: 'Aina', started_at: 1793000000,
  duration_seconds: 125, urgency: 'urgent', needs_owner: true, summary: 'Wants a callback about the lease.', status: 'needs_you', outcome_status: null, ...extra,
});
const detail = (extra = {}) => ({
  ...summary(), fields: { name: 'Aina', reason: 'Lease renewal', urgency: 'urgent', callback_number_masked: '+60 12-•••• 6789', message: 'Please call before 5.' },
  triage: { summary: 'Aina needs a decision on the lease today.', urgency: 'urgent', needs_owner: true, suggested_actions: ['Call Aina back'] },
  triage_state: 'done', transcript: [{ role: 'inara', text: 'Hello.' }, { role: 'caller', text: 'Hi.' }], outcome: null, related_ids: [], ...extra,
});
const presence = (configured, verified = configured) => ({ configured, verified, source: configured ? 'store' : null });
const readiness = (extra = {}) => ({
  enabled: false, kill_switch: true, when_disabled: 'voicemail', public_base_url: 'https://calls.example.com', public_url_configured: true,
  secrets: { twilio_account_sid: presence(true), twilio_auth_token: presence(true), twilio_phone_number: presence(true, false), owner_phone_number: presence(true, false), cloudflare_tunnel_token: presence(true, false) },
  gateway: { listening: false, host: '127.0.0.1', port: 8790 }, tunnel: { state: 'stopped', binary_found: true, exit_code: null, restarts: 0 },
  agent: 'ready', active_calls: 0, outbound_today: 0, daily_outbound_cap: 10, failure: null, ready: false, ...extra,
});

test('row chips cover every status and mode', () => {
  assert.deepEqual(callChip(summary()), { tone: 'warn', label: 'NEEDS YOU' });
  assert.deepEqual(callChip(summary({ status: 'in_progress' })), { tone: 'accent', label: 'IN PROGRESS' });
  assert.deepEqual(callChip(summary({ status: 'failed' })), { tone: 'danger', label: 'FAILED' });
  assert.deepEqual(callChip(summary({ status: 'callback_blocked' })), { tone: 'warn', label: 'BLOCKED' });
  assert.deepEqual(callChip(summary({ status: 'done' })), { tone: 'idle', label: 'SCREENED' });
  assert.deepEqual(callChip(summary({ status: 'done', mode: 'approved_callback' })), { tone: 'idle', label: 'CALLBACK' });
  assert.deepEqual(callChip(summary({ status: 'done', mode: 'task' })), { tone: 'ok', label: 'TASK DONE' });
  assert.equal(callChip(summary({ status: 'done', mode: 'owner_briefing' })).label, 'BRIEFING');
  assert.deepEqual(urgencyChip('urgent'), { tone: 'danger', label: 'URGENT' });
  assert.equal(urgencyChip(null), null);
});

test('list filtering, titles and empty states', () => {
  const calls = [summary(), summary({ id: 'b', status: 'done' }), summary({ id: 'c', status: 'callback_blocked' }), summary({ id: 'd', status: 'failed' })];
  assert.deepEqual(filterCalls(calls, 'needs_you').map(call => call.id), ['rec-1', 'c']);
  assert.deepEqual(filterCalls(calls, 'done').map(call => call.id), ['b']);
  assert.equal(filterCalls(calls, 'all').length, 4);
  assert.deepEqual(filterCalls(null, 'all'), []);
  assert.equal(callTitle(summary()), 'Aina');
  assert.equal(callTitle(summary({ name: null })), '+60 12-•••• 6789');
  assert.equal(callTitle(summary({ name: ' ', counterpart_masked: null })), 'Unknown caller');
  assert.equal(emptyState('needs_you').title, 'No calls need you');
  assert.equal(emptyState('all').title, 'No calls yet');
  assert.equal(emptyState('done').title, 'No calls yet');
  assert.equal(needsCallbackApproval(summary()), true);
  assert.equal(needsCallbackApproval(summary({ status: 'done' })), false);
  assert.equal(needsCallbackApproval(summary({ mode: 'owner_briefing', direction: 'outbound' })), false, 'only screened incoming calls are called back');
  assert.equal(callTitle(summary({ name: null, counterpart_masked: 'withheld' })), 'Withheld number');
});

test('times: HH:MM today, weekday this week, date otherwise', () => {
  const now = new Date(2026, 10, 4, 15, 30);
  assert.equal(formatCallTime(new Date(2026, 10, 4, 9, 5).getTime() / 1000, now, 'en-GB'), '09:05');
  assert.equal(formatCallTime(new Date(2026, 10, 3, 23, 0).toISOString(), now, 'en-GB'), 'Tue');
  assert.equal(formatCallTime(new Date(2026, 9, 29, 12, 0).getTime() / 1000, now, 'en-GB'), 'Thu');
  assert.equal(formatCallTime(new Date(2026, 9, 28, 12, 0).getTime() / 1000, now, 'en-GB'), '28 Oct');
  assert.equal(formatCallTime(new Date(2025, 9, 28, 12, 0).getTime() / 1000, now, 'en-GB'), '28 Oct 2025');
  assert.equal(formatCallTime('not a date', now), '');
  assert.equal(formatDuration(125), '2:05');
  assert.equal(formatDuration(7), '0:07');
  assert.equal(formatDuration(3725), '1:02:05');
  assert.equal(formatDuration(null), '');
  assert.equal(detailMeta(summary()), '+60 12-•••• 6789 · incoming · 2:05');
  assert.equal(detailMeta(summary({ direction: 'outbound', duration_seconds: null, counterpart_masked: null })), 'outgoing');
});

test('summary and message panels say what is known', () => {
  assert.equal(summaryText(detail()), 'Aina needs a decision on the lease today.');
  assert.equal(summaryText(detail({ triage: null, triage_state: 'pending' })), 'Summarising…');
  assert.equal(summaryText(detail({ triage: null, triage_state: 'failed' })), 'No summary — see the transcript');
  assert.deepEqual(messageRows(detail()).map(([label]) => label), ['Callback', 'Reason', 'Message', 'Urgency']);
  assert.deepEqual(messageRows(detail()).at(-1), ['Urgency', 'Urgent']);
  assert.deepEqual(messageRows(detail({ fields: null, urgency: null })), []);
});

test('approve failures map to plain sentences', () => {
  assert.equal(approveErrorMessage('quiet_hours', { start: '21:00', end: '09:00' }), "It's quiet hours (21:00–09:00). Try again later or change quiet hours in Call settings.");
  assert.equal(approveErrorMessage('quiet_hours', { start: '22:30', end: '07:00' }), "It's quiet hours (22:30–07:00). Try again later or change quiet hours in Call settings.");
  assert.equal(approveErrorMessage('daily_cap'), 'Daily call limit reached.');
  assert.equal(approveErrorMessage('cooldown'), 'INARA called this number recently. Try again later.');
  assert.equal(approveErrorMessage('no_callback_number'), 'No callback number was given.');
  assert.equal(approveErrorMessage('calls_disabled'), 'Calls are off.');
  assert.equal(approveErrorMessage('not_ready'), "Call setup isn't complete.");
  assert.equal(approveErrorMessage('not_ready', null, 'Only screened incoming calls can be called back.'), 'Only screened incoming calls can be called back.');
  assert.equal(approveErrorMessage('not_found'), 'This call record no longer exists.');
  assert.equal(callsFailureMessage({ code: 'not_found', message: 'x' }), 'This call record no longer exists.');
  assert.match(approveErrorMessage('busy'), /already on a call/);
  assert.equal(approveErrorMessage('something_else'), '');
  for (const code of ['offline', 'timeout', 'invalid_response']) assert.doesNotMatch(callsFailureMessage({ code, message: 'Refresh revision history before using Studio.' }), /Studio|revision/);
  assert.equal(callsFailureMessage({ code: 'x', message: 'Core says no.' }), 'Core says no.');
  for (const text of [DELETE_CONFIRM, approveErrorMessage('quiet_hours'), approveErrorMessage('daily_cap')]) assert.doesNotMatch(text, /!/);
});

test('callback progress follows call_progress states', () => {
  assert.deepEqual(['dialing', 'ringing', 'in_progress', 'completed', 'no_answer'].map(state => progressText({ state }).text),
    ['Dialing…', 'Ringing…', 'On the call', 'Completed', 'No answer']);
  assert.equal(progressText({ state: 'failed', message: 'The line was busy.' }).text, 'Failed: The line was busy.');
  assert.equal(progressText({ state: 'failed' }).text, 'Failed: the call could not be placed.');
  assert.equal(progressText({ state: 'completed' }).done, true);
  assert.equal(progressText({ state: 'ringing' }).done, false);
  assert.equal(progressText(undefined), null);
});

test('setup checklist rows come from calls_status', () => {
  const status = parseCallsStatus({ ok: true, calls: readiness() });
  assert.deepEqual(setupRows(status).map(row => [row.id, row.label]), [
    ['twilio', 'VERIFIED'], ['inara_number', 'SAVED'], ['owner_number', 'SAVED'], ['tunnel', 'SAVED'], ['address', 'SET'], ['voice', 'READY'], ['forwarding', 'NOT CONFIRMED'],
  ]);
  assert.equal(setupComplete(status), true, 'forwarding and the mobile number are recommended, not required');
  assert.equal(setupRows(status, true).at(-1).label, 'DONE');
  const missing = parseCallsStatus({ ok: true, calls: readiness({ tunnel: { state: 'missing_binary', binary_found: false }, agent: 'unavailable', public_url_configured: false, public_base_url: null,
    secrets: { ...readiness().secrets, twilio_auth_token: presence(true, false) } }) });
  const rows = Object.fromEntries(setupRows(missing).map(row => [row.id, row]));
  assert.deepEqual([rows.twilio.label, rows.tunnel.label, rows.address.label, rows.voice.label], ['NOT VERIFIED', 'CLOUDFLARED MISSING', 'NOT SET', 'NEEDS GEMINI KEY']);
  assert.equal(setupComplete(missing), false);
  assert.equal(setupRows(parseCallsStatus({ ok: true, calls: readiness({ tunnel: { state: 'failed', binary_found: true } }) }))[3].label, 'FAILED');
  assert.equal(setupRows(parseCallsStatus({ ok: true, calls: readiness({ tunnel: { state: 'running', binary_found: true } }) }))[3].label, 'RUNNING');
  assert.equal(setupComplete(null), false);
  assert.equal(answeringProblem(status), '');
  assert.equal(answeringProblem({ ...status, enabled: true, answering: false, tunnel: { state: 'failed', binary_found: true } }), 'The Cloudflare tunnel stopped.');
  assert.equal(answeringProblem({ ...status, enabled: true, answering: true }), '');
});

test('forwarding codes fill in INARA’s number when known', () => {
  assert.deepEqual(forwardingCodes('+60312345678').map(entry => entry.code), ['**67*+60312345678#', '**61*+60312345678**20#', '**62*+60312345678#']);
  assert.equal(forwardingCodes(null)[0].code, '**67*<INARA number>#');
  assert.equal(CANCEL_FORWARDING, '##002#');
});

test('call settings validation mirrors the core', () => {
  assert.deepEqual(validatePublicAddress(' https://Calls.Example.com '), { ok: true, value: 'https://calls.example.com' });
  assert.deepEqual(validatePublicAddress(''), { ok: true, value: '' });
  assert.equal(validatePublicAddress('http://calls.example.com').ok, false);
  assert.equal(validatePublicAddress('https://calls.example.com/').ok, false);
  assert.equal(validatePublicAddress('https://calls.example.com:8443').ok, false);
  assert.equal(validatePublicAddress('https://localhost').ok, false);
  assert.deepEqual(validateWhole('12', 0, 100), { ok: true, value: 12 });
  assert.equal(validateWhole('101', 0, 100).ok, false);
  assert.equal(validateWhole('1.5', 0, 100).ok, false);
  assert.equal(validateWhole('', 2, 30).error, 'Enter a whole number from 2 to 30.');
  assert.equal(validPin('1234'), true);
  assert.equal(validPin('123'), false);
  const settings = callsSettings({ calls: { enabled: true, quiet_hours: { start: '22:00', end: 'x' }, daily_outbound_cap: 5, brief_by_phone: 'urgent', when_disabled: 'bogus', facts: 7, briefing_pin: '9999' } });
  assert.deepEqual(settings.quiet_hours, { start: '22:00', end: '09:00' });
  assert.equal(settings.brief_by_phone, 'urgent');
  assert.equal(settings.when_disabled, null);
  assert.equal(settings.facts, '');
  assert.equal(Object.hasOwn(settings, 'briefing_pin'), false, 'the PIN never reaches the view');
  assert.equal(callsSettings(null).enabled, false);
});

test('contract validators accept the documented shapes and refuse others', () => {
  const nested = parseCallsStatus({ ok: true, calls: readiness() });
  assert.equal(nested.answering, false);
  assert.equal(nested.needs_you_count, 0);
  assert.equal(nested.active_call, null);
  assert.equal(nested.briefing_pin_set, null);
  const flat = parseCallsStatus({ ok: true, ...readiness({ enabled: true, ready: true }), answering: true, needs_you_count: 3, active_call: { id: 'CA1', mode: 'screening', direction: 'inbound', state: 'in_progress' }, briefing_pin_set: true, inara_number: '+60312345678' });
  assert.deepEqual([flat.answering, flat.needs_you_count, flat.active_call.id, flat.briefing_pin_set, flat.inara_number], [true, 3, 'CA1', true, '+60312345678']);
  assert.equal(parseCallsStatus({ ok: true, calls: readiness(), needs_you_count: 2 }).needs_you_count, 2, 'C3 fields may sit beside the nested report');
  assert.equal(parseCallsStatus({ ok: true, calls: readiness({ enabled: 'yes' }) }), null);
  assert.equal(parseCallsStatus({ ok: true, calls: readiness(), needs_you_count: -1 }), null);
  assert.equal(parseCallsStatus({ ok: true, calls: { ...readiness(), needs_you_count: null } }).needs_you_count, 0, 'an uncounted list reads as zero');
  assert.equal(parseCallsStatus({ ok: true, calls: { ...readiness(), active_call: { id: 'abc123', mode: null, direction: 'outbound', state: 'dialing' } } }).active_call.state, 'dialing');
  assert.equal(isCallSummary(summary({ mode: null, started_at: null })), true, 'C3a may not know the mode or start time');
  assert.equal(parseCallsStatus({ ok: true, calls: readiness(), active_call: { id: 5 } }), null);
  assert.equal(parseCallsStatus({ ok: true, calls: readiness(), inara_number: '+60312345678; rm' }), null);
  assert.equal(isCallSummary(summary()), true);
  assert.equal(isCallSummary(summary({ started_at: '2026-11-04T08:00:00Z' })), true);
  assert.equal(isCallSummary(summary({ status: 'archived' })), false);
  assert.equal(isCallSummary(summary({ direction: 'sideways' })), false);
  assert.equal(isCallSummary(summary({ id: '../x' })), false);
  assert.equal(isCallSummary(summary({ needs_owner: 'yes' })), false);
  assert.equal(isCallDetail(detail()), true);
  assert.equal(isCallDetail(detail({ fields: null, triage: null, triage_state: 'pending', transcript: [] })), true);
  assert.equal(isCallDetail(detail({ transcript: [{ role: 'system', text: 'x' }] })), false);
  assert.equal(isCallDetail(detail({ triage: { summary: 'x', urgency: 'low', needs_owner: true, suggested_actions: 'call' } })), false);
  assert.equal(isCallProgress({ call_id: 'CA1', record_id: null, mode: 'approved_callback', direction: 'outbound', state: 'ringing' }), true);
  assert.equal(isCallProgress({ call_id: 'CA1', record_id: null, mode: 'approved_callback', direction: 'outbound', state: 'exploded' }), false);
});

class Socket extends EventEmitter {
  connected = true;
  requests = [];
  emit(event, ...args) {
    if (event.startsWith('calls_') || event === 'update_settings') { this.requests.push({ event, data: args[0], ack: args[1] }); return true; }
    return super.emit(event, ...args);
  }
}

test('calls client sends the documented requests and validates replies', async () => {
  const socket = new Socket();
  const client = createCallsClient(socket);
  assert.equal(socket.requests.length, 0, 'no startup requests');
  const listed = client.list('needs_you');
  assert.deepEqual(socket.requests[0].data, { filter: 'needs_you', limit: 100 });
  socket.requests[0].ack({ ok: true, calls: [summary()] });
  assert.equal((await listed)[0].id, 'rec-1');
  const broken = client.list('all');
  socket.requests[1].ack({ ok: true, calls: [{ id: 'x' }] });
  await assert.rejects(broken, { code: 'invalid_response' });
  await assert.rejects(client.list('everything'), { code: 'invalid_arguments' });
  const opened = client.get('rec-1');
  assert.deepEqual(socket.requests[2], { event: 'calls_get', data: { id: 'rec-1' }, ack: socket.requests[2].ack });
  socket.requests[2].ack({ ok: true, call: detail({ related_ids: undefined }) });
  assert.deepEqual((await opened).related_ids, []);
  const other = client.get('rec-1');
  socket.requests[3].ack({ ok: true, call: detail({ id: 'rec-2' }) });
  await assert.rejects(other, { code: 'invalid_response' }, 'a reply for another record is refused');
  const draft = client.callbackDraft('rec-1');
  socket.requests[4].ack({ ok: true, message: 'Hi Aina, Hiro will be free after 6 pm.' });
  assert.match(await draft, /Aina/);
  await assert.rejects(client.approveCallback('rec-1', 'x'.repeat(501)), { code: 'invalid_arguments' });
  await assert.rejects(client.approveCallback('rec-1', '   '), { code: 'invalid_arguments' });
  const approved = client.approveCallback('rec-1', 'Hi Aina.');
  assert.deepEqual(socket.requests[5].data, { id: 'rec-1', message: 'Hi Aina.' });
  socket.requests[5].ack({ ok: false, code: 'quiet_hours', message: 'Quiet hours.' });
  await assert.rejects(approved, { code: 'quiet_hours' });
  const approvedAgain = client.approveCallback('rec-1', 'Hi Aina.');
  socket.requests[6].ack({ ok: true, call_id: 'CA0123' });
  assert.equal(await approvedAgain, 'CA0123');
  const done = client.markDone('rec-1');
  assert.deepEqual(socket.requests[7].data, { id: 'rec-1' });
  socket.requests[7].ack({ ok: true });
  await done;
  const status = client.status();
  socket.requests[8].ack({ ok: true, calls: readiness() });
  assert.equal((await status).agent, 'ready');
  socket.connected = false;
  await assert.rejects(client.remove('rec-1'), { code: 'offline' });
  assert.equal(socket.requests.length, 9, 'offline actions are not queued');
  client.dispose();
});

test('telephony secrets share the key row messages', () => {
  const saved = { name: 'twilio_phone_number', label: "INARA's Twilio number", configured: true, source: 'store', hint: '5678', verified_at: null, last_check: { ok: false, code: 'no_check', at: 'x' } };
  assert.deepEqual(secretChip(saved), { tone: 'ok', label: 'SAVED ··5678', envOverride: false, hint: '5678', prefix: 'SAVED' });
  assert.deepEqual(secretChip({ ...saved, hint: null }), { tone: 'ok', label: 'SAVED', envOverride: false });
  assert.deepEqual(saveResultMessage('twilio_phone_number', saved), { tone: 'ok', text: 'Saved.' });
  const incomplete = { ...saved, name: 'twilio_account_sid', last_check: { ok: false, code: 'incomplete', at: 'x' } };
  assert.equal(saveResultMessage('twilio_account_sid', incomplete).text, 'Saved. Twilio can check it once the other value is saved.');
  assert.equal(secretChip(incomplete).label, 'SAVED · NOT VERIFIED');
  assert.equal(testResultMessage('twilio_auth_token', incomplete).text, 'Save the other Twilio value first, then test again.');
  assert.equal(testResultMessage('twilio_auth_token', { ...incomplete, last_check: { ok: true, code: 'ok', at: 'x' } }).text, 'Twilio accepted this key.');
});

test('Calls sits in navigation and the palette without taking Call lab’s searches', () => {
  assert.equal(searchCommands('calls')[0].title, 'Calls');
  assert.equal(searchCommands('Call bridge lab')[0].title, 'Call lab');
  assert.equal(featureWorkspace('callsview'), 'callsview');
  assert.deepEqual(workspaceTitles.callsview, ['Calls', 'Calls INARA answered and made for you']);
});

test('presence ping: on input at most once a minute, on focus always, only while focused and connected', () => {
  const target = new EventTarget(), sent = [];
  let clock = 1000, focused = true;
  const socket = { connected: true, emit: (event, data, ack) => { sent.push([event, data, typeof ack]); } };
  const stop = startPresencePing({ socket, target, hasFocus: () => focused, now: () => clock });
  assert.equal(sent.length, 0, 'nothing is sent before input');
  target.dispatchEvent(new Event('keydown'));
  assert.deepEqual(sent, [['presence_ping', {}, 'function']]);
  clock += 30000; target.dispatchEvent(new Event('pointerdown')); target.dispatchEvent(new Event('wheel'));
  assert.equal(sent.length, 1, 'throttled within a minute');
  clock += 30000; target.dispatchEvent(new Event('wheel'));
  assert.equal(sent.length, 2, 'a minute later input pings again');
  clock += 1000; target.dispatchEvent(new Event('focus'));
  assert.equal(sent.length, 3, 'gaining focus pings even inside the minute');
  focused = false; clock += 120000; target.dispatchEvent(new Event('keydown'));
  assert.equal(sent.length, 3, 'input while the window is not focused does not ping');
  focused = true; socket.connected = false; target.dispatchEvent(new Event('keydown'));
  assert.equal(sent.length, 3, 'offline pings are not queued');
  socket.connected = true; stop(); clock += 120000; target.dispatchEvent(new Event('keydown')); target.dispatchEvent(new Event('focus'));
  assert.equal(sent.length, 3, 'stop removes every listener');
});
