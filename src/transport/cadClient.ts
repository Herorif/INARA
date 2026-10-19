import { isArtifact, isJobUpdate } from './guards.ts';
import { RpcError, createRpcScope, type RpcSocket } from './rpc.ts';
import type { BuildRequest, ArtifactRequest, PlanRequest, Recipe, JobRequest, JobLifetime } from './generated/cad.ts';
export type CadJob = { request_id: string; project: string; state: string; phase: string; recipe?: Recipe; [key: string]: unknown };
export interface CadCalls {
  cad_list: { request: Record<string, never>; result: { jobs: CadJob[]; capabilities: { blender: boolean } } };
  cad_submit: { request: BuildRequest; result: { job: CadJob } };
  cad_cancel: { request: JobRequest; result: { job: CadJob } };
  cad_artifact: { request: ArtifactRequest; result: { artifact: { data: string; bytes: number; sha256: string; filename: string } } };
  cad_plan: { request: PlanRequest; result: { recipe: Recipe } };
  cad_lifetime: { request: JobLifetime; result: { job: CadJob } };
  cad_close: { request: Record<string, never>; result: Record<string, unknown> };
}
export function createCadClient(socket: RpcSocket) {
  const scope = createRpcScope(socket);
  return {
    on(event: string, handler: (...args: any[]) => void) {
      return scope.on(event, (...args) => { if (event !== 'cad_job' || isJobUpdate(args[0])) handler(...args); });
    }, dispose: scope.dispose,
    async call<K extends keyof CadCalls>(event: K, data: CadCalls[K]['request'], timeout?: number): Promise<CadCalls[K]['result']> {
      try {
        const result = await scope.call<CadCalls[K]['result']>(event, data, timeout);
        if (event === 'cad_list' && (!Array.isArray((result as CadCalls['cad_list']['result']).jobs) || !(result as CadCalls['cad_list']['result']).jobs.every(job => isJobUpdate(job) && job.recipe && typeof job.recipe.name === 'string'))) {
          throw new RpcError('Build history could not be read. Refresh to try again.', 'invalid_response', true);
        }
        if ((event === 'cad_submit' || event === 'cad_cancel' || event === 'cad_lifetime') && !isJobUpdate((result as { job: unknown }).job)) {
          throw new RpcError('The core returned an invalid revision. Refresh history.', 'invalid_response', true);
        }
        if (event === 'cad_artifact' && !isArtifact((result as CadCalls['cad_artifact']['result']).artifact)) {
          throw new RpcError('The saved export could not be read. Refresh history.', 'invalid_response');
        }
        if (event === 'cad_plan' && !(result as CadCalls['cad_plan']['result']).recipe) {
          throw new RpcError('The core returned an invalid blueprint. Your current design was preserved.', 'invalid_response');
        }
        return result;
      } catch (error) {
        if (error instanceof RpcError && error.code === 'provider_not_configured') {
          error.message = 'AI blueprints are not configured yet. You can still build using dimensions.';
        }
        throw error;
      }
    },
  };
}
