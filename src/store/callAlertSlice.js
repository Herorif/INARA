import { dismissAlert, emptyCallAlerts, receiveAlert, recordOpened } from '../features/calls/callAlertModel.js';

/** P1: the in-app VIP call alert and the request to open Calls on one record. */
export const createCallAlertSlice = (set) => ({
    callAlerts: emptyCallAlerts(),
    // { recordId, approve }: open Calls on this record (approve: focus its callback approval).
    callsFocus: null,
    receiveVipAlert: (payload) => set(state => ({ callAlerts: receiveAlert(state.callAlerts, payload) })),
    dismissVipAlert: () => set(state => ({ callAlerts: dismissAlert(state.callAlerts) })),
    callRecordOpened: (recordId) => set(state => {
        const next = recordOpened(state.callAlerts, recordId);
        return next === state.callAlerts ? {} : { callAlerts: next };
    }),
    focusCall: (focus) => set({ callsFocus: focus }),
    clearCallsFocus: () => set({ callsFocus: null }),
});
