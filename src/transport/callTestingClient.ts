import {createRpcScope, RpcError, type RpcSocket} from './rpc.ts';
import type {ControlledTestState, TestReview, TestPrepare, TestArm} from './generated/callTesting.ts';
export type {ControlledTestState, TestReview} from './generated/callTesting.ts';

const uuid = (value: unknown) => typeof value === 'string' && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value);
const reasons = ['policy_disabled', 'channel_disabled', 'profile_missing', 'profile_changed', 'evidence_missing', 'evidence_invalid',
  'components_missing', 'resource_policy', 'resources_busy', 'resource_capacity', 'resource_fault'];
const blockers = (value: unknown): value is string[] => Array.isArray(value) && value.length <= 11 &&
  new Set(value).size === value.length && value.every(item => reasons.includes(item));
export function validControlledState(value: ControlledTestState, project: string): boolean {
  return !!value && value.project === project && value.unattended_enabled === false &&
    [value.ready, value.policy_enabled, value.worker_busy].every(item => typeof item === 'boolean') &&
    value.voice_mode === 'local_structured_english' && blockers(value.blockers) && value.ready === (value.blockers.length === 0) &&
    (!value.ready || value.policy_enabled && value.draft != null && !value.worker_busy) &&
    (value.active_id == null || uuid(value.active_id) && value.worker_busy) &&
    (value.draft == null || uuid(value.draft.revision) && ['sim', 'whatsapp_personal'].includes(value.draft.channel) &&
      /^[a-f0-9]{64}$/.test(value.draft.profile_sha256) && Number.isInteger(value.draft.max_seconds) && value.draft.max_seconds >= 15 && value.draft.max_seconds <= 180);
}
export function validTestReview(value: TestReview, project: string, revision: string): boolean {
  return !!value && value.project === project && value.revision === revision && uuid(value.revision) &&
    typeof value.ready === 'boolean' && blockers(value.blockers) && value.ready === (value.blockers.length === 0) &&
    (value.ready ? uuid(value.review_id) && Number.isFinite(value.expires_at) : value.review_id == null && value.expires_at == null);
}
export function createCallTestingClient(socket: RpcSocket, project: string) {
  const scope = createRpcScope(socket);
  const state = async (event: string, args: object = {}) => {
    const value = await scope.call<ControlledTestState>(event, args, 12000);
    if (!validControlledState(value, project)) throw new RpcError('Controlled-test scope or readiness changed. Refresh.', 'invalid_response');
    return value;
  };
  return {dispose: scope.dispose, on: scope.on,
    state: () => state('call_test_state'),
    prepare: (args: TestPrepare) => state('call_test_prepare', args),
    arm: (args: TestArm) => state('call_test_arm', args),
    stop: (id: string) => state('call_test_stop', {id}),
    review: async (revision: string) => {
      const value = await scope.call<TestReview>('call_test_review', {revision});
      if (!validTestReview(value, project, revision)) throw new RpcError('Arming review is stale or changed. Refresh.', 'invalid_response');
      return value;
    },
  };
}
