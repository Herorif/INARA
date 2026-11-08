// Approval card content for one pending tool request. Outgoing task calls (C4,
// place_task_call) get their own layout: the core's review sentence says exactly who
// JARVIS will call, on which number, for what, and what it may share. The live design's
// build (build_live_design) gets a short one with the core's summary, and a calendar event
// (calendar_add_event) shows the core's one-line approval sentence.

const GENERIC_SUMMARY = 'JARVIS continues only after you approve. Denying leaves this action undone.';
// The approve labels home_control's review can send (backend/services/home_assistant.py).
const HOME_ACTION_LABELS = ['Turn on', 'Turn off', 'Toggle', 'Set', 'Activate', 'Run', 'Lock', 'Unlock', 'Open', 'Close', 'Arm', 'Disarm', 'Play', 'Pause'];
// Longer MCP arguments are shown as clipped JSON text.
const MCP_DETAILS_LIMIT = 600;

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
  if (request?.tool === 'home_control' && typeof args.approval === 'string' && args.approval.trim()
    && HOME_ACTION_LABELS.includes(args.approve_label)) {
    // Home Assistant (docs/HOME_ASSISTANT.md): the core's sentence, e.g. "Unlock Front door?",
    // approved with its action ("Unlock").
    return { kind: 'home_control', title: args.approval.trim().slice(0, 160), summary: GENERIC_SUMMARY, approveLabel: args.approve_label, denyLabel: 'Not now', details: null };
  }
  if (typeof request?.tool === 'string' && request.tool.startsWith('mcp__') && typeof args.server === 'string' && args.server.trim()) {
    // MCP server tools (docs/MCP.md): "<Server name>: <tool title or name>", with a short
    // JSON of the arguments the server will receive.
    const tool = [args.tool_title, args.mcp_tool].find((value) => typeof value === 'string' && value.trim())?.trim() ?? request.tool;
    const title = `${args.server.trim()}: ${tool}`.slice(0, 160);
    const values = args.arguments && typeof args.arguments === 'object' ? args.arguments : {};
    let text = '';
    try { text = JSON.stringify(values) ?? ''; } catch { text = ''; }
    const details = text.length <= MCP_DETAILS_LIMIT ? values : { arguments: `${text.slice(0, MCP_DETAILS_LIMIT)}…` };
    return { kind: 'mcp_tool', title, summary: GENERIC_SUMMARY, approveLabel: 'Approve', denyLabel: 'Deny', details };
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
