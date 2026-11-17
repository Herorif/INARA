import { createRpcScope, RpcError } from '../../transport/rpc.ts';
import { isRoutine, isTool } from './routinesModel.js';

/**
 * Owner-only Routines RPCs (backend/transport/routines.py). Every acknowledgement is checked
 * here; names, phrases and step arguments stay in this renderer and are never logged.
 */
const invalid = () => new RpcError('The core returned incomplete routines. Try again.', 'invalid_response');

export function createRoutinesClient(socket) {
  const scope = createRpcScope(socket);
  const routine = response => { if (!isRoutine(response.routine)) throw invalid(); return response.routine; };
  return {
    on: scope.on,
    dispose: scope.dispose,
    async list() {
      const response = await scope.call('routines_list', {});
      if (!Array.isArray(response.routines)) throw invalid();
      return response.routines.filter(item => isRoutine(item));
    },
    /** Tools a step may use: { name, description, parameters (JSON schema) }. */
    async tools() {
      const response = await scope.call('routines_tools', {});
      if (!Array.isArray(response.tools)) throw invalid();
      return response.tools.filter(item => isTool(item));
    },
    /** value is { name, trigger, steps }; id updates that routine. */
    async save(value, id) { return routine(await scope.call('routines_save', id ? { id, ...value } : value)); },
    async remove(id) { await scope.call('routines_delete', { id }); },
    async toggle(id, enabled) { return routine(await scope.call('routines_toggle', { id, enabled })); },
    async run(id) { await scope.call('routines_run', { id }); },
  };
}
