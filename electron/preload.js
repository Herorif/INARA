const {
  contextBridge,
  ipcRenderer
} = require('electron');
const bootstrap = ipcRenderer.sendSync('desktop-bootstrap') || {};
contextBridge.exposeInMainWorld('electronAPI', {
  sessionToken: bootstrap.token || '',
  clientId: bootstrap.clientId || '',
  minimize: () => ipcRenderer.send('window-minimize'),
  maximize: () => ipcRenderer.send('window-maximize'),
  close: () => ipcRenderer.send('window-close'),
  quit: () => ipcRenderer.send('app-quit'),
  registerResident: id => ipcRenderer.invoke('resident-register', id),
  residentStatus: () => ipcRenderer.invoke('resident-status'),
  setGaming: value => ipcRenderer.invoke('resident-gaming', value),
  metrics: () => ipcRenderer.invoke('resident-metrics'),
  onResidentState: callback => {
    const listener = (_, state) => callback(state);
    ipcRenderer.on('resident-state', listener);
    return () => ipcRenderer.removeListener('resident-state', listener);
  },
  onCapturePause: callback => {
    const listener = (_, reason) => callback(reason);
    ipcRenderer.on('capture-pause', listener);
    return () => ipcRenderer.removeListener('capture-pause', listener);
  },
  openExternal: url => ipcRenderer.invoke('open-external', url)
});
