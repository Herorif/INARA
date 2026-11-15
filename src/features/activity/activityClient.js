import { createRpcScope, RpcError } from '../../transport/rpc.ts';
import { TRACE_LIMIT, normalizeTrace } from './activityModel.js';

/**
 * Owner-only flight recorder RPCs (backend/transport/trace.py): trace_recent {limit 1-200}
 * newest first, trace_clear, and the trace_added {id, origin, outcome, total_ms} event.
 */
export function createActivityClient(socket) {
  const scope = createRpcScope(socket);
  return {
    dispose: scope.dispose,
    async recent(limit) {
      const safe = Math.max(1, Math.min(TRACE_LIMIT, Math.floor(limit) || 1));
      const response = await scope.call('trace_recent', { limit: safe });
      if (!Array.isArray(response.traces)) throw new RpcError('The core returned an incomplete activity list.', 'invalid_response');
      return response.traces.map(normalizeTrace).filter(Boolean);
    },
    async clear() { await scope.call('trace_clear', {}); },
    onAdded(handler) {
      return scope.on('trace_added', payload => {
        if (payload && typeof payload === 'object' && typeof payload.id === 'string' && payload.id) handler(payload);
      });
    },
  };
}
