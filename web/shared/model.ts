// Модель данных — тот же формат JSON, что у Python-версии (data/templates.json, data/settings.json),
// поэтому образцы и настройки переносятся между версиями без конвертации.

export const PROFILE_PLAIN = "plain";
export const PROFILE_IDE = "ide";
export const PROFILES: Record<string, string> = {
  [PROFILE_PLAIN]: "Блокнот / простое поле",
  [PROFILE_IDE]: "IDE: VS Code, веб-IDE, Jupyter",
};

export const SOUND_STYLES: Record<string, string> = {
  office: "Обычная офисная клавиатура",
  brown: "Механическая, тактильная (Cherry MX Brown)",
  red: "Механическая, линейная",
  cream: "Механическая, глухая («thock»)",
  blue: "Механическая, щелчковая (Kailh Box Jade)",
};
export const LEGACY_SOUND_STYLES: Record<string, string> = { soft: "office", mechanical: "brown", typewriter: "blue" };

export interface Settings {
  hotkey_toggle: string;
  hotkey_restart: string;
  hotkey_stop: string;
  hotkey_next_block: string;
  hotkey_prev_block: string;
  hotkey_next_tab: string;

  cpm: number;
  jitter: number;
  newline_pause_ms: number;
  punct_pause_ms: number;
  fast_indent: boolean;
  indent_with_tab: boolean;
  key_gap_ms: number;
  tab_width: number;
  selection_whole_lines: boolean;
  strip_comments: boolean;
  human_typing: boolean;
  typo_per_100_words: number;
  think_pause_s: number;

  profile: string;
  esc_before_enter: boolean;

  sound_enabled: boolean;
  sound_volume: number;
  sound_style: string;

  hotkey_start_delay_ms: number;
  button_countdown_s: number;
  minimize_on_button_start: boolean;
  autopause_on_focus_change: boolean;
  guard_enabled: boolean;
  auto_advance: boolean;

  open_tabs: string[];
  current_tab: string;
  [key: string]: unknown;   // поля Python-версии (геометрия окна, обновления) сохраняются как есть
}

export const DEFAULT_SETTINGS: Settings = {
  hotkey_toggle: "Ctrl+F9",
  hotkey_restart: "Ctrl+F10",
  hotkey_stop: "Ctrl+F11",
  hotkey_next_block: "Ctrl+F12",
  hotkey_prev_block: "Ctrl+Shift+F12",
  hotkey_next_tab: "",

  cpm: 320,
  jitter: 35,
  newline_pause_ms: 220,
  punct_pause_ms: 50,
  fast_indent: true,
  indent_with_tab: false,
  key_gap_ms: 30,
  tab_width: 4,
  selection_whole_lines: true,
  strip_comments: false,
  human_typing: false,
  typo_per_100_words: 3,
  think_pause_s: 1.5,

  profile: PROFILE_IDE,
  esc_before_enter: false,

  sound_enabled: true,
  sound_volume: 35,
  sound_style: "office",

  hotkey_start_delay_ms: 150,
  button_countdown_s: 3,
  minimize_on_button_start: true,
  autopause_on_focus_change: true,
  guard_enabled: true,
  auto_advance: false,

  open_tabs: [],
  current_tab: "",
};

export const HOTKEYS: [keyof Settings & string, string][] = [
  ["hotkey_toggle", "Старт / пауза / продолжить"],
  ["hotkey_restart", "Начать сначала"],
  ["hotkey_stop", "Остановить"],
  ["hotkey_next_block", "Следующий блок кода"],
  ["hotkey_prev_block", "Предыдущий блок кода"],
  ["hotkey_next_tab", "Следующая вкладка-образец"],
];

/** Значения из файла поверх умолчаний: неизвестные и неверного типа — по умолчанию. */
export function mergeSettings(raw: Record<string, unknown>): Settings {
  const s: Settings = { ...DEFAULT_SETTINGS, ...raw } as Settings;
  for (const [k, def] of Object.entries(DEFAULT_SETTINGS)) {
    const v = raw[k];
    if (v === undefined) continue;
    const ok = Array.isArray(def) ? Array.isArray(v) : typeof v === typeof def;
    if (!ok) (s as Record<string, unknown>)[k] = def;
  }
  s.sound_style = LEGACY_SOUND_STYLES[s.sound_style] ?? s.sound_style;
  if (!(s.sound_style in SOUND_STYLES)) s.sound_style = DEFAULT_SETTINGS.sound_style;
  return s;
}

export const BLOCK_MARKDOWN = "markdown";
export const BLOCK_CODE = "code";

// Типы Markdown-блоков: ключ → [значок, название, цвет полоски]
export const ROLES: Record<string, [string, string, string]> = {
  text: ["📝", "Текст", "#8b949e"],
  task: ["📋", "Условие", "#3b82f6"],
  explain: ["💡", "Пояснение", "#d29922"],
  hint: ["🔎", "Подсказка", "#a855f7"],
};

export interface Block {
  type: string;          // markdown | code
  text: string;
  lang: string;
  sel: number[];         // [start, end] — выделение в блоке кода
  id: string;
  role: string;
  title: string;
  zoom: number;
  print_as: string;      // как печатать Markdown-блок: markdown | plain | comment (см. textprint.ts)
}

export interface Template {
  title: string;
  blocks: Block[];
  active_block: string;
  id: string;
  updated: number;       // секунды, как time.time() в Python
}

export function newId(): string {
  const a = new Uint8Array(6);
  crypto.getRandomValues(a);
  return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function makeBlock(type: string, text = "", extra: Partial<Block> = {}): Block {
  return { type, text, lang: "python", sel: [], id: newId(), role: "text", title: "", zoom: 100, print_as: "markdown", ...extra };
}

export function makeTemplate(title: string, blocks: Block[] = []): Template {
  return { title, blocks, active_block: "", id: newId(), updated: Date.now() / 1000 };
}

export function blockFrom(d: Record<string, unknown>): Block {
  const b = makeBlock(String(d.type ?? BLOCK_CODE));
  for (const k of Object.keys(b) as (keyof Block)[]) {
    if (d[k] !== undefined) (b as unknown as Record<string, unknown>)[k] = d[k];
  }
  if (!Array.isArray(b.sel)) b.sel = [];
  return b;
}

/** Образец из JSON. Старый формат (до v0.3, «задачи») сливается в одну ленту блоков. */
export function templateFrom(d: Record<string, unknown>): Template {
  let blocks: Block[];
  if (Array.isArray(d.tasks)) {
    const tasks = d.tasks as Record<string, unknown>[];
    blocks = [];
    for (const t of tasks) {
      const tb = ((t.blocks as Record<string, unknown>[]) ?? []).map(blockFrom);
      const title = String(t.title ?? "").trim();
      if (tasks.length > 1 && title && !tb.some((b) => b.type === BLOCK_MARKDOWN && b.text.includes(title))) {
        blocks.push(makeBlock(BLOCK_MARKDOWN, `## ${title}`));
      }
      blocks.push(...tb);
    }
  } else {
    blocks = ((d.blocks as Record<string, unknown>[]) ?? []).map(blockFrom);
  }
  return {
    title: String(d.title ?? "Без названия"),
    blocks,
    active_block: String(d.active_block ?? ""),
    id: String(d.id || newId()),
    updated: Number(d.updated ?? Date.now() / 1000),
  };
}

export function freshIds(t: Template): Template {
  return { ...t, id: newId(), active_block: "", blocks: t.blocks.map((b) => ({ ...b, id: newId() })) };
}

export function codeBlocks(t: Template): Block[] {
  return t.blocks.filter((b) => b.type === BLOCK_CODE);
}

/** Переходы по хоткею «следующий блок»: блоки кода и активный текстовый блок, если печатается он —
 *  так из условия задачи попадаем в код под ним. */
export function navBlocks(t: Template): Block[] {
  return t.blocks.filter((b) => b.type === BLOCK_CODE || b.id === t.active_block);
}

/** Номер блока кода (1, 2, …) для заголовка «Код N»; 0 — для текстового блока. */
export function codeNumber(t: Template, b: Block): number {
  return codeBlocks(t).findIndex((x) => x.id === b.id) + 1;
}

/** Язык ближайшего блока кода — сначала ниже (условие стоит над решением), затем выше. */
export function langNear(t: Template, b: Block): string {
  const i = t.blocks.findIndex((x) => x.id === b.id);
  const order = [...t.blocks.slice(i + 1), ...t.blocks.slice(0, Math.max(0, i)).reverse()];
  return order.find((x) => x.type === BLOCK_CODE)?.lang ?? "python";
}

export function blockTitle(b: Block, codeNumber = 0): string {
  if (b.title.trim()) return b.title.trim();
  if (b.type === BLOCK_CODE) return codeNumber ? `Код ${codeNumber}` : "Код";
  return (ROLES[b.role] ?? ROLES.text)[1];
}

const SAMPLE_TASKS: [string, string][] = [
  ["## Задача 1. Сумма чисел\n\nНапишите функцию `total(nums)`, которая возвращает сумму " +
    "чисел списка.\n\n- без встроенной `sum()`\n- пустой список → `0`",
    "def total(nums):\n    result = 0\n    for n in nums:\n        result += n\n    return result\n" +
    "\n\nprint(total([1, 2, 3]))  # 6\nprint(\"Готово!\")"],
  ["## Задача 2. Чётные числа\n\nВыведите все чётные числа от 0 до 10.",
    "for i in range(0, 11, 2):\n    print(i)"],
];

export function sampleTemplate(): Template {
  return makeTemplate("Пример занятия", SAMPLE_TASKS.flatMap(([md, code]) => [
    makeBlock(BLOCK_MARKDOWN, md, { role: "task" }), makeBlock(BLOCK_CODE, code)]));
}

/** Что печатать: выделение (расширенное до целых строк) или весь блок → [текст, смещение]. */
export function typingSlice(text: string, sel: number[], wholeLines: boolean): [string, number] {
  if (sel.length !== 2 || sel[1] <= sel[0]) return [text, 0];
  let a = Math.max(0, sel[0]);
  let b = Math.min(text.length, sel[1]);
  if (wholeLines) {
    a = a > 0 ? text.lastIndexOf("\n", a - 1) + 1 : 0;
    if (b > a && text[b - 1] === "\n") b -= 1;
    const nl = text.indexOf("\n", b);
    b = nl < 0 ? text.length : nl;
  }
  return [text.slice(a, b), a];
}

// ---------------------------------------------------------------- протокол страница ↔ помощник

export type EngineState = "idle" | "countdown" | "running" | "paused" | "finished";

export interface EngineStatus {
  state: EngineState;
  pos: number;          // позиция в печатаемом тексте
  total: number;
  countdown: number;
  job: { tid: string; bid: string; base: number } | null;
}

export type ClientMsg =
  | { t: "saveTemplate"; template: Template }
  | { t: "deleteTemplate"; id: string }
  | { t: "settings"; settings: Partial<Settings> }
  | { t: "cmd"; cmd: "toggle" | "restart" | "stop"; fromButton?: boolean }
  | { t: "block"; d: number }
  | { t: "pauseHotkeys"; on: boolean }   // окно настроек: отпустить хоткеи, чтобы их можно было нажать
  | { t: "shutdown" }                    // выключить помощника (он работает без окна)
  | { t: "autostart"; on: boolean };     // запуск помощника при входе в Windows

export type ServerMsg =
  | { t: "hello"; version: string; settings: Settings; templates: Template[]; engine: EngineStatus;
      hotkeysFailed: string; autostart: boolean }
  | { t: "autostart"; on: boolean }
  | { t: "template"; template: Template }
  | { t: "templateDeleted"; id: string }
  | { t: "settings"; settings: Settings }
  | { t: "engine"; engine: EngineStatus }
  | { t: "sound"; kind: "key" | "space" | "enter" }
  | { t: "notify"; text: string; level?: "info" | "warn" }
  | { t: "focusBlock"; tid: string; bid: string };
