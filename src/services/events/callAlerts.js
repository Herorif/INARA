import { openFocus, parseOpenRequest } from '../../features/calls/callAlertModel.js';

/** P1 Calls alerts: the VIP call card and "open this record" from a VIP balloon click. */
export function registerCallAlertEvents({ onSocket, store: useStore, unsubs }) {
    const s = useStore.getState;
    unsubs.push(onSocket('call_vip_alert', (payload) => s().receiveVipAlert(payload)));
    unsubs.push(onSocket('calls_open', (payload) => {
        const recordId = parseOpenRequest(payload);
        if (recordId) s().focusCall(openFocus(recordId));
    }));
}
