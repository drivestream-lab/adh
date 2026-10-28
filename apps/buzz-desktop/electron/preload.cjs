const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("buzzDesktop", {
  shell: true,
});
