// AutoPrintCode — локальный помощник: страница в браузере + печать в любое окно Windows.
//
//   node server/main.ts            — помощник и страница http://127.0.0.1:8790 (откроется сама)
//   node server/main.ts --dev      — для разработки страницы вместе с «npm run dev:client» (Vite)
//
// Безопасность: слушаем только 127.0.0.1; WebSocket принимает лишь страницы с нашего адреса
// (проверка Origin и Host) — иначе любой открытый сайт мог бы подключиться и «печатать» вашими руками.
import { execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { type WebSocket, WebSocketServer } from "ws";
import {
  blockTitle, type ClientMsg, codeBlocks, codeNumber, type EngineStatus, HOTKEYS, mergeSettings, navBlocks,
  type ServerMsg, type Settings, type Template, templateFrom,
} from "../shared/model.ts";
import { typingText } from "../shared/textprint.ts";
import { Engine } from "./engine.ts";
import { InputHooks } from "./input.ts";
import { log, LOG_FILE } from "./log.ts";
import { DATA_DIR, Store, WEB_DIR } from "./store.ts";
import * as w from "./win32.ts";

const PORT = Number(process.env.AUTOPRINT_PORT || 8790);
const DEV = process.argv.includes("--dev");
const NO_OPEN = DEV || process.argv.includes("--no-open");
const VERSION = JSON.parse(fs.readFileSync(path.join(WEB_DIR, "package.json"), "utf-8")).version as string;
// заголовок страницы начинается с этой метки — так помощник узнаёт окно браузера со страницей
export const OWN_TITLE_MARK = "⌨ AutoPrintCode";
const DIST = path.join(WEB_DIR, "dist");
const SOUNDS = path.resolve(WEB_DIR, "..", "autoprint", "sounds");
const URL_SELF = `http://127.0.0.1:${PORT}`;
const ALLOWED_ORIGINS = new Set([URL_SELF, `http://localhost:${PORT}`,
  ...(DEV ? ["http://localhost:5173", "http://127.0.0.1:5173"] : [])]);
const ALLOWED_HOSTS = new Set([`127.0.0.1:${PORT}`, `localhost:${PORT}`]);

// помощник работает без окна — непредвиденная ошибка должна остаться хотя бы в журнале
process.on("uncaughtException", (e) => {
  log("error", `Непредвиденная ошибка: ${e.stack ?? e}`);
  hardExit();
});

/** Немедленный выход. process.exit ждал бы поток хоткеев, заблокированный в GetMessageW. */
function hardExit(): never {
  process.kill(process.pid);
  throw new Error("unreachable");
}
process.on("unhandledRejection", (e) => log("error", `Необработанное исключение: ${(e as Error)?.stack ?? e}`));

if (process.platform !== "win32") {
  console.error("Помощник AutoPrintCode работает только в Windows (использует WinAPI SendInput).");
  process.exit(1);
}

// ---------------------------------------------------------------- состояние

const store = new Store();
const s = store.settings;
// движок и хоткеи запускаются только после того, как помощник занял порт (startServices):
// второй экземпляр не должен трогать хоткеи — он лишь открывает страницу и выходит
let engine!: Engine;
let input!: InputHooks;
const clients = new Set<WebSocket>();
let hotkeysFailed = "";
type Job = { tid: string; bid: string; base: number; text: string };
let job: Job | null = null;

function send(ws: WebSocket, msg: ServerMsg): void {
  if (ws.readyState === ws.OPEN) ws.send(JSON.stringify(msg));
}

function broadcast(msg: ServerMsg, except?: WebSocket): void {
  const data = JSON.stringify(msg);
  for (const ws of clients) if (ws !== except && ws.readyState === ws.OPEN) ws.send(data);
}

function engineStatus(): EngineStatus {
  return {
    state: engine.state, pos: engine.pos, total: engine.total, countdown: engine.countdown,
    job: job ? { tid: job.tid, bid: job.bid, base: job.base } : null,
  };
}

const notify = (text: string, level: "info" | "warn" = "info") => broadcast({ t: "notify", text, level });

let hotkeysPaused = false;

function applySettings(): void {
  engine.setSettings(s);
  input.setBindings(hotkeysPaused ? {} : Object.fromEntries(HOTKEYS.map(([k]) => [k, String(s[k] ?? "")])));
}

// ---------------------------------------------------------------- команды (как в главном окне Python-версии)

function armed(): { t: Template; bid: string } | null {
  const t = store.get(s.current_tab);
  if (!t || !t.active_block || !t.blocks.some((b) => b.id === t.active_block)) return null;
  return { t, bid: t.active_block };
}

function jobForArmed(): Job | null {
  const a = armed();
  if (!a) return null;
  const block = a.t.blocks.find((b) => b.id === a.bid)!;
  const [text, base] = typingText(a.t, block, s);
  if (!text.trim()) return null;
  return { tid: a.t.id, bid: block.id, base, text };
}

const sameJob = (a: Job | null) => !!(a && job && a.tid === job.tid && a.bid === job.bid && a.base === job.base && a.text === job.text);

function loadJob(j: Job): void {
  job = j;
  engine.load(j.text);
}

function invalidateJobIfIdle(): void {
  if (engine.state === "idle" || engine.state === "finished") job = null;
}

function startParams(fromButton: boolean, countdown?: number): [number, number] {
  if (fromButton) {
    if (s.minimize_on_button_start) {
      // кнопка нажата на странице — сворачиваем окно браузера, фокус вернётся в прошлое окно
      const fg = w.foregroundWindow();
      if (w.windowTitle(fg).includes(OWN_TITLE_MARK)) w.minimizeWindow(fg);
    }
    return [0, countdown ?? s.button_countdown_s];
  }
  return [s.hotkey_start_delay_ms / 1000, countdown ?? 0];
}

function cmdToggle(fromButton = false): void {
  const st = engine.state;
  if (st === "running" || st === "countdown") return engine.pause();
  const j = jobForArmed();
  if (!j) return notify("Нечего печатать: выберите (щёлкните) непустой блок кода или текста.", "warn");
  if (st === "paused" && sameJob(j)) return engine.resume(...startParams(fromButton));
  if (!sameJob(j) || st === "finished" || st === "paused") {
    if (st === "paused") notify("Образец или выделение изменились — печать начнётся с начала.");
    loadJob(j);
  }
  engine.start(...startParams(fromButton));
}

function cmdRestart(fromButton = false): void {
  const j = jobForArmed();
  if (!j) return notify("Нечего печатать: выберите (щёлкните) непустой блок кода или текста.", "warn");
  loadJob(j);
  engine.restart(...startParams(fromButton));
}

function cmdStop(): void {
  engine.stop();
  job = null;
}

function cmdBlock(d: number): void {
  const t = store.get(s.current_tab);
  if (!t) return;
  const ids = navBlocks(t).map((b) => b.id);
  if (!ids.length) return;
  const i = ids.indexOf(t.active_block);
  const j = Math.max(0, Math.min(ids.length - 1, i + d));
  if (engine.busy) cmdStop();
  t.active_block = ids[j];
  store.put(t);
  broadcast({ t: "template", template: t });
  broadcast({ t: "focusBlock", tid: t.id, bid: ids[j] });
  const b = t.blocks.find((x) => x.id === ids[j])!;
  const n = codeNumber(t, b);
  notify(`Активный блок: ${blockTitle(b, n)}${n ? ` (${n} из ${codeBlocks(t).length})` : ""}`);
}

function cmdNextTab(d: number): void {
  const tabs = s.open_tabs.filter((id) => store.get(id));
  if (!tabs.length) return;
  if (engine.state === "running" || engine.state === "countdown") engine.pause();
  const i = tabs.indexOf(s.current_tab);
  s.current_tab = tabs[(i + d + tabs.length) % tabs.length];
  store.saveSettings();
  broadcast({ t: "settings", settings: s });
  notify(`Образец: ${store.get(s.current_tab)!.title}`);
}

function startServices(): void {
  engine = new Engine(s, OWN_TITLE_MARK);
  input = new InputHooks();

  input.on("hotkey", (action) => {
    ({
      hotkey_toggle: () => cmdToggle(),
      hotkey_restart: () => cmdRestart(),
      hotkey_stop: () => cmdStop(),
      hotkey_next_block: () => cmdBlock(+1),
      hotkey_prev_block: () => cmdBlock(-1),
      hotkey_next_tab: () => cmdNextTab(+1),
    } as Record<string, () => void>)[action]?.();
  });
  input.on("failed", (text) => {
    hotkeysFailed = text;
    log("warn", `Не удалось занять хоткеи: ${text}`);
    notify(`Не удалось занять хоткеи: ${text} (заняты другой программой?). Смените их в настройках.`, "warn");
  });
  input.on("tripped", (kind) => {
    if (engine.state === "running") {
      engine.pause(kind === "key" ? "нажата клавиша" : "клик мышью");
      notify(kind === "key" ? "Пауза: вы нажали клавишу" : "Пауза: вы кликнули мышью");
    }
  });

  engine.on("event", (ev) => {
    switch (ev.e) {
      case "state":
        if (ev.state === "running" && s.guard_enabled) input.arm();
        else input.disarm();
        broadcast({ t: "engine", engine: engineStatus() });
        break;
      case "progress":
      case "countdown":
        broadcast({ t: "engine", engine: engineStatus() });
        break;
      case "sound":
        if (s.sound_enabled) broadcast({ t: "sound", kind: ev.kind });
        break;
      case "message":
        notify(ev.text, "warn");
        break;
      case "log":
        log(ev.level, ev.text);
        break;
      case "finished":
        notify("Набор завершён.");
        if (s.auto_advance && job && job.tid === s.current_tab) {
          const t = store.get(job.tid);
          const ids = t ? navBlocks(t).map((b) => b.id) : [];
          const i = ids.indexOf(job.bid);
          if (i >= 0 && i + 1 < ids.length) setTimeout(() => cmdBlock(+1), 400);
        }
        break;
    }
  });
}

// ---------------------------------------------------------------- сообщения страницы

function onClient(ws: WebSocket, msg: ClientMsg): void {
  switch (msg.t) {
    case "saveTemplate": {
      const t = templateFrom(msg.template as unknown as Record<string, unknown>);
      store.put(t);
      broadcast({ t: "template", template: t }, ws);
      break;
    }
    case "deleteTemplate":
      store.remove(msg.id);
      if (job?.tid === msg.id) cmdStop();
      broadcast({ t: "templateDeleted", id: msg.id }, ws);
      break;
    case "settings": {
      const before = JSON.stringify(s);
      Object.assign(s, mergeSettings({ ...s, ...msg.settings }));
      if (JSON.stringify(s) === before) break;
      store.saveSettings();
      applySettings();
      invalidateJobIfIdle();
      broadcast({ t: "settings", settings: s }, ws);
      break;
    }
    case "cmd":
      if (msg.cmd === "toggle") cmdToggle(msg.fromButton);
      else if (msg.cmd === "restart") cmdRestart(msg.fromButton);
      else cmdStop();
      break;
    case "block":
      cmdBlock(msg.d);
      break;
    case "shutdown":
      log("info", "Помощник выключен со страницы");
      void shutdown();
      break;
    case "autostart":
      setAutostart(msg.on);
      broadcast({ t: "autostart", on: getAutostart() });
      break;
    case "pauseHotkeys":
      hotkeysPaused = msg.on;
      applySettings();
      break;
  }
}

// ---------------------------------------------------------------- HTTP: страница и звуки

const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml",
  ".png": "image/png", ".ico": "image/x-icon", ".wav": "audio/wav", ".json": "application/json", ".woff2": "font/woff2",
  ".webmanifest": "application/manifest+json",
};

function serveFile(res: http.ServerResponse, root: string, rel: string): boolean {
  const file = path.resolve(root, "." + path.posix.normalize("/" + rel));
  if (!file.startsWith(root + path.sep) && file !== root) return false;
  let st: fs.Stats;
  try {
    st = fs.statSync(file);
  } catch {
    return false;
  }
  if (!st.isFile()) return false;
  res.writeHead(200, {
    "Content-Type": MIME[path.extname(file)] ?? "application/octet-stream",
    "Cache-Control": rel.startsWith("assets/") || root === SOUNDS ? "public, max-age=31536000, immutable" : "no-cache",
    "X-Content-Type-Options": "nosniff",
  });
  fs.createReadStream(file).pipe(res);
  return true;
}

const server = http.createServer((req, res) => {
  if (!ALLOWED_HOSTS.has(req.headers.host ?? "")) {   // защита от DNS rebinding
    res.writeHead(403).end("Forbidden");
    return;
  }
  const url = new URL(req.url ?? "/", URL_SELF);
  const p = decodeURIComponent(url.pathname);
  if (p.startsWith("/sounds/") && serveFile(res, SOUNDS, p.slice("/sounds/".length))) return;
  if (p === "/api/log") {
    res.writeHead(200, { "Content-Type": "text/plain; charset=utf-8" });
    fs.createReadStream(LOG_FILE).on("error", () => res.end("Журнал пуст.")).pipe(res);
    return;
  }
  if (!DEV && (serveFile(res, DIST, p.slice(1)) || serveFile(res, DIST, "index.html"))) return;
  res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" })
    .end(DEV ? "Режим разработки: страница — на http://localhost:5173" : "Страница не собрана: выполните npm run build");
});

const wss = new WebSocketServer({
  server, path: "/ws", maxPayload: 32 * 1024 * 1024,
  verifyClient: ({ origin, req }: { origin: string; req: http.IncomingMessage }) => ALLOWED_ORIGINS.has(origin) && (DEV || ALLOWED_HOSTS.has(req.headers.host ?? "")),
});

// ws повторяет ошибки HTTP-сервера (например, «порт занят») от своего имени — их обрабатывает server.on("error")
wss.on("error", () => {});

wss.on("connection", (ws) => {
  clients.add(ws);
  send(ws, { t: "hello", version: VERSION, settings: s, templates: store.templates, engine: engineStatus(), hotkeysFailed,
    autostart: getAutostart() });
  ws.on("message", (data) => {
    try {
      onClient(ws, JSON.parse(String(data)) as ClientMsg);
    } catch (e) {
      log("error", `Ошибка обработки сообщения страницы: ${(e as Error).stack}`);
    }
  });
  ws.on("close", () => {
    clients.delete(ws);
    if (hotkeysPaused) {   // страница закрылась с открытыми настройками — вернуть хоткеи
      hotkeysPaused = false;
      applySettings();
    }
  });
});

// ---------------------------------------------------------------- запуск вместе с Windows
// Помощник стартует при входе в систему без окна (conhost --headless) — как Python-версия в трее.
const RUN_KEY = String.raw`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`;
const RUN_VALUE = "AutoPrintCode";

function autostartCommand(): string {
  const conhost = path.join(process.env.SystemRoot ?? String.raw`C:\Windows`, "System32", "conhost.exe");
  return `"${conhost}" --headless "${process.execPath}" "${path.join(WEB_DIR, "server", "main.ts")}" --no-open`;
}

function getAutostart(): boolean {
  try {
    const out = execFileSync("reg", ["query", RUN_KEY, "/v", RUN_VALUE], { windowsHide: true, encoding: "utf-8", stdio: "pipe" });
    return out.includes(autostartCommand());
  } catch {
    return false;
  }
}

function setAutostart(on: boolean): void {
  const args = on
    ? ["add", RUN_KEY, "/v", RUN_VALUE, "/t", "REG_SZ", "/d", autostartCommand(), "/f"]
    : ["delete", RUN_KEY, "/v", RUN_VALUE, "/f"];
  try {
    execFileSync("reg", args, { windowsHide: true, stdio: "pipe" });
    log("info", on ? `Автозапуск включён: ${autostartCommand()}` : "Автозапуск выключен");
  } catch (e) {
    if (on) notify(`Не удалось включить автозапуск: ${(e as Error).message}`, "warn");
  }
}

/** Ярлык установленного приложения (страница, установленная из Chrome/Edge) в меню «Пуск». */
function installedAppShortcut(): string | null {
  const programs = path.join(process.env.APPDATA ?? "", "Microsoft", "Windows", "Start Menu", "Programs");
  for (const dir of [programs, path.join(programs, "Chrome Apps"), path.join(programs, "Microsoft Edge Apps")]) {
    const lnk = path.join(dir, "AutoPrintCode.lnk");
    try {
      // ярлык веб-приложения запускает браузер с --app-id — так не спутать с чужим ярлыком
      if (fs.readFileSync(lnk).includes(Buffer.from("app-id", "utf16le"))) return lnk;
    } catch {
      // нет ярлыка
    }
  }
  return null;
}

/** Открыть страницу: установленным приложением (своё окно и значок), иначе — вкладкой браузера. */
function openBrowser(): void {
  const target = installedAppShortcut() ?? URL_SELF;
  // explorer.exe открывает ссылку или ярлык как двойной щелчок — работает и из помощника без окна
  // (cmd /c start со скрытым окном из процесса без консоли страницу не открывал)
  log("info", `Открываю ${target}`);
  const p = spawn("explorer.exe", [target], { detached: true, stdio: "ignore" });
  p.on("error", (e) => log("error", `Не удалось открыть страницу: ${e.message}`));
  p.unref();
}

server.on("error", (e: NodeJS.ErrnoException) => {
  if (e.code === "EADDRINUSE") {
    log("info", "Помощник уже запущен — только открываю страницу");
    if (!NO_OPEN) openBrowser();
    setTimeout(() => process.exit(0), 500);   // дать explorer.exe стартовать (службы ещё не запущены)
    return;
  }
  throw e;
});

server.listen(PORT, "127.0.0.1", () => {
  startServices();
  applySettings();
  log("info", `==== AutoPrintCode web ${VERSION} · Node ${process.version} · данные ${DATA_DIR}` +
    (store.adoptedFrom ? ` · образцы взяты из ${store.adoptedFrom}` : ""));
  console.log(`\n  AutoPrintCode: ${URL_SELF}\n  Хоткеи: ${s.hotkey_toggle} — старт/пауза. Закрыть помощника — Ctrl+C.\n`);
  if (!NO_OPEN) openBrowser();
});

async function shutdown(): Promise<void> {
  wss.close();
  store.saveTemplatesNow();
  await Promise.allSettled([engine?.close(), input?.close()]);
  process.exit(0);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
