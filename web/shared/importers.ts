// Импорт образцов из .ipynb, .md, .py, .json и экспорт в .ipynb/.json (порт autoprint/importers.py).
// Файл забирается целиком: каждая ячейка — отдельный блок в исходном порядке (пустые пропускаются).
import {
  BLOCK_CODE, BLOCK_MARKDOWN, type Block, codeBlocks, freshIds, makeBlock, makeTemplate, type Template, templateFrom,
} from "./model.ts";

type Cell = [kind: "markdown" | "code", text: string, meta?: { role?: string; title?: string }];

const nl = (s: string) => s.replace(/\r\n?/g, "\n");
const stem = (name: string) => name.replace(/\.[^.]+$/, "");
const trimNl = (s: string) => s.replace(/^\n+|\n+$/g, "");

function build(title: string, cells: Cell[], lang: string): Template {
  const blocks: Block[] = [];
  for (const [kind, text, meta = {}] of cells) {
    if (!text.trim()) continue;
    blocks.push(makeBlock(kind === "markdown" ? BLOCK_MARKDOWN : BLOCK_CODE, text,
      { lang, role: meta.role || "text", title: meta.title || "" }));
  }
  return makeTemplate(title, blocks);
}

function cellText(cell: Record<string, unknown>): string {
  const src = cell.source ?? "";
  return nl(Array.isArray(src) ? src.join("") : String(src)).replace(/\n+$/, "");
}

function importIpynb(name: string, content: string): Template {
  const nb = JSON.parse(content);
  if (!Array.isArray(nb.cells)) throw new Error("Это не тетрадка Jupyter (нет поля cells). Поддерживается формат nbformat 4.");
  const meta = nb.metadata ?? {};
  const lang = String(meta.language_info?.name || meta.kernelspec?.language || "python").toLowerCase();
  const cells: Cell[] = [];
  for (const c of nb.cells) {
    if (c.cell_type === "markdown" || c.cell_type === "code") {
      cells.push([c.cell_type, cellText(c), c.metadata?.autoprintcode ?? {}]);
    } else if (c.cell_type === "raw") {
      cells.push(["markdown", "```\n" + cellText(c) + "\n```"]);
    }
  }
  return build(stem(name), cells, lang);
}

function importMarkdown(name: string, content: string): Template {
  const text = nl(content);
  const fence = /^```[ \t]*([\w+#.-]*)[^\n]*\n([\s\S]*?)^```[ \t]*$/gm;
  const cells: Cell[] = [];
  const langs: string[] = [];
  let pos = 0;
  for (const m of text.matchAll(fence)) {
    cells.push(["markdown", trimNl(text.slice(pos, m.index))]);
    cells.push(["code", m[2].replace(/\n+$/, "")]);
    if (m[2].trim()) langs.push(m[1].toLowerCase() || "text");
    pos = m.index! + m[0].length;
  }
  cells.push(["markdown", trimNl(text.slice(pos))]);
  const t = build(stem(name), cells, "python");
  codeBlocks(t).forEach((b, i) => { if (langs[i]) b.lang = langs[i]; });
  return t;
}

const PY_CELL = /^#[ \t]*%%(.*)$/;
const PY_MD_TAG = /\[\s*(markdown|md)\s*\]/i;

function uncomment(lines: string[]): string {
  return trimNl(lines.map((ln) => {
    const s = ln.trimStart();
    return s.startsWith("# ") ? s.slice(2) : s.startsWith("#") ? s.slice(1) : ln;
  }).join("\n"));
}

/** .py: ячейки «# %%» (VS Code, Spyder, Jupytext) — по ячейке на блок, «# %% [markdown]» — пояснение.
 *  Без разметки — весь файл одним блоком кода. */
function importPython(name: string, content: string): Template {
  const text = nl(content.replace(/^﻿/, ""));
  const lines = text.split("\n");
  const marks = lines.flatMap((ln, i) => (PY_CELL.test(ln) ? [i] : []));
  if (!marks.length) return build(stem(name), [["code", trimNl(text)]], "python");
  const cells: Cell[] = [["code", trimNl(lines.slice(0, marks[0]).join("\n"))]];
  marks.forEach((i, n) => {
    const body = lines.slice(i + 1, n + 1 < marks.length ? marks[n + 1] : lines.length);
    const header = PY_CELL.exec(lines[i])![1];
    if (PY_MD_TAG.test(header)) cells.push(["markdown", uncomment(body)]);
    else cells.push(["code", trimNl(body.join("\n")), header.trim() ? { title: header.trim() } : {}]);
  });
  return build(stem(name), cells, "python");
}

function importJson(_name: string, content: string): Template {
  const raw = JSON.parse(content);
  return freshIds(templateFrom(raw.autoprintcode_template ?? raw));
}

export function importFile(name: string, content: string): Template {
  const ext = name.toLowerCase().split(".").pop();
  if (ext === "ipynb") return importIpynb(name, content);
  if (ext === "md" || ext === "markdown") return importMarkdown(name, content);
  if (ext === "py") return importPython(name, content);
  if (ext === "json") return importJson(name, content);
  throw new Error("Неизвестный формат. Поддерживаются .ipynb, .md, .py, .json.");
}

export function exportIpynb(t: Template): string {
  const src = (text: string) => {
    const lines = text.split("\n");
    return [...lines.slice(0, -1).map((l) => l + "\n"), lines[lines.length - 1]];
  };
  let lang = "python";
  const cells = t.blocks.map((b) => {
    if (b.type === BLOCK_MARKDOWN) {
      return { cell_type: "markdown", source: src(b.text), metadata: { autoprintcode: { role: b.role, title: b.title } } };
    }
    lang = b.lang || lang;
    return { cell_type: "code", metadata: { autoprintcode: { title: b.title } }, execution_count: null,
      outputs: [], source: src(b.text) };
  });
  return JSON.stringify({ cells, nbformat: 4, nbformat_minor: 5, metadata: { language_info: { name: lang } } }, null, 1);
}

export function exportJson(t: Template): string {
  return JSON.stringify({ autoprintcode_template: t }, null, 2);
}
