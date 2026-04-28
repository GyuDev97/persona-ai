const { app, BrowserWindow, ipcMain, screen, shell } = require("electron");
const path = require("path");

let mainWindow;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 980,
    minHeight: 640,
    backgroundColor: "#000000",
    frame: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  mainWindow.loadFile(path.join(__dirname, "index.html"));
}

app.whenReady().then(() => {
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

ipcMain.handle("jarvis:getDisplays", () => {
  return screen.getAllDisplays().map((display) => ({
    id: display.id,
    bounds: display.bounds,
    workArea: display.workArea,
    scaleFactor: display.scaleFactor
  }));
});

ipcMain.handle("jarvis:moveMonitor", (_event, direction) => {
  if (!mainWindow) return;
  const displays = screen.getAllDisplays().sort((a, b) => a.bounds.x - b.bounds.x);
  const current = screen.getDisplayMatching(mainWindow.getBounds());
  const currentIndex = Math.max(0, displays.findIndex((display) => display.id === current.id));
  const nextIndex = direction === "left"
    ? Math.max(0, currentIndex - 1)
    : Math.min(displays.length - 1, currentIndex + 1);
  const target = displays[nextIndex].workArea;
  mainWindow.setBounds({
    x: target.x + 40,
    y: target.y + 40,
    width: Math.min(1280, target.width - 80),
    height: Math.min(820, target.height - 80)
  });
});

ipcMain.handle("jarvis:maximize", () => mainWindow?.maximize());
ipcMain.handle("jarvis:minimize", () => mainWindow?.minimize());
ipcMain.handle("jarvis:restore", () => mainWindow?.restore());
ipcMain.handle("jarvis:toggleAlwaysOnTop", () => {
  if (!mainWindow) return false;
  const next = !mainWindow.isAlwaysOnTop();
  mainWindow.setAlwaysOnTop(next);
  return next;
});
ipcMain.handle("jarvis:nudge", (_event, delta) => {
  if (!mainWindow || !delta) return;
  const bounds = mainWindow.getBounds();
  mainWindow.setBounds({
    ...bounds,
    x: Math.round(bounds.x + (delta.x || 0)),
    y: Math.round(bounds.y + (delta.y || 0))
  });
});
ipcMain.handle("jarvis:openExternal", (_event, url) => {
  if (typeof url === "string" && /^https?:\/\//.test(url)) {
    shell.openExternal(url);
  }
});
