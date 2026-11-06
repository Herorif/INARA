// Talking overlay bridge (electron/overlay-app.cjs). The renderer never receives the token and
// never opens a socket: it gets validated snapshots and levels, and reports back.
const { contextBridge, ipcRenderer } = require('electron');

// Listen from preload time and keep the latest value, so a subscriber that attaches after the
// first snapshot or level arrived still starts from it.
const latest = { 'overlay-snapshot': undefined, 'overlay-level': undefined };
const subscribers = { 'overlay-snapshot': new Set(), 'overlay-level': new Set() };
for (const channel of Object.keys(subscribers)) {
  ipcRenderer.on(channel, (_event, value) => {
    latest[channel] = value;
    for (const callback of subscribers[channel]) callback(value);
  });
}
const subscribe = channel => callback => {
  if (typeof callback !== 'function') return () => {};
  subscribers[channel].add(callback);
  if (latest[channel] !== undefined) callback(latest[channel]);
  return () => { subscribers[channel].delete(callback); };
};

contextBridge.exposeInMainWorld('jarvisOverlay', {
  onSnapshot: subscribe('overlay-snapshot'),
  onLevel: subscribe('overlay-level'),
  ready: () => ipcRenderer.send('overlay-ready'),
  pointer: inside => ipcRenderer.send('overlay-pointer', inside === true),
  stop: () => ipcRenderer.send('overlay-stop'),
  open: () => ipcRenderer.send('overlay-open'),
  done: () => ipcRenderer.send('overlay-done'),
});
