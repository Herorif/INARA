// Approval card content for one pending tool request. Outgoing task calls (C4,
// place_task_call) get their own layout: the core's review sentence says exactly who
// JARVIS will call, on which number, for what, and what it may share. The live design's
// build (build_live_design) gets a short one with the core's summary, and a calendar event
// (calendar_add_event) shows the core's one-line approval sentence.

const GENERIC_SUMMARY = 'JARVIS continues only after you approve. Denying leaves this action undone.';

export function approvalView(request) {
  const args = request && typeof request.args === 'object' && request.args ? request.args : {};
  if (request?.tool === 'place_task_call' && typeof args.summary === 'string' && args.summary.trim()) {
    return { kind: 'task_call', title: 'Outgoing call', summary: args.summary.trim(), approveLabel: 'Approve call', denyLabel: 'Deny', details: null };
  }
  if (request?.tool === 'calendar_add_event' && typeof args.approval === 'string' && args.approval.trim()) {
    // Google Calendar (docs/CALENDAR.md): the core's review sentence, e.g.
    // Add “Lunch with Aisyah” to your calendar, Monday 9 November 13:00 to 14:00?
    return { kind: 'calendar_event', title: 'Add to calendar', summary: args.approval.trim(), approveLabel: 'Add', denyLabel: 'Not now', details: null };
  }
  if (request?.tool === 'build_live_design') {
    // The live design's build (docs/LIVE_DESIGN.md); the panel shows this inline when it is open.
    const summary = typeof args.summary === 'string' && args.summary.trim() ? args.summary.trim() : 'Build the live design as STL and GLB on this PC.';
    return { kind: 'live_design', title: 'Build live design', summary, approveLabel: 'Build', denyLabel: 'Not now', details: null };
  }
  if (request?.tool === 'look_through_camera') {
    // Show JARVIS by voice (docs/VISION_STUDIO.md#show-jarvis): one still photo per approval.
    return { kind: 'camera_look', title: 'Look through your camera?', summary: 'JARVIS wants to look through your camera. It takes one still photo to answer you, then the camera turns off again.', approveLabel: 'Allow once', denyLabel: 'Not now', details: null };
  }
  const title = typeof request?.tool === 'string' && request.tool ? request.tool.replaceAll('_', ' ') : 'Assistant action';
  return { kind: 'generic', title, summary: GENERIC_SUMMARY, approveLabel: 'Approve', denyLabel: 'Deny', details: args };
}
