import {createRpcScope, RpcError, type RpcSocket} from './rpc.ts';
import type {LabState, LabRun, LabRecord} from './generated/callLab.ts';
export type {LabState, LabRun, LabRecord} from './generated/callLab.ts';

const uuid = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value);
const terminal = ['completed', 'interrupted', 'failed', 'uncertain'];
export function validLabState(value: LabState, project: string): boolean {
  return !!value && value.project === project && value.live_enabled === false && value.physical_verified === false &&
    !!value.admission && value.admission.live_enabled === false && value.admission.cloud_fallback === false &&
    value.admission.voice_mode === 'local_structured_english' &&
    [value.admission.admission_ready, value.admission.active].every(item => typeof item === 'boolean') &&
    Array.isArray(value.admission.blockers) && value.admission.blockers.length <= 6 &&
    new Set(value.admission.blockers).size === value.admission.blockers.length &&
    value.admission.blockers.includes('call_physical_unverified') &&
    value.admission.admission_ready === (value.admission.blockers.length === 1) &&
    value.admission.blockers.every(item => ['call_components_missing', 'call_resources_busy', 'resource_policy',
      'resource_fault', 'resource_capacity', 'call_physical_unverified'].includes(item)) &&
    [value.helper_built, value.audio_installed, value.voice_configured, value.model_installed, value.model_accepted, value.worker_supported, value.worker_busy].every(item => typeof item === 'boolean') &&
    (!value.model_accepted || value.model_installed) &&
    Array.isArray(value.runs) && value.runs.length <= 24 && new Set(value.runs.map(item => item?.id)).size === value.runs.length &&
    value.runs.every(item => !!item && uuid(item.id) && item.mode === 'offline_fixture' &&
      ['running', ...terminal].includes(item.state) && Number.isFinite(item.started_at) &&
      (item.finished_at == null || Number.isFinite(item.finished_at)) &&
      (item.record_id == null || uuid(item.record_id)) &&
      (item.code == null || typeof item.code === 'string' && item.code.length <= 120));
}
export function validLabRecord(value: LabRecord, expected: string): boolean {
  return !!value && value.id === expected && value.mode === 'offline_fixture' &&
    value.identity_verified === false && value.message_confirmed === false &&
    ['sim', 'whatsapp_personal'].includes(value.source) && terminal.includes(value.state) &&
    Array.isArray(value.transcript) && value.transcript.length <= 200 && value.transcript.every(item => !!item &&
      ['caller', 'assistant'].includes(item.role) && typeof item.text === 'string' && item.text.length <= 12000) &&
    value.transcript.reduce((sum, item) => sum + item.text.length, 0) <= 12000;
}
export function createCallLabClient(socket: RpcSocket, project: string) {
  const scope = createRpcScope(socket);
  const state = async (event: string, data: object = {}) => {
    const value = await scope.call<LabState>(event, data, 12000);
    if (!validLabState(value, project)) throw new RpcError('Bridge check scope or response changed. Refresh this workspace.', 'invalid_response');
    return value;
  };
  return {
    dispose: scope.dispose, on: scope.on,
    state: () => state('call_lab_state'),
    check: (id: string) => state('call_lab_check', {id}),
    stop: (id: string) => state('call_lab_stop', {id}),
    record: async (id: string, expected: string) => {
      const value = await scope.call<{record: LabRecord}>('call_lab_record', {id});
      if (!validLabRecord(value.record, expected)) throw new RpcError('This local check record is unavailable or changed.', 'invalid_response');
      return value.record;
    },
  };
}
