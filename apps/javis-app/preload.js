const { contextBridge, ipcRenderer } = require("electron");

const statusListeners = new Set();

contextBridge.exposeInMainWorld("jarvis", {
  getDisplays: () => ipcRenderer.invoke("jarvis:getDisplays"),
  moveMonitor: (direction) => ipcRenderer.invoke("jarvis:moveMonitor", direction),
  maximize: () => ipcRenderer.invoke("jarvis:maximize"),
  minimize: () => ipcRenderer.invoke("jarvis:minimize"),
  restore: () => ipcRenderer.invoke("jarvis:restore"),
  toggleAlwaysOnTop: () => ipcRenderer.invoke("jarvis:toggleAlwaysOnTop"),
  nudge: (delta) => ipcRenderer.invoke("jarvis:nudge", delta),
  openExternal: (url) => ipcRenderer.invoke("jarvis:openExternal", url),
  onStatus: (callback) => {
    if (typeof callback === "function") statusListeners.add(callback);
    return () => statusListeners.delete(callback);
  }
});
