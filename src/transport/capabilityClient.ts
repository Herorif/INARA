import { createRpcScope, RpcError, type RpcSocket } from './rpc.ts';
export type ResourceEstimate = { cpu: number; ram_mb: number; vram_mb: number };
export type CapabilityReport = {
  checked_at: number;
  hardware: { cpu_count: number | null; ram_available_mb: number | null; ram_total_mb: number | null; vram_mb: number | null };
  resources: { state: string; running: number; waiting: number; queue_limit: number; budget: ResourceEstimate };
  capabilities: Array<{ id: string; title: string; installed: boolean; configured: boolean; verified: boolean; blocked: string | null; reason: string; status: string; model: string | null; profile: ResourceEstimate | null; last_duration_seconds: number | null }>;
};
export function createCapabilityClient(socket: RpcSocket) {
  const scope = createRpcScope(socket);
  return { on: scope.on, dispose: scope.dispose, async inspect(): Promise<CapabilityReport> {
    const value = await scope.call<CapabilityReport>('capability_diagnostics', {});
    const amount = (n: unknown) => typeof n === 'number' && Number.isFinite(n) && n >= 0;
    const nullable = (n: unknown) => n === null || amount(n);
    const estimate = (v: ResourceEstimate) => v && ['cpu', 'ram_mb', 'vram_mb'].every(k => amount(v[k as keyof ResourceEstimate]));
    if (!amount(value.checked_at) || !value.hardware || !['cpu_count','ram_available_mb','ram_total_mb','vram_mb'].every(k => nullable(value.hardware[k as keyof CapabilityReport['hardware']])) || !value.resources || !estimate(value.resources.budget) || typeof value.resources.state !== 'string' || ![value.resources.running,value.resources.waiting,value.resources.queue_limit].every(amount) || !Array.isArray(value.capabilities) || !value.capabilities.every(c => c && typeof c.id === 'string' && typeof c.title === 'string' && typeof c.reason === 'string' && typeof c.status === 'string' && ['installed','configured','verified'].every(k => typeof c[k as 'installed'] === 'boolean') && (c.blocked === null || typeof c.blocked === 'string') && (c.model === null || typeof c.model === 'string') && (c.profile === null || estimate(c.profile)) && nullable(c.last_duration_seconds))) {
      throw new RpcError('Diagnostics returned an incomplete report. Refresh to try again.', 'invalid_response');
    }
    return value;
  } };
}
