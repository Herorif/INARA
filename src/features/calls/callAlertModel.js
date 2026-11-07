// Pure state for the in-app VIP call alert (P1): the card that shows when a VIP calls while the
// workspace is open, and the request to open Calls on one record. The name and summary are
// the owner's own label and JARVIS's summary; they are shown, never logged.

export const VIP_ALERT_LABEL = 'VIP CALL';
export const LEFT_MESSAGE = 'Left a message.';
const ID = /^[A-Za-z0-9_.:-]{1,128}$/;
const DISMISSED_LIMIT = 64;

export const emptyCallAlerts = () => ({ alert: null, dismissed: [], openRecord: null });

/** `call_vip_alert` -> { recordId, name, summary }, or null when malformed. */
export function parseVipAlert(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const { record_id: recordId, name, summary } = value;
  if (typeof recordId !== 'string' || !ID.test(recordId)) return null;
  if (typeof name !== 'string' || !name.trim() || name.length > 60) return null;
  if (summary !== undefined && summary !== null && (typeof summary !== 'string' || summary.length > 400)) return null;
  return { recordId, name: name.trim(), summary: (typeof summary === 'string' && summary.trim()) || LEFT_MESSAGE };
}

/** `calls_open` -> the record id, or null. */
export const parseOpenRequest = value => value && typeof value === 'object' && typeof value.record_id === 'string' && ID.test(value.record_id) ? value.record_id : null;

/** The card's text. */
export const alertCopy = alert => ({ label: VIP_ALERT_LABEL, title: `${alert.name} called`, summary: alert.summary });

/**
 * A new or updated alert. A dismissed alert never comes back, and none shows for the record
 * the owner already has open; a later update (the triage summary) replaces the same card.
 */
export function receiveAlert(state, payload) {
  const alert = parseVipAlert(payload);
  if (!alert || state.dismissed.includes(alert.recordId) || state.openRecord === alert.recordId) return state;
  return { ...state, alert };
}

const forget = (dismissed, recordId) => [...dismissed.filter(id => id !== recordId), recordId].slice(-DISMISSED_LIMIT);

/** Dismiss hides the card only. */
export function dismissAlert(state) {
  if (!state.alert) return state;
  return { ...state, alert: null, dismissed: forget(state.dismissed, state.alert.recordId) };
}

/** The owner opened a call record in the Calls view (null: none is open). Its card clears. */
export function recordOpened(state, recordId) {
  const id = typeof recordId === 'string' ? recordId : null;
  if (id && state.alert?.recordId === id) return { ...state, alert: null, dismissed: forget(state.dismissed, id), openRecord: id };
  return state.openRecord === id ? state : { ...state, openRecord: id };
}

/** "Call back": open Calls on the record with its callback approval focused (never a call). */
export const callBackFocus = alert => ({ recordId: alert.recordId, approve: true });
/** A VIP balloon click: open Calls on the record. */
export const openFocus = recordId => ({ recordId, approve: false });
