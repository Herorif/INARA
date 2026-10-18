import { isArtifact, isJobUpdate } from './guards.ts';
import { RpcError, createRpcScope, type RpcSocket } from './rpc.ts';
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
export function createImageClient(socket: RpcSocket) {
  const scope = createRpcScope(socket);
  return {
    on(event: string, handler: (...args: any[]) => void) {
      return scope.on(event, (...args) => {
        if (event !== 'image_job' || isJobUpdate(args[0])) handler(...args);
      });
    },
    dispose: scope.dispose,
    async call<K extends keyof ImageCalls>(event: K, data: ImageCalls[K]['request'], timeout?: number): Promise<ImageCalls[K]['result']> {
      const result = await scope.call<ImageCalls[K]['result']>(event, data, timeout);
      // The ACK envelope is checked by the shared scope; list shape is needed before rendering.
      if (event === 'image_list') {
        const list = result as ImageCalls['image_list']['result'];
        if (!Array.isArray(list.jobs) || !list.jobs.every(job => isJobUpdate(job) && job.recipe && typeof job.recipe.name === 'string') || !list.capabilities || typeof list.capabilities.available !== 'boolean') {
          throw new RpcError('Revision history could not be read. Refresh to try again.', 'invalid_response', true);
        }
      }
      if (event === 'image_submit' || event === 'image_cancel') {
        if (!isJobUpdate((result as { job: unknown }).job)) throw new RpcError('The core returned an invalid revision. Refresh history.', 'invalid_response', true);
      }
      if (event === 'image_artifact') {
        const artifact = (result as ImageCalls['image_artifact']['result']).artifact;
        if (!isArtifact(artifact)) {
          throw new RpcError('The saved export could not be read. Refresh history.', 'invalid_response');
        }
      }
      return result;
    },
  };
}
