import { flags } from './features.js';

/** Short decisions overlay current work; tools own one docked workspace. */
export const dialogFeatures = new Set(['settings', 'reminder', 'usage', 'memory', 'capabilities']);
export const featureWorkspace = feature => {
  if (['cad', 'image', 'camera', 'browser', 'printer', 'vision', 'activity'].includes(feature)) return 'studio';
  if (['tasks', 'routines'].includes(feature)) return 'tasks';
  if (feature === 'inbox') return 'inbox';
  return 'connections';
};
export const clearedFeatures = presentation => Object.fromEntries(Object.entries(flags)
  .filter(([feature]) => !presentation || dialogFeatures.has(feature) === (presentation === 'dialog'))
  .map(([, flag]) => [flag, false]));
export const workspaceTitles = {
  assistant: ['Your space to think.', 'A question, an idea, a next step. Start here.'],
  studio: ['Give your ideas form.', 'Choose a canvas. Make something that is yours.'],
  inbox: ['A little less noise.', 'Selected signals from your phone, in one quiet place.'],
  tasks: ['Make room for progress.', 'Plan a workflow. Review each step. Keep the receipts.'],
  connections: ['Your world, within reach.', 'See what is connected, what needs setup and what is ready.'],
  activity: ['Pick up where you left off.', 'Your project artifacts, revisions and recent work.'],
};
