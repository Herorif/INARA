import { receiveBriefing } from '../../features/briefing/briefingModel.js';

/**
 * P2 morning briefing: the core's `briefing` event ({ briefing: card | null }) into the store.
 * The core sends it to authenticated owner renderers on connect and unlock (hydrate) and on
 * every change; a lock clears it here.
 */
export function registerBriefingEvents({ onSocket, store: useStore, unsubs }) {
    unsubs.push(onSocket('briefing', payload => useStore.setState({ briefing: receiveBriefing(payload) })));
    unsubs.push(onSocket('auth_status', data => { if (!data?.authenticated) useStore.setState({ briefing: null }); }));
}
