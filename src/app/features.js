/** One catalog for navigation, commands and panel labels. */
export const features = [
  { id: 'calls', title: 'Call lab', group: 'Connect', keywords: 'sim whatsapp personal phone call assistant simulation check call bridge lab', flag: 'showCallLab' },
  { id: 'inbox', title: 'Inbox', group: 'Organize', keywords: 'phone whatsapp messages selected read only signals notification inbox' },
  { id: 'connections', title: 'Connections', group: 'System', keywords: 'kasa printer dependencies device setup offline status connections readiness', flag: 'showConnectionReadiness' },
  { id: 'tasks', title: 'Tasks', group: 'Organize', keywords: 'task queue workflow plan approval steps receipts reviewed tasks', flag: 'showTaskQueue' },
  { id: 'usage', title: 'Usage', group: 'System', keywords: 'budget spending tokens costs limits evaluations quality usage & quality', flag: 'showUsageCenter' },
  { id: 'memory', title: 'Project memory', group: 'Organize', keywords: 'remember preferences facts decisions search forget export', flag: 'showProjectMemory' },
  { id: 'quick', title: 'Quick assistant', group: 'Assist', keywords: 'voice push talk microphone hotkey compact chat' },
  { id: 'capabilities', title: 'Capabilities', group: 'System', keywords: 'setup diagnostics hardware resources queue readiness capability center', flag: 'showCapabilities' },
  { id: 'activity', title: 'Activity', group: 'Organize', keywords: 'history exports revisions jobs activity & artifacts' },
  { id: 'cad', title: '3D studio', group: 'Create', keywords: 'model mesh stl glb blender scene', heavy: true, flag: 'showCadWindow' },
  { id: 'image', title: 'Images', group: 'Create', keywords: 'picture art generation png image atelier', heavy: true, flag: 'showImageStudio' },
  { id: 'camera', title: 'Vision', group: 'Observe', keywords: 'camera hand tracking preview vision studio', heavy: true },
  { id: 'browser', title: 'Web inspector', group: 'Explore', keywords: 'web research https read only', heavy: false, flag: 'showBrowserWindow' },
  { id: 'reminder', title: 'Reminders', group: 'Organize', keywords: 'schedule tasks alarm', flag: 'showReminderWindow' },
  { id: 'routines', title: 'Routines', group: 'Organize', keywords: 'automation routines routine manager', flag: 'showRoutineWindow' },
  { id: 'desktop', title: 'Desktop', group: 'Connect', keywords: 'apps clipboard system desktop controls', flag: 'showDesktopWindow' },
  { id: 'kasa', title: 'Smart home', group: 'Connect', keywords: 'lights plug kasa', flag: 'showKasaWindow' },
  { id: 'device', title: 'Devices', group: 'Connect', keywords: 'devices control connected devices', flag: 'showDeviceWindow' },
  { id: 'printer', title: 'Print', group: 'Create', keywords: 'printer slice fabrication print workshop', flag: 'showPrinterWindow' },
  { id: 'phone', title: 'Phone companion', group: 'Connect', keywords: 'phone android mobile pairing devices secure android companion', flag: 'showPhoneWindow' },
  { id: 'settings', title: 'Preferences', group: 'System', keywords: 'settings permissions audio', flag: 'showSettings' },
];
export const flags = Object.fromEntries(features.filter(feature => feature.flag).map(feature => [feature.id, feature.flag]));
export const heavyFeatures = new Set(features.filter(feature => feature.heavy).map(feature => feature.id));
export const labels = Object.fromEntries(features.map(feature => [feature.id, feature.title]));
export function searchCommands(query, gaming = false) {
  const terms = query.toLowerCase().trim().split(/\s+/);
  return features.filter(feature => terms.every(term => `${feature.title} ${feature.group} ${feature.keywords}`.toLowerCase().includes(term)))
    .map(feature => ({ ...feature, disabled: !!(gaming && feature.heavy) }));
}
