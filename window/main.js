"use strict";
// Окно программы AutoPrintCode (Electron): страница /app с локального сервера программы.
//
// Окно запускает программа (Python, autoprint/ui/shell_window.py) и говорит с ним по именованному каналу —
// строками JSON. Программа → окно: {op, …, id?}; окно → программа: {ev, …} и ответы {ev:"reply", id, ok, value|error}.
// Канал закрылся (программа вышла или упала) — окно закрывается тоже.
//
// Окно без рамки: края, прилипание к краям экрана, Win+стрелки — Windows; перетаскивание — CSS app-region по
// [data-drag] страницы. Ссылки наружу и «Журнал работы» открывает программа (в тестах это заглушки).
// --autoprint-hidden=1 — окно не показывается никогда (тесты, --selftest): видно/свёрнуто/развёрнуто — «как будто».

const { app, BrowserWindow, Menu, dialog, ipcMain, nativeTheme, screen } = require("electron");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");
const { spawn } = require("node:child_process");
const G = require("./geometry.js");

const FAIL_PREFIX = "Не удалось запустить окно программы";
const READY_WAIT_MS = 6000;        // страница загрузилась, но скрипты не запустились — сообщение через 6 с
const SHOW_WAIT_MS = 2500;         // окно показывается, когда страница готова, но не позже
const MM12 = 12 / 25.4;            // поля листа PDF, дюймы

function arg(name) {
  const p = `--autoprint-${name}=`;
  const a = process.argv.find((s) => s.startsWith(p));
  return a === undefined ? "" : a.slice(p.length);
}
const PIPE = arg("pipe");
const DATA = arg("data");
const HIDDEN = arg("hidden") === "1";

let sock = null, inbox = "";
let win = null, cfg = {}, quitting = false;
let readyToShow = false, shownOnce = false, readyTimer = 0, geoTimer = 0, loadGen = 0;
// показать, когда страница готова: "focus" — вперёд (запуск, «Показать окно»), "inactive" — не забирая клавиатуру
// (окно перезапустилось, пока человек печатал в другом окне), "" — не показывать
let wantShow = "";
let lastMax = false;       // развёрнуто ли — по событиям окна (у свёрнутого и ещё не показанного isMaximized() — false)
const fake = { visible: false, minimized: false, maximized: false, focused: false };   // hidden: состояние «как будто»
let compact = false, big = null, bigMax = false, small = null;   // большое окно (обычный размер), было ли развёрнуто; маленькое
let top = false;

if (!PIPE) {
  // окно запустили само по себе (ярлык, закреплённая кнопка) — запустить программу, она откроет окно
  const exe = path.join(path.dirname(process.execPath), "..", "AutoPrintCode.exe");
  if (app.isPackaged && fs.existsSync(exe)) spawn(exe, [], { detached: true, stdio: "ignore" }).unref();
  process.exit(0);
}

if (DATA) {
  try { fs.mkdirSync(DATA, { recursive: true }); app.setPath("userData", DATA); } catch { /* останется своя папка */ }
}
app.setAppUserModelId("autoprintcode.app");
Menu.setApplicationMenu(null);            // без меню — и без его клавиш (F5, Ctrl+R, Ctrl+Shift+I, Ctrl+±)
app.on("window-all-closed", () => {});    // окно закрывает программа (op quit)
app.whenReady().then(connect);

// ---------------------------------------------------------------- канал с программой
function send(msg) {
  if (sock && !sock.destroyed) sock.write(JSON.stringify(msg) + "\n");
}
function log(level, text) { send({ ev: "log", level, text: String(text).slice(0, 2000) }); }

function connect() {
  sock = net.connect(PIPE);
  sock.setEncoding("utf8");
  sock.on("data", (chunk) => {
    inbox += chunk;
    let i;
    while ((i = inbox.indexOf("\n")) >= 0) {
      const line = inbox.slice(0, i);
      inbox = inbox.slice(i + 1);
      if (!line.trim()) continue;
      let m;
      try { m = JSON.parse(line); } catch { log("warning", "непонятная строка от программы"); continue; }
      handle(m);
    }
  });
  sock.on("close", () => { quitting = true; app.exit(0); });
  sock.on("error", () => {});
  send({ ev: "hello", pid: process.pid, electron: process.versions.electron, chrome: process.versions.chrome });
}

const OPS = {
  init, show, hide, min, max, restore, toggle_max: toggleMax, top: setTop, title, theme,
  compact: setCompact, compact_size: compactSize, reload, quit, js, pdf, print, open_dialog: openDialog,
  save_dialog: saveDialog, devtools, test_drop: testDrop,
};

function handle(m) {
  const fn = OPS[m.op];
  const reply = (ok, v) => m.id !== undefined && send(ok ? { ev: "reply", id: m.id, ok: true, value: v === undefined ? null : v }
    : { ev: "reply", id: m.id, ok: false, error: String((v && v.message) || v) });
  if (!fn) { log("warning", `неизвестная команда окна: ${m.op}`); reply(false, "неизвестная команда"); return; }
  if (!win && m.op !== "init" && m.op !== "quit") { reply(false, "окна ещё нет"); return; }
  try {
    Promise.resolve(fn(m)).then((v) => reply(true, v), (err) => { log("warning", `${m.op}: ${(err && err.message) || err}`); reply(false, err); });
  } catch (err) {
    log("warning", `${m.op}: ${(err && err.message) || err}`);
    reply(false, err);
  }
}

// ---------------------------------------------------------------- окно
const works = () => screen.getAllDisplays().map((d) => d.workArea);
const workFor = (b) => screen.getDisplayMatching(b).workArea;

function init(m) {
  if (win) return;
  cfg = m || {};
  const primary = screen.getPrimaryDisplay().workArea;
  big = G.placeSaved(cfg.big, works(), G.BIG_MIN) || G.defaultBig(primary);
  bigMax = !!(cfg.big && cfg.big.max);
  small = G.placeSaved(cfg.small, works(), G.COMPACT_MIN);
  compact = !!cfg.compact;
  top = !!cfg.top;
  lastMax = bigMax && !compact;
  wantShow = cfg.show === "inactive" ? "inactive" : cfg.show ? "focus" : "";
  const b = compact ? (small || G.defaultCompact(workFor(big))) : big;
  const minSize = compact ? G.COMPACT_MIN : G.BIG_MIN;
  win = new BrowserWindow({
    x: b.x, y: b.y, width: b.width, height: b.height, minWidth: minSize.width, minHeight: minSize.height,
    show: false, frame: false, backgroundColor: cfg.bg || "#161A22", title: cfg.title || "AutoPrintCode",
    icon: cfg.icon && fs.existsSync(cfg.icon) ? cfg.icon : undefined,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"), contextIsolation: true, sandbox: true, nodeIntegration: false,
      spellcheck: false,
    },
  });
  if (cfg.appDetails) { try { win.setAppDetails(cfg.appDetails); } catch { /* только Windows */ } }
  nativeTheme.themeSource = cfg.dark === false ? "light" : "dark";
  win.setAlwaysOnTop(top);
  win.setMaximizable(!compact);           // маленькое окно не разворачивается (двойной щелчок по табло)
  wire(win);
  const h = win.getNativeWindowHandle();
  send({ ev: "hwnd", hwnd: h.length >= 8 ? Number(h.readBigUInt64LE(0)) : h.readUInt32LE(0) });
  load();
}

function wire(w) {
  for (const e of ["show", "hide", "minimize", "restore", "maximize", "unmaximize", "focus", "blur"]) w.on(e, report);
  w.on("maximize", () => { lastMax = true; });
  w.on("unmaximize", () => { lastMax = false; });
  const geo = () => { clearTimeout(geoTimer); geoTimer = setTimeout(reportGeometry, 400); };
  w.on("move", geo);
  w.on("resize", geo);
  w.on("moved", reportGeometry);          // отпустили после перетаскивания / растягивания — место сразу программе
  w.on("resized", reportGeometry);
  w.on("close", (e) => {                  // Alt+F4, «Закрыть» на панели задач: решает программа (в трей или выход)
    if (quitting) return;
    e.preventDefault();
    send({ ev: "close" });
  });
  w.on("page-title-updated", (e) => e.preventDefault());   // заголовок окна — от программы (состояние набора)
  w.once("ready-to-show", () => { readyToShow = true; firstShow(); });
  setTimeout(() => { if (!readyToShow) { readyToShow = true; firstShow(); } }, SHOW_WAIT_MS);
  const wc = w.webContents;
  wc.setWindowOpenHandler(({ url }) => { outside(url); return { action: "deny" }; });
  wc.on("will-navigate", (e, url) => {
    if (ours(url)) return;
    e.preventDefault();
    // ссылку нажали на странице — в браузер человека; ссылку или файл бросили на окно (переход не от страницы) — мимо
    if (e.initiator) outside(url);
  });
  wc.on("did-finish-load", onLoaded);
  wc.on("did-fail-load", (_e, code, desc, url, isMain) => {
    if (isMain && code !== -3 && !isFailPage(url)) fail("страница окна не загрузилась.", `${code} ${desc}`);
  });
  wc.on("render-process-gone", (_e, d) => {
    log("warning", `Страница окна: процесс отрисовки завершился (${d.reason}, код ${d.exitCode})`);
    fail("страница окна перестала отвечать — перезагружаю.");
    setTimeout(load, 1500);
  });
  wc.on("unresponsive", () => log("warning", "Страница окна не отвечает"));
  wc.on("console-message", onConsole);
  wc.setVisualZoomLevelLimits(1, 1).catch(() => {});
}

function onConsole(e, level, message, line, source) {
  // Electron ≥ 35: одно событие с полями; раньше — отдельные аргументы
  const lv = typeof e.level === "string" ? e.level : (["verbose", "info", "warning", "error"][level] || "info");
  if (lv !== "error") return;
  const msg = e.message !== undefined ? e.message : message;
  const ln = e.lineNumber !== undefined ? e.lineNumber : line;
  const src = String((e.sourceId !== undefined ? e.sourceId : source) || "").split("/").pop();
  log("warning", `Страница окна: ${msg} (${src}:${ln})`);
}

function ours(url) {
  if (isFailPage(url)) return true;
  try { return cfg.url && new URL(url).origin === new URL(cfg.url).origin; } catch { return false; }
}
function isFailPage(url) { return String(url || "").startsWith("file:") && String(url).includes("fail.html"); }
function outside(url) {
  if (/^(https?:|mailto:)/i.test(String(url || ""))) send({ ev: "open_url", url: String(url) });
}

// ---------------------------------------------------------------- загрузка и сбой
function reload(m) {                       // программа: «Повторить» (сервер мог запуститься заново — новый адрес)
  if (m && typeof m.url === "string") { cfg.url = m.url; cfg.why = m.why || ""; }
  load();
}

function load() {
  clearTimeout(readyTimer);
  loadGen += 1;
  if (!cfg.url) { fail(cfg.why || "сервер окна не запустился (порты 8791–8799 заняты?)."); return; }
  win.loadURL(cfg.url).catch(() => {});   // ошибка — в did-fail-load
}

function onLoaded() {
  if (isFailPage(win.webContents.getURL())) return;
  send({ ev: "loaded" });
  const until = Date.now() + READY_WAIT_MS;
  const gen = loadGen;                    // страницу перезагрузили или показали сбой — эта проверка уже не нужна
  const check = async () => {
    let ok = false;
    try { ok = await win.webContents.executeJavaScript("window.__ready === true", true); } catch { ok = false; }
    if (gen !== loadGen) return;
    if (ok) { send({ ev: "page_ready" }); return; }
    if (Date.now() > until) { fail("страница окна не запустилась."); return; }
    readyTimer = setTimeout(check, 200);
  };
  readyTimer = setTimeout(check, 100);
}

function fail(why, detail) {
  clearTimeout(readyTimer);
  loadGen += 1;
  send({ ev: "failed", why, detail: detail || "" });
  win.loadFile(path.join(__dirname, "fail.html"), { query: { text: `${FAIL_PREFIX}: ${why}`, dark: cfg.dark === false ? "0" : "1" } })
    .catch(() => {});
  readyToShow = true;
  if (!shownOnce) firstShow();            // уже показанное окно (и свёрнутое на время набора) остаётся как было
}

// ---------------------------------------------------------------- видно / свёрнуто / развёрнуто
function state() {
  if (HIDDEN) return { ...fake };
  return { visible: win.isVisible(), minimized: win.isMinimized(), maximized: win.isMaximized(), focused: win.isFocused() };
}
function report() { send({ ev: "state", ...state(), compact, top }); }
const isMax = () => {
  if (HIDDEN) return fake.maximized;
  return win.isMinimized() || !win.isVisible() ? lastMax : win.isMaximized();
};
const normalBounds = () => (!HIDDEN && (win.isMaximized() || win.isMinimized()) ? win.getNormalBounds() : win.getBounds());

/** Страница готова (или сбой) — показать, как просила программа. */
function firstShow() {
  if (!wantShow || HIDDEN || shownOnce) return;
  if (wantShow === "inactive") {
    win.showInactive();
    if (!compact && bigMax) win.maximize();
    shownOnce = true;
    return;
  }
  reveal();
}

function reveal() {
  if (HIDDEN) return;
  if (win.isMinimized()) win.restore();
  else if (!win.isVisible()) {
    if (!shownOnce && !compact && bigMax) win.maximize();
    else win.show();
  }
  shownOnce = true;
  win.moveTop();
  win.focus();
}

function show() {
  wantShow = "focus";
  if (HIDDEN) {
    Object.assign(fake, { visible: true, minimized: false });
    if (!shownOnce && !compact && bigMax) fake.maximized = true;
    shownOnce = true;
    report();
    return;
  }
  if (readyToShow) reveal();
}
function hide() {
  wantShow = "";
  if (HIDDEN) { Object.assign(fake, { visible: false, focused: false }); report(); return; }
  win.hide();
}
function min() {
  if (HIDDEN) { Object.assign(fake, { minimized: true, focused: false }); report(); return; }
  win.minimize();
}
function max() {
  wantShow = "focus";
  if (HIDDEN) { Object.assign(fake, { visible: true, minimized: false, maximized: true }); report(); return; }
  win.maximize();
  shownOnce = true;
}
function restore() {                  // как showNormal у Qt: не свёрнуто, не развёрнуто, видно
  wantShow = "focus";
  if (HIDDEN) { Object.assign(fake, { visible: true, minimized: false, maximized: false }); report(); return; }
  if (win.isMinimized()) win.restore();
  if (win.isMaximized()) win.unmaximize();
  if (!win.isVisible()) win.show();
  shownOnce = true;
}
function toggleMax() {
  if (isMax()) {
    if (HIDDEN) { fake.maximized = false; report(); } else win.unmaximize();
  } else max();
}
function setTop(m) { top = !!m.on; win.setAlwaysOnTop(top); report(); }
function title(m) { win.setTitle(String(m.title || "AutoPrintCode")); }
function theme(m) {
  cfg.bg = m.bg || cfg.bg;
  cfg.dark = m.dark !== false;
  nativeTheme.themeSource = cfg.dark ? "dark" : "light";
  win.setBackgroundColor(cfg.bg);
}

// ---------------------------------------------------------------- места окна, маленький режим
function reportGeometry() {
  clearTimeout(geoTimer);
  if (!win) return;
  const b = compact ? big : normalBounds();
  const mx = compact ? bigMax : isMax();
  const s = compact ? normalBounds() : small;
  send({ ev: "geometry", big: G.toSaved(b, { max: !!mx }), small: G.toSaved(s) });
}

function setCompact(m) {
  const on = !!m.on;
  if (on === compact) { report(); return; }
  if (on) {
    big = normalBounds();
    bigMax = isMax();
    if (!HIDDEN && win.isMinimized()) win.restore();     // маленький режим включают, чтобы его видеть
    if (bigMax) { if (HIDDEN) fake.maximized = false; else win.unmaximize(); }
    compact = true;
    win.setMaximizable(false);
    win.setMinimumSize(G.COMPACT_MIN.width, G.COMPACT_MIN.height);
    win.setBounds(small || G.defaultCompact(workFor(big)));
  } else {
    if (!HIDDEN && win.isMinimized()) win.restore();
    small = normalBounds();
    compact = false;
    win.setMaximizable(true);
    win.setMinimumSize(G.BIG_MIN.width, G.BIG_MIN.height);
    win.setBounds(big);
    if (bigMax) { if (HIDDEN) fake.maximized = true; else win.maximize(); }
  }
  reportGeometry();
  report();
}

function compactSize(m) {
  if (!compact) return;
  const w = Number(m.w), h = Number(m.h), k = Number(m.k) || 1;
  if (!(w >= 100 && w <= 4000 && h >= 50 && h <= 3000 && k >= 0.5 && k <= 3)) return;
  const cur = win.getBounds();
  win.setBounds(G.compactResize(cur, w, h, k, workFor(cur)));
  reportGeometry();
}

// ---------------------------------------------------------------- выход
function quit() {
  quitting = true;
  try { if (win) reportGeometry(); } catch { /* окно уже закрыто */ }
  setTimeout(() => app.exit(0), 50);       // ответы и места окна успевают уйти программе
}

// ---------------------------------------------------------------- печать, окна выбора файлов, проверки
function js(m) { return win.webContents.executeJavaScript(String(m.code || ""), true); }

async function pdf(m) {
  // поля листа Chromium закрашивает фоном окна: на время печати он белый (в тёмной теме была бы чёрная рамка)
  win.setBackgroundColor("#FFFFFF");
  try {
    const data = await win.webContents.printToPDF({
      pageSize: "A4", landscape: false, printBackground: true,
      margins: { top: MM12, bottom: MM12, left: MM12, right: MM12 },
    });
    fs.writeFileSync(String(m.path), data);
    return true;
  } finally {
    win.setBackgroundColor(cfg.bg || "#161A22");
  }
}

function print() {
  if (HIDDEN) return false;
  return new Promise((resolve) => {
    win.setBackgroundColor("#FFFFFF");
    win.webContents.print({ silent: false, printBackground: true }, (ok, reason) => {
      win.setBackgroundColor(cfg.bg || "#161A22");
      if (!ok && reason && reason !== "cancelled") log("warning", `Печать не удалась: ${reason}`);
      resolve(!!ok);
    });
  });
}

const parentFor = () => (win && !HIDDEN && win.isVisible() && !win.isMinimized() ? win : null);

async function openDialog(m) {
  if (HIDDEN) return [];
  const props = ["openFile"];
  if (m.multi) props.push("multiSelections");
  const opts = { title: m.title || undefined, defaultPath: m.dir || undefined, filters: m.filters || [], properties: props };
  const p = parentFor();
  const r = p ? await dialog.showOpenDialog(p, opts) : await dialog.showOpenDialog(opts);
  return r.canceled ? [] : r.filePaths;
}

async function saveDialog(m) {
  if (HIDDEN) return "";
  const opts = { title: m.title || undefined, defaultPath: m.path || undefined, filters: m.filters || [] };
  const p = parentFor();
  const r = p ? await dialog.showSaveDialog(p, opts) : await dialog.showSaveDialog(opts);
  return r.canceled ? "" : (r.filePath || "");
}

function devtools() { win.webContents.openDevTools({ mode: "detach" }); }

/** Проверки (только hidden): «бросить» на окно файлы или ссылку — как из Проводника или браузера, без мыши. */
async function testDrop(m) {
  if (!HIDDEN) throw new Error("только в проверках");
  const d = win.webContents.debugger;
  if (!d.isAttached()) d.attach("1.3");
  const data = { items: m.items || [], files: m.files || [], dragOperationsMask: 1 };
  for (const type of ["dragEnter", "dragOver", "drop"]) {
    await d.sendCommand("Input.dispatchDragEvent", { type, x: m.x || 400, y: m.y || 300, data });
  }
  return true;
}

// ---------------------------------------------------------------- от страницы (preload.js)
ipcMain.on("shell", (_e, m) => {
  if (!m || typeof m !== "object") return;
  if (m.op === "retry") send({ ev: "retry" });    // программа проверит сервер и пришлёт адрес (op reload)
  else if (m.op === "open_log") send({ ev: "open_log" });
  else if (m.op === "drop" && Array.isArray(m.paths)) {
    const paths = m.paths.map(String).filter(Boolean).slice(0, 50);
    if (paths.length) send({ ev: "drop", paths });
  }
});
