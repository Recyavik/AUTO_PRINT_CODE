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

/** Что печатать из блока → [текст, смещение в блоке, описание для строки состояния]. */
export function typingText(t: Template, b: Block, s: Settings): [string, number, string] {
  if (b.type !== BLOCK_CODE) {
    const mode = b.print_as in PRINT_MODES ? b.print_as : PRINT_MARKDOWN;
    const lang = langNear(t, b);
    const part = { [PRINT_MARKDOWN]: "текст как Markdown", [PRINT_PLAIN]: "простой текст",
      [PRINT_COMMENT]: `текст комментарием (${lang})` }[mode]!;
    return [printable(b.text, mode, lang), 0, part];
  }
  let [text, base] = typingSlice(b.text, b.sel, s.selection_whole_lines);
  let part = b.sel.length === 2 ? "выделенные строки" : "весь блок";
  if (s.strip_comments) {
    text = stripComments(text, b.lang)[0];
    part += ", без комментариев";
  }
  return [text, base, part];
}
