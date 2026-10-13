const {
  contextBridge,
  ipcRenderer
} = require('electron');
const argument = name => process.argv.find(arg => arg.startsWith(`--${name}=`))?.slice(name.length + 3) || '';
contextBridge.exposeInMainWorld('electronAPI', {
  sessionToken: argument('inara-session-token'),
  clientId: argument('inara-client-id'),
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
  openExternal: url => ipcRenderer.invoke('open-external', url)
});
