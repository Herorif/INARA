import { normalizeStatus } from '../../features/home/homeModel.js';

/**
 * Home Assistant status (docs/HOME_ASSISTANT.md): the core's `home_status`, validated into
 * the store as `homeStatus`. The core pushes it on connect, disconnect and when the device
 * count changes; the renderer also asks on connect and unlock. On disconnect the last
 * status stays.
 */
export function registerHomeEvents({ onSocket, socket, store: useStore, unsubs }) {
    const apply = raw => {
        const status = normalizeStatus(raw);
        if (!status) return;
        // A disconnected server leaves no device list behind.
        useStore.setState(status.connected ? { homeStatus: status } : { homeStatus: status, homeDevices: null });
    };
    const refresh = () => {
        try {
            socket.emit('home_status', {}, reply => { if (reply?.ok === true) apply(reply.home); });
        } catch {
            // The next connect or status push refreshes it.
        }
    };
    unsubs.push(onSocket('home_status', apply));
    unsubs.push(onSocket('connect', refresh));
    unsubs.push(onSocket('auth_status', data => { if (data?.authenticated) refresh(); }));
}
