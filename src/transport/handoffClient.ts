import {createRpcScope, RpcError, type RpcSocket} from './rpc.ts';
import type {CreativeReference, HandoffDraft, HandoffRequest} from './generated/handoff.ts';
export const validReference = (v: CreativeReference): boolean => !!v && ['cad','image'].includes(v.source_kind) &&
  /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(v.source_request_id) &&
  /^[a-f0-9]{64}$/.test(v.source_fingerprint) && /^[a-f0-9]{64}$/.test(v.source_sha256);
export function createHandoffClient(socket: RpcSocket, project: string) {
  const scope = createRpcScope(socket);
  return {dispose: scope.dispose, async prepare(request: HandoffRequest): Promise<HandoffDraft> {
    const {draft} = await scope.call<{draft:HandoffDraft}>('creative_handoff', request);
    const readable = (text:unknown, max:number) => typeof text === 'string' && text.trim().length > 0 && text.length <= max;
    if (!draft || draft.project !== project || draft.destination !== request.destination || draft.metadata_only !== true ||
      !validReference(draft.reference) || draft.reference.source_kind !== request.source_kind ||
      draft.reference.source_request_id !== request.source_request_id || draft.reference.source_fingerprint !== request.source_fingerprint ||
      !readable(draft.name,60) || !readable(draft.source_name,60) || !readable(draft.prompt,2000))
      throw new RpcError('The reference changed. Select it again from project artifacts.', 'invalid_response');
    return draft;
  }};
}
