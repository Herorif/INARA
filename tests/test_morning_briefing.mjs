import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  CALL_BACK_LABEL, DISMISS_LABEL, EMPTY_TEXT, PLAY_LABEL, SECTION_LABELS, briefingVisible, headerText, itemLink,
  parseBriefing, playMessage, receiveBriefing,
} from '../src/features/briefing/briefingModel.js';
import {
  DEFAULTS, ENABLED_LABEL, PHONE_HELP, PHONE_LABEL, SPEAK_HELP, SPEAK_LABEL, TIME_FORMAT, WINDOW_ORDER,
  briefingChoice, enabledHelp, phoneTimePatch, playResult, switchPatch, windowPatch,
} from '../src/features/settings/briefingSettingsModel.js';
import { createBriefingSlice } from '../src/store/briefingSlice.js';

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8').replace(/\r\n/g, '\n');
const JOB = '9f3c2a17-5b6d-4c1e-8f00-000000000001';
const RECORD = '5abe8b6d-3fa6-4b7d-8c2f-7e6d0a3b9f65';
// What services/briefing.py composes for the approved mockup (tests/test_morning_briefing.py).
const card = () => ({
  date_label: 'Sunday 8 November',
  sections: [
    { id: 'today', items: [{ time: '10:00', text: 'Dentist, Dr Lim' }, { time: '15:00', text: 'Design review' }] },
    { id: 'reminders', items: [{ time: '—', text: 'Send the invoice to Hafiz' }, { time: '18:00', text: 'Pick up the parcel' }] },
    { id: 'calls', items: [
      { time: '22:41', text: 'Mum · VIP', detail: "Call me when you're up, nothing urgent.", tone: 'accent', action: { kind: 'call', record_id: RECORD } },
      { time: '02:13', text: '1 call ended as spam', tone: 'muted' },
    ] },
    { id: 'jobs', items: [{ time: '23:58', text: 'NAS case built · revision 9f3c2a17', action: { kind: 'studio', request_id: JOB, studio: 'cad' } }] },
  ],
});
const payload = (extra = {}) => ({ date: '2026-11-08', card: card(), expires_at: '2026-11-08T12:00:00+08:00', ...extra });

test('the card is validated into sections in order, with labels and links', () => {
  const briefing = parseBriefing(payload());
  assert.equal(briefing.dateLabel, 'Sunday 8 November');
  assert.equal(briefing.expiresAt, Date.parse('2026-11-08T12:00:00+08:00'));
  assert.deepEqual(briefing.sections.map(section => section.id), ['today', 'reminders', 'calls', 'jobs']);
  assert.deepEqual(briefing.sections.map(section => section.label), ['Today', 'Reminders', 'Overnight calls', 'Finished jobs']);
  const [vip, spam] = briefing.sections[2].items;
  assert.deepEqual(vip, { time: '22:41', text: 'Mum · VIP', detail: "Call me when you're up, nothing urgent.", tone: 'accent', action: { kind: 'call', recordId: RECORD } });
  assert.equal(spam.tone, 'muted');
  assert.equal(briefing.sections[1].items[0].time, '—');
  assert.equal(headerText(briefing), 'GOOD MORNING · SUNDAY 8 NOVEMBER');
  assert.deepEqual(SECTION_LABELS, { today: 'Today', reminders: 'Reminders', calls: 'Overnight calls', jobs: 'Finished jobs' });
  assert.equal(PLAY_LABEL, 'Play again');
  assert.equal(DISMISS_LABEL, 'Dismiss');
});

test('malformed payloads and items are dropped', () => {
  for (const bad of [null, [], 'x', {}, payload({ date: '8 Nov' }), payload({ expires_at: 'soon' }), payload({ card: null }),
    payload({ card: { ...card(), date_label: '' } }), payload({ card: { ...card(), sections: 'x' } })]) {
    assert.equal(parseBriefing(bad), null);
  }
  const value = card();
  value.sections.push({ id: 'weather', items: [{ time: '09:00', text: 'Rain' }] }, { id: 'today', items: [{ time: '11:00', text: 'Twice' }] });
  value.sections[0].items.push({ time: '9:00', text: 'Bad time' }, { time: '12:00', text: '' }, { time: '12:00', text: 'Ok', tone: 'loud', action: { kind: 'call', record_id: 'a b' } });
  const briefing = parseBriefing(payload({ card: value }));
  assert.deepEqual(briefing.sections.map(section => section.id), ['today', 'reminders', 'calls', 'jobs']);
  assert.deepEqual(briefing.sections[0].items.at(-1), { time: '12:00', text: 'Ok', detail: null, tone: null, action: null });
  const controls = parseBriefing(payload({ card: { date_label: 'Sunday\u00008 November', sections: [{ id: 'today', items: [{ time: '10:00', text: 'A\u202eB\n  C' }] }] } }));
  assert.equal(controls.dateLabel, 'Sunday 8 November');
  assert.equal(controls.sections[0].items[0].text, 'A B C');
  assert.deepEqual(parseBriefing(payload({ card: { date_label: 'Sunday 8 November', sections: [] } })).sections, []);
  assert.equal(EMPTY_TEXT, 'Nothing new overnight.');
});

test('the briefing event sets or clears the store value', () => {
  assert.equal(receiveBriefing({ briefing: null }), null);
  assert.equal(receiveBriefing(null), null);
  assert.equal(receiveBriefing({ briefing: payload() }).date, '2026-11-08');
  let state = {};
  const slice = createBriefingSlice(patch => { state = { ...state, ...patch }; });
  assert.equal(slice.briefing, null);
  slice.setBriefing(parseBriefing(payload()));
  assert.equal(state.briefing.sections.length, 4);
});

test('the card hides at its expiry', () => {
  const briefing = parseBriefing(payload());
  assert.equal(briefingVisible(briefing, Date.parse('2026-11-08T11:59:59+08:00')), true);
  assert.equal(briefingVisible(briefing, Date.parse('2026-11-08T12:00:00+08:00')), false);
  assert.equal(briefingVisible(null, 0), false);
});

test('"Call back" opens Calls with the approval focused; a job opens its studio revision', () => {
  const briefing = parseBriefing(payload());
  assert.deepEqual(itemLink(briefing.sections[2].items[0]), { kind: 'call', label: CALL_BACK_LABEL, focus: { recordId: RECORD, approve: true } });
  assert.equal(CALL_BACK_LABEL, 'Call back');
  assert.deepEqual(itemLink(briefing.sections[3].items[0]), { kind: 'studio', feature: 'cad', requestId: JOB, title: 'Open in 3D studio' });
  assert.equal(itemLink(briefing.sections[0].items[0]), null);
});

test('"Play again" explains why JARVIS did not read it out', () => {
  assert.equal(playMessage({ ok: true, spoken: true }), '');
  assert.match(playMessage({ ok: true, spoken: false, reason: 'gaming_mode' }), /Gaming mode/);
  assert.match(playMessage({ ok: true, spoken: false, reason: 'voice_busy' }), /Voice is already on/);
  assert.match(playMessage({ ok: true, spoken: false, reason: 'provider_not_configured' }), /Gemini API key/);
  assert.match(playMessage({ ok: true, spoken: false, reason: 'voice_unavailable' }), /couldn't read it out/);
  assert.equal(playMessage({ code: 'offline', message: 'Connect to the core before using Studio.' }), 'Connect to the core before using Studio.');
});

test('the card sits under the presence header, above the messages, and reuses the VIP call-back path', () => {
  const conversation = read('src/app/Conversation.jsx');
  const header = conversation.indexOf('</header>');
  const card = conversation.indexOf('<MorningBriefingCard onOpen={onOpen} />');
  const body = conversation.indexOf('<div className="conversation-body">');
  assert.ok(header > 0 && header < card && card < body);
  const component = read('src/features/briefing/MorningBriefingCard.jsx');
  assert.match(component, /store\(\)\.focusCall\(link\.focus\)/);
  assert.match(component, /onOpen\?\.\(link\.feature, undefined, link\.requestId\)/);
  assert.match(component, /aria-label=\{DISMISS_LABEL\}/);
  const css = read('src/features/briefing/morning-briefing.css');
  assert.match(css, /border: 1px solid var\(--line-strong\);/);
  assert.match(css, /background: var\(--bg-panel\);/);
  assert.match(css, /grid-template-columns: 120px minmax\(0, 1fr\);/);
  assert.match(css, /grid-template-columns: minmax\(44px, max-content\) minmax\(0, 1fr\);/);
  assert.match(read('src/services/socketSubscriptions.js'), /registerBriefingEvents\(dependencies\);/);
  assert.match(read('src/app/stageModel.js'), /briefing: 'Morning briefing'/);
});

// --- Preferences > Assistant > Morning briefing ---------------------------------------------------

test('the saved briefing settings read with the core defaults', () => {
  assert.deepEqual(DEFAULTS, { enabled: true, window_start: '06:00', window_end: '11:00', speak: true, phone: false, phone_time: '07:30' });
  assert.deepEqual(briefingChoice(null), DEFAULTS);
  assert.deepEqual(briefingChoice({ enabled: 'yes', window_start: '12:00', window_end: '08:00', phone_time: '7:30', phone: true }), { ...DEFAULTS, phone: true });
  assert.deepEqual(briefingChoice({ window_start: '05:30', window_end: '10:00' }), { ...DEFAULTS, window_start: '05:30', window_end: '10:00' });
});

test('the copy matches the approved design', () => {
  assert.equal(ENABLED_LABEL, 'Morning briefing');
  assert.equal(enabledHelp(DEFAULTS), 'The first time you’re at the PC between 06:00 and 11:00.');
  assert.equal(enabledHelp({ ...DEFAULTS, window_start: '05:30' }), 'The first time you’re at the PC between 05:30 and 11:00.');
  assert.equal(SPEAK_LABEL, 'Speak it aloud');
  assert.equal(SPEAK_HELP, 'Otherwise just the card.');
  assert.equal(PHONE_LABEL, 'Also phone me with it');
  assert.equal(PHONE_HELP, 'At a set time, when you’re away from the PC.');
});

test('switch, window and phone-time patches', () => {
  assert.deepEqual(switchPatch(DEFAULTS, 'enabled', false), { briefing: { enabled: false } });
  assert.deepEqual(switchPatch(DEFAULTS, 'phone', true), { briefing: { phone: true } });
  assert.equal(switchPatch(DEFAULTS, 'speak', true), null);
  assert.equal(switchPatch(DEFAULTS, 'window_start', true), null);
  assert.deepEqual(windowPatch(DEFAULTS, '05:30', '11:00'), { patch: { briefing: { window_start: '05:30' } } });
  assert.deepEqual(windowPatch(DEFAULTS, '06:00', '11:00'), {});
  assert.deepEqual(windowPatch(DEFAULTS, '11:00', '06:00'), { error: WINDOW_ORDER });
  assert.deepEqual(windowPatch(DEFAULTS, '', '11:00'), { error: TIME_FORMAT });
  assert.deepEqual(phoneTimePatch(DEFAULTS, '07:00'), { patch: { briefing: { phone_time: '07:00' } } });
  assert.deepEqual(phoneTimePatch(DEFAULTS, '07:30'), {});
  assert.deepEqual(phoneTimePatch(DEFAULTS, '7'), { error: TIME_FORMAT });
});

test('"Play today’s briefing" reports the outcome', () => {
  assert.deepEqual(playResult({ ok: true, spoken: true }), { tone: 'ok', text: 'Playing today’s briefing.' });
  assert.equal(playResult({ ok: true, spoken: false, reason: 'gaming_mode' }).tone, 'warn');
  assert.match(playResult({ ok: true, spoken: false, reason: 'voice_busy' }).text, /^The card is on the Assistant page\./);
  assert.deepEqual(playResult({ code: 'timeout', message: 'The core did not respond.' }), { tone: 'danger', text: 'The core did not respond.' });
});

test('Preferences shows the block under Assistant, the phone time only with the phone switch on', () => {
  const ai = read('src/features/settings/AiSettings.jsx');
  const address = ai.indexOf('data-assistant-address');
  const block = ai.indexOf('<BriefingSettings briefing={briefing} patch={patchSettings} />');
  const voice = ai.indexOf('<VoiceSettings');
  assert.ok(address > 0 && address < block && block < voice);
  const settings = read('src/features/settings/BriefingSettings.jsx');
  assert.match(settings, /\{choice\.phone && <label className=\{TIME_LABEL\}>\{PHONE_TIME_LABEL\}/);
  assert.match(settings, /client\.play\(\)/);
  assert.match(read('src/components/SettingsWindow.jsx'), /<AiSettings assistant=\{assistant\} voice=\{voice\} briefing=\{briefing\} \/>/);
});
