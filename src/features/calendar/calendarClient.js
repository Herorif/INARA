import { createRpcScope, RpcError } from '../../transport/rpc.ts';
import { normalizeStatus } from './calendarModel.js';

// A provider check is not made for the OAuth client (no_check); saving is local.
const SAVE_TIMEOUT = 15000;
// Disconnect makes one bounded revoke request (15 s on the core).
const DISCONNECT_TIMEOUT = 25000;

const invalid = () => new RpcError('The core returned an incomplete calendar status. Try again.', 'invalid_response');

/**
 * Owner-only Google Calendar RPCs (backend/services/calendar_transport.py). The sign-in URL
 * is returned by connect; the card opens it through electronAPI.openExternal.
 */
export function createCalendarClient(socket) {
  const scope = createRpcScope(socket);
  const status = async (event, data = {}, timeout) => {
    const response = await scope.call(event, data, timeout);
    const value = normalizeStatus(response.calendar);
    if (!value) throw invalid();
    return { response, status: value };
  };
  return {
    on: scope.on,
    dispose: scope.dispose,
    async status() { return (await status('calendar_status')).status; },
    async connect() {
      const { response, status: value } = await status('calendar_connect');
      return { status: value, authUrl: typeof response.auth_url === 'string' ? response.auth_url : null };
    },
    async cancel() { return (await status('calendar_cancel')).status; },
    async disconnect() { return (await status('calendar_disconnect', {}, DISCONNECT_TIMEOUT)).status; },
    async setSwitch(id, value) { return (await status('calendar_settings', { [id]: value })).status; },
    /** The owner's OAuth client through the existing secrets route (values go in, status comes out). */
    async saveClient(clientId, clientSecret) {
      for (const [name, value] of [['google_oauth_client_id', clientId], ['google_oauth_client_secret', clientSecret]]) {
        await scope.call('secrets_set', { name, value: value.trim() }, SAVE_TIMEOUT);
      }
      return (await status('calendar_status')).status;
    },
  };
}
