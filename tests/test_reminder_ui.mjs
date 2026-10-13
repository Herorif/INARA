import assert from 'node:assert/strict';
import test from 'node:test';
import { createReminderSlice } from '../src/store/reminderSlice.js';

const createState = () => {
    let state;
    const set = value => { state = { ...state, ...(typeof value === 'function' ? value(state) : value) }; };
    state = createReminderSlice(set);
    return () => state;
};

test('multiple reminders queue once and cancelling the visible one reveals the next', () => {
    const state = createState();
    const first = { id: 'one', delivery_id: 'first', task: 'first task' };
    const second = { id: 'two', delivery_id: 'second', task: 'second task' };
    state().setActiveAlert(first);
    state().setActiveAlert(second);
    state().setActiveAlert(second);
    assert.equal(state().activeAlert.delivery_id, 'first');
    assert.equal(state().alertQueue.length, 1);
    state().removeReminder('one');
    assert.equal(state().activeAlert.delivery_id, 'second');
    assert.equal(state().alertQueue.length, 0);
});

test('server reconnect snapshot restores open alerts and clears dismissed alerts', () => {
    const state = createState();
    state().restoreAlerts([{ id: 'one', delivery_id: 'first' }, { id: 'two', delivery_id: 'second' }]);
    assert.equal(state().activeAlert.delivery_id, 'first');
    state().restoreAlerts([{ id: 'two', delivery_id: 'second' }]);
    assert.equal(state().activeAlert.delivery_id, 'second');
    state().restoreAlerts([]);
    assert.equal(state().activeAlert, null);
    assert.deepEqual(state().alertQueue, []);
});
