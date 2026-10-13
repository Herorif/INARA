const { contextBridge, ipcRenderer, shell } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
    sessionToken: process.argv.find(arg => arg.startsWith('--inara-session-token='))?.split('=')[1] || '',
    minimize: () => ipcRenderer.send('window-minimize'),
    maximize: () => ipcRenderer.send('window-maximize'),
    close: () => ipcRenderer.send('window-close'),
    openExternal: (url) => shell.openExternal(url),
});
