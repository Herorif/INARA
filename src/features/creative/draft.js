/** Bounded in-memory recipe history. Saved revisions remain immutable. */
export const createDraft = value => ({ value, past: [], future: [] });
export function draftReducer(state, action) {
  if (action.type === 'reset') return createDraft(action.value);
  if (action.type === 'undo' && state.past.length) return { value: state.past.at(-1), past: state.past.slice(0, -1), future: [state.value, ...state.future].slice(0, 50) };
  if (action.type === 'redo' && state.future.length) return { value: state.future[0], past: [...state.past, state.value].slice(-50), future: state.future.slice(1) };
  if (action.type !== 'change') return state;
  const value = typeof action.value === 'function' ? action.value(state.value) : action.value;
  if (JSON.stringify(value) === JSON.stringify(state.value)) return state;
  return { value, past: [...state.past, state.value].slice(-50), future: [] };
}
export function recipeDiff(before, after, prefix = '') {
  if (JSON.stringify(before) === JSON.stringify(after)) return [];
  if (before && after && typeof before === 'object' && typeof after === 'object') {
    return [...new Set([...Object.keys(before), ...Object.keys(after)])].flatMap(key => recipeDiff(before[key], after[key], prefix ? `${prefix}.${key}` : key)).slice(0, 512);
  }
  return [{ field: prefix, before, after }];
}
export function parentReference(job) {
  return job?.state === 'succeeded' && /^[a-f0-9]{64}$/.test(job.recipe_fingerprint || '')
    ? { base_request_id: job.request_id, base_fingerprint: job.recipe_fingerprint } : {};
}
