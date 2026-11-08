import { createRpcScope, RpcError } from '../../transport/rpc.ts';
import { normalizeStatus, normalizeTour } from './worldModel.js';

// Stop waits up to 5 s for Node to exit on the core.
const STOP_TIMEOUT = 15000;

const invalid = () => new RpcError('The core returned an incomplete World view reply. Try again.', 'invalid_response');

/** Owner-only World view RPCs (backend/services/world_view.py). */
export function createWorldClient(socket) {
  const scope = createRpcScope(socket);
  const status = async (event, data = {}, timeout) => {
    const response = await scope.call(event, data, timeout);
    const value = normalizeStatus(response.world);
    if (!value) throw invalid();
    return value;
  };
  return {
    on: scope.on,
    dispose: scope.dispose,
    /** page: true while the World page is open (it reports in), false when it closes. */
    status(page) { return status('world_status', typeof page === 'boolean' ? { page } : {}); },
    start() { return status('world_start'); },
    stop() { return status('world_stop', {}, STOP_TIMEOUT); },
    /** Relays God's Eye View's answer to a core world_view. */
    async viewResult(id, ok, steps) { await scope.call('world_view_result', { id, ok, steps }); },
    async tourStop() {
      const response = await scope.call('world_tour_stop');
      const tour = normalizeTour(response.tour);
      if (!tour) throw invalid();
      return tour;
    },
  };
}
