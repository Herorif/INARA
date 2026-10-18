import { RpcError, createRpcScope, type RpcSocket } from './rpc.ts';
import { mergeJob } from '../features/creative/client.js';
import type { ImageRequest, ImageArtifactRequest, ImageRecipe, ImageStats, JobRequest } from './generated/image.ts';
export type ImageJob = {
  request_id: string; project: string; state: string; phase: string;
  recipe?: ImageRecipe; stats?: ImageStats; error?: string;
};
export type ImageArtifact = { data: string; bytes: number; sha256: string; filename: string };
export interface ImageCalls {
  image_list: { request: Record<string, never>; result: { jobs: ImageJob[]; capabilities: { available: boolean; reason?: string; model?: string } } };
  image_submit: { request: ImageRequest; result: { job: ImageJob } };
  image_cancel: { request: JobRequest; result: { job: ImageJob } };
  image_artifact: { request: ImageArtifactRequest; result: { artifact: ImageArtifact } };
  image_close: { request: Record<string, never>; result: Record<string, unknown> };
}
function isJob(value: unknown): value is ImageJob {
  return !!value && typeof value === 'object' && 'request_id' in value && typeof value.request_id === 'string'
    && 'project' in value && typeof value.project === 'string'
    && 'state' in value && typeof value.state === 'string'
    && 'phase' in value && typeof value.phase === 'string';
}
export function reconcileImageHistory(previous: ImageJob[], snapshot: ImageJob[], changed: Set<string>) {
  const byId = new Map(previous.map(job => [job.request_id, job]));
  const result = snapshot.map(job => {
    const old = byId.get(job.request_id);
    return mergeJob(old, job);
  });
  const received = new Set(snapshot.map(job => job.request_id));
  return [...previous.filter(job => changed.has(job.request_id) && !received.has(job.request_id)), ...result].slice(0, 12);
}
export function createImageClient(socket: RpcSocket) {
  const scope = createRpcScope(socket);
  return {
    on(event: string, handler: (...args: any[]) => void) {
      return scope.on(event, (...args) => {
        if (event !== 'image_job' || isJob(args[0])) handler(...args);
      });
    },
    dispose: scope.dispose,
    async call<K extends keyof ImageCalls>(event: K, data: ImageCalls[K]['request'], timeout?: number): Promise<ImageCalls[K]['result']> {
      const result = await scope.call<ImageCalls[K]['result']>(event, data, timeout);
      // The ACK envelope is checked by the shared scope; list shape is needed before rendering.
      if (event === 'image_list') {
        const list = result as ImageCalls['image_list']['result'];
        if (!Array.isArray(list.jobs) || !list.jobs.every(isJob) || !list.capabilities || typeof list.capabilities.available !== 'boolean') {
          throw new RpcError('Revision history could not be read. Refresh to try again.', 'invalid_response', true);
        }
      }
      if (event === 'image_submit' || event === 'image_cancel') {
        if (!isJob((result as { job: unknown }).job)) throw new RpcError('The core returned an invalid revision. Refresh history.', 'invalid_response', true);
      }
      if (event === 'image_artifact') {
        const artifact = (result as ImageCalls['image_artifact']['result']).artifact;
        if (!artifact || typeof artifact.data !== 'string' || typeof artifact.filename !== 'string'
            || !Number.isInteger(artifact.bytes) || artifact.bytes <= 0 || artifact.bytes > 16777216
            || !/^[a-f0-9]{64}$/.test(artifact.sha256)) {
          throw new RpcError('The saved export could not be read. Refresh history.', 'invalid_response');
        }
      }
      return result;
    },
  };
}
