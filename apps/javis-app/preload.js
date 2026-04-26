
const { contextBridge, ipcRenderer } = require("electron");
function finite(n){ return Number.isFinite(Number(n)); }
contextBridge.exposeInMainWorld("jarvis", {
  getDisplays: () => ipcRenderer.invoke("displays:get"),
  moveMonitor: (dir) => {
    if(dir==="left" || dir==="right") ipcRenderer.send("window:move-monitor", dir);
  },
  maximize: () => ipcRenderer.send("window:maximize"),
  minimize: () => ipcRenderer.send("window:minimize"),
  restore: () => ipcRenderer.send("window:restore"),
  toggleAlwaysOnTop: () => ipcRenderer.send("window:toggle-always-on-top"),
  nudge: (delta) => {
    if(!delta) return;
    const x = Number(delta.x), y = Number(delta.y);
    if(finite(x) && finite(y)) ipcRenderer.send("window:nudge", {x,y});
  },
  onStatus: (callback) => ipcRenderer.on("app:status", (_e,msg)=>callback(msg))
});
