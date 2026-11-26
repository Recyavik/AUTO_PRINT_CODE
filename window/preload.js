"use strict";
// Перед страницей окна: файлы с диска, брошенные в окно, и кнопки страницы сбоя (fail.html).
//
// Файлы ловит окно, а не страница (как в 1.1 через Qt): программе уходят настоящие пути — видео в сотни МБ не
// копируются через страницу. Картинки и текст, перетащенные из браузера, — странице, как обычно.
const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("autoprintShell", {
  electron: true,
  files: !!(webUtils && webUtils.getPathForFile),      // пути брошенных файлов доступны
  retry: () => ipcRenderer.send("shell", { op: "retry" }),
  openLog: () => ipcRenderer.send("shell", { op: "open_log" }),
});

/** Тащат файлы с диска (Проводник): в перетаскивании только «Files», без адреса и разметки (те — из браузера). */
function diskFiles(dt) {
  if (!dt) return false;
  const types = Array.from(dt.types || []);
  return types.includes("Files") && !types.includes("text/uri-list") && !types.includes("text/html");
}

for (const type of ["dragenter", "dragover"]) {
  window.addEventListener(type, (e) => {
    if (!diskFiles(e.dataTransfer)) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    e.dataTransfer.dropEffect = "copy";
  }, true);
}

window.addEventListener("drop", (e) => {
  if (!diskFiles(e.dataTransfer)) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  const paths = Array.from(e.dataTransfer.files || []).map((f) => {
    try { return webUtils.getPathForFile(f); } catch { return ""; }
  }).filter(Boolean);
  if (paths.length) ipcRenderer.send("shell", { op: "drop", paths });
}, true);
