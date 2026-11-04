// Approval card content for one pending tool request. Outgoing task calls (C4,
// place_task_call) get their own layout: the core's review sentence says exactly who
// INARA will call, on which number, for what, and what it may share.

const GENERIC_SUMMARY = 'INARA continues only after you approve. Denying leaves this action undone.';

export function approvalView(request) {
  const args = request && typeof request.args === 'object' && request.args ? request.args : {};
  if (request?.tool === 'place_task_call' && typeof args.summary === 'string' && args.summary.trim()) {
    return { kind: 'task_call', title: 'Outgoing call', summary: args.summary.trim(), approveLabel: 'Approve call', denyLabel: 'Deny', details: null };
  }
  const title = typeof request?.tool === 'string' && request.tool ? request.tool.replaceAll('_', ' ') : 'Assistant action';
  return { kind: 'generic', title, summary: GENERIC_SUMMARY, approveLabel: 'Approve', denyLabel: 'Deny', details: args };
}
