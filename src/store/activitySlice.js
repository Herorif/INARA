import { mergeJob } from '../features/creative/client.js';
/** Retain metadata only; binary previews and prompts stay out of global UI state. */
export function recordActivity(entries, kind, job, project) {
  if (!job || job.project !== project || typeof job.request_id !== 'string' || typeof job.phase !== 'string' || !['approval', 'submitting', 'queued', 'running', 'succeeded', 'failed', 'cancelled', 'interrupted'].includes(job.state)) return entries;
  const key = `${kind}:${job.request_id}`, old = entries.find(item => item.key === key);
  const merged = mergeJob(old, {
    key, kind, request_id: job.request_id, project: job.project, state: job.state, phase: job.phase,
    name: job.recipe?.name || old?.name || (kind === 'cad' ? '3D revision' : 'Image revision'),
    created_at: job.created_at || old?.created_at,
    artifacts: job.artifacts ? Object.keys(job.artifacts) : old?.artifacts || [],
    error: job.error,
    background: job.background === true,
    resources: job.resources,
  });
  return [merged, ...entries.filter(item => item.key !== key)].slice(0, 48);
}
export const createActivitySlice = (set, get) => ({
  activity: [], studioSelection: null,
  restoreActivity: (kind, jobs, startedAt) => set(state => {
    const ids = new Set(jobs.map(job => job.request_id));
    let activity = state.activity.filter(item => item.kind !== kind || ids.has(item.request_id) || !item.created_at || item.created_at > startedAt);
    for (const job of [...jobs].reverse()) activity = recordActivity(activity, kind, job, get().currentProject);
    return { activity };
  }),
  recordActivity: (kind, job) => set(state => ({ activity: recordActivity(state.activity, kind, job, get().currentProject) })),
});
