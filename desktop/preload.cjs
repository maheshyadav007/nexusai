const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('nexusDesktop', Object.freeze({
  platform: process.platform,
  caption: (colors) => ipcRenderer.invoke('nexus:caption', colors),
  status: () => ipcRenderer.invoke('nexus:status'),
  action: (action) => ipcRenderer.invoke('nexus:action', action),
  notify: (notice) => ipcRenderer.invoke('nexus:notify', notice),
  quick: (action, value) => ipcRenderer.invoke('nexus:quick', { action, value }),
  onQuickOpen: (listener) => {
    const handler = (_, detail) => listener(detail);
    ipcRenderer.on('nexus:quick-open', handler);
    return () => ipcRenderer.removeListener('nexus:quick-open', handler);
  },
}));
