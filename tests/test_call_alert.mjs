import test from 'node:test';
import assert from 'node:assert/strict';
import {
  LEFT_MESSAGE, VIP_ALERT_LABEL, alertCopy, callBackFocus, dismissAlert, emptyCallAlerts, openFocus, parseOpenRequest,
  parseVipAlert, receiveAlert, recordOpened,
} from '../src/features/calls/callAlertModel.js';
import { createCallAlertSlice } from '../src/store/callAlertSlice.js';

const ID = '5abe8b6d-3fa6-4b7d-8c2f-7e6d0a3b9f65';
const payload = (extra = {}) => ({ record_id: ID, name: 'Mum', summary: 'Mum asked about Sunday dinner.', ...extra });

test('VIP alerts are validated and fall back to "Left a message."', () => {
  assert.deepEqual(parseVipAlert(payload()), { recordId: ID, name: 'Mum', summary: 'Mum asked about Sunday dinner.' });
  assert.equal(parseVipAlert(payload({ summary: '' })).summary, LEFT_MESSAGE);
  assert.equal(parseVipAlert(payload({ summary: undefined })).summary, 'Left a message.');
  for (const bad of [null, [], {}, payload({ record_id: 'x y' }), payload({ name: '' }), payload({ name: 'x'.repeat(61) }), payload({ summary: 3 })]) {
    assert.equal(parseVipAlert(bad), null);
  }
  assert.equal(parseOpenRequest({ record_id: ID }), ID);
  assert.equal(parseOpenRequest({ record_id: '' }), null);
  assert.equal(parseOpenRequest(null), null);
});

test('the card copy: VIP CALL, "<name> called" and the summary', () => {
  assert.deepEqual(alertCopy(parseVipAlert(payload())), { label: 'VIP CALL', title: 'Mum called', summary: 'Mum asked about Sunday dinner.' });
  assert.equal(VIP_ALERT_LABEL, 'VIP CALL');
});

test('an update replaces the card; Dismiss hides it for good', () => {
  let state = receiveAlert(emptyCallAlerts(), payload({ summary: null }));
  assert.equal(state.alert.summary, 'Left a message.');
  state = receiveAlert(state, payload()); // the triage summary arrives
  assert.equal(state.alert.summary, 'Mum asked about Sunday dinner.');
  state = dismissAlert(state);
  assert.equal(state.alert, null);
  assert.deepEqual(state.dismissed, [ID]);
  assert.equal(receiveAlert(state, payload()).alert, null); // never comes back
  assert.equal(dismissAlert(state), state);
  assert.equal(receiveAlert(state, { nope: true }), state);
});

test('opening the record clears its card, and an open record gets none', () => {
  let state = receiveAlert(emptyCallAlerts(), payload());
  state = recordOpened(state, 'other-record');
  assert.ok(state.alert);
  state = recordOpened(state, ID);
  assert.equal(state.alert, null);
  assert.equal(state.openRecord, ID);
  const fresh = recordOpened(emptyCallAlerts(), ID);
  assert.equal(receiveAlert(fresh, payload()).alert, null);
  assert.equal(recordOpened(fresh, ID), fresh);
  assert.equal(recordOpened(fresh, null).openRecord, null);
});

test('Call back asks for the approval; a balloon click only opens the record', () => {
  assert.deepEqual(callBackFocus(parseVipAlert(payload())), { recordId: ID, approve: true });
  assert.deepEqual(openFocus(ID), { recordId: ID, approve: false });
});

test('the store slice wires the model', () => {
  let state = {};
  const set = change => { state = { ...state, ...(typeof change === 'function' ? change(state) : change) }; };
  state = createCallAlertSlice(set);
  state.receiveVipAlert(payload());
  assert.equal(state.callAlerts.alert.name, 'Mum');
  state.focusCall(callBackFocus(state.callAlerts.alert));
  assert.deepEqual(state.callsFocus, { recordId: ID, approve: true });
  state.dismissVipAlert();
  assert.equal(state.callAlerts.alert, null);
  state.clearCallsFocus();
  assert.equal(state.callsFocus, null);
  state.callRecordOpened(ID);
  assert.equal(state.callAlerts.openRecord, ID);
});
