export const pendingJob = job => ['submitting', 'approval', 'queued', 'running'].includes(job?.state);
const rank = {
  submitting: 0,
  approval: 1,
  queued: 2,
  running: 3,
  succeeded: 4,
  cancelled: 4,
  failed: 4,
  interrupted: 4
};
export function mergeJob(previous, incoming) {
  if (previous?.request_id === incoming.request_id && rank[previous.state] > rank[incoming.state]) return previous;
  return {
    ...previous,
    ...incoming
  };
}
export function creativeRpc(socket, event, data, timeout = 10000) {
  return new Promise((resolve, reject) => {
    if (!socket.connected) return reject(new Error('Connect to the core before using Studio.'));
    socket.timeout(timeout).emit(event, data, (error, response) => {
      if (error) reject(new Error('The core did not respond. Refresh build history before trying again.'));else if (!response?.ok) {
        const failure = new Error(event.startsWith('cad_') && response?.code === 'provider_not_configured' ? 'AI blueprints are not configured yet. You can still build using dimensions.' : response?.message || 'The Studio action could not complete.');
        failure.code = response?.code;
        reject(failure);
      } else resolve(response);
    });
  });
}
export async function artifactBytes(artifact) {
  const bytes = Uint8Array.from(atob(artifact.data), char => char.charCodeAt(0));
  if (bytes.length !== artifact.bytes || bytes.length > 16777216) throw new Error('Export size validation failed.');
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  const hash = [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('');
  if (hash !== artifact.sha256) throw new Error('Export integrity validation failed.');
  return bytes;
}
