import { createRpcScope } from '../../transport/rpc.ts';

// Composing reads the calendar (bounded at 10 s on the core) before speech starts.
const PLAY_TIMEOUT = 20000;

/** Owner-only morning briefing RPCs (backend/services/briefing_service.py). */
export function createBriefingClient(socket) {
  const scope = createRpcScope(socket);
  return {
    on: scope.on,
    dispose: scope.dispose,
    get() { return scope.call('briefing_get', {}); },
    dismiss() { return scope.call('briefing_dismiss', {}); },
    play() { return scope.call('briefing_play', {}, PLAY_TIMEOUT); },
  };
}
