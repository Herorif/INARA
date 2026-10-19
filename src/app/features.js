/** One catalog for navigation, commands and panel labels. */
export const features = [
  { id: 'memory', title: 'Project memory', group: 'Organize', keywords: 'remember preferences facts decisions search forget export', flag: 'showProjectMemory' },
  { id: 'quick', title: 'Quick assistant', group: 'Assist', keywords: 'voice push talk microphone hotkey compact chat' },
  { id: 'capabilities', title: 'Capability center', group: 'System', keywords: 'setup diagnostics hardware resources queue readiness', flag: 'showCapabilities' },
  { id: 'activity', title: 'Activity & artifacts', group: 'Organize', keywords: 'history exports revisions jobs' },
  { id: 'cad', title: '3D studio', group: 'Create', keywords: 'model mesh stl glb blender scene', heavy: true, flag: 'showCadWindow' },
  { id: 'image', title: 'Image atelier', group: 'Create', keywords: 'picture art generation png', heavy: true, flag: 'showImageStudio' },
  { id: 'camera', title: 'Vision studio', group: 'Observe', keywords: 'camera hand tracking preview', heavy: true },
  { id: 'browser', title: 'Research browser', group: 'Explore', keywords: 'web research', heavy: true, flag: 'showBrowserWindow' },
  { id: 'reminder', title: 'Reminders', group: 'Organize', keywords: 'schedule tasks alarm', flag: 'showReminderWindow' },
  { id: 'routines', title: 'Routine manager', group: 'Organize', keywords: 'automation routines', flag: 'showRoutineWindow' },
  { id: 'desktop', title: 'Desktop controls', group: 'Connect', keywords: 'apps clipboard system', flag: 'showDesktopWindow' },
  { id: 'kasa', title: 'Smart home', group: 'Connect', keywords: 'lights plug kasa', flag: 'showKasaWindow' },
  { id: 'device', title: 'Connected devices', group: 'Connect', keywords: 'devices control', flag: 'showDeviceWindow' },
  { id: 'printer', title: 'Print workshop', group: 'Create', keywords: 'printer slice fabrication', flag: 'showPrinterWindow' },
  { id: 'vision', title: 'Scene watches', group: 'Observe', keywords: 'watch presence vision', heavy: true, flag: 'showVisionWindow' },
  { id: 'phone', title: 'Android companion', group: 'Connect', keywords: 'phone android mobile pairing devices secure', flag: 'showPhoneWindow' },
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
