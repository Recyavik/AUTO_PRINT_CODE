// Удаление комментариев из кода перед печатью (порт autoprint/comments.py).
//
// Комментарий целиком на строке — строка убирается вместе с переводом строки;
// комментарий в конце строки кода — убирается вместе с пробелами перед ним.
// Если из-за удаления рядом оказались две пустые строки, лишняя тоже убирается.
// Строковые литералы (в том числе тройные кавычки и docstring) не трогаются.
// Shebang «#!» и строка кодировки в начале файла сохраняются.

// Особые правила разбора:
//   ws    — «#» начинает комментарий только в начале строки или после пробела (bash: ${#arr[@]}, ${p##*/})
//   regex — «/…/» после оператора или «(» — регулярное выражение, а не начало комментария (JS: /https?:\/\//)
//   attr  — «#[» — атрибут PHP 8, а не комментарий
type Flag = "ws" | "regex" | "attr";
type Spec = [lineMarks: string[], blocks: [string, string][], quotes: string[], flags: Flag[]];

const HASH = ["#"];
const SLASH = ["//"];
const C_BLOCK: [string, string][] = [["/*", "*/"]];

const LANGS = new Map<string, Spec>();
for (const [names, spec] of [
  ["python py python3 ipython", [HASH, [], ['"""', "'''", '"', "'"], []]],
  ["bash sh shell zsh yaml yml toml r ruby rb perl makefile dockerfile", [HASH, [], ['"', "'"], ["ws"]]],
  ["powershell ps1", [HASH, [["<#", "#>"]], ['"', "'"], ["ws"]]],
  ["javascript js jsx typescript ts tsx", [SLASH, C_BLOCK, ['"', "'", "`"], ["regex"]]],
  ["java kotlin kt scala dart go rust rs swift c cpp c++ cs csharp objective-c json5", [SLASH, C_BLOCK, ['"', "'", "`"], []]],
  ["php", [[...SLASH, ...HASH], C_BLOCK, ['"', "'"], ["attr"]]],
  ["css scss less", [[], C_BLOCK, ['"', "'"], []]],
  ["sql", [["--"], C_BLOCK, ['"', "'"], []]],
  ["lua", [["--"], [["--[[", "]]"]], ['"', "'"], []]],
  ["haskell hs", [["--"], [["{-", "-}"]], ['"'], []]],
  ["html xml svg vue", [[], [["<!--", "-->"]], [], []]],
] as [string, Spec][]) {
  for (const n of names.split(" ")) LANGS.set(n, spec);
}

const KEEP_HEAD = /^#!|^#.*coding[:=]/;
const REGEX_BEFORE = new Set("(,=:[!&|?{};+-*%<>~^");   // после этих символов «/» открывает регулярное выражение

/** → [маркеры строчных комментариев, пары блочных, кавычки, особые правила] или null для неизвестного языка. */
export function langSpec(lang: string): Spec | null {
  return LANGS.get((lang || "").toLowerCase()) ?? null;
}

/** Если в позиции i («/») начинается регулярное выражение JS — позиция после него, иначе -1. */
function regexEnd(text: string, i: number): number {
  let j = i - 1;
  while (j >= 0 && (text[j] === " " || text[j] === "\t")) j -= 1;
  if (j >= 0 && !REGEX_BEFORE.has(text[j]) && text[j] !== "\n" && !text.slice(0, j + 1).endsWith("return")) {
    return -1;   // после значения «/» — это деление
  }
  let inClass = false;
  for (let k = i + 1; k < text.length && text[k] !== "\n"; k++) {
    const c = text[k];
    if (c === "\\") { k += 1; continue; }
    if (c === "[") inClass = true;
    else if (c === "]") inClass = false;
    else if (c === "/" && !inClass) return k + 1;
  }
  return -1;
}

function commentSpans(text: string, [lineMarks, blocks, quotes, flags]: Spec): [number, number][] {
  const spans: [number, number][] = [];
  const n = text.length;
  let i = 0;
  while (i < n) {
    const q = quotes.find((q) => text.startsWith(q, i));
    if (q) {
      let j = i + q.length;
      while (j < n) {
        if (text[j] === "\\") { j += 2; continue; }
        if (text.startsWith(q, j)) { j += q.length; break; }
        if (q.length === 1 && text[j] === "\n") break;   // незакрытая строка — до конца строки
        j += 1;
      }
      i = j;
      continue;
    }
    const b = blocks.find((b) => text.startsWith(b[0], i));
    if (b) {
      let end = text.indexOf(b[1], i + b[0].length);
      end = end < 0 ? n : end + b[1].length;
      spans.push([i, end]);
      i = end;
      continue;
    }
    if (flags.includes("regex") && text[i] === "/" && !text.startsWith("//", i) && !text.startsWith("/*", i)) {
      const end = regexEnd(text, i);
      if (end > 0) { i = end; continue; }
    }
    const m = lineMarks.find((m) => text.startsWith(m, i));
    if (m && !(flags.includes("ws") && m === "#" && i > 0 && !/\s/.test(text[i - 1]))
        && !(flags.includes("attr") && text.startsWith("#[", i))) {
      let end = text.indexOf("\n", i);
      end = end < 0 ? n : end;
      spans.push([i, end]);
      i = end;
      continue;
    }
    i += 1;
  }
  return spans;
}

/** → [текст без комментариев, карта: индекс символа результата → индекс в исходном тексте]. */
export function stripComments(text: string, lang: string): [string, number[]] {
  const spec = langSpec(lang);
  const spans = spec ? commentSpans(text, spec) : [];
  if (!spans.length) return [text, Array.from({ length: text.length }, (_, k) => k)];
  const inComment = new Uint8Array(text.length);
  for (const [a, b] of spans) inComment.fill(1, a, b);

  // строки результата: [индексы оставленных символов, индекс исходного «\n» перед строкой, пустая ли]
  const lines: [number[], number, boolean][] = [];
  let dropped = false;          // после последней оставленной строки была удалена строка
  let trailingDropped = false;
  let start = 0;
  text.split("\n").forEach((line, li) => {
    const end = start + line.length;
    let idx: number[] = [];
    for (let k = start; k < end; k++) if (!inComment[k]) idx.push(k);
    let hadComment = idx.length < line.length;
    if (hadComment && li < 2 && KEEP_HEAD.test(line)) {
      idx = Array.from({ length: line.length }, (_, k) => start + k);
      hadComment = false;
    }
    const blank = !idx.map((k) => text[k]).join("").trim();
    if (hadComment && blank) {
      dropped = trailingDropped = true;          // строка была только комментарием
    } else if (blank && dropped && (!lines.length || lines[lines.length - 1][2])) {
      // лишняя пустая строка рядом с удалённым комментарием
    } else {
      if (hadComment) while (idx.length && " \t".includes(text[idx[idx.length - 1]])) idx.pop();
      lines.push([idx, start - 1, blank]);
      dropped = false;
      if (!blank) trailingDropped = false;
    }
    start = end + 1;
  });
  if (trailingDropped) while (lines.length && lines[lines.length - 1][2]) lines.pop();

  let out = "";
  const omap: number[] = [];
  lines.forEach(([idx, nlAt], n) => {
    if (n) { out += "\n"; omap.push(nlAt); }
    for (const k of idx) { out += text[k]; omap.push(k); }
  });
  return [out, omap];
}
