// Удаление комментариев из кода перед печатью (порт autoprint/comments.py).
//
// Комментарий целиком на строке — строка убирается вместе с переводом строки;
// комментарий в конце строки кода — убирается вместе с пробелами перед ним.
// Если из-за удаления рядом оказались две пустые строки, лишняя тоже убирается.
// Строковые литералы (в том числе тройные кавычки и docstring) не трогаются.
// Shebang «#!» и строка кодировки в начале файла сохраняются.

type Spec = [lineMarks: string[], blocks: [string, string][], quotes: string[]];

const HASH = ["#"];
const SLASH = ["//"];
const C_BLOCK: [string, string][] = [["/*", "*/"]];

const LANGS: Record<string, Spec> = {};
for (const [names, spec] of [
  ["python py python3 ipython", [HASH, [], ['"""', "'''", '"', "'"]]],
  ["bash sh shell zsh powershell ps1 yaml yml toml r ruby rb perl makefile dockerfile", [HASH, [], ['"', "'"]]],
  ["javascript js jsx typescript ts tsx java kotlin kt scala dart go rust rs swift c cpp c++ cs csharp " +
    "objective-c json5", [SLASH, C_BLOCK, ['"', "'", "`"]]],
  ["php", [[...SLASH, ...HASH], C_BLOCK, ['"', "'"]]],
  ["css scss less", [[], C_BLOCK, ['"', "'"]]],
  ["sql lua haskell hs", [["--"], [["/*", "*/"]], ['"', "'"]]],
  ["html xml svg vue", [[], [["<!--", "-->"]], []]],
] as [string, Spec][]) {
  for (const n of names.split(" ")) LANGS[n] = spec;
}

const KEEP_HEAD = /^#!|^#.*coding[:=]/;

export function supported(lang: string): boolean {
  return (lang || "").toLowerCase() in LANGS;
}

/** → [маркеры строчных комментариев, пары блочных, кавычки] или null для неизвестного языка. */
export function langSpec(lang: string): Spec | null {
  return LANGS[(lang || "").toLowerCase()] ?? null;
}

function commentSpans(text: string, [lineMarks, blocks, quotes]: Spec): [number, number][] {
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
    if (lineMarks.some((m) => text.startsWith(m, i))) {
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
  const spec = LANGS[(lang || "").toLowerCase()];
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
