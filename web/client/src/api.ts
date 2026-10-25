// Связь с помощником (WebSocket) и состояние страницы.
// Помощник — источник истины: образцы, настройки, движок печати. Страница показывает и правит.
import { useSyncExternalStore } from "react";
import type { Block, ClientMsg, EngineStatus, ServerMsg, Settings, Template } from "../../shared/model.ts";
import { sounds } from "./sound.ts";

export interface Toast { id: number; text: string; level: "info" | "warn" }

export interface AppState {
  connected: boolean;
  everConnected: boolean;
  stopped: boolean;            // помощник выключен кнопкой ⏻ — не переподключаться
  autostart: boolean;          // помощник запускается вместе с Windows
  version: string;
  settings: Settings | null;
  templates: Template[];
  engine: EngineStatus;
  toasts: Toast[];
  focus: { tid: string; bid: string; n: number } | null;   // «прокрутить к блоку» (хоткей «следующий блок»)
}

let state: AppState = {
  connected: false,
  everConnected: false,
  stopped: false,
  autostart: false,
  version: "",
  settings: null,
  templates: [],
  engine: { state: "idle", pos: 0, total: 0, countdown: 0, job: null },
  toasts: [],
  focus: null,
};

const listeners = new Set<() => void>();
function set(patch: Partial<AppState>): void {
  state = { ...state, ...patch };
  for (const l of listeners) l();
}

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function useApp<T>(select: (s: AppState) => T): T {
  return useSyncExternalStore(subscribe, () => select(state));
}
export const getState = () => state;

// ---------------------------------------------------------------- уведомления

let toastId = 0;
export function toast(text: string, level: "info" | "warn" = "info"): void {
  const t = { id: ++toastId, text, level };
  set({ toasts: [...state.toasts.slice(-3), t] });
  setTimeout(() => set({ toasts: state.toasts.filter((x) => x.id !== t.id) }), level === "warn" ? 7000 : 4000);
}

// ---------------------------------------------------------------- соединение

let ws: WebSocket | null = null;
let retry = 0;

function connect(): void {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => { retry = 0; };
  ws.onmessage = (ev) => onMessage(JSON.parse(ev.data) as ServerMsg);
  ws.onclose = () => {
    set({ connected: false });
    // после ⏻ всё равно проверяем изредка: помощника могут снова запустить через start.bat
    setTimeout(connect, state.stopped ? 3000 : Math.min(5000, 500 * 2 ** retry++));
  };
}
connect();

function send(msg: ClientMsg): boolean {
  if (ws?.readyState !== WebSocket.OPEN) return false;
  ws.send(JSON.stringify(msg));
  return true;
}

function onMessage(m: ServerMsg): void {
  switch (m.t) {
    case "hello": {
      // правки, которые не дошли до помощника (связь пропадала), важнее его копии — досылаем
      const templates = m.templates.map((t) => pending.get(t.id)?.template ?? t);
      set({ stopped: false, autostart: m.autostart, connected: true, everConnected: true, version: m.version, settings: m.settings, templates, engine: m.engine });
      flushAll();
      sounds.configure(m.settings);
      if (m.hotkeysFailed) toast(`Не удалось занять хоткеи: ${m.hotkeysFailed}. Смените их в настройках.`, "warn");
      break;
    }
    case "template": {
      // своя несохранённая правка того же образца важнее — от помощника берём только активный блок
      // (и в отложенную отправку тоже: иначе она вернула бы помощнику прежний активный блок)
      const local = pending.get(m.template.id);
      const t = local ? { ...local.template, active_block: m.template.active_block } : m.template;
      if (local) local.template = t;
      const exists = state.templates.some((x) => x.id === t.id);
      set({ templates: exists ? state.templates.map((x) => (x.id === t.id ? t : x)) : [...state.templates, t] });
      break;
    }
    case "autostart":
      set({ autostart: m.on });
      break;
    case "templateDeleted":
      set({ templates: state.templates.filter((t) => t.id !== m.id) });
      break;
    case "settings":
      set({ settings: m.settings });
      sounds.configure(m.settings);
      break;
    case "engine":
      set({ engine: m.engine });
      break;
    case "sound":
      sounds.play(m.kind);
      break;
    case "notify":
      toast(m.text, m.level);
      break;
    case "focusBlock":
      set({ focus: { tid: m.tid, bid: m.bid, n: (state.focus?.n ?? 0) + 1 } });
      break;
  }
}

// ---------------------------------------------------------------- действия

const pending = new Map<string, { template: Template; timer: number }>();

/** Правка образца: сразу на странице, помощнику — с небольшой задержкой (набор текста идёт потоком). */
export function updateTemplate(t: Template, delay = 400): void {
  t = { ...t, updated: Date.now() / 1000 };
  set({ templates: state.templates.map((x) => (x.id === t.id ? t : x)) });
  const p = pending.get(t.id);
  if (p) clearTimeout(p.timer);
  const timer = window.setTimeout(() => flushTemplate(t.id), delay);
  pending.set(t.id, { template: t, timer });
}

/** Правка одного блока поверх его последней версии (а не копии из замыкания, которая могла устареть:
 *  редактор кода в одном обновлении сообщает и текст, и выделение). */
export function updateBlock(tid: string, bid: string, patch: Partial<Block>, delay?: number): void {
  const t = state.templates.find((x) => x.id === tid);
  if (!t) return;
  updateTemplate({ ...t, blocks: t.blocks.map((b) => (b.id === bid ? { ...b, ...patch } : b)) }, delay);
}

function flushTemplate(id: string): void {
  const p = pending.get(id);
  if (!p) return;
  clearTimeout(p.timer);
  // нет связи — правка остаётся в очереди и уйдёт после переподключения (hello)
  if (send({ t: "saveTemplate", template: p.template })) pending.delete(id);
}

function flushAll(): void {
  for (const id of [...pending.keys()]) flushTemplate(id);
}

export function addTemplate(t: Template, open = true): void {
  set({ templates: [...state.templates, t] });
  send({ t: "saveTemplate", template: t });
  if (open) openTab(t.id);
}

export function deleteTemplate(id: string): void {
  pending.delete(id);
  set({ templates: state.templates.filter((t) => t.id !== id) });
  send({ t: "deleteTemplate", id });
  const s = state.settings!;
  if (s.open_tabs.includes(id)) closeTab(id);
}

export function updateSettings(patch: Partial<Settings>): void {
  if (!state.settings) return;
  const settings = { ...state.settings, ...patch };
  set({ settings });
  sounds.configure(settings);
  send({ t: "settings", settings: patch });
}

export function openTab(id: string): void {
  const s = state.settings!;
  updateSettings({ open_tabs: s.open_tabs.includes(id) ? s.open_tabs : [...s.open_tabs, id], current_tab: id });
}

/** Перетаскивание вкладки: id встаёт перед вкладкой target (after — после неё). */
export function moveTab(id: string, target: string, after: boolean): void {
  const s = state.settings!;
  if (id === target || !s.open_tabs.includes(id)) return;
  const tabs = s.open_tabs.filter((x) => x !== id);
  const i = tabs.indexOf(target);
  if (i < 0) return;
  tabs.splice(after ? i + 1 : i, 0, id);
  if (tabs.join() !== s.open_tabs.join()) updateSettings({ open_tabs: tabs });
}

export function closeTab(id: string): void {
  const s = state.settings!;
  const i = s.open_tabs.indexOf(id);
  const tabs = s.open_tabs.filter((x) => x !== id);
  const current = s.current_tab === id ? (tabs[Math.min(i, tabs.length - 1)] ?? "") : s.current_tab;
  updateSettings({ open_tabs: tabs, current_tab: current });
}

/** Перед командой печати — отправить несохранённые правки, чтобы помощник печатал то, что на экране. */
export function command(cmd: "toggle" | "restart" | "stop", fromButton = false): void {
  flushAll();
  sounds.unlock();
  send({ t: "cmd", cmd, fromButton });
}

export function setAutostart(on: boolean): void {
  send({ t: "autostart", on });
}

export function shutdownHelper(): void {
  flushAll();
  send({ t: "shutdown" });
  set({ stopped: true });
}

export function pauseHotkeys(on: boolean): void {
  send({ t: "pauseHotkeys", on });
}

export function moveBlock(d: number): void {
  flushAll();
  send({ t: "block", d });
}
