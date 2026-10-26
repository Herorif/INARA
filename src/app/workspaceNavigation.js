import { flags } from './features.js';

/** Short decisions overlay current work; tools own one docked workspace. */
export const dialogFeatures = new Set(['settings', 'reminder', 'usage', 'memory', 'capabilities']);
export const featureWorkspace = feature => {
  if (['cad', 'image', 'camera', 'browser', 'printer', 'activity'].includes(feature)) return 'studio';
  if (['tasks', 'routines'].includes(feature)) return 'tasks';
  if (feature === 'inbox') return 'inbox';
  return 'connections';
};
export const clearedFeatures = presentation => Object.fromEntries(Object.entries(flags)
  .filter(([feature]) => !presentation || dialogFeatures.has(feature) === (presentation === 'dialog'))
  .map(([, flag]) => [flag, false]));
/** Page header: [title, meta]. Titles name the page; the meta line says what it is for. */
export const workspaceTitles = {
  assistant: ['Assistant', ''],
  studio: ['Studio', '3D, images, vision and web tools'],
  inbox: ['Inbox', 'Notifications you chose to share from your phone'],
  tasks: ['Tasks', 'Review and run multi-step desktop tasks'],
  connections: ['Connections', 'Devices, phone and calls'],
  activity: ['Activity', 'Artifacts and revisions for this project'],
};
