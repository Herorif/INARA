import { createRpcScope, RpcError } from '../../transport/rpc.ts';
import { isFact } from './memoryModel.js';

/**
 * Owner-only "What JARVIS knows" RPCs (backend/transport/facts.py). Every acknowledgement is
 * checked here; fact text stays in this renderer and is never logged.
 */
const invalid = () => new RpcError('The core returned incomplete memory. Try again.', 'invalid_response');

export function createMemoryClient(socket) {
  const scope = createRpcScope(socket);
  const fact = response => { if (!isFact(response.fact)) throw invalid(); return response.fact; };
  return {
    on: scope.on,
    dispose: scope.dispose,
    /** { paused, facts }: current facts (superseded ones are left out by the core). */
    async list() {
      const response = await scope.call('facts_list', {});
      if (typeof response.paused !== 'boolean' || !Array.isArray(response.facts)) throw invalid();
      return { paused: response.paused, facts: response.facts.filter(item => isFact(item)) };
    },
    /** Changes is a subset of { subject, text, kind, pinned }. */
    async update(id, changes) { return fact(await scope.call('facts_update', { id, ...changes })); },
    async remove(id) { await scope.call('facts_delete', { id }); },
    async pause(paused) {
      const response = await scope.call('facts_pause', { paused });
      if (typeof response.paused !== 'boolean') throw invalid();
      return response.paused;
    },
    /** Every fact (current and superseded) as JSON text. */
    async exportJson() {
      const response = await scope.call('facts_export', {});
      if (typeof response.json !== 'string') throw invalid();
      return response.json;
    },
  };
}
