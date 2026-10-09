// Печать текстовых (Markdown) блоков: условие задачи, пояснение, подсказка (порт autoprint/textprint.py).
//
// Три вида:
//   markdown — исходник как есть (markdown-ячейка Jupyter, .md-файл);
//   plain    — без разметки: «## Заголовок», **жирный**, `код`, [ссылка](url) → просто текст (Блокнот, Word, чат);
//   comment  — простой текст, каждая строка закомментирована по языку ближайшего блока кода
//              (условие в начале файла с решением).
import { langSpec, stripComments } from "./comments.ts";
import { BLOCK_CODE, type Block, langNear, type Settings, type Template, typingSlice } from "./model.ts";

export const PRINT_MARKDOWN = "markdown";
export const PRINT_PLAIN = "plain";
export const PRINT_COMMENT = "comment";
export const PRINT_MODES: Record<string, string> = {
  [PRINT_MARKDOWN]: "как Markdown",
  [PRINT_PLAIN]: "простым текстом",
  [PRINT_COMMENT]: "комментарием в коде",
};

const FENCE = /^\s{0,3}(```|~~~)/;
const HEADING = /^\s{0,3}#{1,6}(?:\s+|$)(.*?)(?:\s+#+)?\s*$/;
const SETEXT = /^\s{0,3}(=+|-+)\s*$/;
const QUOTE = /^\s{0,3}>\s?/;
const RULE = /^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/;
const BULLET = /^(\s*)[*+](\s+)/;
const ESCAPE = /\\([\\`*_{}[\]()#+\-.!>~|])/g;
const CODE = /(`+)(.+?)\1/g;
const IMAGE = /!\[([^\]]*)\]\([^)]*\)/g;
const LINK = /\[([^\]]+)\]\([^)]*\)/g;
const BOLD = /(\*\*|__)(?=\S)(.+?)(?<=\S)\1/g;
// \w в Python — с буквами любых алфавитов, поэтому здесь \p{L}\p{N}
const ITALIC = /(?<![\p{L}\p{N}_*])\*(?=\S)(.+?)(?<=\S)\*(?![\p{L}\p{N}_*])|(?<![\p{L}\p{N}_])_(?=\S)(.+?)(?<=\S)_(?![\p{L}\p{N}_])/gu;
const STRIKE = /~~(?=\S)(.+?)(?<=\S)~~/g;
const HARD_BREAK = /(\\| {2,})$/;
const PRIVATE = 0xe000;   // экранированные символы на время разбора прячутся в область частного использования

function emphasis(s: string): string {
  return s.replace(IMAGE, "$1").replace(LINK, "$1").replace(STRIKE, "$1").replace(BOLD, "$2")
    .replace(ITALIC, (_m, a: string | undefined, b: string | undefined) => a ?? b ?? "");
}

function inline(s: string): string {
  s = s.replace(ESCAPE, (_m, c: string) => String.fromCharCode(PRIVATE + c.charCodeAt(0)));
  let out = "";
  let last = 0;
  for (const m of s.matchAll(CODE)) {
    out += emphasis(s.slice(last, m.index));
    let code = m[2];
    if (code.length > 2 && code[0] === " " && code[code.length - 1] === " ") code = code.slice(1, -1);
    out += code;
    last = m.index! + m[0].length;
  }
  out += emphasis(s.slice(last));
  return out.replace(/[-]/g, (c) => String.fromCharCode(c.charCodeAt(0) - PRIVATE));
}

export function markdownToPlain(text: string): string {
  const lines: string[] = [];
  let fence = "";
  let para = false;   // предыдущая строка — текст абзаца (не код, не пустая)
  for (let line of text.split("\n")) {
    const m = FENCE.exec(line);
    if (fence) {
      if (m && m[1] === fence) fence = "";
      else lines.push(line);            // код внутри ``` — как есть
      continue;
    }
    if (m) {
      fence = m[1];
      para = false;
      continue;
    }
    if (para && SETEXT.test(line)) {    // подчёркивание заголовка «===» / «---»
      para = false;
      continue;
    }
    para = !!line.trim();
    if (RULE.test(line)) {
      lines.push("");
      para = false;
      continue;
    }
    line = line.replace(QUOTE, "");
    const h = HEADING.exec(line);
    if (h) line = h[1];
    line = line.replace(BULLET, "$1-$2").replace(HARD_BREAK, "");
    lines.push(inline(line).trimEnd());
  }
  const out: string[] = [];
  for (const line of lines) if (line || (out.length && out[out.length - 1])) out.push(line);   // не больше одной пустой подряд
  while (out.length && !out[out.length - 1]) out.pop();
  return out.join("\n");
}

/** Простой текст, закомментированный для языка lang (неизвестный язык → «#»). */
export function asComment(text: string, lang: string): string {
  const lines = markdownToPlain(text).split("\n");
  const [marks, blocks] = langSpec(lang) ?? [["#"], []];
  if (marks.length) return lines.map((l) => (l ? `${marks[0]} ${l}` : marks[0])).join("\n");
  if (blocks.length) return [blocks[0][0], ...lines, blocks[0][1]].join("\n");
  return lines.map((l) => (l ? `# ${l}` : "#")).join("\n");
}

/** Что печатать для текстового блока в выбранном виде. */
export function printable(text: string, mode: string, lang = "python"): string {
  if (mode === PRINT_PLAIN) return markdownToPlain(text);
  if (mode === PRINT_COMMENT) return asComment(text, lang);
  return text.replace(/^\n+|\n+$/g, "");
}

/** Открывающая строка ```-блока, внутри которого стоит позиция pos ("" — не внутри). */
function fenceAt(text: string, pos: number): string {
  let fence = "";
  let opener = "";
  for (const line of text.slice(0, pos).split("\n").slice(0, -1)) {
    const m = FENCE.exec(line);
    if (fence) {
      if (m && m[1] === fence) fence = opener = "";
    } else if (m) {
      fence = m[1];
      opener = line;
    }
  }
  return opener;
}

/** Печатаемый текст выделенного куска part (начинается в source с позиции base).
 *  Кусок из середины ```-блока остаётся кодом и в простом тексте. */
export function selectionText(source: string, part: string, base: number, mode: string, lang = "python"): string {
  if (mode !== PRINT_MARKDOWN) {
    const opener = fenceAt(source, base);
    if (opener) return printable(opener + "\n" + part + "\n" + opener.trim().slice(0, 3), mode, lang);
  }
  return printable(part, mode, lang);
}

// ---------------------------------------------------------------- выделение в отрисованном тексте

const LIST_MARK = /^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?/;
const VIEW_BULLET = /^\s*[•◦▪▫·‣○●■□]\s*/;   // маркеры, которые просмотр может добавить к выделению
// разрывы строк, как у str.splitlines() в Python (просмотр Qt отдаёт абзацы через U+2029)
const LINE_BREAKS = new RegExp("(?:" + String.fromCharCode(13, 10) + ")|[" +
  String.fromCharCode(10, 13, 11, 12, 0x1c, 0x1d, 0x1e, 0x85, 0x2028, 0x2029) + "]");

/** Каждая строка исходника — так, как её видно в отрисованном Markdown (без ##, **, маркеров списка). */
function renderedLines(source: string): string[] {
  const out: string[] = [];
  let fence = "";
  let para = false;
  for (let line of source.split("\n")) {
    const m = FENCE.exec(line);
    if (fence) {
      if (m && m[1] === fence) {
        fence = "";
        out.push("");
      } else out.push(line);
      continue;
    }
    if (m) {
      fence = m[1];
      para = false;
      out.push("");
      continue;
    }
    if ((para && SETEXT.test(line)) || RULE.test(line)) {
      para = false;
      out.push("");
      continue;
    }
    para = !!line.trim();
    line = line.replace(QUOTE, "");
    const h = HEADING.exec(line);
    if (h) line = h[1];
    out.push(inline(line.replace(LIST_MARK, "").replace(HARD_BREAK, "")));
  }
  return out;
}

/** Схлопывает пробельные символы в один пробел → [строка, индекс исходного символа для каждого]. */
function squash(text: string): [string, number[]] {
  let out = "";
  const idx: number[] = [];
  for (let i = 0; i < text.length; i++) {
    if (/\s/.test(text[i])) {
      if (out && out[out.length - 1] !== " ") { out += " "; idx.push(i); }
    } else { out += text[i]; idx.push(i); }
  }
  return [out, idx];
}

/** Выделение в отрисованном тексте → [начало, конец] целых строк исходника; [] — не нашлось.
 *  selected — выделенный текст, как его отдаёт просмотр; hint — где примерно началось выделение
 *  (0…1 от длины отрисованного текста): если такой же кусок встречается несколько раз. */
export function findSelection(source: string, selected: string, hint = 0): number[] {
  const lines = renderedLines(source);
  let flat = "";
  const lineOf: number[] = [];
  lines.forEach((line, j) => {
    flat += line + "\n";
    for (let k = 0; k <= line.length; k++) lineOf.push(j);
  });
  const [hay, hayIdx] = squash(flat);
  selected = selected.split(LINE_BREAKS).map((x) => x.replace(VIEW_BULLET, "")).join("\n");
  const need = squash(selected)[0].trim();
  if (!need) return [];

  const occurrences = (s: string, start = 0): number[] => {
    const found: number[] = [];
    for (let i = hay.indexOf(s, start); i >= 0; i = hay.indexOf(s, i + 1)) found.push(i);
    return found;
  };
  const nearest = (found: number[]) =>
    found.reduce((best, i) => (Math.abs(i / Math.max(1, hay.length) - hint) < Math.abs(best / Math.max(1, hay.length) - hint) ? i : best));

  let a: number;
  let b: number;
  const found = occurrences(need);
  if (found.length) {
    a = nearest(found);
    b = a + need.length - 1;
  } else {
    // просмотр мог добавить или убрать символы (маркеры списков, таблицы) — ищем первую и последнюю строку
    const parts = selected.split("\n").map((x) => squash(x)[0].trim()).filter((x) => x);
    const first = occurrences(parts[0]);
    if (!first.length) return [];
    a = nearest(first);
    const last = occurrences(parts[parts.length - 1], a);
    b = last.length ? last[0] + parts[parts.length - 1].length - 1 : a + parts[0].length - 1;
  }
  const ja = lineOf[hayIdx[a]];
  const jb = lineOf[hayIdx[b]];
  const starts = [0];
  for (const line of source.split("\n")) starts.push(starts[starts.length - 1] + line.length + 1);
  return [starts[ja], starts[jb + 1] - 1];
}

/** Что печатать из блока → [текст, смещение в блоке, описание для строки состояния]. */
export function typingText(t: Template, b: Block, s: Settings): [string, number, string] {
  if (b.type !== BLOCK_CODE) {
    const mode = b.print_as in PRINT_MODES ? b.print_as : PRINT_MARKDOWN;
    const lang = langNear(t, b);
    const part = { [PRINT_MARKDOWN]: "текст как Markdown", [PRINT_PLAIN]: "простой текст",
      [PRINT_COMMENT]: `текст комментарием (${lang})` }[mode]!;
    if (b.sel.length !== 2) return [printable(b.text, mode, lang), 0, part];
    const [text, base] = typingSlice(b.text, b.sel, s.selection_whole_lines);
    return [selectionText(b.text, text, base, mode, lang), base, part + ", выделенные строки"];
  }
  let [text, base] = typingSlice(b.text, b.sel, s.selection_whole_lines);
  let part = b.sel.length === 2 ? "выделенные строки" : "весь блок";
  if (s.strip_comments) {
    text = stripComments(text, b.lang)[0];
    part += ", без комментариев";
  }
  return [text, base, part];
}
