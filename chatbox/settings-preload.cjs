'use strict'
const { contextBridge, ipcRenderer } = require('electron')
contextBridge.exposeInMainWorld('slidepilotSettings', {
  read: () => ipcRenderer.invoke('slidepilot:settings', 'read'),
  ready: () => ipcRenderer.invoke('slidepilot:settings', 'ready'),
  write: value => ipcRenderer.invoke('slidepilot:settings', 'write', value),
  provider: () => ipcRenderer.invoke('slidepilot:settings', 'provider'),
  open: target => ipcRenderer.invoke('slidepilot:settings', 'open', { target }),
  workspace: value => ipcRenderer.invoke('slidepilot:workspace-preferences', value),
  onRefresh: callback => {
    const listener = () => callback()
    ipcRenderer.on('slidepilot:settings-refresh', listener)
    return () => ipcRenderer.removeListener('slidepilot:settings-refresh', listener)
  },
})
