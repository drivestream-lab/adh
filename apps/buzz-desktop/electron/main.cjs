const { app, BrowserWindow, shell } = require("electron");
const http = require("node:http");
const path = require("node:path");

const DEV = process.argv.includes("--dev");
const UI_CANDIDATES = DEV
  ? ["http://127.0.0.1:5173/"]
  : ["http://127.0.0.1:8081/", "http://127.0.0.1:8080/buzz/"];

function reachable(url) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: 1500 }, (res) => {
      resolve(Boolean(res.statusCode && res.statusCode < 500));
      res.resume();
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function pickUrl() {
  for (const url of UI_CANDIDATES) {
    if (await reachable(url)) return url;
  }
  return null;
}

async function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 840,
    minHeight: 560,
    title: "Buzz",
    backgroundColor: "#0c1117",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
    },
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
  const url = await pickUrl();
  if (url) {
    await win.loadURL(url);
  } else {
    await win.loadFile(path.join(__dirname, "offline.html"));
  }
}

app.whenReady().then(createWindow);
app.on("window-all-closed", () => app.quit());
