import { createRpcScope, RpcError } from '../../transport/rpc.ts';
import { normalizeDevice, normalizeDevices, normalizeStatus } from './homeModel.js';

// Connect makes up to four bounded requests (10 s each) on the core.
const CONNECT_TIMEOUT = 45000;
// A refresh reads states, areas and config (10 s each); a control reads, acts and reads.
const DEVICES_TIMEOUT = 35000;

const invalid = () => new RpcError('The core returned an incomplete Home Assistant reply. Try again.', 'invalid_response');

/**
 * Owner-only Home Assistant RPCs (backend/services/home_assistant_transport.py). The token
 * goes in through connect and never comes back.
 */
export function createHomeClient(socket) {
  const scope = createRpcScope(socket);
  const status = async (event, data = {}, timeout) => {
    const response = await scope.call(event, data, timeout);
    const value = normalizeStatus(response.home);
    if (!value) throw invalid();
    return value;
  };
  return {
    on: scope.on,
    dispose: scope.dispose,
    status() { return status('home_status'); },
    connect(url, token) { return status('home_connect', { url: url.trim(), token: token.trim() }, CONNECT_TIMEOUT); },
    disconnect() { return status('home_disconnect'); },
    async devices() {
      const response = await scope.call('home_devices', {}, DEVICES_TIMEOUT);
      const list = normalizeDevices(response);
      const value = normalizeStatus(response.home);
      if (!list || !value) throw invalid();
      return { list, status: value };
    },
    async setAccess(entityId, access) {
      const response = await scope.call('home_set_access', { entity_id: entityId, access });
      if (response.entity_id !== entityId || response.access !== access) throw invalid();
      return { entityId, access };
    },
    /** The owner's own tile control: acts at once, no approval card. */
    async control(entityId, action, value) {
      const data = value === undefined || value === null ? { entity_id: entityId, action } : { entity_id: entityId, action, value };
      const response = await scope.call('home_control_direct', data, DEVICES_TIMEOUT);
      if (!normalizeDevice(response.device)) throw invalid();
      return response.device;
    },
  };
}
