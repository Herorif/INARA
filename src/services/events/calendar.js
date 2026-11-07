import { normalizeStatus } from '../../features/calendar/calendarModel.js';

/**
 * Google Calendar status (docs/CALENDAR.md): the core's `calendar_status`, validated into the
 * store as `calendarStatus`. The core pushes it when the connection or a switch changes; the
 * renderer also asks on connect and unlock. On disconnect the last status stays.
 */
export function registerCalendarEvents({ onSocket, socket, store: useStore, unsubs }) {
    const apply = raw => {
        const status = normalizeStatus(raw);
        if (status) useStore.setState({ calendarStatus: status });
    };
    const refresh = () => {
        try {
            socket.emit('calendar_status', {}, reply => { if (reply?.ok === true) apply(reply.calendar); });
        } catch {
            // The next connect or status push refreshes it.
        }
    };
    unsubs.push(onSocket('calendar_status', apply));
    unsubs.push(onSocket('connect', refresh));
    unsubs.push(onSocket('auth_status', data => { if (data?.authenticated) refresh(); }));
}
