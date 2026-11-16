import { createRpcScope, RpcError } from '../../transport/rpc.ts';
import { normalizeItem, normalizeMute } from './proactiveModel.js';

/**
 * Owner-only proactive engine RPCs (backend/transport/proactive.py) and its events:
 * proactive_card {card}, proactive_digest {digest}, proactive_delivered {id, channel}.
 */
export function createProactiveClient(socket) {
  const scope = createRpcScope(socket);
  return {
    on: scope.on,
    dispose: scope.dispose,
    async recent() {
      const response = await scope.call('proactive_recent', {});
      if (!Array.isArray(response.deliveries)) throw new RpcError('The core returned an incomplete list.', 'invalid_response');
      return response.deliveries.map(normalizeItem).filter(Boolean);
    },
    async mutes() {
      const response = await scope.call('proactive_mutes', {});
      if (!Array.isArray(response.mutes)) throw new RpcError('The core returned an incomplete list.', 'invalid_response');
      return response.mutes.map(normalizeMute).filter(Boolean);
    },
    async mute(request) {
      const response = await scope.call('proactive_mute', request);
      return normalizeMute(response.mute);
    },
    async unmute(id) { await scope.call('proactive_unmute', { id }); },
    async dismissDigest() { await scope.call('proactive_digest_dismiss', {}); },
    async focus(focused) { await scope.call('proactive_focus', { focused }); },
  };
}
