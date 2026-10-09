// Движок печати — отдельный поток (порт TypingEngine из typer.py).
//
// Поток никогда не отдаёт управление циклу событий: спит через Atomics.wait (точно, с таймером 1 мс)
// и забирает команды синхронно через receiveMessageOnPort. Главный поток после каждой команды
// делает Atomics.notify — поэтому пауза и стоп срабатывают мгновенно, даже посреди долгой задержки.
//
// Профиль IDE компенсирует «умные» редакторы (VS Code/Monaco, CodeMirror, Jupyter):
//   * перед Enter и перед закрывающими ) ] } " ' ` — Shift+End, пробел, Backspace: стирает всё, что
//     редактор сам дописал справа (автоскобки, автокавычки), и закрывает подсказки;
//   * после Enter — Shift+Home, пробел, Backspace: убирает автоотступ, затем отступ печатается как в образце.
import { type MessagePort, receiveMessageOnPort, workerData } from "node:worker_threads";
import { type EngineState, PROFILE_IDE, type Settings } from "../shared/model.ts";
import { buildUnits, delayAfter, gapSeconds, normalize, type Unit } from "./units.ts";
import * as win32 from "./win32.ts";

// Перед этими символами в профиле IDE очищается правая часть строки (там может быть только то,
// что редактор дописал сам). На «перепечатывание» автоскобок не полагаемся: CodeMirror 6 ломает тройные кавычки.
const CLEAR_BEFORE = new Set(")]}\"'`");

export type EngineCmd =
  | { c: "settings"; settings: Settings }
  | { c: "load"; text: string }
  | { c: "start" | "resume" | "restart"; delay: number; countdown: number }
  | { c: "pause"; reason: string }
  | { c: "stop" };

export type EngineEvent =
  | { e: "state"; state: EngineState }
  | { e: "progress"; pos: number; total: number }
  | { e: "countdown"; n: number }
  | { e: "message"; text: string }
  | { e: "sound"; kind: "key" | "space" | "enter" }
  | { e: "finished" }
  | { e: "preparing"; on: boolean }   // отсчёт, задержка хоткея, ожидание отпускания Ctrl/Alt/Shift
  | { e: "log"; level: "info" | "warn" | "error"; text: string };

const { port, ctrl: ctrlBuf, ownTitleMark, requireTitle, dryRun } = workerData as {
  port: MessagePort; ctrl: SharedArrayBuffer; ownTitleMark: string; requireTitle?: string; dryRun?: boolean;
};
// «сухой» режим для тестов: всё как при печати, но ни одного нажатия и ни одного обращения к окнам
const w: typeof win32 = dryRun ? {
  ...win32, typeChar() {}, tap() {}, modifiersDown: () => false, foregroundWindow: () => 1, windowTitle: () => "dry run",
  describeWindow: () => "dry run", selfElevated: () => false, windowElevated: () => false,
} : win32;
const ctrl = new Int32Array(ctrlBuf);

let s: Settings = (workerData as { settings: Settings }).settings;
let state: EngineState = "idle";
let text = "";
let units: Unit[] = [];
let pos = 0;
let gen = 0;            // меняется при отмене (load/stop/restart) — текущий прогон должен завершиться
let run = false;        // как threading.Event _run: false — пауза
let inRun = false;      // идёт ли прогон (runJob)
let preparing = false;  // идёт подготовка к печати (её тоже можно поставить на паузу)
let pendingStart: { delay: number; countdown: number } | null = null;
let resumeParams = { delay: 0, countdown: 0 };

const emit = (ev: EngineEvent) => port.postMessage(ev);
const log = (text: string, level: "info" | "warn" | "error" = "info") => emit({ e: "log", level, text });

function setState(st: EngineState): void {
  if (state !== st) {
    state = st;
    emit({ e: "state", state: st });
  }
}

// ------------------------------------------------------------ команды

function cancel(): void {
  gen++;
  run = false;
  pendingStart = null;
}

function start(delay: number, countdown: number): void {
  if (!units.length) {
    emit({ e: "message", text: "Нечего печатать: выберите блок кода с текстом." });
    return;
  }
  if (state === "paused") return resume(delay, countdown);
  if (state === "running" || state === "countdown") return;
  if (state === "finished") pos = 0;
  cancel();
  run = true;
  pendingStart = { delay, countdown };
}

function resume(delay: number, countdown: number): void {
  if (state !== "paused") return;
  if (!inRun) {
    setState("idle");
    start(delay, countdown);
    return;
  }
  resumeParams = { delay, countdown };
  run = true;
}

function handle(cmd: EngineCmd): void {
  switch (cmd.c) {
    case "settings":
      s = cmd.settings;
      // пересобрать единицы после смены настроек (только если печать не идёт)
      if ((state === "idle" || state === "finished") && text) {
        units = buildUnits(text, s);
        pos = 0;
      }
      break;
    case "load":
      cancel();
      text = normalize(cmd.text);
      units = buildUnits(text, s);
      pos = 0;
      setState("idle");
      emit({ e: "progress", pos: 0, total: text.length });
      break;
    case "start":
      start(cmd.delay, cmd.countdown);
      break;
    case "resume":
      resume(cmd.delay, cmd.countdown);
      break;
    case "pause":
      if (state === "running" || state === "countdown" || (preparing && run)) {
        run = false;
        setState("paused");
        log(`Пауза (${cmd.reason}) на ${pos}/${units.length}`);
      }
      break;
    case "restart":
      cancel();
      pos = 0;
      setState("idle");
      emit({ e: "progress", pos: 0, total: text.length });
      start(cmd.delay, cmd.countdown);
      break;
    case "stop":
      if (state !== "idle") log(`Стоп на ${pos}/${units.length}`);
      cancel();
      pos = 0;
      setState("idle");
      emit({ e: "progress", pos: 0, total: text.length });
      break;
  }
}

let received = 0;   // сколько команд получено; ctrl[0] — сколько отправлено

function drain(): void {
  for (let m = receiveMessageOnPort(port); m; m = receiveMessageOnPort(port)) {
    received++;
    handle(m.message as EngineCmd);
  }
}

/** Ждать до timeoutMs или до новой команды. */
function waitSignal(timeoutMs: number): void {
  const before = received;
  drain();
  if (received !== before) return;   // пришла команда — сначала её последствия, спать потом
  const sent = Atomics.load(ctrl, 0);
  if (received < sent) {
    // счётчик уже увеличен, а сама команда ещё в пути — подождать миллисекунду, не засыпая надолго
    Atomics.wait(ctrl, 1, 0, 1);
  } else {
    Atomics.wait(ctrl, 0, sent, timeoutMs);
  }
  drain();
}

const now = () => performance.now() / 1000;

/** Сон, прерываемый остановкой. false — печать отменена. Команды (пауза) обрабатываются во время сна. */
function sleep(myGen: number, seconds: number): boolean {
  const end = now() + seconds;
  for (;;) {
    drain();
    if (gen !== myGen) return false;
    const left = end - now();
    if (left <= 0) return true;
    waitSignal(Math.min(left * 1000, 50));
  }
}

/** Короткая пауза между служебными нажатиями (без проверки команд — это доли секунды). */
function gapSleep(): void {
  Atomics.wait(ctrl, 1, 0, gapSeconds(s) * 1000);
}

/** Обдумывание: обрывается паузой. false — печать отменена. */
function think(myGen: number, seconds: number): boolean {
  const end = now() + seconds;
  while (run) {
    drain();
    if (gen !== myGen) return false;
    const left = end - now();
    if (left <= 0) break;
    waitSignal(Math.min(left * 1000, 50));
  }
  return gen === myGen;
}

// ------------------------------------------------------------ печать

/** Ожидание, которое обрывают и пауза, и остановка. false — оборвали. */
function waitRun(myGen: number, seconds: number): boolean {
  return sleep(myGen, seconds) && run;
}

/** Ждёт, пока отпустят Ctrl/Alt/Shift/Win после хоткея (иначе «а» превратится в Ctrl+A).
 *  false — не отпустили за 5 с или ожидание прервали (пауза, стоп). */
function waitModifiersReleased(myGen: number): boolean {
  const deadline = now() + 5;
  while (w.modifiersDown()) {
    if (now() > deadline || !waitRun(myGen, 0.01)) return false;
  }
  return waitRun(myGen, 0.03);
}

const PAUSED = "paused";   // prepare: пока шёл отсчёт или ждали окно, поставили на паузу (или остановили)

/** Отсчёт, ожидание отпускания модификаторов, захват целевого окна.
 *  → hwnd; null — не начато (сообщение показано); PAUSED — пауза или стоп. */
function prepare(myGen: number, delay: number, countdown: number): number | null | typeof PAUSED {
  preparing = true;
  emit({ e: "preparing", on: true });
  try {
    return prepareTarget(myGen, delay, countdown);
  } finally {
    preparing = false;
    emit({ e: "preparing", on: false });
  }
}

function prepareTarget(myGen: number, delay: number, countdown: number): number | null | typeof PAUSED {
  if (countdown > 0) {
    if (!run) return PAUSED;
    setState("countdown");
    for (let n = countdown; n > 0; n--) {
      emit({ e: "countdown", n });
      if (!waitRun(myGen, 1)) {
        emit({ e: "countdown", n: 0 });
        return PAUSED;
      }
    }
    emit({ e: "countdown", n: 0 });
  }
  if (!waitModifiersReleased(myGen)) {
    if (gen !== myGen || !run) return PAUSED;
    log("Не начато: модификаторы удерживаются дольше 5 с", "warn");
    emit({ e: "message", text: "Отпустите Ctrl/Alt/Shift — печать не начата." });
    return null;
  }
  if (delay && !waitRun(myGen, delay)) return PAUSED;
  const hwnd = w.foregroundWindow();
  if (w.windowTitle(hwnd).includes(ownTitleMark)) {
    log("Не начато: в фокусе страница AutoPrintCode");
    emit({ e: "message", text: "Курсор стоит на странице AutoPrintCode. Перейдите в целевое окно и нажмите хоткей ещё раз." });
    return null;
  }
  // только для тестов: печатать лишь в окно с ожидаемым заголовком, иначе — ни одного нажатия
  if (requireTitle && !w.windowTitle(hwnd).includes(requireTitle)) {
    log(`Не начато: в фокусе не тестовое окно, а ${w.describeWindow(hwnd)}`, "warn");
    emit({ e: "message", text: `В фокусе не окно «${requireTitle}» — печать не начата.` });
    return null;
  }
  if (!w.selfElevated() && w.windowElevated(hwnd)) {
    log(`Не начато: окно с правами администратора ${w.describeWindow(hwnd)}`, "warn");
    emit({ e: "message", text: "Окно запущено от имени администратора — Windows не пропустит в него ввод. " +
      "Запустите помощник AutoPrintCode тоже от имени администратора." });
    return null;
  }
  log(`Печать ${pos ? "продолжена" : "начата"} с ${pos}/${units.length} → ${w.describeWindow(hwnd)} · ` +
    `профиль=${s.profile} · ${s.cpm} симв/мин`);
  return hwnd;
}

function runJob(myGen: number, delay: number, countdown: number): void {
  const first = prepare(myGen, delay, countdown);
  if (first === null) {
    if (gen === myGen) {
      setState(pos ? "paused" : "idle");
      run = false;
    }
    return;
  }
  let target = first === PAUSED ? 0 : first;
  // пауза во время подготовки: состояние уже «пауза», цикл ниже дождётся «продолжить»
  if (first !== PAUSED && run) setState("running");
  const total = text.length;
  let thought = -1;   // для какой единицы пауза-обдумывание уже выдержана
  while (gen === myGen && pos < units.length) {
    if (!run || state !== "running") {
      while (!run && gen === myGen) waitSignal(1000);
      if (gen !== myGen) return;
      const next = prepare(myGen, resumeParams.delay, resumeParams.countdown);
      if (next === null) {
        if (gen === myGen) {
          run = false;
          setState("paused");
        }
        continue;
      }
      if (next === PAUSED || !run) continue;
      target = next;
      setState("running");
    }
    const u = units[pos];
    if (u.pause && thought !== pos) {
      // обдумывание прерывается паузой и остановкой; после него заново проверяем окно
      if (!think(myGen, u.pause)) return;
      thought = pos;
      continue;
    }
    if (s.autopause_on_focus_change && w.foregroundWindow() !== target) {
      run = false;
      setState("paused");
      log(`Пауза (сменилось окно → ${w.describeWindow(w.foregroundWindow())}) на ${pos}/${units.length}`);
      emit({ e: "message", text: "Пауза: сменилось активное окно. Вернитесь в нужное окно и продолжите." });
      continue;
    }
    try {
      execute(u);
    } catch (err) {
      log(`Ошибка SendInput на ${pos}/${units.length}: ${err}`, "error");
      run = false;
      setState("paused");
      emit({ e: "message", text: `Ошибка ввода: ${(err as Error).message}` });
      continue;
    }
    pos++;
    emit({ e: "progress", pos: u.srcEnd, total });
    if (!sleep(myGen, delayAfter(u, s))) return;
  }
  if (gen === myGen) {
    setState("finished");
    log(`Набор завершён: ${units.length} единиц`);
    emit({ e: "finished" });
  }
}

function execute(u: Unit): void {
  const ide = s.profile === PROFILE_IDE;
  switch (u.kind) {
    case "char":
      if (ide && CLEAR_BEFORE.has(u.text)) clearRight();
      if ([...u.text].length === 1) w.typeChar(u.text);
      else fast(u.text);
      emit({ e: "sound", kind: u.text === " " ? "space" : "key" });
      break;
    case "fast":
      emit({ e: "sound", kind: "space" });
      fast(u.text);
      break;
    case "tab":
      w.tap(w.VK_TAB);
      emit({ e: "sound", kind: "key" });
      break;
    case "back":
      w.tap(w.VK_BACK);
      emit({ e: "sound", kind: "key" });
      break;
    case "newline":
      if (ide) {
        clearRight();
        if (s.esc_before_enter) {
          w.tap(w.VK_ESCAPE);
          gapSleep();
        }
      }
      w.tap(w.VK_RETURN);
      emit({ e: "sound", kind: "enter" });
      if (ide) {
        gapSleep(); gapSleep();   // дать редактору вставить автоотступ
        w.tap(w.VK_HOME, w.VK_SHIFT);
        gapSleep();
        w.typeChar(" ");
        gapSleep();
        w.tap(w.VK_BACK);
        gapSleep();
      }
      break;
    case "cleanup":
      clearRight();
      break;
  }
}

function clearRight(): void {
  w.tap(w.VK_END, w.VK_SHIFT);
  gapSleep();
  w.typeChar(" ");
  gapSleep();
  w.tap(w.VK_BACK);
  gapSleep();
}

function fast(t: string): void {
  for (const ch of t) {
    w.typeChar(ch);
    gapSleep();
  }
}

// ------------------------------------------------------------ главный цикл потока
for (;;) {
  if (!pendingStart) waitSignal(60_000);   // «сначала» во время прогона уже оставило новый старт
  // TS не видит, что команды внутри waitSignal меняют pendingStart, — читаем явно
  const p = pendingStart as { delay: number; countdown: number } | null;
  if (p) {
    pendingStart = null;
    inRun = true;
    w.highResTimer(true);
    try {
      runJob(gen, p.delay, p.countdown);
    } finally {
      w.highResTimer(false);
      inRun = false;
    }
  }
}
