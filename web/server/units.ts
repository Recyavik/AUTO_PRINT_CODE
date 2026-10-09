// Текст → «единицы» печати и задержки между ними (порт build_units/_delay_after из typer.py и human.py).
import { PROFILE_IDE, type Settings } from "../shared/model.ts";

export type UnitKind = "char" | "fast" | "tab" | "back" | "newline" | "cleanup";

export interface Unit {
  kind: UnitKind;
  text: string;
  srcEnd: number;   // позиция в исходном тексте после этой единицы
  k: number;        // множитель задержки после единицы (имитация ручного ввода)
  pause: number;    // пауза перед единицей, с (обдумывание)
}

const unit = (kind: UnitKind, text: string, srcEnd: number, k = 1, pause = 0): Unit => ({ kind, text, srcEnd, k, pause });

export const PUNCT = new Set(",;:)]}>");

export function normalize(text: string): string {
  return text.replace(/\r\n?/g, "\n");
}

/** Символы строки по кодовым точкам (эмодзи и т. п. — одним символом, как в Python). */
const chars = (s: string) => Array.from(s);

export function buildUnits(text: string, s: Settings, rng: () => number = Math.random): Unit[] {
  const tab = " ".repeat(Math.max(1, s.tab_width));
  let units: Unit[] = [];
  let src = 0;   // в UTF-16 единицах — как позиции в редакторе страницы
  text.split("\n").forEach((line, li) => {
    if (li > 0) { src += 1; units.push(unit("newline", "\n", src)); }
    const m = line.length - line.replace(/^[ \t]+/, "").length;
    if (m && s.indent_with_tab) {
      // как человек: Tab на каждый уровень отступа, остаток — пробелами
      let col = 0;
      const cols: number[] = [];       // cols[i] — ширина отступа после i+1 исходных символов
      for (const ch of line.slice(0, m)) { col += ch === "\t" ? tab.length : 1; cols.push(col); }
      let done = 0;
      for (let level = 1; level <= Math.floor(col / tab.length); level++) {
        done = cols.findIndex((c) => c >= level * tab.length) + 1;
        units.push(unit("tab", "\t", src + done));
      }
      for (let i = 0; i < col % tab.length; i++) units.push(unit("char", " ", src + Math.min(m, done + i + 1)));
    } else if (m) {
      const indent = line.slice(0, m).replaceAll("\t", tab);
      if (s.fast_indent) units.push(unit("fast", indent, src + m));
      else for (let i = 0; i < m; i++) units.push(unit("char", line[i] === "\t" ? tab : line[i], src + i + 1));
    }
    let off = m;
    for (const ch of chars(line.slice(m))) {
      off += ch.length;
      units.push(unit("char", ch === "\t" ? tab : ch, src + off));
    }
    src += line.length;
  });
  if (s.human_typing) units = humanize(units, s, rng);
  if (s.profile === PROFILE_IDE && units.length) units.push(unit("cleanup", "", src));
  return units;
}

function gauss(rng: () => number): number {
  const u = 1 - rng();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rng());
}

export function delayAfter(u: Unit, s: Settings, rng: () => number = Math.random): number {
  const base = 60 / Math.max(30, s.cpm);
  const j = Math.max(0, Math.min(90, s.jitter)) / 100;
  let d: number;
  if (s.human_typing) {
    // логнормальный разброс: в основном ровно, изредка заметная заминка; среднее = base·k
    const sigma = 0.1 + 0.5 * j;
    d = base * u.k * Math.exp(-sigma * sigma / 2 + sigma * gauss(rng));
  } else {
    d = base * (1 - j + 2 * j * rng());
  }
  if (u.kind === "newline") d += s.newline_pause_ms / 1000;
  else if (u.kind === "char" && PUNCT.has(u.text)) d += s.punct_pause_ms / 1000;
  else if (u.kind === "fast") d = base * 0.5;
  else if (u.kind === "cleanup") d = 0;
  return Math.max(d, gapSeconds(s));
}

// Мин. интервал между нажатиями — настройка key_gap_ms. Замер на Блокноте Windows 11:
// при 8–12 мс символы теряются и переставляются, при 30 мс — набор точный.
export function gapSeconds(s: Settings): number {
  return Math.max(5, s.key_gap_ms) / 1000;
}

// ---------------------------------------------------------------- имитация ручного ввода
//
// Безопасность для IDE: опечатка — только буква внутри слова из букв, и всё, что набрано
// до исправления, тоже буквы этого слова. Скобки, кавычки, отступы и Enter никогда не участвуют.

// слова, которые программист набирает «на автомате» — быстрее остальных
const FAMILIAR = new Set(`print return def self import from for in if else elif while True False None and or not range len
class input int str float list dict set append pass break continue with as try except lambda
const let var function console log new this null true false`.split(/\s+/));
// слова, перед которыми человек задумывается (начало нового смыслового куска)
const THINK_BEFORE = new Set("def class for while if elif else try except with return import from function".split(" "));
const SHIFTED = new Set('~!@#$%^&*()_+{}|:"<>?');

const ROWS = [
  ["1234567890-=", "qwertyuiop[]", "asdfghjkl;'", "zxcvbnm,./"],
  ["1234567890-=", "йцукенгшщзхъ", "фывапролджэ", "ячсмитьбю."],
];

const isAlpha = (c: string) => /^\p{L}$/u.test(c);
const isAlnum = (c: string) => /^[\p{L}\p{N}]$/u.test(c);
const isUpper = (c: string) => c !== c.toLowerCase() && c === c.toUpperCase();

const NEIGHBORS: Record<string, string> = (() => {
  const near: Record<string, string> = {};
  for (const rows of ROWS) {
    rows.forEach((row, r) => {
      [...row].forEach((ch, i) => {
        if (!isAlpha(ch)) return;
        const cand = [i - 1, i + 1].filter((j) => j >= 0 && j < row.length).map((j) => row[j]);
        for (const rr of [r - 1, r + 1]) if (rr >= 0 && rr < rows.length && i < rows[rr].length) cand.push(rows[rr][i]);
        near[ch] = cand.filter(isAlpha).join("");
      });
    });
  }
  return near;
})();

const pick = <T>(arr: readonly T[], rng: () => number): T => arr[Math.floor(rng() * arr.length)];
const uniform = (a: number, b: number, rng: () => number) => a + (b - a) * rng();
const isLetterUnit = (u: Unit) => u.kind === "char" && u.text.length === 1 && isAlpha(u.text);

function wrongKey(ch: string, rng: () => number): string | null {
  const near = NEIGHBORS[ch.toLowerCase()];
  if (!near) return null;
  const c = pick([...near], rng);
  return isUpper(ch) ? c.toUpperCase() : c;
}

export function humanize(units: Unit[], s: Settings, rng: () => number = Math.random): Unit[] {
  const think = Math.max(0, s.think_pause_s);
  const typoP = Math.max(0, s.typo_per_100_words) / 100;   // вероятность опечатки в слове
  const n = units.length;
  const isWordCh = (u: Unit) => u.kind === "char" && (isAlnum(u.text) || u.text === "_");

  // слова: непрерывные отрезки букв/цифр/_ в единицах «char»
  const wordOf: ([number, number] | null)[] = new Array(n).fill(null);
  for (let i = 0; i < n;) {
    if (isWordCh(units[i])) {
      let j = i;
      while (j < n && isWordCh(units[j])) j++;
      for (let k = i; k < j; k++) wordOf[k] = [i, j];
      i = j;
    } else i++;
  }
  const word = (span: [number, number]) => units.slice(span[0], span[1]).map((u) => u.text).join("");

  // --- проход 1: ритм (k) и паузы (pause)
  let lineStart = true;
  let prevBlank = true;
  let lineHasText = false;
  const driftPhase = uniform(0, 2 * Math.PI, rng);
  let prevCh = "";
  units.forEach((u, idx) => {
    if (u.kind === "newline") {
      prevBlank = !lineHasText;
      lineStart = true; lineHasText = false; prevCh = "";
      return;
    }
    if (u.kind !== "char" || (lineStart && !u.text.trim())) return;   // отступ (в т.ч. таб → пробелы)
    const span = wordOf[idx];
    const w = span ? word(span) : "";
    const atWordStart = !!span && span[0] === idx;
    if (lineStart && think) {
      let pause = uniform(0.15, 0.45, rng) * think;
      if (prevBlank) pause += uniform(0.3, 0.7, rng) * think;     // новый смысловой кусок
      if (THINK_BEFORE.has(w)) pause += uniform(0.1, 0.4, rng) * think;
      u.pause = pause;
    } else if (atWordStart && think && rng() < 0.04) {
      u.pause = uniform(0.1, 0.4, rng) * think;                   // заминка посреди строки
    }
    lineStart = false; lineHasText = true;

    const ch = u.text;
    let k = 1;
    if (FAMILIAR.has(w)) k *= 0.65;
    else if (atWordStart) k *= 1.3;
    if (SHIFTED.has(ch) || isUpper(ch)) k *= 1.35;
    else if (/^\p{N}$/u.test(ch)) k *= 1.15;
    else if (!isAlnum(ch) && ch !== " " && ch !== "_") k *= 1.2;
    if (ch === prevCh) k *= 0.8;
    k *= 1 + 0.1 * Math.sin(driftPhase + idx / 60);              // плавный дрейф темпа
    u.k = k; prevCh = ch;
  });

  // --- проход 2: опечатки — решается один раз на слово из букв
  const out: Unit[] = [];
  for (let i = 0; i < n;) {
    const span = wordOf[i];
    if (span && span[0] === i && typoP && span[1] - span[0] >= 3 && rng() < typoP
        && units.slice(span[0], span[1]).every(isLetterUnit)) {
      out.push(...typo(units, span, rng));
      i = span[1];
      continue;
    }
    out.push(units[i]);
    i++;
  }
  return out;
}

/** Слово с опечаткой: ошибка → (0–2 верных буквы) → заметил → Backspace → правильно. */
function typo(units: Unit[], [a, b]: [number, number], rng: () => number): Unit[] {
  const letters = units.slice(a, b);
  const pos = 1 + Math.floor(rng() * (letters.length - 1));   // первая буква — без ошибок
  let kind = pick(["near", "near", "near", "swap", "double"] as const, rng) as string;
  if (kind === "swap" && pos + 1 >= letters.length) kind = "near";
  let good = pos;
  let typedWrong: string[];
  let after: number;
  if (kind === "near") {
    const wrong = wrongKey(letters[pos].text, rng);
    if (!wrong) return letters;
    typedWrong = [wrong];
    after = pos + 1;
  } else if (kind === "swap") {
    typedWrong = [letters[pos + 1].text, letters[pos].text];
    after = pos + 2;
  } else {   // double: буква набрана верно, но дважды — стереть надо только лишнюю
    good = pos + 1;
    typedWrong = [letters[pos].text];
    after = pos + 1;
  }
  const extra = Math.min(pick([0, 0, 1, 1, 2], rng), letters.length - after);   // успел набрать дальше
  const out = letters.slice(0, good);
  const srcBefore = letters[good - 1].srcEnd;
  for (const c of typedWrong) out.push(unit("char", c, srcBefore));
  for (let t = after; t < after + extra; t++) out.push(unit("char", letters[t].text, srcBefore, letters[t].k));
  for (let i = 0; i < typedWrong.length + extra; i++) {
    out.push(unit("back", "", srcBefore, 0.6, i === 0 ? uniform(0.25, 0.7, rng) : 0));   // заметил ошибку
  }
  out.push(...letters.slice(good));
  return out;
}
