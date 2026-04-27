const { app, BrowserWindow, ipcMain, screen } = require("electron");

let win;
let currentDisplayIndex = 0;

function getDisplaysSorted() {
  return screen.getAllDisplays().sort((a, b) => a.bounds.x - b.bounds.x);
}

function createWindow() {
  win = new BrowserWindow({
    width: 1400,
    height: 900,
    backgroundColor: "#000000",
    autoHideMenuBar: true,
    webPreferences: {
      preload: __dirname + "/preload.js",
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  win.loadFile("index.html");
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

ipcMain.handle("displays:get", () => {
  return getDisplaysSorted().map((d, i) => ({
    index: i,
    id: d.id,
    bounds: d.bounds,
    workArea: d.workArea,
    scaleFactor: d.scaleFactor,
    primary: d.id === screen.getPrimaryDisplay().id
  }));
});

ipcMain.on("window:move-monitor", (_event, dir) => {
  try {
    if (!win) return;
    const displays = getDisplaysSorted();
    if (!displays || displays.length < 2) {
      win.webContents.send("app:status", "모니터가 하나만 감지되었습니다.");
      return;
    }

    if (dir === "right") currentDisplayIndex = Math.min(displays.length - 1, currentDisplayIndex + 1);
    if (dir === "left") currentDisplayIndex = Math.max(0, currentDisplayIndex - 1);

    const d = displays[currentDisplayIndex];
    const area = d.workArea || d.bounds || { x: 0, y: 0, width: 1400, height: 900 };

    const x = Math.round(Number(area.x || 0) + 20);
    const y = Math.round(Number(area.y || 0) + 20);
    const w = Math.round(Math.max(800, Number(area.width || 1400) - 40));
    const h = Math.round(Math.max(600, Number(area.height || 900) - 40));

    win.setPosition(x, y);
    win.setSize(w, h);
    win.webContents.send("app:status", `${currentDisplayIndex + 1}번 모니터로 이동`);
  } catch (_error) {
    win.webContents.send("app:status", "모니터 이동 중 오류가 발생했습니다.");
  }
});

ipcMain.on("window:maximize", () => {
  if (!win) return;
  win.maximize();
  win.webContents.send("app:status", "창을 최대화했습니다.");
});

ipcMain.on("window:minimize", () => {
  if (!win) return;
  win.minimize();
});

ipcMain.on("window:restore", () => {
  if (!win) return;
  if (win.isMinimized()) win.restore();
  if (win.isMaximized()) win.unmaximize();
  win.webContents.send("app:status", "창을 복원했습니다.");
});

ipcMain.on("window:toggle-always-on-top", () => {
  if (!win) return;
  const next = !win.isAlwaysOnTop();
  win.setAlwaysOnTop(next, "screen-saver");
  win.webContents.send("app:status", next ? "항상 위 고정 ON" : "항상 위 고정 OFF");
});

ipcMain.on("window:nudge", (_event, delta) => {
  try {
    if (!win || !delta) return;
    const dx = Number(delta.x);
    const dy = Number(delta.y);
    if (!Number.isFinite(dx) || !Number.isFinite(dy)) return;
    const [x, y] = win.getPosition();
    win.setPosition(Math.round(x + dx), Math.round(y + dy));
  } catch (_error) {
  }
});
