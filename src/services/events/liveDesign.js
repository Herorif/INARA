import { snapshotPatch } from '../../features/liveDesign/model.js';

/**
 * The owner's live design (docs/LIVE_DESIGN.md): the core's `cad_design` snapshot, validated
 * into the store. The core sends it on connect and unlock while a design exists; the renderer
 * also asks (`cad_design_get`) so a design that ended meanwhile clears. On disconnect the last
 * snapshot stays and the panel shows it as offline.
 */
export function registerLiveDesignEvents({ onSocket, socket, store: useStore, unsubs }) {
    const apply = raw => {
        const patch = snapshotPatch(useStore.getState(), raw);
        if (patch) useStore.setState(patch);
    };
    const refresh = () => {
        try {
            socket.emit('cad_design_get', {}, reply => { if (reply?.ok === true) apply(reply); });
        } catch {
            // The next connect or snapshot refreshes it.
        }
    };
    unsubs.push(onSocket('cad_design', apply));
    unsubs.push(onSocket('connect', refresh));
    unsubs.push(onSocket('auth_status', data => { if (data?.authenticated) refresh(); }));
}
