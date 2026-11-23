// Markdown заметки → HTML — тот же разбор, что scenario.md_html в программе (показ сразу после правки, пока
// программа не прислала свой HTML). Сначала всё экранируется; ссылки — только http(s).
"use strict";

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#x27;");
const BOLD = /\*\*(.+?)\*\*/g;
const ITALIC = /(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])/g;
const INLINE = /(`[^`\n]+`)|\[([^\]\n]+)\]\(([^)\s]+)\)|(https?:\/\/[^\s<>"'`]+)/g;

const emph = (e) => e.replace(BOLD, "<b>$1</b>").replace(ITALIC, "<i>$1</i>");
const link = (url, inner) => `<a href="${esc(url)}" target="_blank" rel="noopener">${inner}</a>`;

export function inline(text) {
  let out = "", pos = 0, m;
  INLINE.lastIndex = 0;
  while ((m = INLINE.exec(text))) {
    out += emph(esc(text.slice(pos, m.index)));
    const [, code, label, url, bare0] = m;
    if (code) out += `<code>${esc(code.slice(1, -1))}</code>`;
    else if (label !== undefined) {
      const inner = emph(esc(label));
      out += /^https?:\/\//i.test(url) ? link(url, inner) : inner;
    } else {
      let bare = bare0, tail = "";
      while (bare && ".,;:!?)»".includes(bare[bare.length - 1])) {
        if (bare.endsWith(")") && (bare.match(/\(/g) || []).length >= (bare.match(/\)/g) || []).length) break;
        tail = bare[bare.length - 1] + tail;
        bare = bare.slice(0, -1);
      }
      out += link(bare, esc(bare)) + esc(tail);
    }
    pos = m.index + m[0].length;
  }
  return out + emph(esc(text.slice(pos)));
}

export function mdHtml(text) {
  const lines = (text || "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let para = [], items = [], kind = "";
  const flushPara = () => { if (para.length) { out.push("<p>" + para.map(inline).join("<br>") + "</p>"); para = []; } };
  const flushList = () => {
    if (items.length) out.push(`<${kind}>` + items.map((x) => `<li>${inline(x)}</li>`).join("") + `</${kind}>`);
    items = []; kind = "";
  };
  const UL = /^\s*[-*•]\s+(.*)$/, OL = /^\s*\d+[.)]\s+(.*)$/, HEAD = /^(#{1,6})\s+(.*)$/, FENCE = /^\s*```/;
  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i];
    if (FENCE.test(ln)) {
      flushPara(); flushList();
      const body = [];
      i++;
      while (i < lines.length && !FENCE.test(lines[i])) body.push(lines[i++]);
      out.push("<pre>" + esc(body.join("\n")) + "</pre>");
      continue;
    }
    if (!ln.trim()) { flushPara(); flushList(); continue; }
    const h = ln.match(HEAD);
    if (h) {
      flushPara(); flushList();
      const n = Math.min(6, h[1].length + 1);
      out.push(`<h${n}>${inline(h[2].trim())}</h${n}>`);
      continue;
    }
    const u = ln.match(UL), o = ln.match(OL);
    if (u || o) {
      flushPara();
      const k = u ? "ul" : "ol";
      if (kind && kind !== k) flushList();
      kind = k;
      items.push((u || o)[1].trim());
      continue;
    }
    if (items.length && /^[ \t]/.test(ln)) { items[items.length - 1] += " " + ln.trim(); continue; }
    flushList();
    para.push(ln.trim());
  }
  flushPara(); flushList();
  return out.join("");
}

export function askParts(text) {
  const q = [], a = [];
  for (const ln of (text || "").split("\n")) {
    const m = ln.match(/^\s*(→|->)\s*(.*)$/);
    if (m) { if (m[2].trim()) a.push(m[2].trim()); } else q.push(ln);
  }
  return [q.join("\n").trim(), a];
}

export function escapeHtml(s) { return esc(s || ""); }
