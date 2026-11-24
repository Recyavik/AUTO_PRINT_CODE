// Правка заметки «как в Word»: в поле — оформленный текст (жирный, курсив, списки, ссылки), в уроке — Markdown.
// toMarkdown: узлы поля → Markdown (тот, что понимают mdHtml здесь и scenario.md_html в программе).
// cleanPaste: HTML из Word, PDF, браузера → только то, что умеет заметка (без стилей, классов и скриптов).
"use strict";
import { mdHtml } from "./md.js";

const BLOCKS = new Set(["P", "DIV", "UL", "OL", "LI", "H1", "H2", "H3", "H4", "H5", "H6", "PRE", "BLOCKQUOTE", "HR", "TABLE",
  "TR", "SECTION", "ARTICLE", "HEADER", "FOOTER"]);
const isBlock = (n) => n.nodeType === 1 && BLOCKS.has(n.tagName);
const httpUrl = (u) => /^https?:\/\//i.test(u || "");

function boldStyle(n) {
  const w = (n.style && n.style.fontWeight) || "";
  return w === "bold" || w === "bolder" || +w >= 600;
}
function italicStyle(n) { return !!(n.style && n.style.fontStyle === "italic"); }

// маркер вокруг текста; пробелы по краям — снаружи («** a **» Markdown не поймёт)
function wrap(mk, inner) {
  const m = inner.match(/^(\s*)([\s\S]*?)(\s*)$/);
  return m[2] ? m[1] + mk + m[2] + mk + m[3] : inner;
}

// набранный текст — как есть: «x**2», «*», «`» не превращаются в разметку
const escText = (s) => s.replace(/[\\`*]/g, (c) => "\\" + c);
// строка абзаца, которая выглядела бы списком, заголовком или ответом, — тоже как есть («2024. Год»)
const escLine = (l) => l.replace(/^(\s*)(#{1,6}\s|[-+•]\s|→|->|\d+[.)]\s)/, (_m, sp, mk) =>
  sp + (/^\d/.test(mk) ? mk.replace(/([.)])/, "\\$1") : "\\" + mk));
const escLines = (s) => s.split("\n").map(escLine).join("\n");

function inlineMd(node, ctx) {
  if (node.nodeType === 3) return escText(node.data.replace(/\u00a0/g, " ").replace(/\n/g, " "));
  if (node.nodeType !== 1) return "";
  const tag = node.tagName;
  if (tag === "BR") return "\n";
  if (tag === "CODE" || tag === "KBD" || tag === "SAMP") {
    const t = node.textContent.replace(/`/g, "'");
    return t.trim() ? "`" + t + "`" : t;
  }
  if (tag === "A") {
    const href = node.getAttribute("href") || "";
    const text = kids(node, ctx);
    if (!httpUrl(href)) return text;
    return text.trim() === href ? href : "[" + text.replace(/[[\]]/g, "") + "](" + href + ")";
  }
  if (tag === "IMG" || tag === "SCRIPT" || tag === "STYLE") return "";
  if (tag === "TD" || tag === "TH") return kids(node, ctx) + " ";
  const notBold = !!node.style && /^(normal|400|lighter)$/.test(node.style.fontWeight || "");   // обёртка Google Docs
  const bold = ((tag === "B" || tag === "STRONG") && !notBold || boldStyle(node)) && !ctx.b;
  const ital = (tag === "I" || tag === "EM" || italicStyle(node)) && !ctx.i;
  let inner = kids(node, { b: ctx.b || bold, i: ctx.i || ital });
  if (ital) inner = wrap("*", inner);
  if (bold) inner = wrap("**", inner);
  return inner;
}

function kids(node, ctx) {
  let out = "";
  for (const c of node.childNodes) out += isBlock(c) ? "\n" + blockMd(c, ctx).trim() + "\n" : inlineMd(c, ctx);
  return out;
}

const tidy = (s) => s.split("\n").map((l) => l.replace(/[ \t]+$/g, "").replace(/^[ \t]+/, "")).join("\n").replace(/^\n+|\n+$/g, "");

function listMd(node, ctx) {
  const ordered = node.tagName === "OL";
  const out = [];
  let i = 1;
  for (const li of node.children) {
    if (li.tagName === "UL" || li.tagName === "OL") { out.push(listMd(li, ctx)); continue; }
    if (li.tagName !== "LI") continue;
    let text = "", nested = [];
    for (const c of li.childNodes) {
      if (c.nodeType === 1 && (c.tagName === "UL" || c.tagName === "OL")) nested.push(listMd(c, ctx));
      else text += isBlock(c) ? " " + kids(c, ctx) : inlineMd(c, ctx);
    }
    text = text.replace(/\s*\n\s*/g, " ").trim();
    if (text) out.push((ordered ? i++ + ". " : "- ") + text);
    out.push(...nested);
  }
  return out.join("\n");
}

function blockMd(node, ctx = {}) {
  const tag = node.tagName;
  if (tag === "UL" || tag === "OL") return listMd(node, ctx);
  if (tag === "PRE") return "```\n" + node.textContent.replace(/\n$/, "") + "\n```";
  if (tag === "HR") return "";
  if (/^H[1-6]$/.test(tag)) {
    const level = Math.max(1, +tag[1] - 1);
    return "#".repeat(level) + " " + kids(node, ctx).replace(/\s*\n\s*/g, " ").trim();
  }
  if ([...node.childNodes].some(isBlock)) return toMarkdown(node);       // div в div (вставка из браузера)
  return escLines(tidy(kids(node, ctx)));
}

export function toMarkdown(root) {
  const parts = [];
  let buf = "";
  const flush = () => { const t = escLines(tidy(buf)); if (t) parts.push(t); buf = ""; };
  for (const n of root.childNodes) {
    if (isBlock(n)) { flush(); const t = blockMd(n); if (t.trim()) parts.push(t); }
    else buf += inlineMd(n, {});
  }
  flush();
  return parts.join("\n\n").replace(/\n{3,}/g, "\n\n").trim();
}

// ---------------------------------------------------------------- вставка
const KEEP = { B: "b", STRONG: "b", I: "i", EM: "i", CODE: "code", A: "a", UL: "ul", OL: "ol", LI: "li", P: "p", BR: "br",
  DIV: "p", H1: "h2", H2: "h2", H3: "h3", H4: "h3", H5: "h3", H6: "h3", PRE: "pre", BLOCKQUOTE: "p", TR: "p" };
const DROP = new Set(["SCRIPT", "STYLE", "META", "TITLE", "HEAD", "LINK", "OBJECT", "IFRAME", "SVG", "IMG", "XML", "TEMPLATE"]);

function cleanNode(src, doc) {
  const frag = doc.createDocumentFragment();
  for (const n of src.childNodes) {
    if (n.nodeType === 3) { frag.appendChild(doc.createTextNode(n.data)); continue; }
    if (n.nodeType !== 1 || DROP.has(n.tagName)) continue;
    const st = (n.getAttribute("style") || "").toLowerCase();
    if (/mso-list:\s*ignore/.test(st) || /display:\s*none/.test(st)) continue;     // маркер списка Word, скрытое
    let tag = KEEP[n.tagName];
    if (tag === "b" && /font-weight:\s*(normal|400)/.test(st)) tag = "";      // Google Docs: <b style="font-weight:normal">
    if (!tag && (n.tagName === "SPAN" || n.tagName === "FONT")) tag = boldStyle(n) ? "b" : italicStyle(n) ? "i" : "";
    if (n.tagName === "P" && /MsoListParagraph/i.test(n.className || "")) tag = "li";
    const inner = cleanNode(n, doc);
    if (n.tagName === "TD" || n.tagName === "TH") inner.appendChild(doc.createTextNode(" "));   // ячейки — через пробел
    if (!tag) { frag.appendChild(inner); continue; }
    const e = doc.createElement(tag);
    if (tag === "a") {
      const href = n.getAttribute("href") || "";
      if (!httpUrl(href)) { frag.appendChild(inner); continue; }
      e.setAttribute("href", href);
    }
    e.appendChild(inner);
    frag.appendChild(e);
  }
  return frag;
}

export function cleanPaste(html) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const body = doc.body;
  const out = document.createElement("div");
  out.appendChild(cleanNode(body, document));
  // пункты списка Word (p.MsoListParagraph → li) — в один список
  let list = null;
  for (const n of [...out.childNodes]) {
    if (n.nodeType === 1 && n.tagName === "LI") {
      if (!list) { list = document.createElement("ul"); out.insertBefore(list, n); }
      list.appendChild(n);
    } else if (!(n.nodeType === 3 && !n.data.trim())) list = null;
  }
  return out.innerHTML;
}

// для проверок: Markdown → поле → Markdown
export function roundtrip(md) {
  const d = document.createElement("div");
  d.innerHTML = mdHtml(md);
  return toMarkdown(d);
}
window.__rt = { toMarkdown, cleanPaste, roundtrip };
