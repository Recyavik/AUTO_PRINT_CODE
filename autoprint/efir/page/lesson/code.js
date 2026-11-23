// Правка кода на месте — CodeMirror 6 (грузится при первой правке). Тот же шрифт и строки, что у показа;
// слева — номера строк и шаги (Alt+1…9 — шаг выделенным строкам, Alt+0 — новый шаг). Одновременно жив один.
"use strict";
import { A, el } from "./state.js";
import * as Q from "./queue.js";
import { stepColor } from "./render.js";

let CM = null;
let cur = null;           // {id, view, node, box, host}

async function load() {
  if (!CM) CM = await import("/static/vendor/cm6.js");
  return CM;
}

function langExt(cm, lang) {
  const l = (lang || "").toLowerCase();
  if (["python", "py"].includes(l)) return cm.python();
  if (["javascript", "js", "jsx"].includes(l)) return cm.javascript();
  if (["typescript", "ts", "tsx"].includes(l)) return cm.javascript({ typescript: true });
  if (["html", "html5", "xml", "svg"].includes(l)) return cm.html();
  if (l === "css") return cm.css();
  if (["java", "kotlin", "kt"].includes(l)) return cm.java();
  if (["cpp", "c++", "c", "csharp", "cs", "c#"].includes(l)) return cm.cpp();
  if (l === "sql") return cm.sql();
  if (l === "json") return cm.json();
  return [];
}

function norm(steps, n) {
  const out = (steps || []).slice(0, n).map((x) => Math.max(1, x | 0));
  const fill = out.length ? out[out.length - 1] : 1;
  while (out.length < n) out.push(fill);
  return out;
}

function mapSteps(steps, tr) {
  const oldDoc = tr.startState.doc;
  const out = norm(steps, oldDoc.lines);
  const ch = [];
  tr.changes.iterChanges((fromA, toA, fromB, toB) => ch.push([fromA, toA, fromB, toB]));
  for (const [fromA, toA, fromB, toB] of ch.reverse()) {        // с конца — номера строк старого текста не съезжают
    const la = oldDoc.lineAt(fromA).number, lb = oldDoc.lineAt(toA).number;
    const n = tr.newDoc.lineAt(toB).number - tr.newDoc.lineAt(fromB).number + 1;
    const s = out[la - 1] || 1;
    out.splice(la - 1, lb - la + 1, ...Array(n).fill(s));
  }
  return out;
}

function extensions(cm, it, onChange) {
  const setSteps = cm.StateEffect.define();
  const stepsField = cm.StateField.define({
    create: (st) => norm(it.steps, st.doc.lines),
    update: (v, tr) => {
      for (const e of tr.effects) if (e.is(setSteps)) return e.value;
      return tr.docChanged ? mapSteps(v, tr) : v;
    },
  });
  class Mark extends cm.GutterMarker {
    constructor(n, s, marked) { super(); this.n = n; this.s = s; this.marked = marked; }
    eq(o) { return o.n === this.n && o.s === this.s && o.marked === this.marked; }
    toDOM() {
      const e = document.createElement("span");
      e.className = "ln";
      if (this.marked) {
        e.style.setProperty("--sc", stepColor(this.s));
        e.title = "Шаг " + this.s;
        const b = document.createElement("b");
        b.textContent = String(this.s);
        e.appendChild(b);
      }
      e.appendChild(document.createTextNode(String(this.n)));
      return e;
    }
  }
  const gutter = cm.gutter({
    class: "gutx",
    lineMarker(view, line) {
      const steps = view.state.field(stepsField);
      const n = view.state.doc.lineAt(line.from).number;
      return new Mark(n, steps[n - 1] || 1, new Set(steps).size > 1);
    },
    lineMarkerChange: (u) => u.docChanged || u.transactions.some((t) => t.effects.some((e) => e.is(setSteps))),
    initialSpacer: () => new Mark(99, 1, false),
  });
  const assign = (view, k) => {
    const st = view.state;
    const steps = st.field(stepsField).slice();
    const max = Math.max(1, ...steps);
    const s = k === 0 ? max + 1 : k;
    for (const r of st.selection.ranges) {
      const a = st.doc.lineAt(r.from).number, b = st.doc.lineAt(r.to).number;
      for (let i = a; i <= b; i++) steps[i - 1] = s;
    }
    view.dispatch({ effects: setSteps.of(steps) });
    return true;
  };
  const stepKeys = [];
  for (let k = 0; k <= 9; k++) stepKeys.push({ key: "Alt-" + k, run: (v) => assign(v, k) });
  const T = cm.tags;
  const style = cm.HighlightStyle.define([
    { tag: T.comment, color: "var(--t-c)", fontStyle: "italic" },
    { tag: [T.keyword, T.controlKeyword, T.operatorKeyword, T.definitionKeyword, T.moduleKeyword], color: "var(--t-k)" },
    { tag: [T.string, T.special(T.string), T.regexp], color: "var(--t-s)" },
    { tag: [T.number, T.bool, T.null], color: "var(--t-n)" },
    { tag: [T.function(T.variableName), T.function(T.propertyName)], color: "var(--t-f)" },
    { tag: [T.className, T.typeName], color: "var(--t-cl)", fontWeight: "600" },
    { tag: T.tagName, color: "var(--t-t)" },
    { tag: T.attributeName, color: "var(--t-a)" },
    { tag: [T.standard(T.variableName), T.special(T.variableName)], color: "var(--t-b)" },
    { tag: [T.meta, T.annotation], color: "var(--t-d)" },
    { tag: [T.operator, T.punctuation], color: "var(--t-o)" },
  ]);
  return [
    stepsField, gutter, cm.history(), cm.drawSelection(), cm.bracketMatching(),
    cm.indentUnit.of("    "), cm.EditorState.tabSize.of(4),
    cm.keymap.of([...stepKeys, cm.indentWithTab, ...cm.defaultKeymap, ...cm.historyKeymap]),
    cm.syntaxHighlighting(style), langExt(cm, it.lang),
    cm.EditorView.updateListener.of((u) => onChange(u, stepsField)),
  ];
}

export function editingCode(id) { return cur && cur.id === id; }

export async function beginCode(n, it, finishOthers) {
  if (cur && cur.id === it.id) { cur.view.focus(); return; }
  finishOthers && finishOthers();
  if (cur) endCode();
  released(it.id);                       // этот же блок ещё держит прежний редактор — убрать его
  const cm = await load();
  A.editing = it.id;
  const box = n.querySelector(".codebox");
  box.classList.add("editing");
  const host = el("div", "cmhost");
  box.insertBefore(host, box.firstChild);
  let selTimer = 0;
  const onChange = (u, stepsField) => {
    if (u.docChanged) {
      const fields = { text: u.state.doc.toString() };
      const steps = u.state.field(stepsField);
      fields.steps = new Set(steps).size > 1 ? steps : [];
      if ((it.sel || []).length) fields.sel = [];             // выделение было в прежнем тексте
      Q.draft(it.id, fields);
    } else if (u.transactions.some((t) => t.effects.length)) {
      const steps = u.state.field(stepsField);
      Q.draft(it.id, { steps: new Set(steps).size > 1 ? steps : [] });
    }
    if (u.selectionSet) {
      clearTimeout(selTimer);
      selTimer = setTimeout(() => {
        const r = u.view.state.selection.main;
        if (!r.empty) Q.draft(it.id, { sel: [r.from, r.to] });   // пустое выделение прежнее не сбрасывает
      }, 400);
    }
  };
  const view = new cm.EditorView({
    parent: host,
    state: cm.EditorState.create({ doc: it.text || "", extensions: extensions(cm, it, onChange) }),
  });
  cur = { id: it.id, view, node: n, box, host };
  view.dom.addEventListener("focusout", (e) => {
    if (e.relatedTarget && view.dom.contains(e.relatedTarget)) return;
    setTimeout(() => { if (cur && cur.view === view && !view.hasFocus) endCode(); }, 0);
  });
  view.dom.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); view.contentDOM.blur(); }
  });
  view.focus();
}

// конец правки: правка уходит сразу; редактор держится, пока программа не пришлёт новый HTML (без мигания)
export function endCode() {
  if (!cur) return;
  const c = cur;
  cur = null;
  const changed = Q.Q.drafts.has(c.id) || Q.Q.pending.some((e) => e.ops.some((o) => o.block === c.id));
  Q.flush(c.id);
  if (A.editing === c.id) A.editing = null;
  A.holding.add(c.id);
  const done = () => {
    if (!A.holding.has(c.id)) return;
    A.holding.delete(c.id);
    c.view.destroy();
    c.host.remove();
    c.box.classList.remove("editing");
    window.dispatchEvent(new Event("suflor:refresh"));
  };
  c.release = done;
  holdTimers.set(c.id, c);
  if (!changed) { holdTimers.delete(c.id); done(); return; }   // код не меняли — ждать нечего
  setTimeout(() => { holdTimers.delete(c.id); done(); }, 1500);
}

const holdTimers = new Map();
// программа прислала блок — редактор можно убрать
export function released(id) {
  const c = holdTimers.get(id);
  if (c) { holdTimers.delete(id); c.release(); }
}
