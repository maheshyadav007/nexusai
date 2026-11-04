const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('nexusDesktop', Object.freeze({
  platform: process.platform,
  caption: (colors) => ipcRenderer.invoke('nexus:caption', colors),
  status: () => ipcRenderer.invoke('nexus:status'),
  action: (action) => ipcRenderer.invoke('nexus:action', action),
  notify: (notice) => ipcRenderer.invoke('nexus:notify', notice),
}));
