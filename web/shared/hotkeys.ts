// Хоткеи в формате «Ctrl+Shift+F12» (как QKeySequence.toString() в Python-версии) ↔ (модификаторы, VK).

const MOD_ALT = 0x0001;
const MOD_CONTROL = 0x0002;
const MOD_SHIFT = 0x0004;
const MOD_WIN = 0x0008;

const NAMED_KEYS: Record<string, number> = {
  SPACE: 0x20, PAUSE: 0x13, INS: 0x2d, INSERT: 0x2d, DEL: 0x2e, DELETE: 0x2e,
  HOME: 0x24, END: 0x23, PGUP: 0x21, PGDOWN: 0x22, LEFT: 0x25, UP: 0x26,
  RIGHT: 0x27, DOWN: 0x28, ESC: 0x1b, ESCAPE: 0x1b, RETURN: 0x0d, ENTER: 0x0d,
  TAB: 0x09, BACKSPACE: 0x08, SCROLLLOCK: 0x91, PRINT: 0x2c,
  "`": 0xc0, "-": 0xbd, "=": 0xbb, "[": 0xdb, "]": 0xdd, ";": 0xba, "'": 0xde,
  ",": 0xbc, ".": 0xbe, "/": 0xbf, "\\": 0xdc,
};

/** 'Ctrl+Alt+F9' → [модификаторы, vk] или null. */
export function parseHotkey(text: string): [number, number] | null {
  if (!text) return null;
  let parts = text.replaceAll(" ", "").split("+");
  if (text.endsWith("++")) parts = [...parts.slice(0, -2), "="];   // «Ctrl++» — клавиша плюс
  let mods = 0;
  let key: string | null = null;
  for (const p of parts) {
    const u = p.toUpperCase();
    if (u === "CTRL" || u === "CONTROL") mods |= MOD_CONTROL;
    else if (u === "ALT") mods |= MOD_ALT;
    else if (u === "SHIFT") mods |= MOD_SHIFT;
    else if (u === "META" || u === "WIN") mods |= MOD_WIN;
    else if (p) key = u;
  }
  if (key === null) return null;
  if (key.length === 1 && /[A-Z0-9]/.test(key)) return [mods, key.charCodeAt(0)];
  const f = /^F(\d+)$/.exec(key);
  if (f && +f[1] >= 1 && +f[1] <= 24) return [mods, 0x70 + +f[1] - 1];
  if (key in NAMED_KEYS) return [mods, NAMED_KEYS[key]];
  return null;
}

const CODE_NAMES: Record<string, string> = {
  Space: "Space", Pause: "Pause", Insert: "Ins", Delete: "Del", Home: "Home", End: "End",
  PageUp: "PgUp", PageDown: "PgDown", ArrowLeft: "Left", ArrowUp: "Up", ArrowRight: "Right", ArrowDown: "Down",
  Escape: "Esc", Enter: "Return", Tab: "Tab", Backspace: "Backspace", ScrollLock: "ScrollLock",
  Backquote: "`", Minus: "-", Equal: "=", BracketLeft: "[", BracketRight: "]", Semicolon: ";", Quote: "'",
  Comma: ",", Period: ".", Slash: "/", Backslash: "\\",
};

/** Событие клавиатуры браузера → «Ctrl+Shift+F12» (null — нажат только модификатор или клавиша не поддерживается).
 *  Берётся физическая клавиша (code), поэтому раскладка не важна. */
export function hotkeyFromEvent(e: { code: string; ctrlKey: boolean; altKey: boolean; shiftKey: boolean; metaKey: boolean }): string | null {
  let key: string | undefined;
  if (/^Key[A-Z]$/.test(e.code)) key = e.code.slice(3);
  else if (/^Digit\d$/.test(e.code)) key = e.code.slice(5);
  else if (/^F\d{1,2}$/.test(e.code)) key = e.code;
  else key = CODE_NAMES[e.code];
  if (!key) return null;
  const mods = [e.ctrlKey && "Ctrl", e.altKey && "Alt", e.shiftKey && "Shift", e.metaKey && "Meta"].filter(Boolean);
  return [...mods, key].join("+");
}
