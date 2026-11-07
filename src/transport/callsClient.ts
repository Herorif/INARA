import { createRpcScope, RpcError, type RpcSocket } from './rpc.ts';

/**
 * Owner-only Calls RPCs (C3). Every acknowledgement is validated here; numbers only
 * arrive masked and secret values never arrive at all.
 */

export type CallFilter = 'needs_you' | 'all' | 'done' | 'spam';
export type CallStatus = 'needs_you' | 'done' | 'in_progress' | 'failed' | 'callback_blocked' | 'spam' | 'blocked';
/** P1: the caller's group in the owner's people list. */
export type CallerGroup = 'vip' | 'known' | 'blocked';
export type CallDirection = 'inbound' | 'outbound';
export type Urgency = 'low' | 'normal' | 'urgent';
export type ProgressState = 'dialing' | 'ringing' | 'in_progress' | 'completed' | 'no_answer' | 'failed';
export type TriageState = 'pending' | 'done' | 'failed' | 'skipped';

export type SecretPresence = { configured: boolean; verified: boolean; source: string | null };
export type ActiveCall = { id: string; mode: string | null; direction: string; state: string };
export type CallsStatus = {
  enabled: boolean;
  when_disabled: string | null;
  public_base_url: string | null;
  public_url_configured: boolean;
  secrets: Record<string, SecretPresence>;
  gateway: { listening: boolean };
  tunnel: { state: string; binary_found: boolean };
  agent: string;
  ready: boolean;
  failure: unknown;
  answering: boolean;
  needs_you_count: number;
  active_call: ActiveCall | null;
  briefing_pin_set: boolean | null;
  /** JARVIS's own number for the forwarding codes, when the core provides it. */
  jarvis_number: string | null;
};
export type CallSummary = {
  id: string;
  direction: CallDirection;
  mode: string | null;
  counterpart_masked: string | null;
  name: string | null;
  started_at: number | string | null;
  duration_seconds: number | null;
  urgency: Urgency | null;
  needs_owner: boolean;
  summary: string | null;
  status: CallStatus;
  outcome_status: string | null;
  /** P1: the saved caller's current group; null for an unsaved caller (or an older core). */
  caller_group: CallerGroup | null;
};
export type CallFields = { name: string | null; reason: string | null; urgency: string | null; callback_number_masked: string | null; message: string | null };
export type CallTriage = { summary: string | null; urgency: string | null; needs_owner: boolean; suggested_actions: string[] };
export type TranscriptTurn = { role: 'caller' | 'jarvis' | 'owner'; text: string };
export type CallDetail = CallSummary & {
  fields: CallFields | null;
  triage: CallTriage | null;
  triage_state: TriageState | null;
  transcript: TranscriptTurn[];
  outcome: { status: string; details: unknown } | null;
  related_ids: string[];
  /** P1: the saved person for this caller, and whether "Add to people", "Mark VIP" and "Block" can work. */
  contact: { id: string; name: string; group: CallerGroup } | null;
  can_add_person: boolean;
};
export type CallProgress = { call_id: string; record_id: string | null; mode: string | null; direction: string; state: ProgressState; message: string | null };

const FILTERS: CallFilter[] = ['needs_you', 'all', 'done', 'spam'];
const STATUSES: CallStatus[] = ['needs_you', 'done', 'in_progress', 'failed', 'callback_blocked', 'spam', 'blocked'];
const GROUPS: CallerGroup[] = ['vip', 'known', 'blocked'];
const DIRECTIONS: CallDirection[] = ['inbound', 'outbound'];
const URGENCIES: Urgency[] = ['low', 'normal', 'urgent'];
const PROGRESS: ProgressState[] = ['dialing', 'ringing', 'in_progress', 'completed', 'no_answer', 'failed'];
const TRIAGE_STATES: TriageState[] = ['pending', 'done', 'failed', 'skipped'];
// Wire names from before the INARA -> JARVIS rename (5 Nov 2026): a core started before it sends
// `inara_number` and the transcript role 'inara'. Read them as the JARVIS names; remove one release later.
const LEGACY_ROLE = 'inara', LEGACY_NUMBER = 'inara_number';
const ROLES = ['caller', 'jarvis', 'owner', LEGACY_ROLE];
export const CALLBACK_LIMIT = 500;
const TEXT_LIMIT = 20000;
const ID = /^[A-Za-z0-9_.:-]{1,128}$/;
const E164 = /^\+[1-9][0-9]{7,14}$/;

type Obj = Record<string, unknown>;
const isObject = (value: unknown): value is Obj => !!value && typeof value === 'object' && !Array.isArray(value);
const isText = (value: unknown, limit = TEXT_LIMIT): value is string => typeof value === 'string' && value.length <= limit;
const optionalText = (value: unknown, limit = TEXT_LIMIT) => value === null || value === undefined || isText(value, limit);
const isId = (value: unknown): value is string => typeof value === 'string' && ID.test(value);
const isCount = (value: unknown): value is number => Number.isInteger(value) && (value as number) >= 0;

export const isSecretPresence = (value: unknown): value is SecretPresence =>
  isObject(value) && typeof value.configured === 'boolean' && typeof value.verified === 'boolean'
  && (value.source === null || value.source === undefined || typeof value.source === 'string');

export const isActiveCall = (value: unknown): value is ActiveCall =>
  isObject(value) && isId(value.id) && optionalText(value.mode, 64) && isText(value.direction, 32) && isText(value.state, 32);

/**
 * `calls_status`: the C1 readiness report (today nested under `calls`) plus the C3 fields.
 * Both a nested and a flat body are accepted; the C3 fields may sit at either level.
 * Returns the normalised status, or null when a required field is missing or mistyped.
 */
export function parseCallsStatus(response: unknown): CallsStatus | null {
  if (!isObject(response)) return null;
  const body: Obj = isObject(response.calls) ? { ...response, ...response.calls } : response;
  const secrets = body.secrets, gateway = body.gateway, tunnel = body.tunnel;
  if (typeof body.enabled !== 'boolean' || typeof body.ready !== 'boolean' || typeof body.public_url_configured !== 'boolean') return null;
  if (!isObject(secrets) || !Object.values(secrets).every(isSecretPresence)) return null;
  if (!isObject(gateway) || typeof gateway.listening !== 'boolean') return null;
  if (!isObject(tunnel) || !isText(tunnel.state, 32) || typeof tunnel.binary_found !== 'boolean') return null;
  if (!isText(body.agent, 32) || !optionalText(body.public_base_url, 300) || !optionalText(body.when_disabled, 32)) return null;
  if (body.answering !== undefined && typeof body.answering !== 'boolean') return null;
  // null: the core could not count its records this time.
  if (body.needs_you_count !== undefined && body.needs_you_count !== null && !isCount(body.needs_you_count)) return null;
  if (body.active_call !== undefined && body.active_call !== null && !isActiveCall(body.active_call)) return null;
  if (body.briefing_pin_set !== undefined && typeof body.briefing_pin_set !== 'boolean') return null;
  const number = body.jarvis_number ?? body[LEGACY_NUMBER];
  if (number !== undefined && number !== null && !(typeof number === 'string' && E164.test(number))) return null;
  return {
    enabled: body.enabled,
    when_disabled: (body.when_disabled as string | null | undefined) ?? null,
    public_base_url: (body.public_base_url as string | null | undefined) || null,
    public_url_configured: body.public_url_configured,
    secrets: secrets as Record<string, SecretPresence>,
    gateway: { listening: gateway.listening as boolean },
    tunnel: { state: tunnel.state as string, binary_found: tunnel.binary_found as boolean },
    agent: body.agent,
    ready: body.ready,
    failure: body.failure ?? null,
    // Before C3, answering is what C1 calls ready (enabled and every part running).
    answering: typeof body.answering === 'boolean' ? body.answering : body.ready,
    needs_you_count: isCount(body.needs_you_count) ? body.needs_you_count : 0,
    active_call: (body.active_call as ActiveCall | null | undefined) ?? null,
    briefing_pin_set: typeof body.briefing_pin_set === 'boolean' ? body.briefing_pin_set : null,
    jarvis_number: typeof number === 'string' ? number : null,
  };
}

const isStartedAt = (value: unknown) => value === null ||
  (typeof value === 'number' && Number.isFinite(value) && value > 0) || (typeof value === 'string' && value.length <= 40 && !Number.isNaN(Date.parse(value)));

export function isCallSummary(value: unknown): value is CallSummary {
  if (!isObject(value)) return false;
  return isId(value.id) && DIRECTIONS.includes(value.direction as CallDirection) && optionalText(value.mode, 64)
    && optionalText(value.counterpart_masked, 64) && optionalText(value.name, 200)
    && isStartedAt(value.started_at)
    && (value.duration_seconds === null || value.duration_seconds === undefined || (typeof value.duration_seconds === 'number' && Number.isFinite(value.duration_seconds) && value.duration_seconds >= 0))
    && (value.urgency === null || value.urgency === undefined || URGENCIES.includes(value.urgency as Urgency))
    && typeof value.needs_owner === 'boolean'
    && optionalText(value.summary, 4000)
    && STATUSES.includes(value.status as CallStatus)
    && optionalText(value.outcome_status, 64)
    && (value.caller_group === null || value.caller_group === undefined || GROUPS.includes(value.caller_group as CallerGroup));
}

const isFields = (value: unknown) => value === null || value === undefined || (isObject(value)
  && ['name', 'reason', 'urgency', 'callback_number_masked', 'message'].every(key => optionalText(value[key], 4000)));
const isTriage = (value: unknown) => value === null || value === undefined || (isObject(value)
  && optionalText(value.summary, 4000) && optionalText(value.urgency, 32) && typeof value.needs_owner === 'boolean'
  && Array.isArray(value.suggested_actions) && value.suggested_actions.length <= 16 && value.suggested_actions.every(item => isText(item, 400)));
const isTurn = (value: unknown) => isObject(value) && ROLES.includes(value.role as string) && isText(value.text);
const isContact = (value: unknown) => value === null || value === undefined || (isObject(value)
  && isId(value.id) && isText(value.name, 200) && GROUPS.includes(value.group as CallerGroup));

export function isCallDetail(value: unknown): value is CallDetail {
  if (!isCallSummary(value)) return false;
  const call = value as unknown as Obj;
  return isFields(call.fields) && isTriage(call.triage)
    && (call.triage_state === null || call.triage_state === undefined || TRIAGE_STATES.includes(call.triage_state as TriageState))
    && Array.isArray(call.transcript) && call.transcript.length <= 2000 && call.transcript.every(isTurn)
    && (call.outcome === null || call.outcome === undefined || (isObject(call.outcome) && isText(call.outcome.status, 64)))
    && (call.related_ids === undefined || (Array.isArray(call.related_ids) && call.related_ids.every(isId)))
    && isContact(call.contact) && (call.can_add_person === undefined || typeof call.can_add_person === 'boolean');
}

export function isCallProgress(value: unknown): value is CallProgress {
  return isObject(value) && isId(value.call_id) && (value.record_id === null || value.record_id === undefined || isId(value.record_id))
    && optionalText(value.mode, 64) && isText(value.direction, 32) && PROGRESS.includes(value.state as ProgressState)
    && optionalText(value.message, 400);
}

export const isRecordReady = (value: unknown): value is { record_id: string } => isObject(value) && isId(value.record_id);

const invalid = () => new RpcError('The core returned an incomplete call record. Refresh Calls to try again.', 'invalid_response');

export function createCallsClient(socket: RpcSocket) {
  const scope = createRpcScope(socket);
  return {
    on: scope.on,
    dispose: scope.dispose,
    async status(): Promise<CallsStatus> {
      const status = parseCallsStatus(await scope.call('calls_status', {}));
      if (!status) throw invalid();
      return status;
    },
    async list(filter: CallFilter, limit = 100): Promise<CallSummary[]> {
      if (!FILTERS.includes(filter)) throw new RpcError('Unknown call filter.', 'invalid_arguments');
      const response = await scope.call<{ calls?: unknown }>('calls_list', { filter, limit });
      if (!Array.isArray(response.calls) || !response.calls.every(isCallSummary)) throw invalid();
      return response.calls.map(call => ({ ...call, caller_group: call.caller_group ?? null }));
    },
    async get(id: string): Promise<CallDetail> {
      const response = await scope.call<{ call?: unknown }>('calls_get', { id });
      if (!isCallDetail(response.call) || response.call.id !== id) throw invalid();
      const transcript = response.call.transcript.map(turn => ((turn.role as string) === LEGACY_ROLE ? { ...turn, role: 'jarvis' as const } : turn));
      return { ...response.call, transcript, related_ids: response.call.related_ids ?? [], contact: response.call.contact ?? null, can_add_person: response.call.can_add_person === true };
    },
    async markDone(id: string): Promise<void> { await scope.call('calls_mark_done', { id }); },
    async remove(id: string): Promise<void> { await scope.call('calls_delete', { id }); },
    async callbackDraft(id: string): Promise<string> {
      const response = await scope.call<{ message?: unknown }>('calls_callback_draft', { id }, 30000);
      if (!isText(response.message, CALLBACK_LIMIT)) throw invalid();
      return response.message;
    },
    /** Fails with the core's code: calls_disabled, not_ready, no_callback_number, quiet_hours, daily_cap, cooldown or busy. */
    async approveCallback(id: string, message: string): Promise<string> {
      if (!message.trim() || message.length > CALLBACK_LIMIT) throw new RpcError('Write what JARVIS should say, up to 500 characters.', 'invalid_arguments');
      const response = await scope.call<{ call_id?: unknown }>('calls_callback_approve', { id, message }, 20000);
      if (!isId(response.call_id)) throw invalid();
      return response.call_id;
    },
    /** Settings patch through the existing update path; failures carry the core's code. */
    async updateSettings(patch: Record<string, unknown>): Promise<void> {
      await scope.call('update_settings', patch);
    },
  };
}
