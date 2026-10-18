import { mergeJob } from '../features/creative/client.js';
export function reconcileHistory<T extends { request_id: string; state: string }>(previous: T[], snapshot: T[], changed: Set<string>): T[] {
  const byId = new Map(previous.map(job => [job.request_id, job]));
  const result = snapshot.map(job => {
    const old = byId.get(job.request_id);
    return mergeJob(old, job);
  });
  const received = new Set(snapshot.map(job => job.request_id));
  return [...previous.filter(job => changed.has(job.request_id) && !received.has(job.request_id)), ...result].slice(0, 12);
}
