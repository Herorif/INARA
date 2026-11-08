// Pure mappings for the Calls view: status -> chip, error code -> plain message,
// times, setup checklist rows and settings validation. No numbers or secrets pass
// through here except the masked values and statuses the core returns.

export const FILTERS = [
  { id: 'needs_you', label: 'Needs you' },
  { id: 'all', label: 'All' },
  { id: 'done', label: 'Done' },
  { id: 'spam', label: 'Spam' },
  { id: 'people', label: 'People' },
];

export const CALLBACK_LIMIT = 500;
export const FACTS_LIMIT = 1000;
export const DELETE_CONFIRM = "Delete this call record? This can't be undone.";
export const FORWARDING_STORAGE_KEY = 'jarvis.calls.forwardingConfirmed';

/** Chip for a list row: { tone, label }. */
export function callChip(call) {
  switch (call?.status) {
    case 'needs_you': return { tone: 'warn', label: 'NEEDS YOU' };
    case 'in_progress': return { tone: 'accent', label: 'IN PROGRESS' };
    case 'failed': return { tone: 'danger', label: 'FAILED' };
    case 'callback_blocked': return { tone: 'warn', label: 'BLOCKED' };
    case 'spam': return { tone: 'idle', label: 'SPAM' };
    case 'blocked': return { tone: 'danger', label: 'BLOCKED' };
    case 'done':
      if (call.mode === 'task') return { tone: 'ok', label: 'TASK DONE' };
      if (call.mode === 'approved_callback') return { tone: 'idle', label: 'CALLBACK' };
      if (call.mode === 'owner_briefing' || call.mode === 'morning_briefing') return { tone: 'idle', label: 'BRIEFING' };
      return { tone: 'idle', label: 'SCREENED' };
    default: return { tone: 'idle', label: 'CALL' };
  }
}

export function urgencyChip(urgency) {
  if (urgency === 'urgent') return { tone: 'danger', label: 'URGENT' };
  if (urgency === 'normal') return { tone: 'idle', label: 'NORMAL' };
  if (urgency === 'low') return { tone: 'idle', label: 'LOW' };
  return null;
}

/** Name if the caller gave one, else the masked number, else a neutral word. */
export const callTitle = call => (call?.name && call.name.trim())
  || (call?.counterpart_masked && call.counterpart_masked !== 'withheld' ? call.counterpart_masked : null)
  || (call?.counterpart_masked === 'withheld' ? 'Withheld number' : 'Unknown caller');

export const directionLabel = direction => direction === 'outbound' ? 'outgoing' : 'incoming';

/** Rows the current tab shows; the core already filters, this keeps a stale list honest. */
export function filterCalls(calls, filter) {
  const list = Array.isArray(calls) ? calls : [];
  if (filter === 'needs_you') return list.filter(call => call.status === 'needs_you' || call.status === 'callback_blocked');
  if (filter === 'done') return list.filter(call => call.status === 'done');
  if (filter === 'spam') return list.filter(call => call.status === 'spam' || call.status === 'blocked');
  return list;
}

export function emptyState(filter) {
  if (filter === 'needs_you') return { title: 'No calls need you', body: 'Calls that need a decision from you show up here.' };
  if (filter === 'spam') return { title: 'No spam', body: 'Sales calls, recorded messages, scams and calls from blocked numbers show up here.' };
  return { title: 'No calls yet', body: 'Calls JARVIS answers or makes for you show up here.' };
}

const toDate = value => {
  if (typeof value === 'number' && Number.isFinite(value)) return new Date(value < 1e11 ? value * 1000 : value);
  if (typeof value === 'string') { const date = new Date(value); return Number.isNaN(date.getTime()) ? null : date; }
  return null;
};
const sameDay = (left, right) => left.getFullYear() === right.getFullYear() && left.getMonth() === right.getMonth() && left.getDate() === right.getDate();

/** List time: HH:MM today, weekday within the last six days, else day and month (and year when not this year). */
export function formatCallTime(startedAt, now = new Date(), locale = undefined) {
  const date = toDate(startedAt);
  if (!date) return '';
  if (sameDay(date, now)) return date.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const days = Math.ceil((midnight - date.getTime()) / 86400000);
  if (date.getTime() < midnight && days <= 6) return new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(date);
  return new Intl.DateTimeFormat(locale, date.getFullYear() === now.getFullYear()
    ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' }).format(date);
}

export const callDateTime = startedAt => toDate(startedAt)?.toISOString() ?? '';

/** m:ss (or h:mm:ss). */
export function formatDuration(seconds) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return '';
  const total = Math.round(seconds), hours = Math.floor(total / 3600), minutes = Math.floor((total % 3600) / 60), rest = total % 60;
  const pad = value => String(value).padStart(2, '0');
  return hours ? `${hours}:${pad(minutes)}:${pad(rest)}` : `${minutes}:${pad(rest)}`;
}

/** "masked number · incoming · 2:05", skipping what is unknown. */
export function detailMeta(call) {
  return [call?.counterpart_masked, directionLabel(call?.direction), formatDuration(call?.duration_seconds)].filter(Boolean).join(' · ');
}

export function summaryText(call) {
  if (call?.status === 'blocked') return "Blocked number. JARVIS said you aren't taking calls and ended the call.";
  if (call?.triage?.summary) return call.triage.summary;
  if (call?.triage_state === 'pending') return 'Summarising…';
  if (call?.triage_state === 'failed') return 'No summary — see the transcript';
  return call?.summary || 'No summary — see the transcript';
}

/** MESSAGE panel rows, only those the caller actually gave. */
export function messageRows(call) {
  const fields = call?.fields || {};
  const urgency = urgencyChip(fields.urgency || call?.urgency);
  return [
    ['Callback', fields.callback_number_masked],
    ['Reason', fields.reason],
    ['Message', fields.message],
    ['Urgency', urgency ? urgency.label.charAt(0) + urgency.label.slice(1).toLowerCase() : null],
  ].filter(([, value]) => typeof value === 'string' && value.trim());
}

/** The approval card shows for calls that wait on a callback decision. */
export const needsCallbackApproval = call => (call?.status === 'needs_you' || call?.status === 'callback_blocked')
  && call.direction === 'inbound' && (call.mode === 'screening' || call.mode === null || call.mode === undefined);

export const ROLE_LABELS = { caller: 'CALLER', jarvis: 'JARVIS', owner: 'YOU' };

export function quietHoursText(quietHours) {
  const start = quietHours?.start || '21:00', end = quietHours?.end || '09:00';
  return `${start}–${end}`;
}

export const NOT_FOUND = 'This call record no longer exists.';

/** calls_callback_approve failure code -> plain sentence; `not_ready` carries the core's real reason. */
export function approveErrorMessage(code, quietHours, message = '') {
  switch (code) {
    case 'quiet_hours': return `It's quiet hours (${quietHoursText(quietHours)}). Try again later or change quiet hours in Call settings.`;
    case 'daily_cap': return 'Daily call limit reached.';
    case 'cooldown': return 'JARVIS called this number recently. Try again later.';
    case 'no_callback_number': return 'No callback number was given.';
    case 'calls_disabled': return 'Calls are off.';
    case 'not_ready': return (typeof message === 'string' && message.trim()) || "Call setup isn't complete.";
    case 'not_found': return NOT_FOUND;
    case 'busy': return 'JARVIS is already on a call. Try again when it ends.';
    default: return '';
  }
}

/** Transport failure -> plain sentence (never the shared RPC scope's Studio wording). */
export function callsFailureMessage(error) {
  const code = error && typeof error === 'object' ? error.code : undefined;
  if (code === 'offline' || code === 'disconnected') return 'JARVIS core is offline. Reconnect and try again.';
  if (code === 'timeout') return 'The core did not answer in time. Refresh Calls before trying again.';
  if (code === 'invalid_response' || code === 'send_failed' || code === 'scope_closed') return 'The request did not finish. Refresh Calls and try again.';
  if (code === 'not_found') return NOT_FOUND;
  const message = error && typeof error === 'object' && typeof error.message === 'string' ? error.message : '';
  return message || 'The request did not finish. Try again.';
}

/** Inline progress line for an approved callback, from call_progress. */
export function progressText(progress) {
  switch (progress?.state) {
    case 'dialing': return { tone: 'accent', text: 'Dialing…', done: false };
    case 'ringing': return { tone: 'accent', text: 'Ringing…', done: false };
    case 'in_progress': return { tone: 'accent', text: 'On the call', done: false };
    case 'completed': return { tone: 'ok', text: 'Completed', done: true };
    case 'no_answer': return { tone: 'warn', text: 'No answer', done: true };
    case 'failed': return { tone: 'danger', text: `Failed: ${progress.message || 'the call could not be placed.'}`, done: true };
    default: return null;
  }
}

/** Carrier forwarding codes (GSM), with JARVIS's number when the core provides it. */
export function forwardingCodes(number) {
  const target = number || '<JARVIS number>';
  return [
    { id: 'busy', label: 'When you are busy', code: `**67*${target}#` },
    { id: 'no_reply', label: "When you don't answer after 20 seconds", code: `**61*${target}**20#` },
    { id: 'unreachable', label: 'When your phone is off or unreachable', code: `**62*${target}#` },
  ];
}
export const CANCEL_FORWARDING = '##002#';

const secret = (status, name) => status?.secrets?.[name] || { configured: false, verified: false, source: null };
const voiceReady = status => status?.agent === 'ready' || status?.agent === 'stub';

/**
 * Setup checklist rows from calls_status: { id, title, tone, label, required }.
 * `required` rows gate turning answering on (what the core's readiness needs, minus the
 * parts that only run while calls are on); the others are recommended.
 */
export function setupRows(status, forwardingConfirmed = false) {
  const sid = secret(status, 'twilio_account_sid'), token = secret(status, 'twilio_auth_token');
  const twilio = !(sid.configured && token.configured) ? { tone: 'idle', label: 'NOT SET', done: false }
    : sid.verified && token.verified ? { tone: 'ok', label: 'VERIFIED', done: true }
      : { tone: 'warn', label: 'NOT VERIFIED', done: true };
  const saved = presence => presence.configured ? { tone: 'ok', label: 'SAVED', done: true } : { tone: 'idle', label: 'NOT SET', done: false };
  const tunnelToken = secret(status, 'cloudflare_tunnel_token');
  const state = status?.tunnel?.state;
  const tunnel = !tunnelToken.configured ? { tone: 'idle', label: 'NOT SET', done: false }
    : state === 'running' ? { tone: 'ok', label: 'RUNNING', done: true }
      : status?.tunnel?.binary_found === false || state === 'missing_binary' ? { tone: 'danger', label: 'CLOUDFLARED MISSING', done: false }
        : state === 'failed' ? { tone: 'danger', label: 'FAILED', done: false }
          : state === 'starting' || state === 'restarting' ? { tone: 'accent', label: 'STARTING', done: true }
            : { tone: 'ok', label: 'SAVED', done: true };
  const address = status?.public_url_configured ? { tone: 'ok', label: 'SET', done: true } : { tone: 'idle', label: 'NOT SET', done: false };
  const voice = voiceReady(status) ? { tone: 'ok', label: 'READY', done: true }
    : status?.agent === 'unavailable' ? { tone: 'warn', label: 'NEEDS GEMINI KEY', done: false }
      : { tone: 'danger', label: 'NOT INSTALLED', done: false };
  const forwarding = forwardingConfirmed ? { tone: 'ok', label: 'DONE', done: true } : { tone: 'idle', label: 'NOT CONFIRMED', done: false };
  return [
    { id: 'twilio', title: 'Twilio account', required: true, ...twilio },
    { id: 'jarvis_number', title: 'JARVIS phone number', required: true, ...saved(secret(status, 'twilio_phone_number')) },
    { id: 'owner_number', title: 'Your mobile number', required: false, ...saved(secret(status, 'owner_phone_number')) },
    { id: 'tunnel', title: 'Cloudflare tunnel', required: true, ...tunnel },
    { id: 'address', title: 'Public address', required: true, ...address },
    { id: 'voice', title: 'Voice', required: true, ...voice },
    { id: 'forwarding', title: 'Carrier forwarding', required: false, ...forwarding },
  ];
}

/** True when every required row is done: answering may be turned on. */
export const setupComplete = status => !!status && setupRows(status).every(row => !row.required || row.done);

/** Calls are on but the core is not answering yet: a short reason, else ''. */
export function answeringProblem(status) {
  if (!status?.enabled || status.answering) return '';
  if (status.tunnel?.state === 'failed') return 'The Cloudflare tunnel stopped.';
  if (status.tunnel?.state === 'missing_binary' || status.tunnel?.binary_found === false) return 'cloudflared is not installed.';
  if (!voiceReady(status)) return 'The phone voice is not ready.';
  if (status.tunnel?.state === 'starting' || status.tunnel?.state === 'restarting' || !status.gateway?.listening) return 'JARVIS is still starting the phone gateway.';
  return 'Call setup is not complete.';
}

// --- Call settings --------------------------------------------------------------
export const BRIEF_OPTIONS = [
  { id: 'off', label: 'Off' },
  { id: 'urgent', label: 'Urgent only' },
  { id: 'needs_owner', label: 'When needed' },
];
export const WHEN_DISABLED_OPTIONS = [
  { id: 'voicemail', label: 'Voicemail' },
  { id: 'hangup', label: 'Hang up' },
];
const HOST = /^https:\/\/[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$/;
const TIME = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;

/** Public address: '' clears it; otherwise https:// plus a host name only (the core's rule). */
export function validatePublicAddress(raw) {
  const value = String(raw ?? '').trim();
  if (!value) return { ok: true, value: '' };
  const lowered = value.replace(/^https:\/\/[^/]*/i, match => match.toLowerCase());
  if (lowered.length <= 253 && HOST.test(lowered)) return { ok: true, value: lowered };
  if (/^http:\/\//i.test(value)) return { ok: false, error: 'Use an https:// address.' };
  return { ok: false, error: 'Use https:// and a host name only, for example https://calls.example.com, with no path or trailing slash.' };
}

export const validTime = value => typeof value === 'string' && TIME.test(value);

/** Whole number within [min, max], or an error sentence. */
export function validateWhole(raw, min, max) {
  const text = String(raw ?? '').trim();
  if (!/^\d+$/.test(text)) return { ok: false, error: `Enter a whole number from ${min} to ${max}.` };
  const value = Number(text);
  if (value < min || value > max) return { ok: false, error: `Enter a whole number from ${min} to ${max}.` };
  return { ok: true, value };
}

export const validPin = value => /^[0-9]{4,8}$/.test(String(value ?? ''));

/** The saved calls.* section with only well-formed values (unknown ones become null). */
export function callsSettings(settings) {
  const calls = settings && typeof settings === 'object' && settings.calls && typeof settings.calls === 'object' ? settings.calls : {};
  const whole = value => Number.isInteger(value) ? value : null;
  const pick = (value, options) => options.some(option => option.id === value) ? value : null;
  const quiet = calls.quiet_hours && typeof calls.quiet_hours === 'object' ? calls.quiet_hours : {};
  return {
    enabled: calls.enabled === true,
    public_base_url: typeof calls.public_base_url === 'string' ? calls.public_base_url : '',
    quiet_hours: { start: validTime(quiet.start) ? quiet.start : '21:00', end: validTime(quiet.end) ? quiet.end : '09:00' },
    daily_outbound_cap: whole(calls.daily_outbound_cap),
    number_cooldown_minutes: whole(calls.number_cooldown_minutes),
    when_disabled: pick(calls.when_disabled, WHEN_DISABLED_OPTIONS),
    facts: typeof calls.facts === 'string' ? calls.facts : '',
    max_call_minutes: whole(calls.max_call_minutes),
    brief_by_phone: pick(calls.brief_by_phone, BRIEF_OPTIONS),
  };
}
