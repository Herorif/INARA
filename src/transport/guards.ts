/** Runtime guards for untrusted ACK/event envelopes; field authority stays server-side. */
export function isJobUpdate(value: unknown): value is { request_id: string; project: string; state: string; phase: string } {
  if (!value || typeof value !== 'object') return false;
  return 'request_id' in value && typeof value.request_id === 'string'
    && 'project' in value && typeof value.project === 'string'
    && 'state' in value && typeof value.state === 'string'
    && ['approval','submitting','queued','running','succeeded','failed','cancelled','interrupted'].includes(value.state)
    && 'phase' in value && typeof value.phase === 'string';
}
export function isArtifact(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false;
  return 'data' in value && typeof value.data === 'string' && value.data.length <= 22369628
    && 'filename' in value && typeof value.filename === 'string'
    && 'bytes' in value && typeof value.bytes === 'number' && Number.isInteger(value.bytes) && value.bytes > 0 && value.bytes <= 16777216
    && 'sha256' in value && typeof value.sha256 === 'string' && /^[a-f0-9]{64}$/.test(value.sha256);
}
